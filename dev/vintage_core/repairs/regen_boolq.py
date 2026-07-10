"""BoolQ passage-level repair: reuse where a good sibling exists, generate only where none does.

Same shape as regen_squad but on the BoolQ multiple-choice ``query`` passage. Choices, gold, the
question, and the ``Passage:`` scaffold are reconstructed byte-for-byte; only the passage prose is
restyled. The strict release gate is the acceptance test for every produced row.

Usage:
  python -m dev.vintage_core.repairs.regen_boolq [--check] [--generate]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import decompose_boolq as db
from dev.vintage_core.repairs.regen_squad import (
    _generate as _generate_passages,
    _normalize_ascii,
    no_new_anachronism,
)

REL = Path("eval_data/reading_comprehension/boolq.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _row_ok(filtered_row, restyled_passage, suffix, idx):
    query = db.rebuild_query(_normalize_ascii(restyled_passage), suffix)
    candidate = {"query": query, "choices": filtered_row["choices"], "gold": filtered_row["gold"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("boolq", "multiple_choice", idx, filtered_row, candidate)
    return candidate if not issues else None


def plan():
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)
    retained = set()
    for i in range(len(filt)):
        try:
            source_passage, _ = db.split_query(filt[i]["query"])
            candidate_passage, _ = db.split_query(rest[i]["query"])
        except ValueError:
            continue
        if candidate_passage != source_passage:
            retained.add(i)
    groups = db.unique_passages(filt)
    reuse, gen_queue, skipped = {}, {}, []
    for passage, idxs in groups.items():
        rev = [i for i in idxs if i not in retained]
        if not rev:
            continue
        donor = None
        for i in (j for j in idxs if j in retained):
            try:
                donor, _ = db.split_query(rest[i]["query"]); break
            except ValueError:
                continue
        if donor is None:
            gen_queue[passage] = rev
            continue
        for i in rev:
            _p, suffix = db.split_query(filt[i]["query"])
            row = _row_ok(filt[i], donor, suffix, i)
            (reuse.__setitem__(i, row) if row else skipped.append(i))
    return filt, rest, reuse, gen_queue, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--max-units", type=int, default=0)
    args = ap.parse_args()
    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"boolq: reuse-fixable offline={len(reuse)} | gen-needed passages={len(gen_queue)} "
          f"({sum(len(v) for v in gen_queue.values())} rows) | unsafe-skipped={len(skipped)}")
    if args.generate and gen_queue:
        selected_queue = dict(list(gen_queue.items())[:args.max_units or None])
        styled = _generate_passages(selected_queue, filt, workers=args.workers)
        got = 0
        for passage, idxs in selected_queue.items():
            sp = styled.get(passage)
            if not sp:
                continue
            for i in idxs:
                _p, suffix = db.split_query(filt[i]["query"])
                row = _row_ok(filt[i], sp, suffix, i)
                if row:
                    reuse[i] = row; got += 1
        print(f"boolq: generated_units={len(selected_queue)} generated+accepted rows={got}")
    if args.check:
        print("boolq: --check, no writes"); return
    if not reuse:
        print("boolq: nothing to write"); return
    for i, row in reuse.items():
        rest[i] = row
    _write(CANDIDATE / REL, rest)
    print(f"boolq: wrote {len(reuse)} repaired rows")


if __name__ == "__main__":
    main()
