"""Reconcile completed filter audits with the current temporal policy.

This is intentionally deterministic and does not rerun the LLM filter. It resolves two classes
of legacy audit gaps:

- filter calls that failed and were conservatively defaulted to keep;
- items kept before the generated-item science blocklist was introduced.

Run without ``--apply`` to preview changes. ``--apply`` atomically updates the audit JSONL files.
"""
import argparse
import json
import os
import tempfile
from collections import Counter, defaultdict

from . import config
from .load import load_tasks
from .temporal import modern_terms, science_anachronisms


AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")
# ``rna`` occurs as a hyphen-delimited morpheme in these two foreign-language samples. It is not
# the scientific acronym and must not trigger the science policy.
SCIENCE_FALSE_POSITIVE_ALLOWLIST = {
    ("bigbench_language_identification", 2211),
    ("bigbench_language_identification", 9267),
}


def reconcile_reason(label, idx, item, record):
    """Return a removal reason, or ``None`` when the existing keep remains valid."""
    if record.get("src") == "error":
        return "unresolved filter failure removed conservatively"

    science = science_anachronisms(item)
    if science and (label, idx) not in SCIENCE_FALSE_POSITIVE_ALLOWLIST:
        return "current science policy: " + ", ".join(science)

    modern = modern_terms(item)
    # Satellite is explicitly advisory in the original filter policy because natural satellites
    # and the word itself predate the cutoff. The completed audit already adjudicated these uses.
    if modern and set(modern) != {"satellite"}:
        return "current temporal policy: " + ", ".join(modern)
    return None


def _load_audit(label):
    path = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    with open(path, encoding="utf-8") as f:
        return path, [json.loads(line) for line in f if line.strip()]


def _atomic_jsonl(path, rows):
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _report(changes, before_kept, after_kept):
    by_label = Counter(label for label, _, _, _ in changes)
    by_kind = Counter("filter_error" if old.get("src") == "error" else "policy"
                      for _, _, old, _ in changes)
    lines = [
        "# Filter audit reconciliation",
        "",
        "This deterministic pass reconciles the completed filter audit with the stricter temporal",
        "policy later used for generated backfills. It makes no API calls.",
        "",
        f"- Newly removed source rows: **{len(changes)}**",
        f"- Unresolved filter failures removed: **{by_kind['filter_error']}**",
        f"- Current-policy conflicts removed: **{by_kind['policy']}**",
        f"- Kept source rows: **{before_kept} -> {after_kept}**",
        "",
        "| Benchmark | Newly removed |",
        "| --- | ---: |",
    ]
    for label, count in sorted(by_label.items()):
        lines.append(f"| `{label}` | {count} |")
    lines += ["", "## Decisions", ""]
    for label, idx, old, new in sorted(changes):
        lines.append(
            f"- `{label}` source_idx `{idx}`: {new['reason']} "
            f"(prior: `{old.get('src', '')}` / {old.get('reason', '')})"
        )
    return "\n".join(lines).rstrip() + "\n"


def run(apply=False):
    changes = []
    prepared = {}
    before_kept = after_kept = 0
    for task in load_tasks():
        label = task["label"]
        path, records = _load_audit(label)
        if len(records) != task["n"]:
            raise RuntimeError(f"{label} audit is partial: {len(records)}/{task['n']}")
        if [r.get("idx") for r in records] != list(range(task["n"])):
            raise RuntimeError(f"{label} audit indices are not unique and contiguous")

        updated = []
        for record in records:
            old = dict(record)
            before_kept += bool(record["keep"])
            reason = None
            if record["keep"]:
                reason = reconcile_reason(label, record["idx"], task["data"][record["idx"]], record)
            if reason:
                record = dict(record)
                record.update({
                    "keep": False,
                    "src": "policy",
                    "reason": reason,
                    "reconciled": True,
                    "prior_src": old.get("src", ""),
                    "prior_reason": old.get("reason", ""),
                })
                changes.append((label, record["idx"], old, record))
            after_kept += bool(record["keep"])
            updated.append(record)
        prepared[path] = updated

    report = _report(changes, before_kept, after_kept)
    print(report.split("## Decisions", 1)[0].rstrip())
    if not apply:
        print("\ndry run only; rerun with --apply to update audits")
        return changes

    for path, rows in prepared.items():
        _atomic_jsonl(path, rows)
    print("\napplied audit reconciliation")
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="atomically update audit JSONL files")
    args = parser.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
