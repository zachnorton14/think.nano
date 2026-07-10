"""Repair and validate the audited commonsense/restyle benchmark family.

This script is deliberately offline: confirmed bad restyles are replaced with the
same-index filtered source row, source provenance metadata is restored, and the
result is checked for scoring and prompt-contract regressions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dev.vintage_core.bundle_validation import digit_tokens as strict_digit_tokens  # noqa: E402
from dev.vintage_core.bundle_validation import quoted_spans  # noqa: E402


FILTERED = ROOT / "artifacts" / "vintage-core-filtered" / "eval_data"
RESTYLED = ROOT / "artifacts" / "vintage-core-restyle" / "eval_data"

TASKS = {
    "copa": ("commonsense_reasoning/copa.jsonl", "multiple_choice"),
    "winograd": ("language_understanding/winograd_wsc.jsonl", "schema"),
    "winogrande": ("language_understanding/winogrande.jsonl", "schema"),
    "commonsense_qa": ("commonsense_reasoning/commonsense_qa.jsonl", "multiple_choice"),
    "piqa": ("commonsense_reasoning/piqa.jsonl", "multiple_choice"),
    "hellaswag": ("language_understanding/hellaswag.jsonl", "multiple_choice"),
}

# Confirmed semantic, grammatical-joint, scaffold, or protected-literal failures.
REVERT_INDICES = {
    "copa": {73, 82, 94, 95},
    "winograd": {39, 54, 135, 153, 154, 199},
    "winogrande": {
        50, 134, 148, 160, 182, 260, 264, 324, 432, 627, 681, 688,
        765, 930, 1012, 1044, 1167, 1200, 1214, 1218,
    },
    "commonsense_qa": {26, 170, 328, 344, 887, 1112},
    "piqa": {128, 190, 220, 702, 982},
    "hellaswag": {
        # Broken stem-choice joints (1658 also absorbs the gold answer).
        164, 284, 840, 1492, 1658, 2089, 2160,
        # Gold continuation absorbed into the stem.
        3966, 5148, 5704,
        # Digits changed, spelled out, or deleted.
        1488, 2278, 3397, 3492, 3533, 3683, 3726, 4276, 4466, 4487,
        4731, 4807, 4903, 5096, 5181, 5416, 5443, 5903,
        # Quoted material or inch unit changed.
        2035, 3635, 5408,
    },
}

PROVENANCE_KEYS = {
    "backfilled",
    "source_idx",
    "source_reason",
    "source_src",
    "generation_revision",
}

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
TERMINAL_RE = re.compile(r"[.!?]\s*$")
CHOICES_MARKER = "\nChoices:\n"


class RepairError(RuntimeError):
    pass


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def text_fields(item: dict, task_type: str) -> list[str]:
    if task_type == "multiple_choice":
        return [item["query"]]
    if task_type == "schema":
        return list(item["context_options"])
    raise RepairError(f"unsupported task type: {task_type}")


def digit_tokens(item: dict, task_type: str) -> list[str]:
    return strict_digit_tokens("\n".join(text_fields(item, task_type)))


def _diff_span_pair(options: list[str]) -> tuple[str, str]:
    a, b = options
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(a), len(b)) - prefix
        and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]
    ):
        suffix += 1
    return (
        a[prefix: len(a) - suffix if suffix else len(a)],
        b[prefix: len(b) - suffix if suffix else len(b)],
    )


def _ngrams(text: str, size: int = 8) -> set[tuple[str, ...]]:
    tokens = [token.lower() for token in TOKEN_RE.findall(text)]
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def validate_answer_copy(original: dict, repaired: dict, task_type: str, label: str, idx: int) -> None:
    if task_type == "multiple_choice":
        answer = original["choices"][original["gold"]]
        distractor_grams = set().union(*(
            _ngrams(choice)
            for choice_idx, choice in enumerate(original["choices"])
            if choice_idx != original["gold"]
        ))
        answer_grams = _ngrams(answer) - distractor_grams
        before = _ngrams(original["query"]) & answer_grams
        after = _ngrams(repaired["query"]) & answer_grams
    else:
        answer = original["continuation"]
        before = _ngrams("\n".join(original["context_options"])) & _ngrams(answer)
        after = _ngrams("\n".join(repaired["context_options"])) & _ngrams(answer)
    added = after - before
    if added:
        sample = " ".join(next(iter(sorted(added))))
        raise RepairError(f"{label} idx={idx}: new gold/continuation phrase: {sample!r}")


def validate_item(original: dict, repaired: dict, task_type: str, label: str, idx: int) -> None:
    if task_type == "multiple_choice":
        if repaired["choices"] != original["choices"]:
            raise RepairError(f"{label} idx={idx}: choices changed")
        if repaired["gold"] != original["gold"]:
            raise RepairError(f"{label} idx={idx}: gold changed")
        expected_markers = original["query"].count(CHOICES_MARKER)
        actual_markers = repaired["query"].count(CHOICES_MARKER)
        if expected_markers and actual_markers != 1:
            raise RepairError(
                f"{label} idx={idx}: embedded Choices block count={actual_markers}, expected=1"
            )
    else:
        if repaired["continuation"] != original["continuation"]:
            raise RepairError(f"{label} idx={idx}: continuation changed")
        if repaired["gold"] != original["gold"]:
            raise RepairError(f"{label} idx={idx}: gold changed")
        if len(repaired["context_options"]) != len(original["context_options"]):
            raise RepairError(f"{label} idx={idx}: context option count changed")
        if _diff_span_pair(repaired["context_options"]) != _diff_span_pair(original["context_options"]):
            raise RepairError(f"{label} idx={idx}: schema minimal-pair difference changed")
        if not any(TERMINAL_RE.search(option) for option in original["context_options"]):
            if any(TERMINAL_RE.search(option) for option in repaired["context_options"]):
                raise RepairError(f"{label} idx={idx}: new terminal punctuation before continuation")

    if digit_tokens(repaired, task_type) != digit_tokens(original, task_type):
        raise RepairError(
            f"{label} idx={idx}: digit tokens changed: "
            f"{digit_tokens(original, task_type)!r} -> {digit_tokens(repaired, task_type)!r}"
        )
    original_quotes = quoted_spans("\n".join(text_fields(original, task_type)))
    repaired_quotes = quoted_spans("\n".join(text_fields(repaired, task_type)))
    if repaired_quotes != original_quotes:
        raise RepairError(f"{label} idx={idx}: quoted material changed")
    validate_answer_copy(original, repaired, task_type, label, idx)


def repair_task(label: str, relative: str, task_type: str, check_only: bool) -> tuple[int, int]:
    source_path = FILTERED / relative
    target_path = RESTYLED / relative
    source = read_jsonl(source_path)
    target = read_jsonl(target_path)
    if len(source) != len(target):
        raise RepairError(f"{label}: row count differs: {len(source)} != {len(target)}")

    reverted = 0
    metadata_rows = 0
    repaired_rows = []
    for idx, (original, restyled) in enumerate(zip(source, target)):
        if idx in REVERT_INDICES[label]:
            if check_only and restyled != original:
                raise RepairError(f"{label} idx={idx}: audited row was not reverted")
            repaired = dict(original)
            if restyled != original:
                reverted += 1
        else:
            repaired = dict(restyled)
            restored = False
            for key in PROVENANCE_KEYS:
                if key in original:
                    if repaired.get(key) != original[key]:
                        repaired[key] = original[key]
                        restored = True
            if restored:
                metadata_rows += 1
        validate_item(original, repaired, task_type, label, idx)
        repaired_rows.append(repaired)

    if not check_only:
        write_jsonl(target_path, repaired_rows)
    return reverted, metadata_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    for label, (relative, task_type) in TASKS.items():
        reverted, metadata_rows = repair_task(label, relative, task_type, args.check)
        action = "validated" if args.check else "repaired"
        print(
            f"{label}: {action}; reverted={reverted}; "
            f"metadata_rows_restored={metadata_rows}"
        )


if __name__ == "__main__":
    main()
