"""LAMBADA final-sentence-frozen restyle: light passage restyle, fail-closed.

Restyles only the text before the (frozen) final sentence and reconstructs the context so the
strict LAMBADA contract (final fragment, target occurrences, sentence count, quotes) cannot be
violated by the frozen tail. Every produced row must pass the release gate + anachronism check;
failures stay the exact filtered original, so row counts never change.

Staged rollout (per plan):
  python -m dev.vintage_core.repairs.regen_lambada --pilot 50   # blind review file, no bundle write
  python -m dev.vintage_core.repairs.regen_lambada --pilot 500
  python -m dev.vintage_core.repairs.regen_lambada --generate   # full, writes accepted rows
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import decompose_lambada as dl
from dev.vintage_core.repairs.regen_squad import (
    _normalize_ascii, no_new_anachronism, _restore_boundary_whitespace, _component_changed,
)

REL = Path("eval_data/language_understanding/lambada_openai.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"
REVIEW = ROOT / "dev" / "vintage_core" / "review" / "restyle_lambada_pilot.md"


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _protected(prefix, target):
    spans = set(bv.quoted_spans(prefix))
    if target and target in prefix:
        spans.add(target)
    return sorted(spans)


def _row_ok(filtered_row, restyled_prefix, fragment, idx):
    source_prefix, _ = dl.split_context(filtered_row["context"])
    prefix = _restore_boundary_whitespace(source_prefix, _normalize_ascii(restyled_prefix))
    if not _component_changed(source_prefix, prefix):
        return None
    candidate = {"context": dl.rebuild_context(prefix, fragment), "continuation": filtered_row["continuation"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("lambada_openai", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def _generate(filt, idxs, workers=32):
    from dev.vintage_core import prompts
    from dev.vintage_core.client import chat, Truncated, RateLimited
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")

    def one(idx):
        prefix, frag = dl.split_context(filt[idx]["context"])
        msgs = prompts.lambada_passage_messages(prefix, _protected(prefix, filt[idx]["continuation"]))
        try:
            text = _normalize_ascii(chat(msgs, model, base, temperature=0.4, max_tokens=4096).strip())
        except (Truncated, RateLimited, Exception):  # noqa: BLE001
            return idx, None
        return idx, _row_ok(filt[idx], text, frag, idx)

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(one, i) for i in idxs]):
            idx, row = f.result()
            if row:
                out[idx] = row
    return out


def _write_review(filt, accepted, idxs):
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# LAMBADA pilot ({len(accepted)}/{len(idxs)} accepted)\n"]
    for idx in idxs:
        row = accepted.get(idx)
        lines.append(f"\n## idx {idx} — {'ACCEPTED' if row else 'rejected (stays original)'}")
        lines.append(f"- target: `{filt[idx]['continuation']}`")
        pre, frag = dl.split_context(filt[idx]["context"])
        lines.append(f"- ORIG prefix: {pre[-300:]!r}")
        if row:
            npre, _ = dl.split_context(row["context"])
            lines.append(f"- NEW  prefix: {npre[-300:]!r}")
        lines.append(f"- frozen final: {frag!r}")
    REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=0, help="review-only: N items, write review file, no bundle write")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)

    if args.pilot:
        idxs = list(range(min(args.pilot, len(filt))))
        accepted = _generate(filt, idxs, args.workers)
        _write_review(filt, accepted, idxs)
        print(f"lambada pilot: {len(accepted)}/{len(idxs)} accepted -> review at {REVIEW}")
        return

    if args.generate:
        idxs = [i for i in range(len(filt)) if rest[i]["context"] == filt[i]["context"]]  # not yet restyled
        accepted = _generate(filt, idxs, args.workers)
        for i, row in accepted.items():
            rest[i] = row
        _write(CANDIDATE / REL, rest)
        print(f"lambada: generated+accepted={len(accepted)} of {len(idxs)} queued; wrote bundle")


if __name__ == "__main__":
    main()
