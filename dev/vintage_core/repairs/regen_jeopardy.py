"""Category-frozen Jeopardy regeneration with fail-closed offline validation.

Only exact filtered-original rows are queued. The visible uppercase category prefix, target,
metadata, numbers, quotations, and answer-slot shape are protected. Failed generations remain
the exact filtered source row.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core import prompts
from dev.vintage_core.client import chat
from dev.vintage_core.repairs import decompose_jeopardy as dj
from dev.vintage_core.repairs.regen_squad import _normalize_ascii, no_new_anachronism


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts/vintage-core-filtered"
CANDIDATE = ROOT / "artifacts/vintage-core-restyle"
REL = Path("eval_data/world_knowledge/jeopardy_all.jsonl")
DEICTIC_RE = re.compile(r"\b(this|these|he|she|his|her|its|term|word|name|city|country|river)\b", re.I)
# These locally staged candidates passed the deterministic gate and a separate semantic review.
# Candidates with factual additions, target weakening, or duplicated category prose are omitted.
AUDITED_STAGED_SAFE = frozenset({
    11, 38, 44, 50, 73, 113, 115, 170, 181, 202, 206, 260, 264, 265, 287, 289,
    322, 346, 349, 407, 467, 474, 502, 509, 542, 572, 582, 683, 746, 783, 794,
    864, 869, 974, 1019, 1029, 1145, 1247, 1261, 1498, 1593,
})


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, rows: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    temporary.replace(path)


def _slot_signature(clue: str) -> list[str]:
    return [match.group(0).lower() for match in DEICTIC_RE.finditer(clue)]


def _candidate_row(source: dict, clue: str, idx: int) -> dict | None:
    scaffold, original_clue = dj.split_context(source["context"])
    clue = _normalize_ascii(clue.strip())
    if not clue or source["continuation"].lower() in clue.lower():
        return None
    if bool(original_clue.rstrip().endswith("?")) != bool(clue.rstrip().endswith("?")):
        return None
    original_slots = _slot_signature(original_clue)
    if original_slots and not set(original_slots).issubset(_slot_signature(clue)):
        return None
    if bv.digit_tokens(original_clue) != bv.digit_tokens(clue):
        return None
    if bv.quoted_spans(original_clue) != bv.quoted_spans(clue):
        return None
    if not 0.7 <= len(clue) / max(1, len(original_clue)) <= 1.4:
        return None
    candidate = dict(source)
    candidate["context"] = dj.rebuild_context(scaffold, clue)
    if not no_new_anachronism(source, candidate):
        return None
    return candidate if not bv.validate_pair("jeopardy", "language_modeling", idx, source, candidate) else None


def plan(target_coverage: float = 0.98):
    source = _read(SOURCE / REL)
    restyled = _read(CANDIDATE / REL)
    changed = sum(before != after for before, after in zip(source, restyled))
    needed = max(0, math.ceil(target_coverage * len(source)) - changed)
    originals = [idx for idx, (before, after) in enumerate(zip(source, restyled)) if before == after]
    return source, restyled, originals, needed


def _salvage_staging(source: list[dict], restyled: list[dict], path: Path) -> dict[int, dict]:
    wrappers = {row["idx"]: row["candidate"] for row in _read(path)}
    accepted = {}
    for idx in AUDITED_STAGED_SAFE:
        if idx >= len(source) or restyled[idx] != source[idx] or idx not in wrappers:
            continue
        staged_context = wrappers[idx].get("context", "")
        try:
            _staged_scaffold, clue = dj.split_context(staged_context)
        except ValueError:
            clue = staged_context
        candidate = _candidate_row(source[idx], clue, idx)
        if candidate and candidate != source[idx]:
            accepted[idx] = candidate
    return accepted


def _generate_one(source: dict, idx: int, retries: int = 3) -> tuple[int, dict | None]:
    _scaffold, clue = dj.split_context(source["context"])
    messages = prompts.jeopardy_clue_restyle_messages(clue, source["continuation"])
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    for attempt, temperature in enumerate((0.2, 0.5, 0.8)[:retries]):
        try:
            generated = chat(
                messages, model, base, temperature=temperature,
                max_tokens=(4096, 4096, 8192)[attempt],
            )
        except Exception:  # noqa: BLE001 - fail closed
            continue
        candidate = _candidate_row(source, generated, idx)
        if candidate:
            return idx, candidate
    return idx, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--target", type=float, default=0.98)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--salvage-local", type=Path, metavar="STAGING_JSONL")
    args = parser.parse_args()

    source, restyled, originals, needed = plan(args.target)
    print(f"jeopardy: originals={len(originals)} needed_for_target={needed}")
    salvaged = {}
    if args.salvage_local:
        salvaged = _salvage_staging(source, restyled, args.salvage_local.expanduser())
        for idx, row in salvaged.items():
            restyled[idx] = row
        if salvaged and not args.check:
            _write(CANDIDATE / REL, restyled)
        print(f"jeopardy: locally salvaged={len(salvaged)}")
        changed = sum(before != after for before, after in zip(source, restyled))
        needed = max(0, math.ceil(args.target * len(source)) - changed)
        originals = [idx for idx, (before, after) in enumerate(zip(source, restyled)) if before == after]
        print(f"jeopardy: after salvage originals={len(originals)} needed_for_target={needed}")
    if args.check or not args.generate or not needed:
        return
    queue = originals[:args.max_items or None]
    accepted = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_generate_one, source[idx], idx) for idx in queue]
        for future in as_completed(futures):
            idx, row = future.result()
            if row:
                accepted[idx] = row
                if len(accepted) >= needed:
                    # Running calls finish, but excess accepted rows are harmless and improve coverage.
                    pass
    for idx, row in accepted.items():
        restyled[idx] = row
    if accepted:
        _write(CANDIDATE / REL, restyled)
    print(f"jeopardy: attempted={len(queue)} accepted={len(accepted)}")


if __name__ == "__main__":
    main()
