"""Revert unsafe CoQA and SQuAD restyles without making API calls.

The repair is intentionally conservative: a vintage candidate is retained only when
all score-sensitive literals and prompt scaffolding agree with the filtered source.
Unsafe rows are replaced by the corresponding filtered JSONL line byte-for-byte.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tempfile
from pathlib import Path


TASKS = {
    "coqa": Path("eval_data/reading_comprehension/coqa.jsonl"),
    "squad": Path("eval_data/reading_comprehension/squad.jsonl"),
}

MARKERS = {
    "coqa": ("Story:", "Preceding questions:", "Final question:", "Question:", "Answer:"),
    "squad": ("Context:", "Question:", "Answer:"),
}

# These examples were confirmed manually during the audit. The general gates below
# catch them as well; retaining the indices here makes that audit coverage explicit.
KNOWN_WHOLESALE_DELETIONS = {
    "coqa": frozenset(
        {305, 565, 578, 734, 887, 1064, 1220, 1405, 1415, 1498, 1607, 1783, 2549, 2650, 3397, 4197}
    ),
    "squad": frozenset({1, 3, 5, 7, 8, 12, 19, 20, 23, 27}),
}

KNOWN_GOLD_LEAKS = {
    "coqa": frozenset(
        {
            58, 140, 759, 764, 842, 1193, 1372, 1384, 1640, 1646, 1827,
            1914, 1946, 1955, 2343, 2469, 2567, 2640, 2792, 2823, 2909,
            3064, 3091, 3104, 3340, 3721, 4006, 4038, 4044, 4104, 4198,
        }
    ),
    "squad": frozenset({80, 637, 1372, 1650, 2040, 2447, 2617, 3373}),
}

# A whitespace token containing any digit. This deliberately includes forms the
# original validator missed, such as ``19th``, ``c1600``, and sentence-final ``1892.``.
DIGIT_TOKEN_RE = re.compile(r"\S*\d\S*")
QUOTE_RE = re.compile(r'"[^"]*"|“[^”]*”|‘[^’]*’')


def _read_jsonl(path: Path) -> tuple[list[str], list[dict]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if any(not line.strip() for line in raw_lines):
        raise ValueError(f"{path}: blank JSONL line")
    rows = []
    for line_no, line in enumerate(raw_lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: row is not an object")
        rows.append(row)
    return raw_lines, rows


def _marker_pattern(markers: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(marker) for marker in sorted(markers, key=len, reverse=True)))


def _before_layout(text: str, position: int) -> tuple[str, int]:
    if position == 0:
        return ("start", 0)
    prefix = text[:position]
    whitespace = re.search(r"\s*$", prefix).group(0)
    newline_count = whitespace.count("\n")
    if newline_count:
        return ("line", newline_count)
    return ("inline", 0)


def _marker_signature(text: str, markers: tuple[str, ...]) -> tuple[tuple[str, tuple[str, int], str], ...]:
    """Capture marker sequence plus protected before/after whitespace layout."""
    pattern = _marker_pattern(markers)
    signature = []
    for match in pattern.finditer(text):
        after = re.match(r"\s*", text[match.end() :]).group(0)
        signature.append((match.group(0), _before_layout(text, match.start()), after))
    return tuple(signature)


def _unsafe_reasons(label: str, idx: int, source: dict, candidate: dict) -> list[str]:
    if candidate == source:
        return []

    reasons = []
    if set(candidate) != set(source):
        reasons.append("keys")
        return reasons
    if candidate.get("continuation") != source.get("continuation"):
        reasons.append("continuation")

    source_context = source.get("context")
    candidate_context = candidate.get("context")
    if not isinstance(source_context, str) or not isinstance(candidate_context, str):
        reasons.append("context_type")
        return reasons

    if _marker_signature(candidate_context, MARKERS[label]) != _marker_signature(source_context, MARKERS[label]):
        reasons.append("scaffold")
    if not candidate_context.endswith("\nAnswer: "):
        reasons.append("final_blank")
    if DIGIT_TOKEN_RE.findall(candidate_context) != DIGIT_TOKEN_RE.findall(source_context):
        reasons.append("digit_tokens")
    if QUOTE_RE.findall(candidate_context) != QUOTE_RE.findall(source_context):
        reasons.append("quotes")

    continuation = source.get("continuation")
    if isinstance(continuation, str) and continuation:
        source_occurrences = source_context.count(continuation)
        candidate_occurrences = candidate_context.count(continuation)
        if candidate_occurrences != source_occurrences:
            reasons.append("target_occurrences")
        if candidate_context.rstrip().endswith(continuation):
            reasons.append("filled_answer")

    if idx in KNOWN_WHOLESALE_DELETIONS[label]:
        reasons.append("known_wholesale_deletion")
    if idx in KNOWN_GOLD_LEAKS[label]:
        reasons.append("known_gold_leak")
    return reasons


def _atomic_write(path: Path, lines: list[str]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def repair_task(label: str, source_root: Path, target_root: Path, check: bool) -> dict:
    relative = TASKS[label]
    source_path = source_root / relative
    target_path = target_root / relative
    source_lines, source_rows = _read_jsonl(source_path)
    target_lines, target_rows = _read_jsonl(target_path)
    if len(source_rows) != len(target_rows):
        raise ValueError(
            f"{label}: row count differs: source={len(source_rows)} target={len(target_rows)}"
        )

    output_lines = list(target_lines)
    reason_counts: collections.Counter[str] = collections.Counter()
    reverted = []
    for idx, (source, candidate) in enumerate(zip(source_rows, target_rows)):
        reasons = _unsafe_reasons(label, idx, source, candidate)
        if not reasons:
            continue
        reverted.append(idx)
        reason_counts.update(reasons)
        output_lines[idx] = source_lines[idx]

    if reverted and not check:
        _atomic_write(target_path, output_lines)

    return {
        "task": label,
        "rows": len(source_rows),
        "reverted": len(reverted),
        "kept_vintage": len(source_rows) - sum(source == target for source, target in zip(source_rows, target_rows)) - len(reverted),
        "already_original": sum(source == target for source, target in zip(source_rows, target_rows)),
        "reasons": dict(sorted(reason_counts.items())),
        "indices": reverted,
    }


def _parse_args() -> argparse.Namespace:
    workspace = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=workspace / "artifacts/vintage-core-filtered",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=workspace / "artifacts/vintage-core-restyle",
    )
    parser.add_argument("--check", action="store_true", help="report unsafe rows without writing")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summaries = [
        repair_task(label, args.source_root.resolve(), args.target_root.resolve(), args.check)
        for label in TASKS
    ]
    print(json.dumps(summaries, ensure_ascii=False, sort_keys=True))
    if args.check and any(summary["reverted"] for summary in summaries):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
