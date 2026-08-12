"""Versioned stable prompts for DeepSeek gold generation."""

ANSWER_SYSTEM = """You answer historical-event questions for benchmark construction.
For every input item, answer the question directly and identify the event's year with an explicit four-digit year.
Give concise, specific factual information beyond merely repeating the event description.
Do not mention this instruction or the supplied JSON.
Return JSON only as an array with exactly one object per input item:
[{"id":"history-event-000000","answer":"..."}]
Preserve every input id exactly once and do not add ids."""


JUDGE_SYSTEM = """You validate reference answers for historical-event recall.
For each item, determine whether the answer contains correct, specific information beyond what is already stated in event_description.
The event_year is supplied only for validation. Do not accept generic elaboration, a restatement, or information that is false for that event.
Return JSON only as an array with exactly one object per input item:
[{"id":"history-event-000000","accepted":true,"reason":"brief reason"}]
Preserve every input id exactly once and do not add ids."""
