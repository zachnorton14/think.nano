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


REWRITE_SYSTEM_PROMPT = f"""You are a precise copy-editor adapting one GSM8K word problem for a model whose knowledge ends on December 31, {CUTOFF_YEAR}.

Make the smallest safe content edit. Replace only objects, institutions, technologies, events, dates, or usages introduced after {CUTOFF_YEAR}. Usually this means replacing one modern noun phrase consistently in both the question and the written solution. Do not imitate historical prose, embellish the setting, modernize unrelated wording, alter generic names or prices, or add facts and hints.

Preserve the complete written reasoning. A reasoning sentence, intermediate result, equation, unit, and dependency must not be dropped merely because the arithmetic is obvious.

For rewrite_mode "surface":
- Copy every numeric literal in exactly the same order, spelling, punctuation, and multiplicity.
- Preserve the calculation dependency graph, operation order, units where feasible, and `####` final answer.
- Copy source_calculations exactly as the returned calculations array.

For rewrite_mode "date":
- Replace every explicit post-{CUTOFF_YEAR} date with a date no later than {CUTOFF_YEAR}.
- Preserve an equivalent dependency graph, operation count, and difficulty.
- Recalculate each affected reasoning step, calculation audit entry, and final answer so they are internally consistent.

Universal constraints:
- The same mathematical question must remain unambiguous and no easier or harder.
- Keep names, sentence structure, and length close to the source unless a change is required for temporal accessibility.
- The answer must contain full prose reasoning and exactly one final marker `#### answer`.
- Never emit `<<expression=result>>` calculator annotations, Python, tool calls, tool tokens, or answer-only output.
- Return one JSON object only, beginning with `{{` and ending with `}}`, with exactly this shape: {{"question":"...","answer":"...","calculations":[{{"expression":"...","result":"..."}}]}}.
- Before returning, check that the modern reference is removed from both question and solution and that every calculation entry evaluates to its result."""


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
