"""Repair audited science/QA Vintage CORE restyles without making API calls.

The restyle is kept when it satisfies the protected scoring/content contract.  A
row is replaced by its filtered source when an audit finding or deterministic
gate identifies semantic risk.  Run from the repository root:

    python -m dev.vintage_core.repairs.repair_science_qa
    python -m dev.vintage_core.repairs.repair_science_qa --check
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FILTERED = ROOT / "artifacts" / "vintage-core-filtered" / "eval_data"
RESTYLE = ROOT / "artifacts" / "vintage-core-restyle" / "eval_data"

TASKS = {
    "openbook_qa": ("commonsense_reasoning/openbook_qa.jsonl", "multiple_choice"),
    "arc_challenge": ("world_knowledge/arc_challenge.jsonl", "multiple_choice"),
    "arc_easy": ("world_knowledge/arc_easy.jsonl", "multiple_choice"),
    "boolq": ("reading_comprehension/boolq.jsonl", "multiple_choice"),
    "jeopardy": ("world_knowledge/jeopardy_all.jsonl", "language_modeling"),
}

# Confirmed semantic, answer-hint, answer-joint, and proper-name regressions from
# paired human review.  Other unsafe rows are caught by the general gates below.
AUDIT_REVERTS = {
    "openbook_qa": {374, 425},
    "arc_challenge": {6, 325, 487, 967, 1080},
    "arc_easy": {298, 552, 976, 1029, 1571, 1606, 1634, 1767, 1781, 1900, 1980},
    "boolq": {29, 301, 506, 881, 945},
    "jeopardy": {265, 286, 1449, 1490, 1613},
}

# Capture the complete lexical token containing each digit.  This recognizes
# terminal-period numbers (``17.`` -> ``17``), ordinals, alphanumeric forms
# such as ``F1``, and compounds such as ``base-10``.
DIGIT_TOKEN_RE = re.compile(r"\b[\w.-]*\d[\w.-]*\b", re.UNICODE)
NUMBER_WITH_UNIT_RE = re.compile(
    r"(?<![\w.])(?:\.\d+|\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?)"
    r"(?:st|nd|rd|th)?(?:[A-Za-z°%]+)?(?!\w)",
    re.IGNORECASE,
)
QUOTE_SPAN_RE = re.compile(r"``.*?''|\"[^\"]*\"|“[^”]*”|‘[^’]*’", re.DOTALL)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _editable_text(item: dict, task_type: str) -> str:
    return item["query"] if task_type == "multiple_choice" else item["context"]


def _digit_tokens(item: dict, task_type: str) -> tuple[list[str], list[str]]:
    text = _editable_text(item, task_type)
    return DIGIT_TOKEN_RE.findall(text), NUMBER_WITH_UNIT_RE.findall(text)


def _quote_spans(item: dict, task_type: str) -> list[str]:
    return QUOTE_SPAN_RE.findall(_editable_text(item, task_type))


def _contains_target(text: str, target: str) -> bool:
    target = target.strip()
    if not target:
        return False
    # Word boundaries prevent short targets such as "act" from matching
    # "character" while retaining multiword and punctuation-bearing answers.
    return re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", text, re.IGNORECASE) is not None


def _new_answer_leak(label: str, source: dict, candidate: dict, task_type: str) -> bool:
    before = _editable_text(source, task_type)
    after = _editable_text(candidate, task_type)
    if task_type == "language_modeling":
        target = source["continuation"]
    else:
        # Yes/no labels are control labels, not textual answer spans.  Their
        # ordinary occurrence in a BoolQ passage is not leakage.
        if label == "boolq":
            return False
        target = source["choices"][source["gold"]]
    return not _contains_target(before, target) and _contains_target(after, target)


def _boolq_scaffold_ok(source: dict, candidate: dict) -> bool:
    if not source["query"].startswith("Passage: ") or "\nQuestion:" not in source["query"]:
        raise AssertionError("unexpected BoolQ source scaffold")
    return candidate["query"].startswith("Passage: ") and "\nQuestion:" in candidate["query"]


def _jeopardy_prefix(item: dict) -> str:
    prefix, separator, _ = item["context"].partition(":")
    if not separator or prefix != prefix.upper():
        raise AssertionError(f"unexpected Jeopardy category prefix: {item['context'][:80]!r}")
    return prefix + ":"


def _score_contract(source: dict, candidate: dict, task_type: str) -> bool:
    if task_type == "multiple_choice":
        return source["choices"] == candidate.get("choices") and source["gold"] == candidate.get("gold")
    return source["continuation"] == candidate.get("continuation")


def _content_keys(task_type: str) -> set[str]:
    if task_type == "multiple_choice":
        return {"query", "choices", "gold"}
    return {"context", "continuation"}


def _with_source_metadata(source: dict, candidate: dict, task_type: str) -> tuple[dict, list[str]]:
    """Keep restyled scoring content while restoring the exact source key contract."""
    content = _content_keys(task_type)
    row = {key: value for key, value in candidate.items() if key in content}
    restored = []
    for key, value in source.items():
        if key not in content:
            if candidate.get(key) != value:
                restored.append(key)
            row[key] = value
    return row, restored


def _reasons(label: str, idx: int, source: dict, candidate: dict, task_type: str) -> list[str]:
    reasons = []
    if idx in AUDIT_REVERTS[label] and candidate != source:
        reasons.append("human_audit")
    if not _score_contract(source, candidate, task_type):
        reasons.append("score_contract")
    if _digit_tokens(source, task_type) != _digit_tokens(candidate, task_type):
        reasons.append("digit_tokens")
    if _quote_spans(source, task_type) != _quote_spans(candidate, task_type):
        reasons.append("quoted_material")
    if _new_answer_leak(label, source, candidate, task_type):
        reasons.append("answer_leak")
    if label == "boolq" and not _boolq_scaffold_ok(source, candidate):
        reasons.append("boolq_scaffold")
    if label == "jeopardy" and not candidate["context"].startswith(_jeopardy_prefix(source)):
        reasons.append("jeopardy_prefix")
    return reasons


def repair(check_only: bool = False) -> dict[str, dict]:
    summary = {}
    for label, (relative, task_type) in TASKS.items():
        source_path = FILTERED / relative
        target_path = RESTYLE / relative
        source_rows = _read(source_path)
        target_rows = _read(target_path)
        if len(source_rows) != len(target_rows):
            raise AssertionError(f"{label}: count mismatch {len(source_rows)} != {len(target_rows)}")

        repaired = []
        reason_counts = collections.Counter()
        reverted = []
        metadata_restored = collections.Counter()
        for idx, (source, candidate) in enumerate(zip(source_rows, target_rows)):
            reasons = _reasons(label, idx, source, candidate, task_type)
            if check_only and reasons:
                raise AssertionError(f"{label}:{idx}: unsafe current row: {', '.join(reasons)}")
            if reasons:
                row = dict(source)
                reverted.append(idx)
                reason_counts.update(reasons)
            else:
                row, restored_keys = _with_source_metadata(source, candidate, task_type)
                if check_only and (set(candidate) != set(source) or restored_keys):
                    raise AssertionError(f"{label}:{idx}: source key/metadata contract changed")
                metadata_restored.update(restored_keys)
            repaired.append(row)

        # Final fail-closed verification.  Reverted rows trivially satisfy the
        # protected gates; retained rows must satisfy them independently.
        for idx, (source, row) in enumerate(zip(source_rows, repaired)):
            if not _score_contract(source, row, task_type):
                raise AssertionError(f"{label}:{idx}: score contract changed")
            if set(source) != set(row):
                raise AssertionError(f"{label}:{idx}: keys changed")
            for key in set(source) - _content_keys(task_type):
                if source[key] != row[key]:
                    raise AssertionError(f"{label}:{idx}: metadata {key!r} changed")
            if _digit_tokens(source, task_type) != _digit_tokens(row, task_type):
                raise AssertionError(f"{label}:{idx}: digit-bearing tokens changed")
            if _quote_spans(source, task_type) != _quote_spans(row, task_type):
                raise AssertionError(f"{label}:{idx}: quoted material changed")
            if _new_answer_leak(label, source, row, task_type):
                raise AssertionError(f"{label}:{idx}: answer leaked")
            if label == "boolq" and not _boolq_scaffold_ok(source, row):
                raise AssertionError(f"{label}:{idx}: scaffold changed")
            if label == "jeopardy":
                if not row["context"].startswith(_jeopardy_prefix(source)):
                    raise AssertionError(f"{label}:{idx}: category prefix changed")
                if "category" in source and row.get("category") != source["category"]:
                    raise AssertionError(f"{label}:{idx}: category metadata changed")

        if not check_only:
            _write(target_path, repaired)
        summary[label] = {
            "rows": len(repaired),
            "reverted": len(reverted),
            "reverted_indices": reverted,
            "reasons": dict(sorted(reason_counts.items())),
            "metadata_restored": dict(sorted(metadata_restored.items())),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify current artifacts without writing")
    args = parser.parse_args()
    print(json.dumps(repair(check_only=args.check), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
