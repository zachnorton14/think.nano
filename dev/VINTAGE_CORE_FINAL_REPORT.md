# Vintage CORE

## A period-aligned version of CORE for language models with a 1930 knowledge cutoff

This document describes the final Vintage CORE v1.0.0 benchmark, the process used to build it,
and the final comparison of Think Unbounded d32, a modern nanochat d24 model, and Michael Hla's
GPT-1900 d34. It consolidates the final benchmark artifacts, build log, filtering and restyling
code, review records, release validation, and final evaluation workflow into a single report.

The authoritative benchmark artifacts are the tracked bundles in
[`artifacts/vintage-core-filtered`](../artifacts/vintage-core-filtered) and
[`artifacts/vintage-core-restyle`](../artifacts/vintage-core-restyle). The released Hugging Face
dataset is [`jbduran/vintage-core`](https://huggingface.co/datasets/jbduran/vintage-core), pinned
by the evaluation runners to revision `v1.0.0`.

## Introduction

After running training or data ablations, we need a way to decide what helped and what did not.
Validation loss and validation bits per byte, or BPB, are important signals when the validation
distribution is held fixed. They are not, however, directly comparable when the underlying
dataset changes. A model trained on a different corpus can see a different validation
distribution, tokenizer, register, or domain mix, so a change in BPB is not by itself a clean
measure of general capability across data ablations.

Early in the project we therefore used CORE, the metric reported by nanochat for its GPT-2
speedruns. CORE comes from the DataComp-LM work. DataComp-LM evaluated models on 53 downstream
tasks and defined a lower-variance 22-task CORE subset intended to provide useful signal even at
small model scales. Each task is scored as centered accuracy:

```text
centered_accuracy = (accuracy - random_baseline) / (1 - random_baseline)
CORE = mean(centered_accuracy over tasks)
```

This maps random guessing to 0 and perfect accuracy to 1 before the tasks are averaged. It keeps
a binary task with a 50% random floor from receiving more free credit than a four-choice task with
a 25% random floor. The original GPT-2 XL checkpoint scores approximately `0.256525` on nanochat's
22-task CORE implementation. The original source is the
[`DataComp-LM` paper](https://arxiv.org/abs/2406.11794), and nanochat's practical definition and
GPT-2 reference are documented in its
[`LEADERBOARD.md`](https://github.com/karpathy/nanochat/blob/master/dev/LEADERBOARD.md).

CORE solves the validation-distribution problem, but its tasks assume a modern world model. A
historical model can fail because it does not know about websites, software, post-1930 people,
modern organizations, or later scientific concepts. A low score can therefore combine two
different things: a lack of general capability and a mismatch between the benchmark's time period
and the model's training cutoff.

Vintage CORE is our adaptation of CORE for models whose knowledge ends in 1930. It preserves the
existing evaluation mechanics and as much of the original benchmark as possible. It removes two
tasks, filters post-cutoff items from the remaining tasks, restores small tasks with reviewed
period-valid replacements, and creates a second bundle in which eligible prose is restyled toward
the register of writing from roughly 1800 to 1930. The evaluator, task definitions, likelihood
scoring, random baselines, and centered aggregation remain the same.

The benchmark is distributed as two aligned bundles:

- **Filtered Vintage CORE** removes items that require post-1930 knowledge. Surviving items keep
  their original prose. Small tasks are restored to their original size with reviewed backfills.
- **Restyled Vintage CORE** uses the exact same task configuration, item set, row order, choices,
  answers, and protected continuations as the filtered bundle. Eligible prose is restyled into a
  period register. If a rewrite could not be retained safely, the exact filtered row is used.

Because original CORE contains 22 tasks while Vintage CORE contains 20, comparisons across all
three bundles use **Common-20**: the centered mean over the 20 task labels shared by Original,
Filtered, and Restyled CORE. Native 22-task Original CORE and native 20-task Vintage CORE are both
useful within their own settings, but Common-20 is the like-for-like number used in the final
leaderboard.

This design follows the same broad strategy later used in the TypewriterLM paper's historical
HellaSwag experiment: retain the original benchmark construct, filter temporally mismatched
content, and then rewrite the surviving content into a historical register rather than authoring
a wholly new reasoning benchmark. TypewriterLM first retained 5,362 relatively timeless
HellaSwag examples through keyword filtering and then produced 2,048 historically rewritten
examples with Claude Sonnet 4.6. That discussion and Table 6 appear in
[`Pretraining Language Models on Historical Text`](https://arxiv.org/pdf/2606.02991#page=7).

## Final leaderboard

### Evaluation protocol

Each model was evaluated on:

1. Original CORE, containing 22 task labels.
2. Filtered Vintage CORE v1.0.0, containing 20 task labels.
3. Restyled Vintage CORE v1.0.0, containing the same 20 labels and the same physical rows as the
   filtered bundle.

The final comparison is the centered CORE score over the same 20-task intersection. Higher is
better. Original CORE is reduced to those 20 labels only for the Common-20 column; the underlying
original evaluation still runs all 22 tasks.

The final chart reports the following Common-20 scores:

| Model | Original | Filtered | Restyled | Filtered minus Original | Restyled minus Filtered |
| --- | ---: | ---: | ---: | ---: | ---: |
| Think Unbounded d32 | 16.3% | 17.5% | 17.6% | +1.2 points | +0.1 points |
| Modern d24 | 26.3% | 26.2% | 25.3% | -0.1 points | -0.9 points |
| GPT-1900 d34 | 12.1% | 12.7% | 13.9% | +0.6 points | +1.2 points |

These values are the percentages displayed in the final comparison chart. The exact
full-precision values and per-task results are stored in the persisted evaluation JSON files in
the `jbduran/think.nano` Hugging Face model repository under
`evaluations/vintage-core-v1.0.0/`.

The charted result is straightforward. Think Unbounded d32 rises from 16.3% on the original
Common-20 set to 17.5% after filtering and 17.6% after restyling. The modern d24 model is nearly
unchanged by filtering and declines from 26.2% to 25.3% under restyling. GPT-1900 rises from 12.1%
to 12.7% after filtering and to 13.9% after restyling.

### Evaluated models

#### Think Unbounded d32

The final model is `Think.Unbounded-d32-v2mix-cont`, evaluated at final checkpoint step `9600`.
The final evaluation runner is
[`runs/Think.Unbounded-d32-v2mix-cont-full-eval.sh`](https://github.com/zachnorton14/think.nano/blob/dev/runs/Think.Unbounded-d32-v2mix-cont-full-eval.sh).

Its recorded training configuration includes:

- depth 32;
- `1,677,724,672` scaling parameters in the experiment configuration;
- a 4,096-token maximum sequence length;
- a `SSSL` attention-window pattern;
- FP8 tensorwise training;
- a target parameter-to-data ratio of 12;
- a 2,097,152-token total batch size;
- a 20,132,659,200-token mixture schedule;
- clean pre-1930 base data followed by the recorded ratio-21 and ratio-45 midtraining stages;
- a continuation from the parent Think Unbounded d32 checkpoint at step 5,500;
- final evaluation on checkpoint step 9,600.

The evaluation runner verifies the final checkpoint and tokenizer, downloads Vintage CORE
revision `v1.0.0`, evaluates Original, Filtered, and Restyled CORE in full with
`max-per-task=-1`, computes the 20-task intersection, writes `summary.csv`, logs native and
Common-20 results to Weights & Biases, and syncs the evaluation artifacts.

#### Modern d24

The modern comparison model is the nanochat d24 artifact
[`ChrisMcCormick/nanochat-d24-2026-02-02`](https://huggingface.co/ChrisMcCormick/nanochat-d24-2026-02-02),
pinned in the evaluator to artifact revision
`2ccf42323ff3bedcc986191d688e5827f33c237c`. Its runtime is pinned to the corresponding nanochat
revision `7ac837cff8efc0e85502e2b3a934a35e2d937b8d`. The model registry records a published native
Original CORE score of `0.2633`; the final comparison chart uses its Common-20 result, not the
native 22-task aggregate.

#### GPT-1900 d34

The historical reference model is Michael Hla's
[`mhla/gpt1900-d34-22btok`](https://huggingface.co/mhla/gpt1900-d34-22btok), pinned to artifact
revision `d6330f9f0a17ce13da36fb951d7987bb03e6fbd0`. It is a d34 model trained on approximately
22 billion tokens. The evaluation runner uses the nanochat runtime bundled with that artifact,
rather than silently substituting the current think.nano runtime.

The modern d24 and GPT-1900 d34 evaluations were executed by the durable reference runner
[`runs/vintage-core-reference-models.sh`](https://github.com/zachnorton14/think.nano/blob/dev/runs/vintage-core-reference-models.sh).
That runner pins the evaluator to commit `82b7e92adf04aac6418b29e6bbca7ddfd479c462`, restores any
previously completed bundle, uploads each completed JSON immediately, produces the Common-20
tables, and persists the final files under `evaluations/vintage-core-v1.0.0/<model-id>/`.

## Original CORE

CORE is an aggregate evaluation, not a model and not a training loss. nanochat's implementation
is dependency-light and likelihood based. It does not generate free-form responses and it does
not use an LLM judge during evaluation.

The three task formats are:

- **Multiple choice.** Each possible answer is appended to a shared prompt. The evaluator selects
  the option with the lowest average cross-entropy loss over the candidate continuation.
- **Schema.** Two or more contexts vary while a continuation is held fixed. The evaluator selects
  the context under which the shared continuation is most likely.
- **Language modeling.** The model must reproduce the exact continuation through greedy token
  prediction. The item is correct only when the continuation matches.

Most tasks prepend fixed few-shot demonstrations before the scored item. The task manifest
controls the number of demonstrations, delimiters, dataset URI, and task type. The evaluator
shuffles with a fixed seed and is deterministic for a fixed model, tokenizer, bundle, and runtime.

The original 22 task labels and their adaptation decisions were:

| Task | Category | Original N | Final action |
| --- | --- | ---: | --- |
| `squad` | Reading comprehension | 10,570 | Filter and restyle |
| `coqa` | Reading comprehension | 7,983 | Filter and restyle |
| `boolq` | Reading comprehension | 3,270 | Filter and restyle |
| `copa` | Commonsense reasoning | 100 | Filter, backfill to N, restyle |
| `commonsense_qa` | Commonsense reasoning | 1,221 | Filter, backfill to N, restyle |
| `piqa` | Commonsense reasoning | 1,838 | Filter and restyle |
| `openbook_qa` | Commonsense reasoning | 500 | Filter, backfill to N, restyle |
| `jeopardy` | World knowledge | 2,117 | Filter and restyle |
| `bigbench_qa_wikidata` | World knowledge | 20,321 | Filter; copied unchanged in restyle |
| `arc_easy` | World knowledge | 2,376 | Filter and restyle |
| `arc_challenge` | World knowledge | 1,172 | Filter, backfill to N, restyle |
| `bigbench_dyck_languages` | Symbolic problem solving | 1,000 | Drop |
| `agi_eval_lsat_ar` | Symbolic problem solving | 230 | Filter, backfill to N; copied unchanged in restyle |
| `bigbench_cs_algorithms` | Symbolic problem solving | 1,320 | Drop |
| `bigbench_operators` | Symbolic problem solving | 210 | Filter; copied unchanged in restyle |
| `bigbench_repeat_copy_logic` | Symbolic problem solving | 32 | Filter; manual restyle where applicable |
| `hellaswag_zeroshot` | Language understanding | 10,042 | Filter and restyle; shared physical file |
| `lambada_openai` | Language understanding | 5,153 | Filter and light-touch restyle |
| `hellaswag` | Language understanding | 10,042 | Filter and restyle; shared physical file |
| `winograd` | Language understanding | 273 | Filter, backfill to N, restyle |
| `winogrande` | Language understanding | 1,267 | Filter, backfill to N, restyle |
| `bigbench_language_identification` | Language understanding | 10,000 | Filter; copied unchanged in restyle |

The 22 labels contain 91,037 task-level rows. Since the two HellaSwag labels point to the same
10,042-row physical file, this corresponds to 80,995 unique physical source rows. After removing
the two dropped tasks, the 20 retained labels start from 88,717 task-level rows or 78,675 unique
physical rows.

## Why two benchmarks were removed

### `bigbench_cs_algorithms`

`bigbench_cs_algorithms` contains 1,320 examples built around modern computer-science constructs,
including longest-common-subsequence and dynamic-programming problems. The concepts and the task
format are not appropriate for a model whose knowledge and text distribution end in 1930. The
original benchmark audit also found that its centered score remained nearly flat across both data
scaling and model depth. It was therefore removed rather than superficially rewriting modern
computer-science problems into period prose.

### `bigbench_dyck_languages`

`bigbench_dyck_languages` contains 1,000 bracket-sequence completion examples. The mechanics are
not tied to a post-1930 fact, but artificial bracket strings are absent from the prose distribution
on which the historical model was trained. The task was removed because it is out of distribution
for the intended model and does not test a construct retained in Vintage CORE.

These are the only two task-level removals. The other temporally mismatched benchmarks were
adapted at the item level rather than discarded.

## Final Vintage CORE dataset

### Final task inventory

The table below describes the actual packaged v1.0.0 bundles. `Regex removed` counts items with a
hard post-1930 year. `LLM removed` counts additional items removed by the temporal judge or final
reconciliation. `Backfill` counts reviewed replacements added to restore small tasks. `Restyled`
counts meaningful packaged prose changes from the filtered bundle. HellaSwag zero-shot and
few-shot share one physical file, so their counts appear twice at the task-label level.

| Task | Type | Shots | Random baseline | Original | Regex removed | LLM removed | Retained | Backfill | Final | Restyled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bigbench_repeat_copy_logic` | LM | 10 | 0% | 32 | 0 | 0 | 32 | 0 | 32 | 16 |
| `copa` | MC | 0 | 50% | 100 | 0 | 4 | 96 | 4 | 100 | 98 |
| `bigbench_operators` | LM | 10 | 0% | 210 | 0 | 0 | 210 | 0 | 210 | 0 |
| `agi_eval_lsat_ar` | MC | 3 | 20% | 230 | 0 | 12 | 218 | 12 | 230 | 0 |
| `winograd` | Schema | 0 | 50% | 273 | 0 | 9 | 264 | 9 | 273 | 268 |
| `openbook_qa` | MC | 0 | 25% | 500 | 0 | 44 | 456 | 44 | 500 | 490 |
| `arc_challenge` | MC | 10 | 25% | 1,172 | 8 | 159 | 1,005 | 167 | 1,172 | 1,154 |
| `commonsense_qa` | MC | 10 | 20% | 1,221 | 1 | 117 | 1,103 | 118 | 1,221 | 1,213 |
| `winogrande` | Schema | 0 | 50% | 1,267 | 0 | 113 | 1,154 | 113 | 1,267 | 1,242 |
| `piqa` | MC | 10 | 50% | 1,838 | 0 | 519 | 1,319 | 0 | 1,319 | 1,293 |
| `jeopardy` | LM | 10 | 0% | 2,117 | 248 | 231 | 1,638 | 0 | 1,638 | 1,609 |
| `arc_easy` | MC | 10 | 25% | 2,376 | 12 | 344 | 2,020 | 0 | 2,020 | 1,992 |
| `boolq` | MC | 10 | 63% | 3,270 | 1,326 | 929 | 1,015 | 0 | 1,015 | 1,011 |
| `lambada_openai` | LM | 0 | 0% | 5,153 | 8 | 758 | 4,387 | 0 | 4,387 | 2,202 |
| `coqa` | LM | 0 | 0% | 7,983 | 2,142 | 1,571 | 4,270 | 0 | 4,270 | 4,199 |
| `bigbench_language_identification` | MC | 10 | 9.1% | 10,000 | 315 | 2,115 | 7,570 | 0 | 7,570 | 0 |
| `hellaswag_zeroshot` | MC | 0 | 25% | 10,042 | 43 | 3,923 | 6,076 | 0 | 6,076 | 6,030 |
| `hellaswag` | MC | 10 | 25% | 10,042 | 43 | 3,923 | 6,076 | 0 | 6,076 | 6,030 |
| `squad` | LM | 10 | 0% | 10,570 | 3,261 | 3,025 | 4,284 | 0 | 4,284 | 4,244 |
| `bigbench_qa_wikidata` | LM | 10 | 0% | 20,321 | 27 | 10,786 | 9,508 | 0 | 9,508 | 0 |
| **Task-level total** |  |  |  | **88,717** | **7,434** | **28,582** | **52,701** | **467** | **53,168** | **33,091** |

At the physical-file level, the 20-task source contained 78,675 unique rows. The filters retained
46,625 unique rows and the 467 backfills brought the released bundle to 47,092 unique rows.
Filtered and Restyled contain exactly the same 47,092 unique rows.

Meaningful restyle coverage is:

- 27,061 of 47,092 unique physical rows, or 57.5%;
- 33,091 of 53,168 task-level rows, or 62.2%.

The difference between the unique and task-level figures comes from counting the shared
HellaSwag file under both its zero-shot and few-shot task labels.

### What each retained task measures

- `copa`: two-choice causal commonsense.
- `openbook_qa`: four-choice elementary science and physical reasoning.
- `commonsense_qa`: everyday commonsense about people, places, objects, and actions.
- `piqa`: two-choice physical commonsense concerning tools and practical actions.
- `winograd`: pronoun resolution between two candidate antecedents.
- `winogrande`: sentence-completion coreference and semantic plausibility.
- `lambada_openai`: exact prediction of the final word of a book passage.
- `bigbench_language_identification`: identification of the language used in a sentence.
- `hellaswag_zeroshot`: zero-shot selection of a plausible scenario continuation.
- `hellaswag`: the same HellaSwag physical data with ten few-shot demonstrations.
- `boolq`: yes/no reading comprehension over a short passage.
- `coqa`: exact short-answer conversational reading comprehension.
- `squad`: exact-answer passage-based reading comprehension.
- `bigbench_repeat_copy_logic`: exact symbolic repetition under counting and ordering rules.
- `bigbench_operators`: application of newly defined symbolic operators.
- `agi_eval_lsat_ar`: multiple-choice analytical reasoning from a passage and constraints.
- `arc_challenge`: difficult, often multi-step grade-school science reasoning.
- `jeopardy`: exact-answer general knowledge in literature, history, word origins, and science.
- `arc_easy`: basic grade-school scientific knowledge and reasoning.
- `bigbench_qa_wikidata`: exact factual completions derived from Wikidata relations.

## Post-processing pipeline

### 1. Load and exclude

The pipeline loaded the original nanochat evaluation bundle, preserved the original task formats,
and excluded `bigbench_cs_algorithms` and `bigbench_dyck_languages`. All other task labels were
processed. HellaSwag's zero-shot and few-shot labels were recognized as views of the same physical
dataset so filtering and restyling decisions could be shared.

### 2. Deterministic temporal prescan

Every item was concatenated across its prompt, choices, contexts, and continuation and scanned by
two regular expressions.

The year expression recognizes four-digit years from 1500 through 2099. A detected year greater
than 1930 is an authoritative removal. The final rule is:

```text
find every four-digit year in [1500, 2099]
remove the item if any detected year > 1930
```

The modern-term expression flags the following vocabulary families as hints for the LLM judge:

```text
internet, software, website, online, smartphone, iphone, android, google,
facebook, twitter, youtube, super bowl, laptop, astronaut, spacecraft,
satellite, covid, video game, microchip, transistor, helicopter
```

These hints are not automatic removals because a token can be ambiguous; `satellite`, for
example, can refer to a natural moon. Terms such as `television` and `nfl` were deliberately not
treated as modern because they existed by the cutoff. `compute` was excluded because it produced
false positives in `bigbench_operators`.

Generated backfills were also checked against a conservative post-1930 science and technology
list covering neutrons, plate tectonics, subduction, transform faults, DNA, RNA, the genetic code,
antibiotics, radar, jet engines, atomic bombs, nuclear weapons and reactors, ecosystems, the cell
cycle, photocopying, Xerox, and ribosomes. Pre-cutoff concepts such as mitochondria, continental
drift, quantum theory, penicillin, polymers, electrons, protons, chromosomes, and First World War
sonar were explicitly not included in that rejection list.

### 3. LLM temporal filtering

All non-year-removed items, including items in tasks initially labeled `KEEP`, were passed to an
LLM temporal judge. The final configuration used direct OpenAI-compatible API calls with a minimal
project-owned system prompt and no agent harness.

The filter configuration was:

- primary model: `deepseek-v4-flash-free`;
- primary endpoint: OpenCode Zen;
- fallback model: `deepseek-v4-flash`;
- fallback endpoint: OpenCode Go;
- temperature: 0;
- batch size: 10 items;
- stable batch system prompt for prefix caching;
- per-item fallback when a batch response omitted an item or failed to parse;
- resumable per-task JSONL audit files recording item index, keep/remove decision, source,
  regex signals, and reason.

The judge was asked to decide temporal fairness only. Difficulty, quality, and correctness were
outside the filtering decision. It removed an item when answering required knowledge of a
post-1930 year, person, place, organization, brand, creative work, technology, invention,
scientific discovery, event, or concept. It retained physical and causal commonsense, arithmetic,
logic, pre-1930 science, classical history and literature, and ordinary objects and technologies
that existed before 1930.

Named-entity judgment was particularly important for `bigbench_qa_wikidata`: a relation may not
contain a year or an obvious modern word while still asking about a person or organization that
did not exist before the cutoff.

The most frequent recorded removal reasons included unresolved filter failures removed
conservatively, modern ecosystem terminology, the post-1930 Scottish Parliament, online
shopping, the Super Bowl, the European Union, frisbees, the United Methodist Church, post-1930
NFL players and teams, and websites.

### 4. Backfilling small tasks

Filtering can make small tasks too coarse or noisy. Tasks whose **original** size was at most
1,300 examples were restored to their original size after filtering. Larger tasks retained their
surviving rows and were not padded.

The final bundle contains 467 backfills:

| Task | Backfills |
| --- | ---: |
| `copa` | 4 |
| `agi_eval_lsat_ar` | 12 |
| `winograd` | 9 |
| `openbook_qa` | 44 |
| `arc_challenge` | 167 |
| `commonsense_qa` | 118 |
| `winogrande` | 113 |
| **Total** | **467** |

Backfills were generated with GLM 5.2 through the clean API. Each replacement had to match the
original task's schema and capability, use timeless reasoning or knowledge well established
before 1930, preserve the required key set and option count, contain exactly one defensible
answer, use period-clean distractors, and set the gold index to the actually correct answer in
the new item. ARC-Challenge replacements were required to retain applied, multi-step science
difficulty rather than collapse into simple trivia.

The backfills went through deterministic validation, review files, a 432-record audit of the
staged set, and a targeted regeneration pass covering 72 rejected or borderline records. The
final package contains the post-review replacements and provenance fields.

### 5. Construction of the restyled bundle

The restyled bundle was built downstream from the filtered bundle. It did not choose a new item
set. Its purpose was to change language register while holding benchmark content and scoring
contracts fixed.

The main restyle configuration used:

- primary model: `mimo-v2.5-free`;
- primary endpoint: OpenCode Zen;
- operational fallback: `mimo-v2.5` through OpenCode Go;
- prompt version recorded by the generation pipeline as `restyle-v3`;
- deterministic style-hint assignment by row index;
- style hints `schoolbook`, `examination`, `encyclopaedia`, and `miscellany`, weighted 35%, 30%,
  20%, and 15%;
- staged candidates separate from approved rows;
- deterministic validation before approval and packaging;
- exact filtered fallback for unsafe, rejected, or unapproved generations.

Four tasks were intentionally copied unchanged into the restyled bundle:

- `bigbench_operators`;
- `agi_eval_lsat_ar`;
- `bigbench_language_identification`;
- `bigbench_qa_wikidata`.

`bigbench_repeat_copy_logic` was handled as a manual-special-case task; 16 of its 32 rows differ
meaningfully from filtered. HellaSwag was generated once and shared between the few-shot and
zero-shot task labels.

### Restyle prompt specification

The main prompt instructed the model to act as a copy editor, not a benchmark author. The target
was the plain formal register of schoolbooks, readers, examination papers, encyclopedias, and
newspapers written between roughly 1800 and 1930. Mock-Elizabethan language such as `thee`,
`thou`, and `forsooth` was prohibited.

The target voice was described as measured and exact, using subordinate clauses, semicolons,
occasional passive voice, and quiet declarative certainty. Suggested diction included:

```text
figure out -> ascertain, determine
a lot of -> a great many
kids -> children
guy -> man, fellow
okay -> very well
gets -> becomes, obtains, receives
really / very -> indeed, exceedingly
big -> great, vast
famous -> celebrated
strange -> curious, singular
use -> employ
need -> require
buy -> purchase
start -> commence
show -> exhibit
on -> upon, where natural
```

The style directions were subordinate to strict format rules:

- For multiple-choice items, only the stem or query could be restyled. Every choice had to remain
  byte-for-byte identical and in the same order, and the gold index could not change.
- For schema items, the shared continuation had to remain byte-for-byte identical. Both candidate
  contexts had to receive the same conservative edit so their original minimal difference was
  preserved. New causal or disambiguating language was prohibited.
- For exact-continuation language-modeling items, the continuation or answer had to remain
  byte-for-byte identical. The edited context still had to lead naturally and unambiguously to
  that target.
- Leading `Question:` or `Q:` tokens, trailing `Answer:` or `A:` tokens, labels, protected line
  breaks, and other task scaffolding had to remain exact.
- A goal had to remain a goal, a question a question, and a fragment a fragment. Restyling could
  not change the speech act tested by the answer choices.
- If choices grammatically completed the stem, the edited stem had to join correctly with every
  choice.
- Numbers, units, dates, formulas, proper names, quoted material, key sets, counts, row order,
  choices, gold labels, and protected continuations had to remain unchanged.
- The rewrite could not add hints, ambiguity, post-1930 content, new historical facts, or content
  absent from the source. It had to stay within approximately 1.5 times the original length.

The prompt's core self-check was: same meaning, same single correct answer, same keys and order,
byte-identical protected fields, intact scaffolding and grammatical joints, a genuine period
register where possible, and no new anachronism.

### Task-specific restyling

The initial general restyle pass exposed several task-specific failure modes. The final benchmark
therefore includes specialized processing rather than relying on a single unconstrained rewrite.

#### SQuAD and CoQA

Long-form reading-comprehension rows contain immutable `Context:`, `Question:`, and `Answer:`
machinery. Passage-only rewriting was introduced so the model receives bare passage prose, while
the benchmark scaffold, question, answer blank, and protected answer spans are reconstructed in
code. The passage prompt requires exact preservation of every number, proper name, title,
technical term, quoted span, fact, and protected answer phrase. It prohibits summarization,
compression, added information, and non-ASCII punctuation.

#### BoolQ

The passage and question structure is protected, the fixed yes/no answer choice contract remains
unchanged, and rows with scaffold, modality, quotation, number, or semantic drift fall back to
their filtered originals.

#### Jeopardy

The category prefix, clue contract, and target slot require special protection. The specialized
prompt receives a clue and hidden target, returns only the restyled clue, and is prohibited from
emitting the target or an answer-specific synonym. Category metadata and visible prefixes are
restored during packaging.

#### HellaSwag

HellaSwag requires every edited stem to join grammatically with every protected continuation.
The final validator checks choice absorption, answer leakage, digit and quotation preservation,
shared-file identity, and stem-choice joints. The same physical file is used for both the zero-shot
and ten-shot labels.

#### LAMBADA

LAMBADA is sensitive to any edit that changes how predictable the last word is. The final
light-touch workflow freezes the target continuation and the final sentence or fragment. Dialogue
structure, speakers, quoted spans, attribution verbs, sentence count, tense, modality, degree,
and punctuation are protected. Candidate sentence edits receive an additional semantic audit;
uncertain sentences remain original. This produced meaningful changes in 2,202 of 4,387 rows.

#### Winograd and Winogrande

Schema contexts are treated as minimal pairs. The same conservative transformation is applied to
both contexts, the exact shared continuation is protected, and edits that add a reason, agent,
authority, emphasis, or answer cue are rejected.

### 6. Offline repair and final packaging

The first packaged restyle passed shallow schema checks but a later exhaustive audit found
release-blocking semantic and structural defects in some generated rows. The pre-repair snapshot
is preserved in Git commit `c346dc2`. The filtered reference was first tracked in commit
`25c53a0`.

The repair process was deliberately conservative. Rows with unsafe generations were replaced by
the exact same-index row from the filtered reference; safe generations were kept byte-for-byte.
Missing source metadata was restored. Subsequent specialized repair passes raised safe coverage
again, including the passage-only long-form workflow and the light-touch LAMBADA workflow. This
is why the current final coverage is higher than the earlier July 10 offline-repair snapshot.

The final restyled bundle combines:

- safe model-generated restyles;
- reviewed manual rewrites;
- deterministic specialized repairs;
- exact filtered-original fallbacks.

An unchanged fallback is an explicit part of the release design. It preserves the filtered item
and scoring contract when a period rewrite cannot be accepted safely.

## Examples of final transformations

The following examples illustrate transformations preserved in the final review records. Choices
and gold labels are shown to make clear that the task contract is unchanged.

### Multiple choice

Filtered:

```text
Question: Who wrote the tragedy Hamlet?
Choices: Shakespeare; Dickens; Homer; Dante
```

Restyled:

```text
Question: By whom was the tragedy of Hamlet written?
Choices: Shakespeare; Dickens; Homer; Dante
```

### Physical reasoning

Filtered:

```text
Question: How do I remove stains from a leather wallet?
```

Restyled:

```text
Question: State by what means stains may be removed from a wallet of leather.
```

The two answer choices remain exact.

### Schema minimal pair

Filtered:

```text
[0] The city councilmen refused the demonstrators a permit because the city councilmen
[1] The city councilmen refused the demonstrators a permit because the demonstrators
continuation: feared violence.
```

Restyled:

```text
[0] The city councilmen denied the demonstrators a permit, because the city councilmen
[1] The city councilmen denied the demonstrators a permit, because the demonstrators
continuation: feared violence.
```

The continuation and the minimal difference between the alternatives remain exact.

### Causal continuation

Filtered:

```text
The man drank heavily at the party, therefore
```

Restyled:

```text
The man had drunk heavily at the party; consequently
```

The protected candidate consequences remain unchanged and both continue to join grammatically
with the edited stem.

### SQuAD passage and question

Filtered:

```text
Context: ... A professional fundraiser will aid in finding business sponsors and individual
donors, but still may need the city council to help fund the event. ...
Question: Who helped find sponsors and donors to help with the cost?
Answer:
```

Restyled:

```text
Context: ... A professional fundraiser shall assist in procuring business sponsors and individual
donors, yet may require the city council to aid in financing the event. ...
Question: Who assisted in procuring sponsors and donors to help defray the cost?
Answer:
```

The exact continuation remains `A professional fundraiser`.

The complete final examples are the JSONL rows in the two tracked artifact directories. The
original fully assembled prompts and five source examples per original task are also reproduced
in [`VINTAGE_CORE_BENCHMARK.md`](VINTAGE_CORE_BENCHMARK.md).

## Quality assurance

### Filter audit

Every retained task received the deterministic scan and LLM temporal filter. The build log records
the total, hard-year removals, LLM removals, survivors, backfills, and final count for each task.
The per-item audit files record the reason for each keep or removal decision.

### Backfill audit

Backfill review checked:

1. gold-answer correctness;
2. a unique defensible answer;
3. benchmark construct and schema fidelity;
4. knowledge and terminology compatible with the cutoff.

Rejected or borderline records were regenerated or revised, then deterministically validated and
merged offline.

### Restyle audit and repair

The pre-repair restyle audit compared every one of the 47,092 unique rows and included 719 manual
paired reviews. It checked row counts and order, task configuration, key sets, choices, gold
labels, continuations, scaffolds, numbers, quoted spans, answer occurrences, edit and length
outliers, temporal-regex hits, punctuation, approved coverage, and fallback behavior.

The audit identified failures such as deleted question scaffolds, answers inserted into contexts,
changed numeric facts, missing Jeopardy prefixes, broken stem-choice joints, and prompt-provenance
ambiguity. Those findings drove the offline reverts, stricter validators, and specialized repair
passes described above.

### Final release gate

The current bundle validation covers all 47,092 unique rows and reports zero issues. It verifies:

- identical task configuration between Filtered and Restyled;
- identical task counts, physical row order, and source key sets;
- exact choices, choice order, and gold labels;
- protected language-modeling continuations;
- strict digit-bearing tokens, including years and ordinals;
- quoted spans;
- BoolQ, CoQA, SQuAD, CommonsenseQA, and Jeopardy scaffolding;
- no newly inserted exact answer-choice or continuation text;
- schema minimal-pair preservation and grammatical continuation joints;
- identity of the physical HellaSwag data shared across both labels.

The release can be checked offline with:

```bash
python -m dev.vintage_core.bundle_validation \
  --source artifacts/vintage-core-filtered \
  --candidate artifacts/vintage-core-restyle
```

The expected final output is:

```text
validated_rows=47092 issues=0
```

## Cost

The repository records the model configuration, some provider usage counters, and paid-equivalent
pricing used for monitoring. It does not contain one complete final cash ledger covering every
filter, backfill, restyle, repair, free-tier call, subscription call, and retry. A precise total
cash expenditure is therefore not recoverable from the final tracked artifacts alone.

The implemented pipeline was designed around free or subscription-backed endpoints:

- filtering used DeepSeek V4 Flash free as the primary route and the paid OpenCode Go route as a
  fallback;
- backfilling used GLM 5.2 through OpenCode Go;
- restyling used MiMo 2.5 free as the primary route and paid MiMo 2.5 as a fallback;
- offline validation, reconciliation, reversion, packaging, and bundle repair did not require
  model calls.

The restyle runner records the following paid MiMo Go equivalent rates for monitoring:

| Token class | Recorded rate |
| --- | ---: |
| Uncached input | $0.14 per million tokens |
| Cached input | $0.0028 per million tokens |
| Output | $0.28 per million tokens |

The early planning document estimated approximately $2.60 for a full DeepSeek filter pass,
$20-$30 for a small Opus backfill job, approximately $360 for a task-capped Opus restyle, and
approximately $1,100 for a full all-Opus restyle. Those were planning estimates for a pipeline
that was not ultimately used. They should not be reported as the final project cost.

The final factual cost statement is therefore:

> Vintage CORE was produced primarily through free-tier and subscription-included model access,
> with paid fallbacks available. The repository does not preserve a complete final cash ledger,
> so the exact total direct spend is not reported. Earlier all-API and all-Opus estimates describe
> rejected planning options rather than the final implementation.

## Reproducibility and release artifacts

### Benchmark bundle

- Release: `jbduran/vintage-core`, revision `v1.0.0`.
- Filtered subdirectory: `filtered/`.
- Restyled subdirectory: `restyled/`.
- Expected task labels: 20.
- Expected unique rows in each bundle: 47,092.
- Local filtered reference: [`artifacts/vintage-core-filtered`](../artifacts/vintage-core-filtered).
- Local canonical restyle: [`artifacts/vintage-core-restyle`](../artifacts/vintage-core-restyle).
- Pre-repair restyle snapshot: Git commit `c346dc2`.
- First tracked filtered reference: Git commit `25c53a0`.

### Evaluator

The evaluator computes raw per-task results, centered per-task results, native CORE, and
Common-20 CORE. It writes one JSON file per bundle plus summary and per-task CSVs. The final d32
runner also logs every raw and centered task result to the existing W&B run.

The final evaluation paths are:

```text
evaluations/vintage-core-v1.0.0/Think.Unbounded-d32-v2mix-cont/
evaluations/vintage-core-v1.0.0/modern-d24/
evaluations/vintage-core-v1.0.0/gpt1900-d34/
```

Each result directory is expected to contain `original.json`, `filtered.json`, `restyled.json`,
and summary tables. The d32 training experiment also keeps its results under
`experiments/Think.Unbounded-d32-v2mix-cont/evals/vintage_core/` before synchronization.

### Important comparison conventions

- Use native Original CORE when comparing against the nanochat GPT-2 threshold of `0.256525`.
- Use Common-20 when comparing Original, Filtered, and Restyled bundles.
- Do not place a native 22-task Original score beside a native 20-task Vintage score without
  labeling the difference.
- Treat HellaSwag zero-shot and few-shot as two task labels but one physical dataset when reporting
  storage or unique-row counts.
- Report restyle coverage because the released restyled bundle deliberately includes exact
  filtered fallbacks.
- Keep the release revision `v1.0.0` and model artifact revisions attached to published results.

## Scope and recorded limitations

The following properties are part of the final benchmark record:

- Vintage CORE adapts original CORE; it is not a newly authored general-intelligence benchmark.
- The cutoff is 1930. Content established by 1930 is allowed even when it feels old-fashioned or
  technologically advanced, while post-1930 facts and concepts are removed.
- The LLM filter depends partly on the judge's entity knowledge. The project retains per-item
  reasons and review artifacts so those decisions can be audited.
- The random baselines and scoring implementation are inherited from CORE. Exact-match language
  modeling can undercount semantically correct variants; the project retained that scorer so all
  models are evaluated consistently.
- Restyled CORE is only partially restyled: 57.5% of unique physical rows contain meaningful
  vintage or manual prose changes. The remainder are deliberate filtered-original fallbacks or
  designated exact-copy tasks.
- Restyling is constrained by correctness. Choices, gold answers, continuations, and task
  scaffolding take priority over stylistic coverage.
- The final leaderboard contains one final evaluation result for each of the three charted models.
  It is a model-and-bundle comparison, not a claim that every possible historical or modern model
  responds identically.
- The displayed chart rounds Common-20 scores to one decimal percentage point. The persisted JSON
  files contain full-precision aggregates and per-task results.

## Source record

The report above incorporates the substantive contents of the following project records:

- [`VINTAGE_CORE_BENCHMARK.md`](VINTAGE_CORE_BENCHMARK.md): original CORE definition, task formats,
  all 22 source tasks, sample prompts, temporal scan, signal analysis, and removal decisions.
- [`vintage_core/LOG.md`](vintage_core/LOG.md): final item-level filtering counts, backfills, final
  task sizes, common removal reasons, and review samples.
- [`vintage-core-plan-v2.md`](vintage-core-plan-v2.md): final pipeline design, two-bundle A/B,
  all-task filtering, low-N backfill rule, direct API requirement, and planned verification.
- [`vintage_core/config.py`](vintage_core/config.py): final task verdicts, drop set, backfill
  threshold, output paths, model identifiers, and endpoint roles.
- [`vintage_core/temporal.py`](vintage_core/temporal.py): cutoff year, year regex, modern-term
  hints, and post-1930 science validation terms.
- [`vintage_core/prompts.py`](vintage_core/prompts.py): final filter, backfill, general restyle,
  passage-only, Jeopardy, and LAMBADA prompt specifications.
- [`vintage_core/filter.py`](vintage_core/filter.py): batching, fallbacks, audit persistence,
  deduplication of shared physical tasks, and resumption behavior.
- [`vintage_core/restyle.py`](vintage_core/restyle.py): staging, prompt version, style distribution,
  task-specific processing, validation, paid-equivalent accounting, and packaging.
- [`vintage_core/review/backfill_audit.md`](vintage_core/review/backfill_audit.md): semantic audit of
  staged replacement items.
- [`vintage_core/review/regeneration_applied.md`](vintage_core/review/regeneration_applied.md):
  targeted regeneration record for rejected and borderline backfills.
- [`vintage_core/review/restyle_bundle_audit.md`](vintage_core/review/restyle_bundle_audit.md):
  exhaustive historical pre-repair audit and the defects that led to the release repair.
- [`vintage_core/review/restyle_repair_report.md`](vintage_core/review/restyle_repair_report.md):
  offline reversion strategy, restored metadata, and release-gate definition.
- [`../artifacts/vintage-core-filtered/EVAL_GAUNTLET.md`](../artifacts/vintage-core-filtered/EVAL_GAUNTLET.md):
  final task descriptions, final counts, backfill composition, task types, shots, and baselines.
- [`../artifacts/vintage-core-restyle/RESTYLE_REPORT.md`](../artifacts/vintage-core-restyle/RESTYLE_REPORT.md):
  final task-level and physical-row restyle coverage.
- [`../artifacts/VINTAGE_CORE.md`](../artifacts/VINTAGE_CORE.md): tracked release provenance and
  validation command.
- [`vintage_core_colab/vintage_core_eval.py`](vintage_core_colab/vintage_core_eval.py): pinned
  multi-model evaluator and Common-20 table generation.
- [`nanochat/core_eval.py`](../nanochat/core_eval.py): underlying likelihood-based CORE scoring.
- [`scripts/base_eval.py`](../scripts/base_eval.py): checkpoint evaluation and structured result
  output.

External references:

- Jeffrey Li et al., [DataComp-LM: In search of the next generation of training sets for language
  models](https://arxiv.org/abs/2406.11794).
- Andrej Karpathy, [nanochat](https://github.com/karpathy/nanochat).
- Andrej Karpathy, [nanochat Time-to-GPT-2 leaderboard](https://github.com/karpathy/nanochat/blob/master/dev/LEADERBOARD.md).
- Andrej Karpathy, [Beating GPT-2 for much less than $100](https://github.com/karpathy/nanochat/discussions/481).
- Xiaoxi Luo et al., [Pretraining Language Models on Historical Text](https://arxiv.org/abs/2606.02991).
- Vintage CORE dataset, [`jbduran/vintage-core`](https://huggingface.co/datasets/jbduran/vintage-core).
- Think Unbounded and persisted evaluation artifacts,
  [`jbduran/think.nano`](https://huggingface.co/jbduran/think.nano).
- Michael Hla's GPT-1900 d34 artifact,
  [`mhla/gpt1900-d34-22btok`](https://huggingface.co/mhla/gpt1900-d34-22btok).
- Modern nanochat d24 artifact,
  [`ChrisMcCormick/nanochat-d24-2026-02-02`](https://huggingface.co/ChrisMcCormick/nanochat-d24-2026-02-02).

