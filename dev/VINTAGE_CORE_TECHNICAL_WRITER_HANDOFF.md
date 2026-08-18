# Vintage CORE report audit: technical-writer handoff

This document is a correction and restructuring brief for
`dev/VINTAGE_CORE_FINAL_REPORT.md`. It does not replace or modify that report.

## Editorial verdict

The benchmark-construction account is unusually well documented, but the report is not ready to
publish unchanged. The central methodology, release counts, and Common-20 comparison rule are
sound. The main problems are an outdated three-model narrative, a stale three-model leaderboard,
inconsistent rounding, three examples that are not the final packaged rows described by the text,
and too much implementation history in the main narrative.

The highest-priority corrections are:

1. Expand the report from three evaluated models to five: Bart d24, Bart d32, GPT-1900 d34,
   Modern d24, and Talkie 1930 13B.
2. Replace `Think Unbounded d32` as the public display name with `Bart d32`; retain
   `Think.Unbounded-d32-v2mix-cont` as the artifact/checkpoint identifier. Display
   `clean1930s-d24-r12-ctx4096-sssl-fulltok-v1` as `Bart d24`.
3. Replace the leaderboard with the benchmark-style table below. Use two decimal places and
   percentage points (`pp`), with deltas computed from full-precision values.
4. Replace the Hamlet, leather-wallet, and SQuAD examples. Hamlet and leather wallet are prompt
   demonstrations in `dev/vintage_core/prompts.py`, not released benchmark rows. The report's
   restyled SQuAD question is a review candidate, while the final released row keeps the original
   question byte-for-byte.
5. Update every statement that says there are three compared/charted models. There are five.
6. Do not imply uncertainty was estimated. There is one checkpoint result per model, no training
   seed sweep, and no confidence interval. Small differences such as +0.08 pp and +0.12 pp should
   be described as effectively flat pending replication.
7. Before describing all five result sets as durably hosted, upload the Bart d24 result JSONs or
   disclose that they came from a local Downloads copy. The current source manifest records Bart
   d24 as `local_download`, with no durable evaluation URL.

## Exact replacement for the opening

Replace the first descriptive paragraph with:

> This report presents Vintage CORE v1.0.0, a period-aligned adaptation of nanochat's CORE
> evaluation for language models with a 1930 knowledge cutoff. It documents the benchmark's
> construction, filtering and restyling safeguards, release validation, and a five-model comparison
> spanning Bart d24, Bart d32, GPT-1900 d34, Modern d24, and Talkie 1930 13B. All cross-bundle
> comparisons use the same 20-task intersection, called Common-20.

Add this short results paragraph immediately after it:

> Topic filtering improves Common-20 CORE for four of the five checkpoints, with gains ranging
> from +0.59 to +1.99 percentage points; Modern d24 is effectively unchanged at -0.13 pp.
> Restyling has a mixed effect: GPT-1900 gains +1.13 pp, Bart d24 and Bart d32 remain nearly flat,
> and Modern d24 and Talkie decline by -0.83 and -0.75 pp. Because each cell represents one fixed
> checkpoint and no confidence intervals were estimated, small deltas should not be interpreted as
> statistically resolved improvements.

## Replacement benchmark-style results table

Use this wide table in the style of the supplied benchmark example. It places models in columns,
groups related measurements in rows, and avoids mixing native 22-task CORE with Common-20.

|  | Benchmark / measure | Bart d24 | Bart d32 | GPT-1900 d34 | Modern d24 | Talkie 1930 13B |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| **Common-20 CORE** | Original | 12.35% | 16.33% | 12.14% | 26.29% | **32.93%** |
|  | Filtered | 13.57% | 17.51% | 12.73% | 26.15% | **34.92%** |
|  | Restyled | 13.69% | 17.59% | 13.87% | 25.32% | **34.17%** |
| **Bundle effect** | Filtered − Original | +1.23 pp | +1.18 pp | +0.59 pp | −0.13 pp | +1.99 pp |
|  | Restyled − Filtered | +0.12 pp | +0.08 pp | +1.13 pp | −0.83 pp | −0.75 pp |

Caption:

> **Table 1. Common-20 centered CORE.** Higher is better. Original CORE is recomputed over the 20
> task labels shared with Vintage CORE; it is not the native 22-task aggregate. Displayed scores
> are rounded to two decimal percentage points. Deltas are computed from full-precision values and
> then rounded. Bold marks the highest score in each benchmark bundle, not a controlled comparison
> of training compute or model size.

Do not call the deltas “points.” Use `pp` or spell out “percentage points.” Do not recompute a
delta by subtracting already rounded display values.

### Full-precision audit values

