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
import re
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import decompose_boolq as db
from dev.vintage_core.repairs.regen_squad import (
    _component_changed,
    _component_shape_ok,
    _generate as _generate_passages,
    _load_local_staging,
    _normalize_ascii,
    _restore_boundary_whitespace,
    no_new_anachronism,
)

REL = Path("eval_data/reading_comprehension/boolq.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"

AUDITED_REVERTS = frozenset({401, 1011})


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _apply_audited_reverts(filt, rest) -> dict[int, dict]:
    """Return exact filtered rows for the stable, human-audited reject list."""
    return {idx: filt[idx] for idx in AUDITED_REVERTS}


def _row_ok(filtered_row, restyled_passage, suffix, idx):
    source_passage, _source_suffix = db.split_query(filtered_row["query"])
    passage = _restore_boundary_whitespace(source_passage, _normalize_ascii(restyled_passage))
    if not _component_shape_ok(source_passage, passage):
        return None
    query = db.rebuild_query(passage, suffix)
    candidate = {"query": query, "choices": filtered_row["choices"], "gold": filtered_row["gold"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("boolq", "multiple_choice", idx, filtered_row, candidate)
    return candidate if not issues else None


def _local_passage_candidates(query: str) -> list[str]:
    candidates: list[str] = []
    try:
        passage, _suffix = db.split_query(query)
        candidates.append(passage)
    except ValueError:
        pass
    prose = re.sub(r"^\s*Passage\s*:\s*", "", query, count=1, flags=re.IGNORECASE)
    markers = list(re.finditer(r"(?:\n\s*|[ \t]+)Question\s*:", prose, re.IGNORECASE))
    if markers:
        candidates.append(prose[:markers[-1].start()])
    else:
        questions = list(re.finditer(
            r"\n+(?:Is|Are|Was|Were|Do|Does|Did|Can|Could|Will|Would|Has|Have|Had)\b",
            prose, re.IGNORECASE,
        ))
        candidates.append(prose[:questions[-1].start()] if questions else prose)
    out: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def salvage_local(filt, gen_queue, staging_dir: Path):
    staged = _load_local_staging(staging_dir, "boolq")
    salvaged, remaining = {}, {}
    for source_passage, idxs in db.unique_passages(filt).items():
        wanted = set(gen_queue.get(source_passage, ()))
        if not wanted:
            continue
        pool = []
        for donor_idx in idxs:
            wrapper = staged.get(donor_idx)
            if not wrapper:
                continue
            for passage in _local_passage_candidates(wrapper.get("query", "")):
                if _component_changed(source_passage, passage) and passage not in pool:
                    pool.append(passage)
        failed = []
        for idx in idxs:
            if idx not in wanted:
                continue
            _passage, suffix = db.split_query(filt[idx]["query"])
            row = next(
                (candidate for passage in pool
                 if (candidate := _row_ok(filt[idx], passage, suffix, idx)) is not None
                 and candidate != filt[idx]),
                None,
            )
            if row is None:
                failed.append(idx)
            else:
                salvaged[idx] = row
        if failed:
            remaining[source_passage] = failed
    return salvaged, remaining


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
        if _component_changed(source_passage, candidate_passage):
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
            if i in AUDITED_REVERTS:
                skipped.append(i)
                gen_queue.setdefault(passage, []).append(i)
                continue
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
    ap.add_argument("--salvage-local", type=Path, metavar="PATH",
                    help="reuse passage prose from PATH/boolq.jsonl staging wrappers; no network")
    ap.add_argument("--apply-audited-reverts", action="store_true",
                    help="restore known-bad audited rows to exact filtered fallbacks")
    args = ap.parse_args()
    if args.apply_audited_reverts:
        filt = _read(SOURCE / REL)
        rest = _read(CANDIDATE / REL)
        reverted = _apply_audited_reverts(filt, rest)
        for idx, row in reverted.items():
            rest[idx] = row
        if not args.check:
            _write(CANDIDATE / REL, rest)
        disposition = "validated (dry-run)" if args.check else "applied"
        print(f"boolq: audited reverts {disposition}={len(reverted)}")
    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"boolq: reuse-fixable offline={len(reuse)} | gen-needed passages={len(gen_queue)} "
          f"({sum(len(v) for v in gen_queue.values())} rows) | unsafe-skipped={len(skipped)}")
    if args.salvage_local:
        salvaged, gen_queue = salvage_local(filt, gen_queue, args.salvage_local)
        reuse.update(salvaged)
        print(f"boolq: local-staging salvaged={len(salvaged)} rows | "
              f"remaining generation={sum(len(v) for v in gen_queue.values())} rows")
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
