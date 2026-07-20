# Vintage GSM8K adaptation

This package snapshots official `openai/gsm8k` `main`, removes only `<<expression=result>>`
calculator annotations, and adapts temporally inaccessible rows for a model whose knowledge
ends on December 31, 1930. It preserves official IDs, order, and 7,473/1,319 split counts.

The pipeline is deliberately gated:

1. `prepare` creates an immutable source snapshot and verifies removed calculations.
2. `judge` is cacheable and resumable. It writes each completed request and never treats an
   API error as `keep`.
3. `report` writes `review/judge.md` and `review/decisions.jsonl`.
4. A reviewer sets each flagged row's `decision` to `keep`, `rewrite`, or `manual`, with a
   reason. `manual` rows also need `question`, `answer`, and `calculations`.
5. `rewrite` only processes rows explicitly approved for rewriting.
6. `verify` runs deterministic checks, cross-split leakage checks, an answer-blind solver,
   and the temporal judge.
7. `package` refuses to emit data until all gates pass.

Run `python -m dev.vintage_gsm8k --help` for all options. By default, state is under
`artifacts/vintage-gsm8k/`. Staged attempts are append-only; rerunning a stage resumes from
the latest valid record for each ID.

For training, set `"gsm8k_variant": "vintage"` in the experiment's `data` object or pass
`--gsm8k-variant vintage` to SFT/RL directly. Raw remains the default. Evaluate both with
`-a 'GSM8K|GSM8K-Vintage'` once the vintage data is packaged.
