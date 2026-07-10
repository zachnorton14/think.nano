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
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import decompose_coqa as dc
from dev.vintage_core.repairs.regen_squad import _normalize_ascii

REL = Path("eval_data/reading_comprehension/coqa.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"


def _read(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path: Path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _row_ok(filtered_row: dict, restyled_story: str, prefix: str, suffix: str, idx: int) -> dict | None:
    context = dc.rebuild_row(prefix, _normalize_ascii(restyled_story), suffix)
    candidate = {"context": context, "continuation": filtered_row["continuation"]}
    issues = bv.validate_pair("coqa", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def plan():
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)
    retained = {i for i in range(len(filt)) if rest[i]["context"] != filt[i]["context"]}
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
        for i in rev:
            prefix, _story, suffix = dc.split_row(filt[i]["context"])
            row = _row_ok(filt[i], donor_story, prefix, suffix, i)
            (reuse.__setitem__(i, row) if row else skipped.append(i))
    return filt, rest, reuse, gen_queue, skipped


def _generate(stories):
    from dev.vintage_core import prompts
    from dev.vintage_core.client import chat, Truncated
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    out = {}
    for story in stories:
        msgs = prompts.passage_restyle_messages(story)
        try:
            text = chat(msgs, model, base, temperature=0.4, max_tokens=8192).strip()
        except Truncated:
            continue
        out[story] = _normalize_ascii(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--generate", action="store_true")
    args = ap.parse_args()

    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"coqa: reuse-fixable offline={len(reuse)} rows | "
          f"gen-needed stories={len(gen_queue)} ({sum(len(v) for v in gen_queue.values())} rows) | "
          f"unsafe-skipped={len(skipped)}")

    if args.generate and gen_queue:
        styled = _generate(list(gen_queue))
        got = 0
        for story, idxs in gen_queue.items():
            ss = styled.get(story)
            if not ss:
                continue
            for i in idxs:
                prefix, _s, suffix = dc.split_row(filt[i]["context"])
                row = _row_ok(filt[i], ss, prefix, suffix, i)
                if row:
                    reuse[i] = row
                    got += 1
        print(f"coqa: generated+accepted rows={got}")

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
