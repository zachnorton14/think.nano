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


def _restore_boundary_whitespace(source: str, candidate: str) -> str:
    """Keep source-owned whitespace at the editable component boundary."""
    leading = source[: len(source) - len(source.lstrip())]
    trailing = source[len(source.rstrip()):]
    return f"{leading}{candidate.strip()}{trailing}"


def _component_changed(source: str, candidate: str) -> bool:
    """Whitespace-only edits do not qualify as a restyle."""
    return source.strip() != candidate.strip()


def _component_shape_ok(source: str, candidate: str) -> bool:
    """Reject non-restyles and newly inserted/removed question sentences."""
    return _component_changed(source, candidate) and source.count("?") == candidate.count("?")


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
    source_passage, _source_suffix = ds.split_row(filtered_row["context"])
    passage = _restore_boundary_whitespace(source_passage, _normalize_ascii(restyled_passage))
    if not _component_shape_ok(source_passage, passage):
        return None
    context = ds.rebuild_row(passage, suffix)
    candidate = {"context": context, "continuation": filtered_row["continuation"]}
    if not no_new_anachronism(filtered_row, candidate):
        return None
    issues = bv.validate_pair("squad", "language_modeling", idx, filtered_row, candidate)
    return candidate if not issues else None


def _local_passage_candidates(context: str) -> list[str]:
    """Extract prose from old outputs whose SQuAD scaffold was damaged."""
    candidates: list[str] = []
    try:
        passage, _suffix = ds.split_row(context)
        candidates.append(passage)
    except ValueError:
        pass
    prose = re.sub(r"^\s*Context\s*:\s*", "", context, count=1, flags=re.IGNORECASE)
    markers = list(re.finditer(r"(?:\n\s*|[ \t]+)Question\s*:", prose, re.IGNORECASE))
    candidates.append(prose[:markers[-1].start()] if markers else prose)
    out: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _load_local_staging(path: Path, label: str) -> dict[int, dict]:
    return {
        wrapper["idx"]: wrapper["candidate"]
        for wrapper in _read(path / f"{label}.jsonl")
        if isinstance(wrapper.get("idx"), int) and isinstance(wrapper.get("candidate"), dict)
    }


def salvage_local(filt, gen_queue, staging_dir: Path):
    """Keep only staged prose, rebuild immutable scaffolds, and run the normal row gate."""
    staged = _load_local_staging(staging_dir, "squad")
    salvaged: dict[int, dict] = {}
    remaining: dict[str, list[int]] = {}
    for source_passage, idxs in ds.unique_passages(filt).items():
        wanted = set(gen_queue.get(source_passage, ()))
        if not wanted:
            continue
        pool: list[str] = []
        for donor_idx in idxs:
            wrapper = staged.get(donor_idx)
            if not wrapper:
                continue
            for passage in _local_passage_candidates(wrapper.get("context", "")):
                if _component_changed(source_passage, passage) and passage not in pool:
                    pool.append(passage)
        failed = []
        for idx in idxs:
            if idx not in wanted:
                continue
            _passage, suffix = ds.split_row(filt[idx]["context"])
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
            source_passage, _ = ds.split_row(filt[i]["context"])
            candidate_passage, _ = ds.split_row(rest[i]["context"])
        except ValueError:
            continue
        if _component_changed(source_passage, candidate_passage):
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
    if not candidate or not _component_shape_ok(source, candidate):
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
    ap.add_argument("--salvage-local", type=Path, metavar="PATH",
                    help="reuse prose from PATH/squad.jsonl staging wrappers; no network")
    args = ap.parse_args()

    filt, rest, reuse, gen_queue, skipped = plan()
    print(f"squad: reuse-fixable offline={len(reuse)} rows | "
          f"gen-needed passages={len(gen_queue)} ({sum(len(v) for v in gen_queue.values())} rows) | "
          f"unsafe-skipped={len(skipped)}")

    if args.salvage_local:
        salvaged, gen_queue = salvage_local(filt, gen_queue, args.salvage_local)
        reuse.update(salvaged)
        print(f"squad: local-staging salvaged={len(salvaged)} rows | "
              f"remaining generation={sum(len(v) for v in gen_queue.values())} rows")

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