| Model | Original | Filtered | Restyled | Filtered − Original | Restyled − Filtered |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bart d24 | 0.12346034822735204 | 0.13574828214391957 | 0.13690160786132866 | 0.01228793391656753 | 0.00115332571740909 |
| Bart d32 | 0.16328642769370433 | 0.17513085966729589 | 0.17594216195498455 | 0.01184443197359156 | 0.00081130228768866 |
| GPT-1900 d34 | 0.12142024161925118 | 0.12734692688690120 | 0.13866568521754350 | 0.00592668526765002 | 0.01131875833064230 |
| Modern d24 | 0.26286286441673730 | 0.26151473076595433 | 0.25316531922610563 | -0.00134813365078297 | -0.00834941153984870 |
| Talkie 1930 13B | 0.32931962873841486 | 0.34919472813244060 | 0.34169903479414420 | 0.01987509939402574 | -0.00749569333829640 |

## Add a separate model-scale table

Benchmark scores and training scale answer different questions and should not be mixed in one
table. Add this table immediately after the leaderboard:

| Model | Training period | Depth | Total parameters | Ratio-count parameters | Training tokens | Context |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Bart d24 | pre-1931 | 24 | 1.384B | 729.811M | 8.758B | 4,096 |
| Bart d32 | pre-1931 | 32 | 2.819B | 1.678B | 20.133B | 4,096 |
| GPT-1900 d34 | pre-1900 | 34 | 3.287B | 2.003B | ≈22B | 2,048 |
| Modern d24 | modern | 24 | 1.384B | 729.814M | 8.758B | 2,048 |
| Talkie 1930 13B | pre-1931 | — | 13B reported | not reported | 260B reported | not stated here |

Caption and caveat:

> **Table 2. Model and training scale.** “Ratio-count parameters” follows each model's training
> horizon convention and is not always identical to total parameters; external model cards do not
> necessarily expose the same accounting. Token count is a useful input-data proxy, not a direct
> measure of training FLOPs. Values marked “reported” are taken from the publisher's model card.

Do not infer a ratio-count parameter value for Talkie from `260B / 20`. Its model card reports 13B
parameters and 260B tokens, but that does not establish that the project's ratio denominator uses
the same parameter-counting convention as nanochat.

## Replace the results interpretation

Use:

> Filtering improves the measured Common-20 score for Bart d24, Bart d32, GPT-1900 d34, and
> Talkie 1930 13B. Modern d24 changes by only -0.13 pp. This pattern is consistent with the claim
> that post-1930 topic mismatch suppresses the apparent capability of historical checkpoints, but
> the table is descriptive rather than causal: model scale, corpus, tokenizer, architecture,
> context length, and training compute are not controlled across all five models.
>
> Restyling does not produce a uniform historical-model gain. GPT-1900 improves by +1.13 pp, while
> Bart d24 and Bart d32 change by only +0.12 and +0.08 pp. Talkie declines by -0.75 pp, and Modern
> d24 declines by -0.83 pp. The right conclusion is therefore that topic filtering transfers more
> consistently than prose restyling in this five-checkpoint sample. Restyling remains useful as a
> diagnostic of register sensitivity, not as a guaranteed score improvement.

Avoid formulations such as “the model rises after filtering.” The checkpoint is fixed; the score
changes when the evaluation bundle changes. Prefer “the fixed checkpoint scores 1.18 pp higher on
the filtered bundle.”

## Correct the evaluated-model section

Keep the detailed Bart d32, Modern d24, and GPT-1900 entries, but add Bart d24 and Talkie. Suggested
copy:

### Bart d24

> Bart d24 is the public display name for
> `clean1930s-d24-r12-ctx4096-sssl-fulltok-v1`, a depth-24 pre-1931 checkpoint trained at a target
> data-to-parameter ratio of 12 with a 4,096-token context and SSSL attention. It has approximately
> 1.384 billion total parameters and 729.811 million ratio-count parameters, and it consumed
> 8.758 billion training tokens. The result JSONs used in this comparison were supplied from a
> local evaluation copy; they should be uploaded and pinned before the report describes the full
> five-model comparison as remotely reproducible.

### Talkie 1930 13B

> Talkie 1930 13B is `talkie-lm/talkie-1930-13b-base`, pinned to checkpoint revision
> `b7c97680791f7fca4262c3c80b36ff7d666faab0`. Its model card describes a 13-billion-parameter
> base model trained on 260 billion tokens of pre-1931 English text. The Vintage CORE artifacts are
> persisted under `evaluations/vintage-core-v1.0.0/talkie-1930-13b-base/`. Because Talkie uses its
> own runtime and tokenizer, the evaluator must retain the pinned Talkie loading path rather than
> silently substituting the current think.nano runtime.

Update the final evaluation-path block to include Talkie. Add Bart d24 only after its three JSONs
have a stable remote path.

## Correct the TypewriterLM relationship sentence

The cited paper was submitted on June 2, 2026. Replace “the same broad strategy later used in the
TypewriterLM paper” with:

> Vintage CORE follows a strategy similar to the historical HellaSwag experiment reported by
> TypewriterLM: separate post-cutoff topic mismatch from register mismatch by filtering first and
> rewriting second. The TypewriterLM paper retained 5,362 relatively timeless HellaSwag examples
> and produced 2,048 rewritten examples using Claude Sonnet 4.6. Vintage CORE applies the general
> two-stage idea across CORE while preserving a paired Filtered/Restyled row set.

