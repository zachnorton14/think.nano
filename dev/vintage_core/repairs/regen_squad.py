"""SQuAD passage-level repair: reuse where a good sibling exists, generate only where none does.

Every SQuAD row shares its passage with ~4.6 others. The offline pass fixes reverted rows whose
passage was already restyled+validated on a sibling row (no API). Only passages where *every*
row was reverted need generation, and each such passage is restyled once and reused across its
rows. Scaffold + question + blank answer are reconstructed byte-for-byte from the filtered
original, so scaffold deletion and filled answers are impossible; the strict release gate
(digit tokens, answer leakage, markers) is the acceptance test for every produced row.

Usage:
  python -m dev.vintage_core.repairs.regen_squad            # offline reuse + report gen queue
  python -m dev.vintage_core.repairs.regen_squad --check    # dry run, no writes
  python -m dev.vintage_core.repairs.regen_squad --generate # also call the endpoint for the queue
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core import temporal
from dev.vintage_core.repairs import decompose_squad as ds

REL = Path("eval_data/reading_comprehension/squad.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"

_DASH_RE = re.compile("[—–―]")  # em / en / horizontal-bar dashes -> ASCII hyphen


def _normalize_ascii(text: str) -> str:
    return _DASH_RE.sub("-", text)


def no_new_anachronism(filtered_row: dict, candidate: dict) -> bool:
    """Reject a restyle that introduces a post-1930 year or science/tech term not in the source.

    The filtered passages are already temporally clean, so this catches any modern content the
    generator invents while rewriting (the release gate does not check this).
    """
    if set(temporal.post_cutoff_years(candidate)) - set(temporal.post_cutoff_years(filtered_row)):
        return False
    if set(temporal.science_anachronisms(candidate)) - set(temporal.science_anachronisms(filtered_row)):
        return False
    return True


def _read(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path: Path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _row_ok(filtered_row: dict, restyled_passage: str, suffix: str, idx: int) -> dict | None:
    """Reconstruct a row from a restyled passage and accept only if it passes the release gate."""
    passage = _normalize_ascii(restyled_passage)
    context = ds.rebuild_row(passage, suffix)
    candidate = {"context": context, "continuation": filtered_row["continuation"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("squad", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def plan():
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)
    retained = set()
    for i in range(len(filt)):
        try:
            source_passage, _ = ds.split_row(filt[i]["context"])
            candidate_passage, _ = ds.split_row(rest[i]["context"])
        except ValueError:
            continue
        if candidate_passage != source_passage:
            retained.add(i)
    groups = ds.unique_passages(filt)  # passage -> [idx...]

    reuse = {}          # idx -> reconstructed row (offline, no API)
    gen_queue = {}      # passage -> [idx...] needing generation (no good sibling)
    skipped = []        # reverted rows we could not safely fix offline

    for passage, idxs in groups.items():
        rev = [i for i in idxs if i not in retained]
        if not rev:
            continue
        ret = [i for i in idxs if i in retained]
        donor_passage = None
        for i in ret:
            try:
                donor_passage, _ = ds.split_row(rest[i]["context"])  # restyled passage from sibling
                break
            except ValueError:
                continue
        if donor_passage is None:
            gen_queue[passage] = rev
            continue
        failed = []
        for i in rev:
            _p, suffix = ds.split_row(filt[i]["context"])  # this row's immutable scaffold+question
            row = _row_ok(filt[i], donor_passage, suffix, i)
            if row:
                reuse[i] = row
            else:
                skipped.append(i)
                failed.append(i)
        # A sibling donor may not preserve this row's answer span. Regenerate the same source
        # passage with the failed rows' protected spans instead of abandoning them permanently.
        if failed:
            gen_queue[passage] = failed
    return filt, rest, reuse, gen_queue, skipped


def _protected_spans(passage, idxs, filt):
    """Answer spans (if any) and quotations in this passage that must survive verbatim."""
    spans = {filt[i]["continuation"] for i in idxs if filt[i].get("continuation")}
    spans |= set(bv.quoted_spans(passage))
    return sorted(s for s in spans if s and s in passage)


def _generated_passage_ok(source, candidate, protected_spans):
    """Cheap passage-only gate before rebuilding every task row."""
    if not candidate:
        return False
    if bv.digit_tokens(source) != bv.digit_tokens(candidate):
        return False
    if bv.quoted_spans(source) != bv.quoted_spans(candidate):
        return False
    if any(candidate.count(span) != source.count(span) for span in protected_spans):
        return False
    if not 0.7 <= len(candidate) / max(1, len(source)) <= 1.4:
        return False
    source_item = {"context": source, "continuation": ""}
    candidate_item = {"context": candidate, "continuation": ""}
    return no_new_anachronism(source_item, candidate_item)


def _generate(gen_queue, filt, workers=32, retries=3):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from dev.vintage_core import prompts
    from dev.vintage_core.client import chat, Truncated, RateLimited
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")

    def one(passage, idxs):
        protected = _protected_spans(passage, idxs, filt)
        msgs = prompts.passage_restyle_messages(passage, protected)
        temperatures = (0.2, 0.5, 0.8)
        token_budgets = (8192, 8192, 12288)
        for attempt in range(retries):
            try:
                text = _normalize_ascii(chat(
                    msgs, model, base,
                    temperature=temperatures[min(attempt, len(temperatures) - 1)],
                    max_tokens=token_budgets[min(attempt, len(token_budgets) - 1)],
                ).strip())
            except (Truncated, RateLimited, Exception):  # noqa: BLE001 - retry, then keep original
                continue
            if _generated_passage_ok(passage, text, protected):
                return passage, text
        return passage, None

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, p, i) for p, i in gen_queue.items()]
        for f in as_completed(futs):
            passage, text = f.result()
            if text:
                out[passage] = text
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="dry run, no writes")
    ap.add_argument("--generate", action="store_true", help="call endpoint for the gen queue")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--max-units", type=int, default=0,
                    help="generate only the first N passages; 0 means the full queue")
    args = ap.parse_args()

    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"squad: reuse-fixable offline={len(reuse)} rows | "
          f"gen-needed passages={len(gen_queue)} ({sum(len(v) for v in gen_queue.values())} rows) | "
          f"unsafe-skipped={len(skipped)}")

    generated_rows = 0
    if args.generate and gen_queue:
        selected_queue = dict(list(gen_queue.items())[:args.max_units or None])
        styled = _generate(selected_queue, filt, workers=args.workers)
        for passage, idxs in selected_queue.items():
            sp = styled.get(passage)
            if not sp:
                continue
            for i in idxs:
                _p, suffix = ds.split_row(filt[i]["context"])
                row = _row_ok(filt[i], sp, suffix, i)
                if row:
                    reuse[i] = row
                    generated_rows += 1
        print(f"squad: generated_units={len(selected_queue)} generated+accepted rows={generated_rows}")

    if args.check:
        print("squad: --check, no writes")
        return
    if not reuse:
        print("squad: nothing to write")
        return
    for i, row in reuse.items():
        rest[i] = row
    _write(CANDIDATE / REL, rest)
    print(f"squad: wrote {len(reuse)} repaired rows to {CANDIDATE / REL}")


if __name__ == "__main__":
    main()
