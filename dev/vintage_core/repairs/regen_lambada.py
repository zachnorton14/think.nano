"""LAMBADA sentence-array restyle: light per-sentence restyle, fail-closed per element.

The (tail-frozen) prefix is split into a lossless sentence array in code. Sentences that are
head-truncated, the penultimate cue, target-bearing, or pure dialogue are marked verbatim and
never sent. The rest go to the model as a JSON array; the model returns a same-length array. Each
returned sentence is validated independently (quotes, newlines, digits, no post-1930) and reverted
to its original if it fails - so one bad sentence never discards the passage, and sentence count is
guaranteed by structure. The reconstructed row must still pass the full release gate.

Staged rollout:
  python -m dev.vintage_core.repairs.regen_lambada --pilot 50   # blind review file, no bundle write
  python -m dev.vintage_core.repairs.regen_lambada --generate   # full, writes accepted rows
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core import temporal
from dev.vintage_core.repairs import decompose_lambada as dl
from dev.vintage_core.repairs.regen_squad import _restore_boundary_whitespace

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


def _element_ok(orig: str, new: str) -> bool:
    """Accept a restyled sentence only if it preserves quotes, newlines, digits and stays pre-1930."""
    if not isinstance(new, str) or not new.strip():
        return False
    if bv.quoted_spans(orig) != bv.quoted_spans(new):
        return False
    if orig.count("\n") != new.count("\n"):
        return False
    if bv.digit_tokens(orig) != bv.digit_tokens(new):
        return False
    if set(temporal.post_cutoff_years({"context": new})) - set(temporal.post_cutoff_years({"context": orig})):
        return False
    if set(temporal.science_anachronisms({"context": new})) - set(temporal.science_anachronisms({"context": orig})):
        return False
    return True


def _restyle_prefix(filt_row, chat_fn):
    """Return a restyled prefix (or None if nothing safely changed)."""
    prefix, _frag = dl.split_context(filt_row["context"])
    marked = dl.mark_verbatim(dl.split_sentences(prefix), filt_row["continuation"])
    editable = [m["text"] for m in marked if not m["verbatim"]]
    if not editable:
        return None
    from dev.vintage_core import prompts
    try:
        out = chat_fn(prompts.lambada_sentence_messages(editable))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(out, list) or len(out) != len(editable):
        return None
    # restore each element's original boundary whitespace (preserves inter-sentence spaces and
    # newlines), then accept/revert per element and splice back in order
    def resolve(orig, new):
        if not isinstance(new, str):
            return orig
        restored = _restore_boundary_whitespace(orig, new)
        return restored if _element_ok(orig, restored) else orig
    validated = [resolve(orig, new) for orig, new in zip(editable, out)]
    it = iter(validated)
    pieces = [m["text"] if m["verbatim"] else next(it) for m in marked]
    restyled = "".join(pieces)
    return restyled if restyled != prefix else None


def _row_ok(filt_row, restyled_prefix, idx):
    _prefix, frag = dl.split_context(filt_row["context"])
    candidate = {"context": dl.rebuild_context(restyled_prefix, frag), "continuation": filt_row["continuation"]}
    issues = bv.validate_pair("lambada_openai", "language_modeling", idx, filt_row, candidate)
    return candidate if not issues else None


def _chat_json_fn():
    from dev.vintage_core.client import chat_json
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    return lambda msgs: chat_json(msgs, model, base, temperature=0.4, max_tokens=4096)


def _generate(filt, idxs, workers=32):
    chat_fn = _chat_json_fn()

    def one(idx):
        pre = _restyle_prefix(filt[idx], chat_fn)
        return (idx, _row_ok(filt[idx], pre, idx)) if pre is not None else (idx, None)

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(one, i) for i in idxs]):
            idx, row = f.result()
            if row:
                out[idx] = row
    return out


def _write_review(filt, accepted, idxs):
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# LAMBADA pilot ({len(accepted)}/{len(idxs)} passages styled)\n"]
    for idx in idxs:
        row = accepted.get(idx)
        lines.append(f"\n## idx {idx} - {'STYLED' if row else 'unchanged (stays original)'}")
        lines.append(f"- target: `{filt[idx]['continuation']}`")
        pre, frag = dl.split_context(filt[idx]["context"])
        lines.append(f"- ORIG prefix: {pre[-320:]!r}")
        if row:
            npre, _ = dl.split_context(row["context"])
            lines.append(f"- NEW  prefix: {npre[-320:]!r}")
        lines.append(f"- frozen final: {frag!r}")
    REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)

    if args.pilot:
        idxs = list(range(min(args.pilot, len(filt))))
        accepted = _generate(filt, idxs, args.workers)
        _write_review(filt, accepted, idxs)
        print(f"lambada pilot: {len(accepted)}/{len(idxs)} passages styled -> review at {REVIEW}")
        return

    if args.generate:
        idxs = [i for i in range(len(filt)) if rest[i]["context"] == filt[i]["context"]]
        accepted = _generate(filt, idxs, args.workers)
        for i, row in accepted.items():
            rest[i] = row
        _write(CANDIDATE / REL, rest)
        print(f"lambada: styled {len(accepted)} of {len(idxs)} passages; wrote bundle")


if __name__ == "__main__":
    main()