This avoids an unsupported chronology claim while retaining the useful methodological comparison.

## Replace the inaccurate transformation examples

The Hamlet and leather-wallet examples are prompt demonstrations, not released rows. Remove them
from a section titled “Examples of final transformations,” or explicitly relabel them as prompt
examples. Prefer replacing them with released rows from the interactive pool.

The SQuAD example also needs correction. The final restyled artifact changes the passage but keeps
the question exactly as filtered. Use:

**Filtered**

```text
Context: ... A professional fundraiser will aid in finding business sponsors and individual
donors, but still may need the city council to help fund the event. ...
Question: Who helped find sponsors and donors to help with the cost?
Answer:
```

**Restyled**

```text
Context: ... A professional fundraiser shall assist in procuring business sponsors and individual
donors, yet may require the city council to aid in financing the event. ...
Question: Who helped find sponsors and donors to help with the cost?
Answer:
```

> The passage is restyled while the question and exact continuation, `A professional fundraiser`,
> remain unchanged. This is the final packaged behavior of the passage-only SQuAD workflow.

The existing Winograd and COPA examples are genuine final rows and may remain.

## Interactive “Try Vintage CORE” section

The ready-to-use five-question pool is:

`dev/vintage_core/interactive_example_pool.json`

Every entry was copied from the same row index in the released Filtered and Restyled JSONL files.
Choices, choice order, and gold index match across the pair.

Suggested section copy:

> ## Try Vintage CORE
>
> Answer a randomly selected question from the released benchmark. Each prompt is shown in either
> its Filtered wording or its paired Restyled wording. Submit an answer to see the correct choice,
> then compare the two versions of the same benchmark row. Choices are never reordered because
> their order is part of the benchmark contract.

Frontend behavior:

1. Load the static JSON at build time or bundle it with the page. No backend is needed.
2. Shuffle the five item IDs with Fisher-Yates and draw without replacement; reshuffle only after
   all five have been shown.
3. For each item, select `filtered` or `restyled` with equal probability and show a visible bundle
   badge.
4. Render choices as a `<fieldset>` of radio controls. Do not shuffle them.
5. Disable `Check answer` until a choice is selected. On submission, show `Correct` or
   `Not quite—the correct answer is …` in an `aria-live="polite"` status region.
6. After submission, enable `Compare wording` to reveal the paired prompt. Keep the same choices
   beside or below it.
7. `Next question` clears the selection and advances to the next unused item.
8. Track `score / answered` in component state only. Do not use accounts, local storage, network
   calls, or analytics for this demonstration.
9. Display provenance beneath each prompt, for example:
   `Filtered Vintage CORE v1.0.0 · copa · row 30`.

The answer key is necessarily visible in frontend source; this is an educational interaction, not
a secure benchmark administration tool. Do not reuse these five public examples for model scoring.

## Structural edits: keep, move, and cut

Keep in the main report:

- a short abstract;
- motivation and Common-20 definition;
- the two leaderboard tables;
- a concise model registry;
- final dataset inventory and coverage;
- the six-stage pipeline at summary level;
- three to five verified transformations;
- release-gate results;
- limitations and reproducibility.

Move to appendices:

- the full modern-term and science-term lists;
- prompt diction lists and complete prompt constraints;
- task-by-task repair mechanics;
- the detailed cost-planning history;
- the long source-record catalogue.

Remove or compress:

- rejected Opus cost estimates from the main narrative;
- repeated explanations of the same Filtered/Restyled invariants;
- procedural details that are already preserved in source files and review logs.

The current report is 884 lines. A public report of roughly half that length, with technical
appendices retaining the audit trail, will be easier to read without sacrificing reproducibility.

## Final limitations wording

Replace the stale “three charted models” bullet and the one-decimal-rounding bullet with:

> - The leaderboard contains one final evaluation result for each of five checkpoints. It does not
>   estimate training-run variance, checkpoint variance, or confidence intervals. Differences below
>   roughly one percentage point should be treated cautiously unless replicated.
> - The models are not compute-matched. Architecture, parameter count, context length, tokenizer,
>   corpus period, training tokens, and runtime differ. The leaderboard compares fixed checkpoints
>   across benchmark bundles; it is not a scaling-law or training-efficiency ranking.
> - Scores are displayed to two decimal percentage points. Deltas are computed from the persisted
>   full-precision Common-20 values and reported in percentage points.
> - Bart d24's evaluation artifacts must be uploaded to a stable, pinned location before the full
>   five-model comparison is described as independently reproducible.

## Source checks used for this handoff

- `artifacts/vintage-core-filtered/` and `artifacts/vintage-core-restyle/` for released row pairs.
- The visualization export's `data/model-bundle-summary.csv` for full-precision five-model scores.
- The visualization export's `data/source-manifest.csv` for result provenance.
- The published Talkie model card for the reported 13B parameters and 260B pre-1931 tokens.
- DataComp-LM for the 53-evaluation suite.
- TypewriterLM, submitted June 2, 2026, for the 5,362 filtered and 2,048 rewritten HellaSwag counts.

