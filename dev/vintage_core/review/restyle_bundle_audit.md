# Vintage CORE Restyle Bundle Audit

Date: 2026-07-10

Compared bundles:

- Source: `~/.cache/nanochat/vintage-core-filtered`
- Candidate: `~/.cache/nanochat/vintage-core-restyle`

## Verdict

The filtered/restyle A/B design is sound, and several core invariants are intact, but the
current packaged restyle is **not eval-safe**. It loads successfully, yet loading and shallow
schema validation miss release-blocking regressions in the mutable prose.

The highest-risk tasks are CoQA, SQuAD, Jeopardy, ARC-Easy, and HellaSwag. COPA, Winograd,
Winogrande, CommonsenseQA, PIQA, OpenBookQA, ARC-Challenge, and BoolQ need selective repair.
The four copy-designated tasks and deferred LAMBADA have no restyle regression because they are
byte-identical to the filtered bundle.

## Coverage and method

- Exhaustive paired comparison of all 47,092 unique physical rows (53,168 task-level rows;
  HellaSwag is shared by the zero-shot and few-shot labels).
- Verified task config, row counts/order, keys, choices, gold labels, continuations, scaffolds,
  literal numbers, quoted spans, answer occurrence, edit/length outliers, temporal regex hits,
  non-ASCII punctuation, approved coverage, and byte-identical fallback behavior.
- 719 manual paired reviews, selected from all small tasks plus high-edit, high-expansion,
  scaffold, answer-overlap, literal-change, and semantic-risk strata.
- All 100 COPA rows and all 32 repeat-copy rows were manually checked.

## What is correct

- `core.yaml` is identical between filtered and restyle: 20 tasks and unchanged scoring config.
- Every packaged dataset has the same row count and order as filtered.
- For normally restyled tasks, choices/order, gold labels, and protected continuations are exact.
- The 214 eligible-but-unapproved unique rows are byte-identical filtered fallbacks. Leaving a
  hard item original is safer than accepting a lossy rewrite, but this should be reported clearly.
- HellaSwag is generated once and correctly shared by `hellaswag` and `hellaswag_zeroshot`.
- No newly introduced post-1930 regex/science hit was found.
- 53 repository tests pass, but the tests do not cover the major failure classes below.

## Release blockers and systemic defects

### 1. Long-form scaffolding is mutable and frequently disappears

- SQuAD: 1,515/4,284 fail strict `Context:/Question:/Answer:` scaffold/line preservation.
  1,103 contain neither literal `Question:` nor `Answer:`; 1,080 have no `Question:`, no question
  mark, and no answer/response blank. Example idx 1 deletes the question entirely and leaves the
  continuation `a week` answering nothing.
- CoQA: 973/4,270 fail strict story/history/final-question/answer scaffold preservation; 516 do
  not end in the required blank `Answer:` cue. At least 16 rows wholesale-delete the final query
  machinery (for example idx 1415).
- BoolQ: 15 rows lose `Passage:` and/or `Question:` labels.

`validate_item()` checks LM continuation identity and target-occurrence decreases, but does not
freeze internal scaffolding.

### 2. Gold answers are copied into editable contexts

- CoQA: 31 contexts newly end with the exact continuation, including idx 140
  (`Answer: a bear`), idx 1640 (full gold sentence), and idx 4044 (`Answer: Three`).
- SQuAD: 8 direct filled-answer leaks: 80, 637, 1372, 1650, 2040, 2447, 2617, 3373.
- Jeopardy: 9 new case-insensitive target occurrences; idx 100 directly names Benito Mussolini.
- ARC-Easy: idx 1571 inserts `atmosphere` (the gold choice) into the stem; idx 1606 inserts
  `one meter`.
- Winogrande idx 260 paraphrases the protected continuation inside the context.
- PIQA idx 220 and 702 supply/paraphrase their gold choices in the stem.
- HellaSwag idx 1658, 3966, 5148, and 5704 absorb substantial gold-continuation content.

The LM validator rejects only target occurrence decreases, not increases. MC validation does not
reject new answer-choice text in the stem.

### 3. Number preservation has a regex blind spot

The current number regex does not see an integer followed by sentence punctuation, digit
ordinals such as `19th`, or prefixed forms such as `c1600`. This allowed factual changes to pass
`apply` as valid.

- CoQA: 76 rows fail strict digit-token preservation (22 source passages).
- SQuAD: 250 rows fail strict digit-token preservation (106 source passages).
- HellaSwag: 11 rows change/delete digits (shared by both task labels).
- BoolQ idx 495 changes the digit sequence.
- Examples: SQuAD idx 3078 changes `1892` to `the following year`; idx 4060 changes `1756` to
  `the ensuing year`; idx 4085 changes `1757` to `the preceding year`.

### 4. Jeopardy's task contract is not protected

- 108/1,638 contexts fail exact uppercase category-prefix preservation.
- The separate `category` key is dropped from 1,637 restyled rows.
- idx 1316 changes a clue whose target is `rhinestones` into a question asking for the Rhine.
- idx 265 produces the broken joint `New this` + `South Wales`.
- idx 286 removes the unknown city slot for target `Charleston`.
- idx 1490 removes/obscures the requested nickname slot for `spuds`.

The current scorer ignores the separate `category` key, but losing the visible prefix can remove
disambiguating evidence and violates the promised byte-for-byte prefix rule.

### 5. Prompt provenance is not reproducible

The prompt was materially edited after v3 candidates already existed, but `PROMPT_VERSION` was
returned to `restyle-v3` so existing wrappers would not become stale. The bundle therefore mixes
outputs from different prompt text under the same version identifier. A prompt content hash should
be stored and validated instead of relying only on a hand-maintained version string.

