# Vintage CORE Filtered - Eval Gauntlet

This is the Artifact A Vintage CORE bundle. Source items requiring post-1930
knowledge are removed under the reconciled temporal policy, dropped benchmarks are
excluded, and eligible low-N tasks are restored with reviewed period-valid backfills.
Counts below describe the current packaged bundle, including committed backfills.

Bundle: `/Users/jonathanduran-ortiz/.cache/nanochat/vintage-core-filtered`

## Scoring

The existing CORE scorer is unchanged. Multiple-choice and schema tasks use
accuracy, language-modeling tasks use exact continuation match, and centered
metrics use the random baselines in `eval_meta_data.csv`.

## Commonsense Reasoning

### `copa`

- Task type: multiple choice
- Few-shot examples: 0
- Final datapoints: 100
- Composition: 96 retained + 4 reviewed backfills
- Random baseline: 50%
- Description: Cause-and-effect commonsense questions requiring selection between two possible causes or consequences.

### `openbook_qa`

- Task type: multiple choice
- Few-shot examples: 0
- Final datapoints: 500
- Composition: 456 retained + 44 reviewed backfills
- Random baseline: 25%
- Description: Four-choice elementary science questions testing factual knowledge and physical or scientific reasoning.

### `commonsense_qa`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 1221
- Composition: 1103 retained + 118 reviewed backfills
- Random baseline: 20%
- Description: Four-choice questions testing everyday commonsense knowledge and basic reasoning about people, places, and objects.

### `piqa`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 1319
- Composition: 1319 retained + 0 reviewed backfills
- Random baseline: 50%
- Description: Two-choice physical commonsense questions testing practical knowledge of objects, tools, and everyday actions.

## Language Understanding

### `winograd`

- Task type: schema
- Few-shot examples: 0
- Final datapoints: 273
- Composition: 264 retained + 9 reviewed backfills
- Random baseline: 50%
- Description: Winograd schema questions testing semantic resolution of an ambiguous pronoun between two candidate antecedents.

### `winogrande`

- Task type: schema
- Few-shot examples: 0
- Final datapoints: 1267
- Composition: 1154 retained + 113 reviewed backfills
- Random baseline: 50%
- Description: Two-choice sentence-completion schemas testing commonsense coreference and semantic plausibility.

### `lambada_openai`

- Task type: language modeling
- Few-shot examples: 0
- Final datapoints: 4387
- Composition: 4387 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Book passages requiring exact prediction of the final word from the preceding context.

### `bigbench_language_identification`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 7570
- Composition: 7570 retained + 0 reviewed backfills
- Random baseline: 9.1%
- Description: Four-choice identification of the language used in a presented sentence.

### `hellaswag_zeroshot`

- Task type: multiple choice
- Few-shot examples: 0
- Final datapoints: 6076
- Composition: 6076 retained + 0 reviewed backfills
- Random baseline: 25%
- Description: Zero-shot selection of the most plausible continuation for an everyday scenario.

### `hellaswag`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 6076
- Composition: 6076 retained + 0 reviewed backfills
- Random baseline: 25%
- Description: Few-shot selection of the most plausible continuation for an everyday scenario.

## Reading Comprehension

### `boolq`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 1015
- Composition: 1015 retained + 0 reviewed backfills
- Random baseline: 63%
- Description: Short passages followed by yes-or-no reading-comprehension questions scored as multiple choice.

### `coqa`

- Task type: language modeling
- Few-shot examples: 0
- Final datapoints: 4270
- Composition: 4270 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Conversational passage-based questions requiring an exact short answer using the story and preceding dialogue.

### `squad`

- Task type: language modeling
- Few-shot examples: 10
- Final datapoints: 4284
- Composition: 4284 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Passage-based reading comprehension requiring an exact answer supported by the supplied context.

## Symbolic Problem Solving

### `bigbench_repeat_copy_logic`

- Task type: language modeling
- Few-shot examples: 10
- Final datapoints: 32
- Composition: 32 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Symbolic instruction-following tasks requiring exact repetition of words under simple counting and ordering rules.

### `bigbench_operators`

- Task type: language modeling
- Few-shot examples: 10
- Final datapoints: 210
- Composition: 210 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Symbolic problems requiring application of newly defined mathematical operators to compute an exact result.

### `agi_eval_lsat_ar`

- Task type: multiple choice
- Few-shot examples: 3
- Final datapoints: 230
- Composition: 218 retained + 12 reviewed backfills
- Random baseline: 20%
- Description: LSAT-style analytical reasoning games requiring deductions from a passage and a set of logical constraints.

## World Knowledge

### `arc_challenge`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 1172
- Composition: 1005 retained + 167 reviewed backfills
- Random baseline: 25%
- Description: The difficult ARC science split: four-choice grade-school questions requiring applied, often multi-step scientific reasoning.

### `jeopardy`

- Task type: language modeling
- Few-shot examples: 10
- Final datapoints: 1638
- Composition: 1638 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Exact-answer general-knowledge clues drawn from literature, history, word origins, and science categories.

### `arc_easy`

- Task type: multiple choice
- Few-shot examples: 10
- Final datapoints: 2020
- Composition: 2020 retained + 0 reviewed backfills
- Random baseline: 25%
- Description: The easier ARC science split: four-choice grade-school questions testing basic scientific knowledge and reasoning.

### `bigbench_qa_wikidata`

- Task type: language modeling
- Few-shot examples: 10
- Final datapoints: 9508
- Composition: 9508 retained + 0 reviewed backfills
- Random baseline: 0%
- Description: Exact factual completions derived from structured Wikidata relations.
