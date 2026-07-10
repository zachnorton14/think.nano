"""CoQA story-level repair: reuse where a good sibling exists, generate only where none does.

Mirrors regen_squad but on the CoQA ``Story:`` block. The offline pass fixes reverted turns whose
story was already restyled+validated on a sibling turn (no API). Only stories where every turn was
reverted need generation, and each story is restyled once and reused across its turns. Dialogue
history, final question, and the blank answer are reconstructed byte-for-byte from the filtered
original; the strict release gate is the acceptance test for every produced row.

Usage:
  python -m dev.vintage_core.repairs.regen_coqa            # offline reuse + report gen queue
  python -m dev.vintage_core.repairs.regen_coqa --check    # dry run, no writes
  python -m dev.vintage_core.repairs.regen_coqa --generate # also call the endpoint for the queue
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import decompose_coqa as dc
from dev.vintage_core.repairs.regen_squad import (
    _component_changed,
    _component_shape_ok,
    _generate,
    _load_local_staging,
    _normalize_ascii,
    _restore_boundary_whitespace,
    no_new_anachronism,
)

REL = Path("eval_data/reading_comprehension/coqa.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"

# Human-audited failures must remain exact filtered fallbacks until a fresh generation passes
# the normal fail-closed gate. In particular, do not immediately reapply a flawed sibling donor.
AUDITED_REVERTS = frozenset({2364, 2631, 3984})


def _read(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path: Path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _apply_audited_reverts(filt, rest) -> dict[int, dict]:
    """Return exact filtered rows for the stable, human-audited reject list."""
    return {idx: filt[idx] for idx in AUDITED_REVERTS}


def _row_ok(filtered_row: dict, restyled_story: str, prefix: str, suffix: str, idx: int) -> dict | None:
    _source_prefix, source_story, _source_suffix = dc.split_row(filtered_row["context"])
    story = _restore_boundary_whitespace(source_story, _normalize_ascii(restyled_story))
    if not _component_shape_ok(source_story, story):
        return None
    context = dc.rebuild_row(prefix, story, suffix)
    candidate = {"context": context, "continuation": filtered_row["continuation"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("coqa", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def _local_story_candidates(context: str) -> list[str]:
    candidates: list[str] = []
    try:
        _prefix, story, _suffix = dc.split_row(context)
        candidates.append(story)
    except ValueError:
        pass
    marks = list(re.finditer(r"(?:^|\n)\s*(?:STORY|NARRATIVE)\s*:", context, re.IGNORECASE))
    if marks:
        prose = context[marks[-1].end():]
        boundaries = list(re.finditer(
            r"\n\s*(?:(?:Preceding|Earlier|Previous)\s+(?:questions|queries|inquiries)|"
            r"Final\s+(?:question|query)|The\s+final\s+(?:question|query)|"
            r"Hereupon\s+is\s+the\s+final\s+question|Concluding\s+question|Last\s+question)\s*:",
            prose, re.IGNORECASE,
        ))
        if boundaries:
            candidates.append(prose[:boundaries[0].start()])
    out: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def salvage_local(filt, gen_queue, staging_dir: Path):
    staged = _load_local_staging(staging_dir, "coqa")
    salvaged: dict[int, dict] = {}
    remaining: dict[str, list[int]] = {}
    for source_story, idxs in dc.unique_stories(filt).items():
        wanted = set(gen_queue.get(source_story, ()))
        if not wanted:
            continue
        pool: list[str] = []
        for donor_idx in idxs:
            wrapper = staged.get(donor_idx)
            if not wrapper:
                continue
            for story in _local_story_candidates(wrapper.get("context", "")):
                if _component_changed(source_story, story) and story not in pool:
                    pool.append(story)
        failed = []
        for idx in idxs:
            if idx not in wanted:
                continue
            prefix, _story, suffix = dc.split_row(filt[idx]["context"])
            row = next(
                (candidate for story in pool
                 if (candidate := _row_ok(filt[idx], story, prefix, suffix, idx)) is not None
                 and candidate != filt[idx]),
                None,
            )
            if row is None:
                failed.append(idx)
            else:
                salvaged[idx] = row
        if failed:
            remaining[source_story] = failed
    return salvaged, remaining


def plan():
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)
    retained = set()
    for i in range(len(filt)):
        try:
            _sp, source_story, _ss = dc.split_row(filt[i]["context"])
            _cp, candidate_story, _cs = dc.split_row(rest[i]["context"])
        except ValueError:
            continue
        if _component_changed(source_story, candidate_story):
            retained.add(i)
    groups = dc.unique_stories(filt)  # story -> [idx...]

    reuse = {}
    gen_queue = {}
    skipped = []

    for story, idxs in groups.items():
        rev = [i for i in idxs if i not in retained]
        if not rev:
            continue
        ret = [i for i in idxs if i in retained]
        donor_story = None
        for i in ret:
            try:
                _p, donor_story, _s = dc.split_row(rest[i]["context"])
                break
            except ValueError:
                continue
        if donor_story is None:
            gen_queue[story] = rev
            continue
        failed = []
        for i in rev:
            if i in AUDITED_REVERTS:
                skipped.append(i)
                failed.append(i)
                continue
            prefix, _story, suffix = dc.split_row(filt[i]["context"])
            row = _row_ok(filt[i], donor_story, prefix, suffix, i)
            if row:
                reuse[i] = row
            else:
                skipped.append(i)
                failed.append(i)
        if failed:
            gen_queue[story] = failed
    return filt, rest, reuse, gen_queue, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--max-units", type=int, default=0)
    ap.add_argument("--salvage-local", type=Path, metavar="PATH",
                    help="reuse story prose from PATH/coqa.jsonl staging wrappers; no network")
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
        print(f"coqa: audited reverts {disposition}={len(reverted)}")

    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"coqa: reuse-fixable offline={len(reuse)} rows | "
          f"gen-needed stories={len(gen_queue)} ({sum(len(v) for v in gen_queue.values())} rows) | "
          f"unsafe-skipped={len(skipped)}")

    if args.salvage_local:
        salvaged, gen_queue = salvage_local(filt, gen_queue, args.salvage_local)
        reuse.update(salvaged)
        print(f"coqa: local-staging salvaged={len(salvaged)} rows | "
              f"remaining generation={sum(len(v) for v in gen_queue.values())} rows")

    if args.generate and gen_queue:
        selected_queue = dict(list(gen_queue.items())[:args.max_units or None])
        styled = _generate(selected_queue, filt, workers=args.workers)
        got = 0
        for story, idxs in selected_queue.items():
            ss = styled.get(story)
            if not ss:
                continue
            for i in idxs:
                prefix, _s, suffix = dc.split_row(filt[i]["context"])
                row = _row_ok(filt[i], ss, prefix, suffix, i)
                if row:
                    reuse[i] = row
                    got += 1
        print(f"coqa: generated_units={len(selected_queue)} generated+accepted rows={got}")

    if args.check:
        print("coqa: --check, no writes")
        return
    if not reuse:
        print("coqa: nothing to write")
        return
    for i, row in reuse.items():
        rest[i] = row
    _write(CANDIDATE / REL, rest)
    print(f"coqa: wrote {len(reuse)} repaired rows")


if __name__ == "__main__":
    main()
