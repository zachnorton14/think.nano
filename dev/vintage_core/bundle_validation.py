"""Strict offline validation for filtered/restyled Vintage CORE bundles.

This module intentionally checks scoring and prompt machinery, not whether the prose is
beautiful.  It is safe to run without an API key and is used as the final release gate for a
tracked bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


DIGIT_TOKEN_RE = re.compile(
    r"(?<!\w)[A-Za-z]*-?\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?(?:st|nd|rd|th)?(?!\w)",
    re.IGNORECASE,
)
QUOTED_SPAN_RE = re.compile(r"``.*?''|\"(?:\\.|[^\"\\])*\"|“[^”]*”|‘[^’]*’", re.DOTALL)

CONTENT_KEYS = {
    "multiple_choice": {"query", "choices", "gold"},
    "schema": {"context_options", "continuation", "gold"},
    "language_modeling": {"context", "continuation"},
}

TASK_MARKERS = {
    "boolq": ("Passage:", "Question:"),
    "coqa": ("Story:", "Preceding questions:", "Final question:", "Question:", "Answer:"),
    "squad": ("Context:", "Question:", "Answer:"),
}

EXACT_COPY_TASKS = {
    "bigbench_operators",
    "agi_eval_lsat_ar",
    "lambada_openai",
    "bigbench_language_identification",
    "bigbench_qa_wikidata",
}


@dataclass(frozen=True)
class BundleIssue:
    task: str
    idx: int
    reason: str

    def render(self) -> str:
        return f"{self.task}:{self.idx}: {self.reason}"


def digit_tokens(text: str) -> list[str]:
    """Return every digit-bearing token protected by the restyle contract.

    Unlike the old validator this sees ``1892.``, ``19th``, and ``c1600``.
    """
    return DIGIT_TOKEN_RE.findall(text or "")


def quoted_spans(text: str) -> list[str]:
    return QUOTED_SPAN_RE.findall(text or "")


def marker_signature(text: str, markers: tuple[str, ...]) -> list[tuple[str, str]]:
    """Record marker order plus whether each marker starts a line."""
    if not markers:
        return []
    pattern = re.compile("|".join(re.escape(marker) for marker in sorted(markers, key=len, reverse=True)))
    out = []
    for match in pattern.finditer(text):
        if match.start() == 0:
            placement = "start"
        elif text[match.start() - 1] == "\n":
            placement = "line"
        else:
            placement = "inline"
        out.append((match.group(0), placement))
    return out


def _text_fields(item: dict, task_type: str) -> list[str]:
    if task_type == "multiple_choice":
        return [item["query"], *item["choices"]]
    if task_type == "schema":
        return [*item["context_options"], item["continuation"]]
    return [item["context"], item["continuation"]]


def _joined_text(item: dict, task_type: str) -> str:
    return "\n".join(_text_fields(item, task_type))


def _diff_span_pair(options: list[str]) -> tuple[str, str] | None:
    if len(options) != 2:
        return None
    left, right = options
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(left), len(right)) - prefix
        and left[len(left) - 1 - suffix] == right[len(right) - 1 - suffix]
    ):
        suffix += 1
    return (
        left[prefix : len(left) - suffix if suffix else len(left)],
        right[prefix : len(right) - suffix if suffix else len(right)],
    )


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", value.lower()))


def _choice_leaks(original: dict, candidate: dict) -> list[str]:
    before = _normalized_phrase(original["query"])
    after = _normalized_phrase(candidate["query"])
    leaks = []
    for choice in original["choices"]:
        phrase = _normalized_phrase(choice)
        # Single labels and tiny function words are too noisy to be useful.
        if len(phrase) >= 4 and after.count(phrase) > before.count(phrase):
            leaks.append(choice)
    return leaks


def _has_new_joint_collision(original: dict, candidate: dict) -> bool:
    continuation = original["continuation"]
    if not re.match(r"\s*[.!?,;:]", continuation):
        return False
    for old, new in zip(original["context_options"], candidate["context_options"]):
        old_collision = bool(re.search(r"[.!?,;:]\s*$", old))
        new_collision = bool(re.search(r"[.!?,;:]\s*$", new))
        if new_collision and not old_collision:
            return True
    return False


def validate_pair(label: str, task_type: str, idx: int, original: dict, candidate: dict) -> list[BundleIssue]:
    issues: list[BundleIssue] = []

    def add(reason: str) -> None:
        issues.append(BundleIssue(label, idx, reason))

    if set(candidate) != set(original):
        add(f"keys changed: source={sorted(original)} candidate={sorted(candidate)}")
        return issues

    if task_type == "multiple_choice":
        if candidate["choices"] != original["choices"]:
            add("choices/order changed")
        if candidate["gold"] != original["gold"]:
            add("gold changed")
        leaks = _choice_leaks(original, candidate)
        if leaks:
            add(f"choice text newly appears in query: {leaks[:2]}")
        if "\nChoices:\n" in original["query"]:
            if candidate["query"].count("\nChoices:\n") != original["query"].count("\nChoices:\n"):
                add("embedded Choices block count changed")
    elif task_type == "schema":
        if candidate["continuation"] != original["continuation"]:
            add("continuation changed")
        if candidate["gold"] != original["gold"]:
            add("gold changed")
        if _diff_span_pair(candidate["context_options"]) != _diff_span_pair(original["context_options"]):
            add("minimal-pair difference changed")
        if _has_new_joint_collision(original, candidate):
            add("new punctuation collision at continuation joint")
    else:
        if candidate["continuation"] != original["continuation"]:
            add("continuation changed")
        target = original["continuation"]
        if target and candidate["context"].count(target) != original["context"].count(target):
            add("continuation occurrence count changed")

    before = _joined_text(original, task_type)
    after = _joined_text(candidate, task_type)
    if digit_tokens(before) != digit_tokens(after):
        add("digit-bearing tokens changed")
    if quoted_spans(before) != quoted_spans(after):
        add("quoted spans changed")

    markers = TASK_MARKERS.get(label)
    if markers:
        old_text = original.get("context", original.get("query", ""))
        new_text = candidate.get("context", candidate.get("query", ""))
        if marker_signature(old_text, markers) != marker_signature(new_text, markers):
            add("protected scaffold marker sequence/placement changed")
        if label in {"coqa", "squad"} and not new_text.rstrip().endswith("Answer:"):
            add("context no longer ends in a blank Answer: cue")

    if label == "jeopardy":
        prefix = original["context"].split(":", 1)[0] + ":"
        if not candidate["context"].startswith(prefix):
            add("visible category prefix changed")

    return issues


def _load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def audit_bundle(source: str, candidate: str) -> tuple[list[BundleIssue], dict[str, int]]:
    with open(os.path.join(source, "core.yaml"), encoding="utf-8") as handle:
        source_core = yaml.safe_load(handle)
    with open(os.path.join(candidate, "core.yaml"), encoding="utf-8") as handle:
        candidate_core = yaml.safe_load(handle)
    issues: list[BundleIssue] = []
    counts: dict[str, int] = {}
    if source_core != candidate_core:
        issues.append(BundleIssue("<bundle>", -1, "core.yaml changed"))

    written: set[str] = set()
    for task in source_core["icl_tasks"]:
        label = task["label"]
        uri = task["dataset_uri"]
        # The two HellaSwag labels intentionally share one physical file.
        if uri in written:
            counts[label] = counts.get("hellaswag", 0)
            continue
        written.add(uri)
        original_rows = _load_jsonl(os.path.join(source, "eval_data", uri))
        candidate_rows = _load_jsonl(os.path.join(candidate, "eval_data", uri))
        counts[label] = len(candidate_rows)
        if len(original_rows) != len(candidate_rows):
            issues.append(BundleIssue(label, -1, f"row count changed: {len(original_rows)} -> {len(candidate_rows)}"))
            continue
        if label == "bigbench_repeat_copy_logic":
            # The manual rows are code-owned; this catches artifact drift. Their instruction
            # semantics are covered by the dedicated restyle tests and human audit.
            from .restyle import _manual_repeat_copy_items

            expected_rows = _manual_repeat_copy_items()
            if candidate_rows != expected_rows:
                issues.append(BundleIssue(label, -1, "manual repeat-copy artifact differs from code"))
            continue
        for idx, (original, restyled) in enumerate(zip(original_rows, candidate_rows)):
            if label in EXACT_COPY_TASKS and original != restyled:
                issues.append(BundleIssue(label, idx, "designated copy task changed"))
                continue
            issues.extend(validate_pair(label, task["icl_task_type"], idx, original, restyled))
    return issues, counts


def render_coverage_report(source: str, candidate: str) -> str:
    """Describe actual row-level changes, rather than counting staged wrappers."""
    with open(os.path.join(source, "core.yaml"), encoding="utf-8") as handle:
        core = yaml.safe_load(handle)
    lines = [
        "# Vintage CORE Restyle Coverage",
        "",
        "This report counts actual packaged row differences from the tracked filtered bundle.",
        "A filtered-original row is an intentional correctness-preserving fallback.",
        "",
        "| Task | N | Vintage/manual rows | Filtered-original rows | Coverage |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    task_total = 0
    task_changed = 0
    unique_total = 0
    unique_changed = 0
    seen: set[str] = set()
    for task in core["icl_tasks"]:
        uri = task["dataset_uri"]
        original_rows = _load_jsonl(os.path.join(source, "eval_data", uri))
        candidate_rows = _load_jsonl(os.path.join(candidate, "eval_data", uri))
        changed = sum(before != after for before, after in zip(original_rows, candidate_rows))
        total = len(candidate_rows)
        task_total += total
        task_changed += changed
        if uri not in seen:
            unique_total += total
            unique_changed += changed
            seen.add(uri)
        coverage = 100 * changed / total if total else 0
        lines.append(
            f"| `{task['label']}` | {total} | {changed} | {total - changed} | {coverage:.1f}% |"
        )
    lines += [
        "",
        f"Task-level rows: {task_changed:,}/{task_total:,} changed ({100 * task_changed / task_total:.1f}%).",
        f"Unique physical rows: {unique_changed:,}/{unique_total:,} changed "
        f"({100 * unique_changed / unique_total:.1f}%).",
        "",
        "Validation status: run `python -m dev.vintage_core.bundle_validation`; a released bundle must report zero issues.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="artifacts/vintage-core-filtered")
    parser.add_argument("--candidate", default="artifacts/vintage-core-restyle")
    parser.add_argument("--report", help="write an actual-difference coverage report")
    args = parser.parse_args()
    issues, counts = audit_bundle(args.source, args.candidate)
    for issue in issues:
        print(issue.render())
    if args.report:
        Path(args.report).write_text(
            render_coverage_report(args.source, args.candidate), encoding="utf-8"
        )
        print(f"wrote_report={args.report}")
    print(f"validated_rows={sum(counts.values())} issues={len(issues)}")
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