### 6. The built-in audit is too shallow

`_audit_flags()` reruns the same incomplete validator and checks whole-JSON length. Whole-JSON
length is diluted by protected choices and misses stem-only over-expansion. It does not detect
scaffold deletion, filled answers, new choice text, Jeopardy prefix loss, terminal-joint
punctuation, proper-name loss, or semantic difficulty drift.

### 7. Hard style rules are not enforced

- At least 820 unique items introduce non-ASCII punctuation despite the ASCII-only rule
  (principally em dashes; HellaSwag counted once).
- Stem/context expansion over 1.5x occurs frequently, including OpenBookQA 87, ARC-Challenge 41,
  ARC-Easy 79, PIQA 222, Jeopardy 84, and HellaSwag 120.
- Backfill provenance fields are stripped from hundreds of restyled rows. This is scoring-neutral
  metadata loss, but violates the same-keys rule.

## Benchmark-by-benchmark disposition

| Benchmark | Verdict | Confirmed findings |
| --- | --- | --- |
| `bigbench_repeat_copy_logic` | Logic pass; restyle incomplete | All 32 continuations satisfy their instructions. Only 16/32 rows actually differ from filtered although the plan/report treats all 32 as manual rewrites. |
| `copa` | Targeted repair | Broken/shifted joints at 73, 82, 94, 95; participial and duplicate-subject causal fragments remain. |
| `bigbench_operators` | Pass unchanged | 210/210 byte-identical. |
| `agi_eval_lsat_ar` | Pass unchanged | 230/230 byte-identical. |
| `winograd` | Targeted repair | Six terminal-period + continuation joint failures: 39, 54, 135, 153, 154, 199. Semantic minimal-pair sample otherwise sound. |
| `openbook_qa` | Targeted repair | idx 374 changes the stem-choice relation; 425 breaks the continuation joint; 87 stems exceed 1.5x; 9 accepted-original fallbacks. |
| `arc_challenge` | Targeted repair | 1080 nearly states the answer; 325 and 967 add answer-specific distinctions/hints; 41 expansions; one fallback. |
| `commonsense_qa` | Targeted repair | 328 duplicates the full Choices scaffold; 26, 170, 344, 887 add definitions/constraints/hints; 2 unchanged full-style failures. |
| `winogrande` | Targeted repair | 16 terminal-joint failures plus substantive defects at 134, 260, 264, 930, 1044. |
| `piqa` | Targeted repair | Task reframing/answer leakage at 128, 190, 220, 702, 982; clear unchanged style failures at 376, 423, 467, 969. |
| `jeopardy` | Fail/blocker | Wrong-target clue 1316; 9 answer leaks; broken unknown slots; 108 category-prefix failures; category key removed. |
| `arc_easy` | Fail/blocker | Answer inserted at 1571; choices inserted/reordered at 1634; answer-cue regressions at 976, 1606, 1767; proper-name loss. |
| `boolq` | Targeted repair | Semantic modality drift at 301 and 881; 15 scaffold losses; quoted-content violations; idx 495 number drift. |
| `lambada_openai` | Pass as deferred/unrestyled | 4,387/4,387 byte-identical. The planned 50-item blind pilot was never started. |
| `coqa` | Fail/blocker | 973 strict scaffold failures, 31 direct answer leaks, strict digit drift, wholesale Q/A-history/final-query deletion. |
| `bigbench_language_identification` | Pass unchanged | 7,570/7,570 byte-identical. |
| `hellaswag_zeroshot` | Fail/blocker (shared) | Same shared defects as HellaSwag; zero-shot/few-shot file equivalence itself is correct. |
| `hellaswag` | Fail/blocker | 7 broken choice joints, 4 answer absorptions, 11 digit failures, quote/unit changes, 15 full-context fallbacks, non-ASCII punctuation. |
| `squad` | Fail/blocker | 1,515 strict scaffold failures, 1,080 definite query deletions, 8 direct answer leaks, strict digit drift. |
| `bigbench_qa_wikidata` | Pass unchanged | 9,508/9,508 byte-identical. |

## Recommended repair order

1. **Freeze structure in code before any more generation.** Parse and reconstruct SQuAD, CoQA,
   BoolQ, CommonsenseQA, Jeopardy, and stem-choice joints from immutable source scaffolds.
2. **Fix validators:** strict digit token preservation; reject answer occurrence increases and
   newly introduced choice text; preserve all source keys; protect Jeopardy prefix; reject filled
   answer blanks; validate each choice/context continuation joint; normalize/reject non-ASCII
   punctuation.
3. **Use prompt hashes.** Any prompt change must stale only the affected task candidates via a
   stored content hash; do not reuse a semantic version after changing prompt text.
4. **Repair safely before regenerating:** immediately revert confirmed bad rows to their filtered
   originals. That produces an accurate, partially styled bundle without model calls.
5. **Regenerate selectively:** CoQA/SQuAD scaffold failures and direct leaks; all Jeopardy and
   ARC-Easy flags; then the smaller targeted lists above. Do not regenerate already-safe rows.
6. **Optimize long-form work:** restyle each repeated SQuAD passage once and attach immutable
   per-row questions/answer blanks afterward. For CoQA, separately freeze the story, dialogue
   history, and final question/blank. This reduces calls and prevents cross-row passage drift.
7. **Add a release gate:** full deterministic scan plus stratified semantic review of every task;
   packaging should emit explicit restyled/original/flagged counts and refuse unresolved blockers.

## Bottom line

Keep the filtered source bundle. Do not evaluate or publish the present restyle as a clean
register-only A/B. The fastest safe recovery is to revert all confirmed bad/flagged rows to
filtered originals, strengthen the validators and structure reconstruction, and then regenerate
only the affected rows.
