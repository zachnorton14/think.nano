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
from dev.vintage_core.repairs import decompose_squad as ds

REL = Path("eval_data/reading_comprehension/squad.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"

_DASH_RE = re.compile("[—–―]")  # em / en / horizontal-bar dashes -> ASCII hyphen


def _normalize_ascii(text: str) -> str:
    return _DASH_RE.sub("-", text)


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
    issues = bv.validate_pair("squad", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def plan():
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)
    retained = {i for i in range(len(filt)) if rest[i]["context"] != filt[i]["context"]}
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
        for i in rev:
            _p, suffix = ds.split_row(filt[i]["context"])  # this row's immutable scaffold+question
            row = _row_ok(filt[i], donor_passage, suffix, i)
            (reuse.__setitem__(i, row) if row else skipped.append(i))
    return filt, rest, reuse, gen_queue, skipped


def _generate(passages):
    from dev.vintage_core import prompts
    from dev.vintage_core.client import chat, Truncated
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    out = {}
    for passage in passages:
        msgs = prompts.passage_restyle_messages(passage)
        try:
            text = chat(msgs, model, base, temperature=0.4, max_tokens=8192).strip()
        except Truncated:
            continue
        out[passage] = _normalize_ascii(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="dry run, no writes")
    ap.add_argument("--generate", action="store_true", help="call endpoint for the gen queue")
    args = ap.parse_args()

    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"squad: reuse-fixable offline={len(reuse)} rows | "
          f"gen-needed passages={len(gen_queue)} ({sum(len(v) for v in gen_queue.values())} rows) | "
          f"unsafe-skipped={len(skipped)}")

    generated_rows = 0
    if args.generate and gen_queue:
        styled = _generate(list(gen_queue))
        for passage, idxs in gen_queue.items():
            sp = styled.get(passage)
            if not sp:
                continue
            for i in idxs:
                _p, suffix = ds.split_row(filt[i]["context"])
                row = _row_ok(filt[i], sp, suffix, i)
                if row:
                    reuse[i] = row
                    generated_rows += 1
        print(f"squad: generated+accepted rows={generated_rows}")

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
