"""Fill small-task restyle fallbacks to a coverage target, without changing bundle size.

Only rows still byte-identical to the tracked filtered bundle are eligible. Generation is
explicit (``--generate``), bounded, validated offline, and written atomically. A failed item
remains the exact filtered row.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core import prompts
from dev.vintage_core.client import chat_json
from dev.vintage_core.repairs.regen_squad import no_new_anachronism
from dev.vintage_core.restyle import ValidationError, validate_item


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts/vintage-core-filtered"
CANDIDATE = ROOT / "artifacts/vintage-core-restyle"
TASKS = {
    "copa": ("commonsense_reasoning/copa.jsonl", "multiple_choice"),
    "winograd": ("language_understanding/winograd_wsc.jsonl", "schema"),
    "openbook_qa": ("commonsense_reasoning/openbook_qa.jsonl", "multiple_choice"),
    "winogrande": ("language_understanding/winogrande.jsonl", "schema"),
    "piqa": ("commonsense_reasoning/piqa.jsonl", "multiple_choice"),
}
CAPITALIZED = re.compile(r"(?<![.!?]\s)\b[A-Z][A-Za-z]*(?:[-'][A-Za-z]+)?\b")
TEMPERATURES = (0.2, 0.5, 0.8)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, rows: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    temporary.replace(path)


def _text(item: dict, task_type: str) -> str:
    if task_type == "multiple_choice":
        return "\n".join([item["query"], *item["choices"]])
    return "\n".join([*item["context_options"], item["continuation"]])


def _names_preserved(source: dict, candidate: dict, task_type: str) -> bool:
    """Conservatively retain capitalized content tokens not at sentence boundaries."""
    before = collections.Counter(CAPITALIZED.findall(_text(source, task_type)))
    after = collections.Counter(CAPITALIZED.findall(_text(candidate, task_type)))
    return all(after[token] >= count for token, count in before.items())


def _accept(label: str, task_type: str, idx: int, source: dict, generated) -> dict | None:
    try:
        candidate = validate_item(generated, source, task_type, label)
    except (ValidationError, TypeError, ValueError):
        return None
    if candidate == source or not _names_preserved(source, candidate, task_type):
        return None
    if not no_new_anachronism(source, candidate):
        return None
    return candidate if not bv.validate_pair(label, task_type, idx, source, candidate) else None


def _generate_one(label: str, task_type: str, idx: int, source: dict) -> tuple[int, dict | None]:
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    feedback = ""
    for attempt, temperature in enumerate(TEMPERATURES):
        messages = prompts.restyle_messages(
            source,
            task_type,
            {"label": label},
            "schoolbook",
            rejection_feedback=feedback,
        )
        try:
            generated = chat_json(
                messages,
                model,
                base,
                temperature=temperature,
                max_tokens=(2048, 4096, 8192)[attempt],
            )
        except Exception as exc:  # noqa: BLE001 - a failed call must leave the source row intact
            feedback = f"The prior attempt failed: {exc}"
            continue
        candidate = _accept(label, task_type, idx, source, generated)
        if candidate:
            return idx, candidate
        feedback = "The prior response violated a scoring or preservation constraint."
    return idx, None


def plan(label: str, target: float = 0.98):
    rel, task_type = TASKS[label]
    source = _read(SOURCE / "eval_data" / rel)
    restyled = _read(CANDIDATE / "eval_data" / rel)
    if len(source) != len(restyled):
        raise ValueError(f"{label}: row count differs: {len(source)} != {len(restyled)}")
    changed = sum(before != after for before, after in zip(source, restyled))
    needed = max(0, math.ceil(target * len(source)) - changed)
    originals = [idx for idx, (before, after) in enumerate(zip(source, restyled)) if before == after]
    return rel, task_type, source, restyled, originals, needed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="*", metavar="TASK")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--target", type=float, default=0.98)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-items", type=int, default=0)
    args = parser.parse_args()

    selected = args.tasks or sorted(TASKS)
    unknown = sorted(set(selected) - set(TASKS))
    if unknown:
        parser.error(f"unknown tasks: {', '.join(unknown)}")
    for label in selected:
        rel, task_type, source, restyled, originals, needed = plan(label, args.target)
        print(f"{label}: originals={len(originals)} needed_for_target={needed}")
        if args.check or not args.generate or not needed:
            continue
        limit = min(len(originals), args.max_items or len(originals))
        accepted: dict[int, dict] = {}
        for start in range(0, limit, args.workers):
            if len(accepted) >= needed:
                break
            batch = originals[start : min(start + args.workers, limit)]
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [
                    executor.submit(_generate_one, label, task_type, idx, source[idx])
                    for idx in batch
                ]
                for future in as_completed(futures):
                    idx, row = future.result()
                    if row and len(accepted) < needed:
                        accepted[idx] = row
        for idx, row in accepted.items():
            restyled[idx] = row
        if accepted:
            _write(CANDIDATE / "eval_data" / rel, restyled)
        print(f"{label}: attempted<={limit} accepted={len(accepted)}")


if __name__ == "__main__":
    main()
