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

# Human-audited, scoring-neutral restyles for the remaining small-task fallbacks.  Only
# editable prompt fields are listed; _audited_candidate copies choices, continuation,
# gold labels, and provenance from the filtered source row.
AUDITED_CORRECTIONS: dict[str, dict[int, dict[str, object]]] = {
    "copa": {
        73: {"query": "The politician's conviction for fraud meant that"},
        82: {"query": "Political violence had broken out in the nation; therefore"},
        94: {"query": "The airline had mishandled my luggage; consequently"},
        95: {"query": "The woman remained in an ill humour; consequently"},
    },
    "winograd": {
        54: {"context_options": [
            "There is a gap in the wall; one may observe the garden behind the gap",
            "There is a gap in the wall; one may observe the garden behind the wall",
        ]},
        135: {"context_options": [
            "The path to the lake had been obstructed, wherefore we could not employ the path",
            "The path to the lake had been obstructed, wherefore we could not employ the lake",
        ]},
        153: {"context_options": [
            "The foxes, gaining entry by night, assault the chickens. I shall be obliged to dispatch the foxes",
            "The foxes, gaining entry by night, assault the chickens. I shall be obliged to dispatch the chickens",
        ]},
        154: {"context_options": [
            "The foxes, which gain entrance by night, are attacking the chickens. I shall be obliged to guard the foxes",
            "The foxes, which gain entrance by night, are attacking the chickens. I shall be obliged to guard the chickens",
        ]},
        199: {"context_options": [
            "John engaged Bill for the care of John",
            "John engaged Bill for the care of Bill",
        ]},
    },
    "openbook_qa": {
        37: {"query": "The instruments termed Thermometers"},
        56: {"query": "The lunar surface is known to contain"},
        64: {"query": "A leaf fallen earthward"},
        89: {"query": "Those agents termed Pollinators"},
        95: {"query": "The disturbances called Earthquakes"},
        131: {"query": "What flavor would the fruit reputed to have struck Sir Issac Newton's head possess"},
        153: {"query": "The process called Evaporation"},
        199: {"query": "Roasting a turkey demands the addition of what form of energy"},
        218: {"query": "Which creature lays eggs"},
        266: {"query": "The process called Evaporation"},
        284: {"query": "Cellular respiration's refuse is"},
        303: {"query": "The tissue called Xylem"},
        331: {"query": "Substances called Fossil fuels"},
        353: {"query": "Desert regions are generally"},
    },
    "winogrande": {
        148: {"context_options": [
            "John made no mention of his canoe, but discussed at length with Ron the matter of the raft, because John seldom employed the canoe",
            "John made no mention of his canoe, but discussed at length with Ron the matter of the raft, because John seldom employed the raft",
        ]},
    },
    "piqa": {
        73: {"query": "Question: To make ready a loaf pan before baking Blueberry Lemon Financiers.\n"},
        74: {"query": "Question: Increase one's capacity to learn a new subject.\n"},
        79: {"query": "Question: winterizing drafty windows\n"},
        83: {"query": "Question: Make an illustration suitable for a fish tank.\n"},
        86: {"query": "Question: the drying of flowers\n"},
        128: {"query": "Question: Detect an unfamiliar sound from an automobile.\n"},
        179: {"query": "Question: the proper manner of holding a match whose flame is fading\n"},
        217: {"query": "Question: cut an onion without bringing tears to the eyes\n"},
        240: {"query": "Question: How one ought to tie a pair of shoes.\n"},
        376: {"query": "Question: How may I open a water bottle if I cannot do so with my hands\n"},
        423: {"query": "Question: Remove small pieces of shell from a cracked egg.\n"},
        433: {"query": "Question: How to Meditate properly\n"},
        463: {"query": "Question: Remove a musty odour from a room.\n"},
        471: {"query": "Question: How ought one shower\n"},
        482: {"query": "Question: Create disposable door mats for wet weather.\n"},
        526: {"query": "Question: How one boils pasta\n"},
        574: {"query": "Question: Make bean sprouts in the home.\n"},
        589: {"query": "Question: How one strengthens the jaw for boxing\n"},
        625: {"query": "Question: how one prepares a salad of smoked trout\n"},
    },
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
    # Compare fields independently. Joining them made a trailing newline in a source query
    # alter whether the first capitalized word of an unchanged choice was counted after
    # validate_item normalized that newline (notably, nearly every PIQA row).
    if task_type == "multiple_choice":
        source_fields = [source["query"], *source["choices"]]
        candidate_fields = [candidate["query"], *candidate["choices"]]
    else:
        source_fields = [*source["context_options"], source["continuation"]]
        candidate_fields = [*candidate["context_options"], candidate["continuation"]]
    before = collections.Counter(token for field in source_fields for token in CAPITALIZED.findall(field))
    after = collections.Counter(token for field in candidate_fields for token in CAPITALIZED.findall(field))
    return all(after[token] >= count for token, count in before.items())


def _audited_candidate(source: dict, correction: dict[str, object]) -> dict:
    candidate = {key: value for key, value in source.items()}
    candidate.update(correction)
    return candidate


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
    parser.add_argument(
        "--apply-audited",
        action="store_true",
        help="apply the local human-audited corrections before considering generation",
    )
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
        if args.apply_audited:
            accepted: dict[int, dict] = {}
            added = 0
            refreshed = 0
            for idx, correction in AUDITED_CORRECTIONS.get(label, {}).items():
                is_original = idx in originals
                if is_original and added >= needed:
                    continue
                row = _accept(
                    label,
                    task_type,
                    idx,
                    source[idx],
                    _audited_candidate(source[idx], correction),
                )
                if row and row != restyled[idx]:
                    accepted[idx] = row
                    if is_original:
                        added += 1
                    else:
                        refreshed += 1
            for idx, row in accepted.items():
                restyled[idx] = row
            if accepted:
                _write(CANDIDATE / "eval_data" / rel, restyled)
            originals = [idx for idx in originals if idx not in accepted]
            needed -= added
            print(
                f"{label}: audited_added={added} audited_refreshed={refreshed} "
                f"remaining_needed={needed}"
            )
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
