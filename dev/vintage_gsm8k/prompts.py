"""Versioned, cacheable prompts used by the Vintage GSM8K pipeline."""

from __future__ import annotations

import json

from .config import CUTOFF_YEAR


JUDGE_SYSTEM_PROMPT = f"""You audit GSM8K word problems for a model whose knowledge ends on December 31, {CUTOFF_YEAR}.

Judge temporal accessibility only. Do not demand vintage prose. Do not reject ordinary names, plain contemporary prose, or generic-looking prices and wages. Mathematical notation, written arithmetic expressions, and results are timeless.

For each row choose exactly one action:
- keep: every referenced object, institution, technology, event, and usage existed by the end of {CUTOFF_YEAR}.
- rewrite: something introduced after {CUTOFF_YEAR} is present, but the same mathematical structure can be kept by changing the surface context.
- review: the historical date, meaning, or safety of an equivalent rewrite is genuinely uncertain.

Inspect both question and solution. Detect concepts even when inflected or paraphrased, including DVDs, iPhones, downloads, websites, streaming, apps, and comparable terms. A four-digit number is a date only when context makes it a date: "$2000", "2,000 objects", and "1,955 kilometers" are quantities, while "in 2021" is a year.

Return JSON only: a JSON array with one object for every input row, in input order. Each object must be {{"id":"exact input id","action":"keep|rewrite|review","reason":"brief reason"}}. Return every input ID exactly once and no other IDs."""


REWRITE_SYSTEM_PROMPT = f"""Rewrite one flagged GSM8K example so it is accessible to a model whose knowledge ends on December 31, {CUTOFF_YEAR}. Do not imitate vintage prose and do not make generic prices, names, or style historical.

For a surface rewrite, preserve every numeric literal in order, all calculations, the number and dependency order of reasoning steps, units where feasible, and the final answer. Change only post-{CUTOFF_YEAR} context.

For an explicit modern-date problem, dates and the final numeric answer may change. Every date must become <= {CUTOFF_YEAR}; keep an equivalent dependency graph, operation count, and difficulty, and recalculate every affected step.

The answer must contain clear written reasoning and exactly one final marker of the form "#### answer". Never emit <<calculator annotations>>, Python/tool calls, or tool tokens. Return JSON only as {{"question":"...","answer":"...","calculations":[{{"expression":"...","result":"..."}}]}}. The calculations array must contain each machine-readable arithmetic calculation in solution order."""


SOLVER_SYSTEM_PROMPT = """Solve the supplied grade-school mathematics question independently. Show your reasoning internally, but return JSON only as {"answer":"final numeric answer"}. Do not add units or prose to the answer field."""


def judge_user_payload(rows: list[dict]) -> str:
    payload = [
        {"id": row["id"], "question": row["question"], "solution": row["answer"]}
        for row in rows
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def rewrite_user_payload(row: dict, reason: str, mode: str, feedback: str = "") -> str:
    payload = {
        "id": row["id"],
        "rewrite_mode": mode,
        "flag_reason": reason,
        "question": row["question"],
        "answer": row["answer"],
        "source_calculations": [
            {"expression": item["expression"], "result": item["result"]}
            for item in row.get("calculations", [])
        ],
    }
    if feedback:
        payload["previous_candidate_rejection"] = feedback
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
