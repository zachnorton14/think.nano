# Vintage CORE — Benchmark Reference & Audit

> Working reference for building a period-adapted (1930-cutoff) version of the CORE metric.
> Auto-generated samples are rendered with the repo's own `nanochat/core_eval.py` functions,
> so they are exactly what the model is scored on. Audit section at the end is hand-written and meant to be edited.

## 1. What CORE is

CORE is **not a model and not a training signal** — it is an *aggregate accuracy metric* over 22 fixed
in-context-learning tasks, introduced in DCLM ([2406.11794](https://arxiv.org/abs/2406.11794)) and built on
MosaicML's Eval Gauntlet. Its purpose: give a **low-variance signal of model/dataset quality at small scale**.
DCLM showed task rankings at 400M correlate with 7B (Pearson up to 0.98) — which is exactly why it is the right
instrument for comparing d12 -> d24 -> d34 before scaling up.

CORE is the **de-noised cut** of the 35-task Gauntlet: it drops the high-variance tasks (MMLU, GSM8K, SVAMP,
simple-arithmetic, TriviaQA, SIQA, StrategyQA, long-context). Start from these 22; do not re-add what CORE removed.

### How a task is scored

Everything is **likelihood-based — zero generation, no LLM judge** (this is why CORE is cheap, ~30 min full, and
fully deterministic). Three task types:

- **Multiple choice** — each candidate answer is appended to a shared stem; the option with the **lowest average
  cross-entropy loss** wins. (common prefix, varying suffix)
- **Schema** (Winograd-style) — the *context* varies, the continuation is shared; pick the context that makes the
  shared continuation most likely. (varying prefix, common suffix)
- **Language modeling** — the model must reproduce an exact continuation via greedy argmax (exact-match).

Each task's accuracy is **centered** so random-guessing = 0 and perfect = 1:

```
centered = (accuracy - random_baseline) / (1 - random_baseline)
```
CORE = mean of the 22 centered scores. This stops a 50%-floor binary task and a 25%-floor 4-way task from
contributing unequal "free" points. (Identical formula to the Gauntlet's; see `scripts/base_eval.py:168`.)

### Few-shot note

Most tasks prepend N few-shot examples (same format) before the scored item. In Section 3 below, each task shows
**one fully-assembled prompt with 2 few-shot examples** (so you can see the framing), then **5 sample items**
shown *without* the few-shot prefix for readability. At eval time, N such examples are prepended to each.

## 2. The 22 tasks at a glance

The **verdict axis is anachronism only** — what makes the task fair for a 1930 model. It is independent of
how much *signal* a task gives at a given scale (that is Section 3). `N` = eval examples.

| # | Task | Category | N | Verdict | Rationale (temporal axis) |
|---|------|----------|---|---------|----------------------------|
| 1 | `squad` | Reading Comprehension | 10570 | **DROP** | Content-anachronistic (e.g. Super Bowl 50); cannot restyle a nonexistent event. (swap ruled out) |
| 2 | `coqa` | Reading Comprehension | 7983 | **REWRITE** | Stories era-neutral (kitten Cotton); restyle surface prose to 1930 register. |
| 3 | `boolq` | Reading Comprehension | 3270 | **DROP** | Below chance at d12 AND d24 (62% baseline); does not respond to depth -> structurally unscorable for this model class. |
| 4 | `copa` | Commonsense Reasoning | 100 | **KEEP** | Fully timeless causal commonsense; faucets existed in 1930. |
| 5 | `commonsense_qa` | Commonsense Reasoning | 1221 | **REWRITE** | Timeless reasoning, modern framing (revolving door/bank). [anomaly: drops with depth - watch] |
| 6 | `piqa` | Commonsense Reasoning | 1838 | **REWRITE+FILTER** | Timeless physical reasoning, modern register/objects. Restyle + drop modern items. |
| 7 | `openbook_qa` | Commonsense Reasoning | 500 | **REWRITE** | Timeless commonsense/science; light restyle. |
| 8 | `jeopardy` | World Knowledge | 2117 | **FILTER** | Many items already pre-1930 (Bacon, Byrd). Date-filter Science/post-1930 facts. |
| 9 | `bigbench_qa_wikidata` | World Knowledge | 20321 | **FILTER** | Drop modern entities. ANSWER-side trap: "Novosibirsk -> Russia" should be USSR in 1930. |
| 10 | `arc_easy` | World Knowledge | 2376 | **FILTER** | Pre-1930 science fine; drop modern-tech items. |
| 11 | `arc_challenge` | World Knowledge | 1172 | **FILTER** | 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor. |
| 12 | `bigbench_dyck_languages` | Symbolic Problem Solving | 1000 | **KEEP** | Era-neutral symbol manipulation; needs no modern knowledge. Scales with depth (0.065->0.124). Was wrongly dropped on signal. |
| 13 | `agi_eval_lsat_ar` | Symbolic Problem Solving | 230 | **KEEP** | Era-neutral analytical logic (abstract scheduling); no modern knowledge -> FAIR. Low d12 signal is capacity, not anachronism. |
| 14 | `bigbench_cs_algorithms` | Symbolic Problem Solving | 1320 | **DROP** | Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data. |
| 15 | `bigbench_operators` | Symbolic Problem Solving | 210 | **KEEP** | Pure abstraction (defined operators), era-neutral. Fairest symbolic task. |
| 16 | `bigbench_repeat_copy_logic` | Symbolic Problem Solving | 32 | **REWRITE** | Mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens. |
| 17 | `hellaswag_zeroshot` | Language Understanding | 10042 | **REWRITE** | Same source, 0-shot variant of hellaswag. |
| 18 | `lambada_openai` | Language Understanding | 5153 | **REWRITE** | Modern-novel prose (register). Strong signal, scales well -> rewrite to held-out period books, do NOT drop. |
| 19 | `hellaswag` | Language Understanding | 10042 | **REWRITE** | Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite). |
| 20 | `winograd` | Language Understanding | 273 | **KEEP** | Timeless pronoun resolution; register already period-appropriate. |
| 21 | `winogrande` | Language Understanding | 1267 | **KEEP** | Timeless; optional light restyle. |
| 22 | `bigbench_language_identification` | Language Understanding | 10000 | **KEEP** | Era-neutral (religious-translation sentences period-plausible). Low priority. |

**Verdict legend:** KEEP = era-neutral, use as-is · REWRITE = restyle register, content fine · FILTER = date-drop anachronistic items, keep rest · DROP = anachronistic / impossible / structurally unscorable.

**Only 3 DROPs, each justified on a distinct axis:** `squad` (content can't be restyled) · `cs_algorithms` (modern-CS concept + spurious baseline, flat across depth & data) · `boolq` (below chance at d12 *and* d24). Tasks once dropped for "low d12 signal" (`agi_eval_lsat_ar`, `bigbench_dyck_languages`, `lambada_openai`) are **reinstated** — low signal is a scale artifact, not unfairness.

## 3. Empirical signal at d12

### Run inventory

Three knobs are varied: **data/FLOPs** (vintage r11->r20->r30, fixed d12), **dataset** (vintage vs modern),
and **model depth** (modern d12 vs d24). `r11.a`/`r11.b` are two seeds of the identical r11 config -> their
CORE gap is the **noise floor**. (BPB across datasets is on different val sets -> not comparable.)

| run | dataset | depth | ratio | tokens | FLOPs | val BPB | CORE | axis |
|-----|---------|-------|-------|--------|-------|---------|------|------|
| `r11.a` | vintage | d12 | 11.25 | 1.24B | 1.10e+18 | 1.0520 | 0.0792 | data scaling |
| `r11.b` | vintage | d12 | 11.25 | 1.24B | 1.10e+18 | 1.0514 | 0.0669 | data scaling |
| `r20` | vintage | d12 | 20 | 2.20B | 1.95e+18 | 1.0181 | 0.0775 | data scaling |
| `r30` | vintage | d12 | 30 | 3.30B | 2.93e+18 | 0.9945 | 0.0896 | data scaling |
| `modern` | climbmix | d12 | ~12 | 1.32B | 1.17e+18 | 0.8793* | 0.1479 | dataset / depth |
| `modern-d24` | climbmix | **d24** | ~12 | -- | 4.33e+19 | 0.7488* | 0.2603 | **depth** |

*\*modern BPB is on a different validation set than vintage — do not compare across datasets.*

### Key findings (TL;DR)

1. **Depth is the dominant lever, not data.** Doubling depth (modern d12->d24, same ratio) moves CORE **+0.112**
   (0.148 -> 0.260); scaling data 2.7x at fixed d12 moved it only +0.017. **The d12 model is the bottleneck.**
2. **"d12 noise" is two things (3D).** Run-to-run *variance* = sample size (fixable by larger N); CORE being
   *flat/uninformative* = model capacity (only fixed by depth). `winograd` proves it: stable 0.099 at d12 ->
   0.370 at d24, N unchanged. So at d12 use **BPB** to compare data; CORE needs d24+.
3. **Era-neutral collapse:** the vintage/modern CORE gap (+0.075) lives entirely in temporally-loaded tasks;
   era-neutral tasks are within noise. Modern data is a better-matched *benchmark*, not a smarter model (3B).
4. **Verdicts are anachronism-only.** Low signal never justifies a drop (it lifts with scale). Only 3 DROPs
   survive on real grounds; `agi_eval_lsat_ar`, `dyck`, `lambada` are reinstated (Section 2).

### 3A. Data scaling at fixed d12 (r11 -> r20 -> r30)

Two r11 seeds shown **separately** (`r11.a`, `r11.b`); `noise` = |a - b|. `dr30` = r30 minus the r11 mean.
`scales?` compares that to the noise floor: **yes** = real data response, **~** = marginal, **flat** = no response.
Sorted by `dr30` (biggest mover first) — but `scales?` is mechanical, so the top low-N rows (`copa`, `winogrande`,
`boolq`) are noise/coarse-bin artifacts, **not** real scaling. Trust the high-N rows; see callouts.

| Task | N | r11.a | r11.b | noise | r20 | r30 | dr30 | scales? |
|------|---|-------|-------|-------|-----|-----|------|---------|
| `copa` | 100 | +0.100 | +0.060 | 0.040 | +0.060 | +0.180 | +0.100 | yes |
| `boolq` | 3270 | -0.106 | -0.172 | 0.066 | -0.069 | -0.076 | +0.063 | ~ |
| `winogrande` | 1267 | +0.004 | -0.032 | 0.036 | -0.009 | +0.023 | +0.037 | yes |
| `piqa` | 1838 | +0.097 | +0.085 | 0.012 | +0.103 | +0.126 | +0.035 | yes |
| `squad` | 10570 | +0.021 | +0.015 | 0.006 | +0.034 | +0.047 | +0.030 | yes |
| `arc_easy` | 2376 | +0.082 | +0.074 | 0.008 | +0.099 | +0.101 | +0.023 | ~ |
| `coqa` | 7983 | +0.070 | +0.080 | 0.010 | +0.086 | +0.094 | +0.019 | ~ |
| `bigbench_qa_wikidata` | 20321 | +0.083 | +0.070 | 0.013 | +0.057 | +0.095 | +0.018 | ~ |
| `agi_eval_lsat_ar` | 230 | +0.092 | +0.065 | 0.027 | +0.082 | +0.092 | +0.014 | flat |
| `hellaswag_zeroshot` | 10042 | +0.036 | +0.032 | 0.003 | +0.043 | +0.047 | +0.013 | ~ |
| `lambada_openai` | 5153 | +0.250 | +0.194 | 0.056 | +0.221 | +0.233 | +0.012 | flat |
| `hellaswag` | 10042 | +0.041 | +0.035 | 0.006 | +0.042 | +0.048 | +0.010 | ~ |
| `bigbench_cs_algorithms` | 1320 | +0.422 | +0.381 | 0.041 | +0.382 | +0.410 | +0.008 | flat |
| `bigbench_operators` | 210 | +0.067 | +0.114 | 0.048 | +0.110 | +0.095 | +0.005 | flat |
| `bigbench_language_identification` | 10000 | +0.177 | +0.174 | 0.003 | +0.175 | +0.181 | +0.005 | ~ |
| `commonsense_qa` | 1221 | +0.143 | +0.144 | 0.001 | +0.129 | +0.148 | +0.005 | ~ |
| `bigbench_repeat_copy_logic` | 32 | +0.000 | +0.000 | 0.000 | +0.000 | +0.000 | +0.000 | flat |
| `winograd` | 273 | +0.099 | +0.099 | 0.000 | +0.092 | +0.099 | +0.000 | flat |
| `jeopardy` | 2117 | +0.000 | +0.000 | 0.000 | +0.000 | +0.000 | -0.000 | ~ |
| `bigbench_dyck_languages` | 1000 | +0.109 | +0.112 | 0.003 | +0.111 | +0.110 | -0.000 | flat |
| `arc_challenge` | 1172 | -0.061 | -0.044 | 0.017 | -0.039 | -0.061 | -0.009 | flat |
| `openbook_qa` | 500 | +0.016 | -0.016 | 0.032 | -0.005 | -0.021 | -0.021 | flat |

**Callouts (the few tasks worth reading individually):**

- `piqa` (REWRITE+FILTER, N=1838): Clean monotonic climb (0.09->0.10->0.13), high-N -> genuine data response.
- `squad` (DROP, N=10570): Monotonic (0.02->0.03->0.05) -> small but real.
- `hellaswag` (REWRITE, N=10042): Tiny but clean monotonic climb (0.038->0.042->0.048).
- `arc_easy` (FILTER, N=2376): Climbs then plateaus (0.08->0.10->0.10).
- `commonsense_qa` (REWRITE, N=1221): Flat ~0.14 -> capacity-bound, not data-bound at d12.
- `lambada_openai` (REWRITE, N=5153): Flat across data (0.22->0.22->0.23); apparent noise is tokenizer-driven.
- `copa` (KEEP, N=100): N=100 -> +0.10 is a coarse-bin jump, not real scaling.
- `winograd` (KEEP, N=273): Identical 0.099 in 3 of 4 runs -> pinned/quantized, no signal.
- `bigbench_cs_algorithms` (DROP, N=1320): Flat ~0.40 -> spurious artifact, data-independent.
- `bigbench_qa_wikidata` (FILTER, N=20321): Non-monotonic (0.08->0.06->0.09) -> noise-dominated despite N=20k.

**Read:** only a handful of **high-N, temporally-loaded** tasks (piqa, squad, arc_easy, hellaswag) show a clean
monotonic climb with data — and even those move <0.04 over 2.7x tokens. Everything else is flat or noise.
The lesson is structural: **a d12 model cannot convert lower loss into task accuracy fast enough for CORE to
see it.** This is why CORE "is very noisy at d12" — it is the right metric at the wrong scale.

### 3B. Vintage vs modern at d12 (era-neutral collapse)

Same scale, different *dataset*. Vintage = r11 2-seed mean; gap gated on the same noise floor.

| group | tasks | mean gap (modern - vintage) |
|-------|-------|------------------------------|
| temporally-loaded (REWRITE/FILTER/DROP) | 12 | **+0.130** |
| era-neutral (KEEP) | 7 | +0.008 (within noise) |

Biggest robust modern wins: `arc_easy` +0.34, `piqa` +0.23, `qa_wikidata` +0.19 — all register/content loaded.
Era-neutral tasks (`operators`, `language_id`, `winograd`, `copa`) sit at the noise floor. **This is the
empirical case for the whole vintage adaptation:** vanilla CORE penalizes register and anachronism, not capability.
Caveat: part of `arc_easy`/`qa_wikidata` is *genuine* (book data teaches less QA-format science) — filter/rewrite
should shrink the gap toward ~0, and any residual is real signal worth keeping.

### 3C. Model depth (modern d12 -> d24, same data ratio)

The decisive axis. Same dataset (climbmix), same ratio (~12), **double the depth**. Doubling depth moves CORE
**+0.112** (0.148 -> 0.260) -- ~6.5x more than scaling data 2.7x did (+0.017). BPB: 0.8793 -> 0.7488.

| Task | N | d12 | d24 | depth dr | note |
|------|---|-----|-----|----------|------|
| `winograd` | 273 | +0.099 | +0.370 | +0.271 | PINNED at 0.099 across all four d12 runs -> 0.370 at d24. Pure capacity ceiling, not noise. |
| `bigbench_qa_wikidata` | 20321 | +0.267 | +0.536 | +0.269 | Fact retrieval: biggest depth gain. Needs params to store/recall facts. |
| `squad` | 10570 | +0.147 | +0.398 | +0.251 |  |
| `hellaswag` | 10042 | +0.131 | +0.368 | +0.237 |  |
| `hellaswag_zeroshot` | 10042 | +0.140 | +0.360 | +0.220 |  |
| `jeopardy` | 2117 | +0.009 | +0.198 | +0.189 | Fact retrieval DEAD at d12 (~0) -> alive at d24. Depth-gated. |
| `copa` | 100 | +0.100 | +0.280 | +0.180 |  |
| `arc_challenge` | 1172 | +0.018 | +0.197 | +0.179 | Near-zero at d12 -> +0.18 at d24. Reasoning is depth-gated. |
| `arc_easy` | 2376 | +0.419 | +0.555 | +0.136 |  |
| `piqa` | 1838 | +0.320 | +0.448 | +0.128 |  |
| `openbook_qa` | 500 | +0.072 | +0.197 | +0.125 |  |
| `lambada_openai` | 5153 | +0.316 | +0.428 | +0.112 |  |
| `winogrande` | 1267 | +0.021 | +0.124 | +0.103 |  |
| `coqa` | 7983 | +0.178 | +0.244 | +0.066 |  |
| `bigbench_dyck_languages` | 1000 | +0.065 | +0.124 | +0.059 |  |
| `bigbench_operators` | 210 | +0.105 | +0.152 | +0.048 |  |
| `bigbench_repeat_copy_logic` | 32 | +0.000 | +0.031 | +0.031 |  |
| `agi_eval_lsat_ar` | 230 | +0.109 | +0.136 | +0.027 |  |
| `boolq` | 3270 | -0.069 | -0.063 | +0.006 | Flat below chance at BOTH depths -> structurally unscorable (justifies DROP). |
| `bigbench_language_identification` | 10000 | +0.177 | +0.171 | -0.007 |  |
| `bigbench_cs_algorithms` | 1320 | +0.427 | +0.414 | -0.013 | Flat across depth too -> confirmed spurious/saturated. |
| `commonsense_qa` | 1221 | +0.204 | +0.058 | -0.146 | ANOMALY: drops with depth (0.20 -> 0.06). Unstable -> watch before trusting. |

**The winograd proof.** `winograd` reads **exactly 0.099** in all four d12 runs (both vintage seeds, vintage
r-ladder, modern d12) -- *zero* variance -- then jumps to **0.370** at d24 with N unchanged (273). A
sample-size problem would make it *noisy*; instead it is perfectly *stable but flat*. That is a **capacity
ceiling**, and only depth releases it. Same story for `jeopardy` (~0 -> 0.198) and `arc_challenge` (0.02 -> 0.20):
fact-retrieval and multi-step reasoning are **depth-gated**.

### 3D. Where does CORE's "d12 noise" come from? (variance vs. ceiling)

Two different things get bundled under "noisy". Separating them resolves the Jonathan/Owen question:

| Phenomenon | Driven by | Fixable by more eval examples? | Evidence |
|------------|-----------|-------------------------------|----------|
| **Run-to-run variance** (two identical runs differ) | **sample size (1/sqrt(N))** | **Yes**, where larger eval sets exist | copa (N=100) swings 0.06<->0.10; high-N tasks stable |
| **Low signal / no movement** (CORE flat vs data, scores near floor) | **model capacity (depth)** | **No** | winograd stable 0.099 at d12 -> 0.370 at d24; jeopardy ~0 -> 0.198 |

- **Jonathan is right** that the *variance* comes from small N -- and Owen is right that you *could* shrink it
  with more examples (where the source dataset allows; copa has only 100, repeat_copy 32 -- you cannot mint more).
- **Owen is right** that the reason CORE is *uninformative* at d12 is model depth, not sample size. Upping N would
  tighten each measurement but would NOT lift winograd off 0.099 or make the +0.017 data effect large -- only
  depth does that. The two r11 seeds prove variance is small (0.012); the d24 run proves the *ceiling* is the
  real limiter.
- **So both, about different things.** Net: at d12, raise *N* to reduce variance, but you cannot buy *signal* --
  that needs depth. For comparing data recipes at d12, use **BPB** (capacity-insensitive); reserve **CORE** for
  d24+ where the ceiling lifts.

## 4. The 22 benchmarks — 5 samples each, as the model sees them

---

## Reading Comprehension

### `squad`  —  DROP
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Content-anachronistic (e.g. Super Bowl 50); cannot restyle a nonexistent event. (swap ruled out)

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as "Super Bowl L"), so that the logo could prominently feature the Arabic numerals 50.
Question: Which NFL team represented the NFC at Super Bowl 50?
Answer: Carolina Panthers

Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Fo
[... truncated for this doc ...]
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Denver Broncos'
```
```
[sample 2]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Carolina Panthers'
```
```
[sample 3]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Santa Clara, California'
```
```
[sample 4]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Denver Broncos'
```
```
[sample 5]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'gold'
```

### `coqa`  —  REWRITE
*Language modeling · 0-shot · baseline 0% · delimiter `' '`*  
> Stories era-neutral (kitten Cotton); restyle surface prose to 1930 register.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite sad. She often wished she looked like the rest of her family. So one day, when Cotton found a can of the old farmer's orange paint, she used it to paint herself like them. When her mommy and sisters found her they started laughing. 

"What are you doing, Cotton?!" 

"I only wanted to be more like you". 

Cotton's mommy rubbed her face on Cotton's and said "Oh Cotton, but your fur is so pretty and 
[... truncated for this doc ...]
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'white'
```
```
[sample 2]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'in a barn'
```
```
[sample 3]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'no'
```
```
[sample 4]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'with her mommy and 5 sisters'
```
```
[sample 5]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'orange and white'
```

### `boolq`  —  DROP
*Multiple choice · 10-shot · baseline 62% · delimiter `'\nAnswer: '`*  
> Below chance at d12 AND d24 (62% baseline); does not respond to depth -> structurally unscorable for this model class.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Passage: Property tax or 'house tax' is a local tax on buildings, along with appurtenant land. It is and imposed on the Possessor (not the custodian of property as per 1978, 44th amendment of constitution). It resembles the US-type wealth tax and differs from the excise-type UK rate. The tax power is vested in the states and is delegated to local bodies, specifying the valuation method, rate band, and collection procedures. The tax base is the annual rental value (ARV) or area-based rating. Owner-occupied and other properties not producing rent are assessed on cost and then converted into ARV by applying a percentage of cost, usually four percent. Vacant land is generally exempt. Central government properties are exempt. Instead a 'service charge' is permissible under executive order. Properties of foreign missions also enjoy tax exemption without requiring reciprocity. The tax is usually accompanied by service taxes, e.g., water tax, drainage tax, conservancy (sanitation) tax, lighting tax, all using the same tax base. The rate structure is flat on rural (panchayat) properties, but 
[... truncated for this doc ...]
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Passage: All biomass goes through at least some of these steps: it needs to be grown, collected, dried, fermented, distilled, and burned. All of these steps require resources and an infrastructure. The total amount of energy input into the process compared to the energy released by burning the resulting ethanol fuel is known as the energy balance (or ``energy returned on energy invested''). Figures compiled in a 2007 report by National Geographic Magazine point to modest results for corn ethanol produced in the US: one unit of fossil-fuel energy is required to create 1.3 energy units from the resulting ethanol. The energy balance for sugarcane ethanol produced in Brazil is more favorable, wi
[... truncated for this doc ...]
CHOICES (* = gold):
  * [0] no
    [1] yes
```
```
[sample 2]
STEM:
Passage: Property tax or 'house tax' is a local tax on buildings, along with appurtenant land. It is and imposed on the Possessor (not the custodian of property as per 1978, 44th amendment of constitution). It resembles the US-type wealth tax and differs from the excise-type UK rate. The tax power is vested in the states and is delegated to local bodies, specifying the valuation method, rate band, and collection procedures. The tax base is the annual rental value (ARV) or area-based rating. Owner-occupied and other properties not producing rent are assessed on cost and then converted into ARV by applying a percentage of cost, usually four percent. Vacant land is generally exempt. Central gov
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 3]
STEM:
Passage: Phantom pain sensations are described as perceptions that an individual experiences relating to a limb or an organ that is not physically part of the body. Limb loss is a result of either removal by amputation or congenital limb deficiency. However, phantom limb sensations can also occur following nerve avulsion or spinal cord injury.
Question: is pain experienced in a missing body part or paralyzed area?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 4]
STEM:
Passage: Harry Potter and the Escape from Gringotts is an indoor steel roller coaster at Universal Studios Florida, a theme park located within the Universal Orlando Resort. Similar to dark rides, the roller coaster utilizes special effects in a controlled-lighting environment and also employs motion-based 3-D projection of both animation and live-action sequences to enhance the experience. The ride, which is themed to the Gringotts Wizarding Bank, became the flagship attraction for the expanded Wizarding World of Harry Potter when it opened on July 8, 2014.
Question: is harry potter and the escape from gringotts a roller coaster ride?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 5]
STEM:
Passage: Hydroxyzine preparations require a doctor's prescription. The drug is available in two formulations, the pamoate and the dihydrochloride or hydrochloride salts. Vistaril, Equipose, Masmoran, and Paxistil are preparations of the pamoate salt, while Atarax, Alamon, Aterax, Durrax, Tran-Q, Orgatrax, Quiess, and Tranquizine are of the hydrochloride salt.
Question: is there a difference between hydroxyzine hcl and hydroxyzine pam?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```

---

## Commonsense Reasoning

### `copa`  —  KEEP
*Multiple choice · 0-shot · baseline 50% · delimiter `' '`*  
> Fully timeless causal commonsense; faucets existed in 1930.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
The man turned on the faucet, therefore water flowed from the spout.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
The man turned on the faucet, therefore water flowed from the spout.
CHOICES (* = gold):
    [0] the toilet filled with water.
  * [1] water flowed from the spout.
```
```
[sample 2]
STEM:
The girl found a bug in her cereal, therefore she lost her appetite.
CHOICES (* = gold):
    [0] she poured milk in the bowl.
  * [1] she lost her appetite.
```
```
[sample 3]
STEM:
The woman retired, therefore she received her pension.
CHOICES (* = gold):
  * [0] she received her pension.
    [1] she paid off her mortgage.
```
```
[sample 4]
STEM:
I wanted to conserve energy, therefore i shut off the light in the unoccupied room.
CHOICES (* = gold):
    [0] i swept the floor in the unoccupied room.
  * [1] i shut off the light in the unoccupied room.
```
```
[sample 5]
STEM:
The hamburger meat browned, because the cook grilled it.
CHOICES (* = gold):
    [0] the cook froze it.
  * [1] the cook grilled it.
```

### `commonsense_qa`  —  REWRITE
*Multiple choice · 10-shot · baseline 20% · delimiter `' '`*  
> Timeless reasoning, modern framing (revolving door/bank). [anomaly: drops with depth - watch]

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: What do people aim to do at work?
Choices:
A. complete job
B. kill animals
C. wear hats
D. talk to each other
Answer: A

Question: Where would you find magazines along side many other printed works?
Choices:
A. doctor
B. bookstore
C. train station
D. mortuary
Answer: B

Question: A revolving door is convenient for two direction travel, but it also serves as a security measure at a what?
Choices:
A. bank
B. department store
C. mall
D. new york
Answer: A
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Question: A revolving door is convenient for two direction travel, but it also serves as a security measure at a what?
Choices:
A. bank
B. department store
C. mall
D. new york
Answer: A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 2]
STEM:
Question: What do people aim to do at work?
Choices:
A. complete job
B. kill animals
C. wear hats
D. talk to each other
Answer: A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 3]
STEM:
Question: Where would you find magazines along side many other printed works?
Choices:
A. doctor
B. bookstore
C. train station
D. mortuary
Answer: B
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 4]
STEM:
Question: Where are  you likely to find a hamburger?
Choices:
A. fast food restaurant
B. ground up dead cows
C. mouth
D. cow carcus
Answer: A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 5]
STEM:
Question: James was looking for a good place to buy farmland.  Where might he look?
Choices:
A. midwest
B. estate
C. farming areas
D. illinois
Answer: A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```

### `piqa`  —  REWRITE+FILTER
*Multiple choice · 10-shot · baseline 50% · delimiter `'\nAnswer: '`*  
> Timeless physical reasoning, modern register/objects. Restyle + drop modern items.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: dresser

Answer: finish, woodgrain with  bobby pin

Question: To fight Ivan Drago in Rocky for sega master system.

Answer: You have to defeat Apollo Creed and Clubber Lang first.

Question: How do I ready a guinea pig cage for it's new occupants?

Answer: Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Question: How do I ready a guinea pig cage for it's new occupants?

Answer: Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
CHOICES (* = gold):
  * [0] Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
    [1] Provide the guinea pig with a cage full of a few inches of bedding made of ripped jeans material, you will also need to supply it with a water bottle and a food dish.
```
```
[sample 2]
STEM:
Question: dresser

Answer: finish, woodgrain with  bobby pin
CHOICES (* = gold):
    [0] replace drawer with bobby pin
  * [1] finish, woodgrain with  bobby pin
```
```
[sample 3]
STEM:
Question: To fight Ivan Drago in Rocky for sega master system.

Answer: You have to defeat Apollo Creed and Clubber Lang first.
CHOICES (* = gold):
    [0] Drago isn't in this game because it was released before Rocky IV.
  * [1] You have to defeat Apollo Creed and Clubber Lang first.
```
```
[sample 4]
STEM:
Question: Make outdoor pillow.

Answer: Blow into trash bag and tie with rubber band.
CHOICES (* = gold):
    [0] Blow into tin can and tie with rubber band.
  * [1] Blow into trash bag and tie with rubber band.
```
```
[sample 5]
STEM:
Question: ice box

Answer: will turn into a cooler if you add water to it
CHOICES (* = gold):
  * [0] will turn into a cooler if you add water to it
    [1] will turn into a cooler if you add soda to it
```

### `openbook_qa`  —  REWRITE
*Multiple choice · 0-shot · baseline 25% · delimiter `' '`*  
> Timeless commonsense/science; light restyle.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to quit eating lunch out
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to quit eating lunch out
CHOICES (* = gold):
    [0] make more phone calls
  * [1] quit eating lunch out
    [2] buy less with monopoly money
    [3] have lunch with friends
```
```
[sample 2]
STEM:
There is most likely going to be fog around: a marsh
CHOICES (* = gold):
  * [0] a marsh
    [1] a tundra
    [2] the plains
    [3] a desert
```
```
[sample 3]
STEM:
Predators eat bunnies
CHOICES (* = gold):
    [0] lions
    [1] humans
  * [2] bunnies
    [3] grass
```
```
[sample 4]
STEM:
Oak tree seeds are planted and a sidewalk is paved right next to that spot, until eventually, the tree is tall and the roots must extend past the sidewalk, which means parts may break the concrete
CHOICES (* = gold):
    [0] roots may be split
    [1] roots may begin to die
  * [2] parts may break the concrete
    [3] roots may fall apart
```
```
[sample 5]
STEM:
An electric car runs on electricity via electrical conductors
CHOICES (* = gold):
    [0] gasoline
    [1] a power station
  * [2] electrical conductors
    [3] fuel
```

---

## World Knowledge

### `jeopardy`  —  FILTER
*Language modeling · 10-shot · baseline 0% · delimiter `'\nAnswer: '`*  
> Many items already pre-1930 (Bacon, Byrd). Date-filter Science/post-1930 facts.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
WORLD HISTORY: Accused of accepting bribes, Francis Bacon was imprisoned in this forbidding complex in 1621
Answer: Tower of London

WORLD HISTORY: More than 250,000 died in fighting before France granted this African nation independence July 3, 1962
Answer: Algeria

WORLD HISTORY: This Navy commander flew from a base at Little America to the South Pole & back Nov. 28-29, 1929
Answer: Admiral Richard Byrd
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
WORLD HISTORY: This Navy commander flew from a base at Little America to the South Pole & back Nov. 28-29, 1929
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Admiral Richard Byrd'
```
```
[sample 2]
CONTEXT:
WORLD HISTORY: Accused of accepting bribes, Francis Bacon was imprisoned in this forbidding complex in 1621
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Tower of London'
```
```
[sample 3]
CONTEXT:
WORLD HISTORY: More than 250,000 died in fighting before France granted this African nation independence July 3, 1962
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Algeria'
```
```
[sample 4]
CONTEXT:
WORLD HISTORY: In 1784 she founded the city of Sevastopol in her new domain of the Crimea
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Catherine the Great'
```
```
[sample 5]
CONTEXT:
WORLD HISTORY: This Portuguese Admiral of the Indian Seas discovered & named the Amirante Islands
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Vasco da Gama'
```

### `bigbench_qa_wikidata`  —  FILTER
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Drop modern entities. ANSWER-side trap: "Novosibirsk -> Russia" should be USSR in 1930.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
The country of Novosibirsk is Russia

The country of citizenship of Isabel Martínez de Perón is Argentina

The native language of Daniel Schneidermann is French
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
The native language of Daniel Schneidermann is
GOLD CONTINUATION (model must produce):
  >>> 'French'
```
```
[sample 2]
CONTEXT:
The country of Novosibirsk is
GOLD CONTINUATION (model must produce):
  >>> 'Russia'
```
```
[sample 3]
CONTEXT:
The country of citizenship of Isabel Martínez de Perón is
GOLD CONTINUATION (model must produce):
  >>> 'Argentina'
```
```
[sample 4]
CONTEXT:
The sport played by Shane Victorino is
GOLD CONTINUATION (model must produce):
  >>> 'baseball'
```
```
[sample 5]
CONTEXT:
The country of citizenship of Moana Pozzi is
GOLD CONTINUATION (model must produce):
  >>> 'Italy'
```

### `arc_easy`  —  FILTER
*Multiple choice · 10-shot · baseline 25% · delimiter `'\nAnswer: '`*  
> Pre-1930 science fine; drop modern-tech items.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: Which piece of safety equipment is used to keep mold spores from entering the respiratory system?
Answer: breathing mask

Question: Meiosis is a type of cell division in which germ cells divide to produce haploid cells. Where does meiosis occur?
Answer: ovary cells

Question: Which statement best explains why photosynthesis is the foundation of most food webs?
Answer: Sunlight is the source of energy for nearly all ecosystems.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Question: Which statement best explains why photosynthesis is the foundation of most food webs?
Answer: Sunlight is the source of energy for nearly all ecosystems.
CHOICES (* = gold):
  * [0] Sunlight is the source of energy for nearly all ecosystems.
    [1] Most ecosystems are found on land instead of in water.
    [2] Carbon dioxide is more available than other gases.
    [3] The producers in all ecosystems are plants.
```
```
[sample 2]
STEM:
Question: Which piece of safety equipment is used to keep mold spores from entering the respiratory system?
Answer: breathing mask
CHOICES (* = gold):
    [0] safety goggles
  * [1] breathing mask
    [2] rubber gloves
    [3] lead apron
```
```
[sample 3]
STEM:
Question: Meiosis is a type of cell division in which germ cells divide to produce haploid cells. Where does meiosis occur?
Answer: ovary cells
CHOICES (* = gold):
    [0] brain cells
    [1] bone cells
    [2] muscle cells
  * [3] ovary cells
```
```
[sample 4]
STEM:
Question: Which characteristic describes the texture of a kitten's fur?
Answer: soft
CHOICES (* = gold):
    [0] gray
    [1] warm
    [2] long
  * [3] soft
```
```
[sample 5]
STEM:
Question: Which best describes the structure of an atom?
Answer: a massive core surrounded by negatively-charged particles
CHOICES (* = gold):
    [0] a lightweight core surrounded by neutral particles
  * [1] a massive core surrounded by negatively-charged particles
    [2] a network of interacting positive and negative particles
    [3] overlapping layers of neutral, positive, and negative particles
```

### `arc_challenge`  —  FILTER
*Multiple choice · 10-shot · baseline 25% · delimiter `'\nAnswer: '`*  
> 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: A group of engineers wanted to know how different building designs would respond during an earthquake. They made several models of buildings and tested each for its ability to withstand earthquake conditions. Which will most likely result from testing different building designs?
Answer: buildings will be made safer

Question: The end result in the process of photosynthesis is the production of sugar and oxygen. Which step signals the beginning of photosynthesis?
Answer: Chlorophyll in the leaf captures light energy.

Question: An astronomer observes that a planet rotates faster after a meteorite impact. Which is the most likely effect of this increase in rotation?
Answer: Planetary days will become shorter.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Question: An astronomer observes that a planet rotates faster after a meteorite impact. Which is the most likely effect of this increase in rotation?
Answer: Planetary days will become shorter.
CHOICES (* = gold):
    [0] Planetary density will decrease.
    [1] Planetary years will become longer.
  * [2] Planetary days will become shorter.
    [3] Planetary gravity will become stronger.
```
```
[sample 2]
STEM:
Question: A group of engineers wanted to know how different building designs would respond during an earthquake. They made several models of buildings and tested each for its ability to withstand earthquake conditions. Which will most likely result from testing different building designs?
Answer: buildings will be made safer
CHOICES (* = gold):
    [0] buildings will be built faster
  * [1] buildings will be made safer
    [2] building designs will look nicer
    [3] building materials will be cheaper
```
```
[sample 3]
STEM:
Question: The end result in the process of photosynthesis is the production of sugar and oxygen. Which step signals the beginning of photosynthesis?
Answer: Chlorophyll in the leaf captures light energy.
CHOICES (* = gold):
    [0] Chemical energy is absorbed through the roots.
    [1] Light energy is converted to chemical energy.
  * [2] Chlorophyll in the leaf captures light energy.
    [3] Sunlight is converted into chlorophyll.
```
```
[sample 4]
STEM:
Question: A physicist wants to determine the speed a car must reach to jump over a ramp. The physicist conducts three trials. In trials two and three, the speed of the car is increased by 20 miles per hour. What is the physicist investigating when he changes the speed?
Answer: the independent (manipulated) variable
CHOICES (* = gold):
    [0] the control
    [1] the hypothesis statement
    [2] the dependent (responding) variable
  * [3] the independent (manipulated) variable
```
```
[sample 5]
STEM:
Question: An astronaut drops a 1.0 kg object and a 5.0 kg object on the Moon. Both objects fall a total distance of 2.0 m vertically. Which of the following best describes the objects after they have fallen a distance of 1.0 m?
Answer: They have each gained one-half of their maximum kinetic energy.
CHOICES (* = gold):
    [0] They have each lost kinetic energy.
    [1] They have each gained the same amount of potential energy.
    [2] They have each lost the same amount of potential energy.
  * [3] They have each gained one-half of their maximum kinetic energy.
```

---

## Symbolic Problem Solving

### `bigbench_dyck_languages`  —  KEEP
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Era-neutral symbol manipulation; needs no modern knowledge. Scales with depth (0.065->0.124). Was wrongly dropped on signal.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: < < [ ( ) ] >
Output: >

Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: ( { < > }
Output: )

Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: [ < < { } > [ { [ ] ( ( ( ( < ( ( ) ) > ) ) ) [ ] ) } ] { } < [ { ( { < ( ) > } ) } ( ) ] > > {
Output: } ]
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: [ < < { } > [ { [ ] ( ( ( ( < ( ( ) ) > ) ) ) [ ] ) } ] { } < [ { ( { < ( ) > } ) } ( ) ] > > {
Output:
GOLD CONTINUATION (model must produce):
  >>> '} ]'
```
```
[sample 2]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: < < [ ( ) ] >
Output:
GOLD CONTINUATION (model must produce):
  >>> '>'
```
```
[sample 3]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: ( { < > }
Output:
GOLD CONTINUATION (model must produce):
  >>> ')'
```
```
[sample 4]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: [ [ ] < [ { [ { ( { ( ( { < [ ( ( < > ) ) ] > } ) ) < < { < ( { ( [ [ ] ] ) } ) > } > > } ( { [ [ ( [ ( ) ] < { } > { } ) ] ] } [ < { [ ] } > < ( ) > ] [ ( ) ] ) ) } ] } ] > ] [
Output:
GOLD CONTINUATION (model must produce):
  >>> ']'
```
```
[sample 5]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: < [ ( ) [ ( ) ] ] ( [ < ( ( ( < < { [ ] } < [ { } ] > > > [ < [ < [ < < [ { ( { [ { < ( ) > } ] [ ] } ( ) ) } ] ( [ ( ( < ( ) > ) ) ] ) < > > > ] > ] > ] { } ) ) ) > ] )
Output:
GOLD CONTINUATION (model must produce):
  >>> '>'
```

### `agi_eval_lsat_ar`  —  KEEP
*Multiple choice · 3-shot · baseline 20% · delimiter `' '`*  
> Era-neutral analytical logic (abstract scheduling); no modern knowledge -> FAIR. Low d12 signal is capacity, not anachronism.

**Full prompt as scored (showing 2 of 3 few-shot):**

```
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: If Kyle and Lenore do not give reports, then the morning reports on Monday, Tuesday, and Wednesday, respectively, could be given by
Choices:
A.) Helen, George, and Nina
B.) Robert, George, and Helen
C.) Irving, Robert, and Helen
D.) Olivia, Robert, and Irving
Answer: D

Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will 
[... truncated for this doc ...]
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: Which one of the following could be the schedule of the students' reports?
Choices:
A.) Mon. morning: Irving; M
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 2]
STEM:
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: If Kyle and Lenore do not give reports, then the morning reports on Monday, Tuesday, and Wednesday, respectivel
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 3]
STEM:
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: Which one of the following is a pair of students who, if they give reports on the same day as each other, must 
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 4]
STEM:
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: If George, Nina, and Robert give reports and they do so on different days from one another, which one of the fo
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 5]
STEM:
Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give individual oral reports during three consecutive days—Monday, Tuesday, and Wednesday. Exactly two reports will be given each day—one in the morning and one in the afternoon—according to the following conditions: Tuesday is the only day on which George can give a report. Neither Olivia nor Robert can give an afternoon report. If Nina gives a report, then on the next day Helen and Irving must both give reports, unless Nina's report is given on Wednesday.
Q: If Kyle gives the afternoon report on Tuesday, and Helen gives the afternoon report on Wednesday, which one of 
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```

### `bigbench_cs_algorithms`  —  DROP
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Given two strings, determine the length of the longest common subsequence.

Strings: GDMKSZERXGPYTKJRQMLSSKLEALAJGS IEENJJUFVSYNX
Length of longest common subsequence: 4

Given two strings, determine the length of the longest common subsequence.

Strings: MKBOAUC SZFLGZIFSVPNIANSPZCXZSDJPLMBYK
Length of longest common subsequence: 2

Given two strings, determine the length of the longest common subsequence.

Strings: ZUIEJOBQXVLXBMVOOMNJQSHJPY OVCOZNKRCXBYSMWOPRWMXIPCMRKX
Length of longest common subsequence: 8
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: ZUIEJOBQXVLXBMVOOMNJQSHJPY OVCOZNKRCXBYSMWOPRWMXIPCMRKX
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '8'
```
```
[sample 2]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: GDMKSZERXGPYTKJRQMLSSKLEALAJGS IEENJJUFVSYNX
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '4'
```
```
[sample 3]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: MKBOAUC SZFLGZIFSVPNIANSPZCXZSDJPLMBYK
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '2'
```
```
[sample 4]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: NYFHVYS YKOPMNDEJGKMNYTMQAFOUPYNDB
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '4'
```
```
[sample 5]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: CYMELIHGBDQGYBLUJYJVNTZAXBLVZP BCRFZFYGPYIQZHHOYGDHQQSXFXA
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '8'
```

### `bigbench_operators`  —  KEEP
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Pure abstraction (defined operators), era-neutral. Fairest symbolic task.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Given the definition of the op operator, compute the result.
op n1 n2 ... nn extracts the last multiple of 8 from the n listed numbers.
op 4 32 128 132 = 128

Given the definition of the op operator, compute the result.
i op1 j is the product of i and j; i op2 j is the integer division of i by j.
2 op1 6 op2 4 = 3

Given the definition of the op operator, compute the result.
op i is either the half of i when i is even, or its double when it is not.
op (op 17) = 17
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
Given the definition of the op operator, compute the result.
op i is either the half of i when i is even, or its double when it is not.
op (op 17) =
GOLD CONTINUATION (model must produce):
  >>> '17'
```
```
[sample 2]
CONTEXT:
Given the definition of the op operator, compute the result.
op n1 n2 ... nn extracts the last multiple of 8 from the n listed numbers.
op 4 32 128 132 =
GOLD CONTINUATION (model must produce):
  >>> '128'
```
```
[sample 3]
CONTEXT:
Given the definition of the op operator, compute the result.
i op1 j is the product of i and j; i op2 j is the integer division of i by j.
2 op1 6 op2 4 =
GOLD CONTINUATION (model must produce):
  >>> '3'
```
```
[sample 4]
CONTEXT:
Given the definition of the op operator, compute the result.
i op j is the remainder of the integer division of i by j.
5 op 3 =
GOLD CONTINUATION (model must produce):
  >>> '2'
```
```
[sample 5]
CONTEXT:
Given the definition of the op operator, compute the result.
op n1 n2 ... nn selects the smallest prime from the n listed numbers or returns 0 if none is prime.
op -16 1 7 4 =
GOLD CONTINUATION (model must produce):
  >>> '7'
```

### `bigbench_repeat_copy_logic`  —  REWRITE
*Language modeling · 10-shot · baseline 0% · delimiter `' '`*  
> Mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
repeat with logic:

Q: say python twice and data once, and then repeat all of this three times.
A: python python data python python data python python data

repeat with logic:

Q: output if you teach a person to fish you will three times
A: if you teach a person to fish you will if you teach a person to fish you will if you teach a person to fish you will

repeat with logic:

Q: A watermelon has seven seeds. Repeat they're delicious once for every seed
A: they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
repeat with logic:

Q: A watermelon has seven seeds. Repeat they're delicious once for every seed
A:
GOLD CONTINUATION (model must produce):
  >>> "they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious"
```
```
[sample 2]
CONTEXT:
repeat with logic:

Q: say python twice and data once, and then repeat all of this three times.
A:
GOLD CONTINUATION (model must produce):
  >>> 'python python data python python data python python data'
```
```
[sample 3]
CONTEXT:
repeat with logic:

Q: output if you teach a person to fish you will three times
A:
GOLD CONTINUATION (model must produce):
  >>> 'if you teach a person to fish you will if you teach a person to fish you will if you teach a person to fish you will'
```
```
[sample 4]
CONTEXT:
repeat with logic:

Q: repeat election to the council three times, but after every other word say cool
A:
GOLD CONTINUATION (model must produce):
  >>> 'election to cool the council cool election to cool the council cool election to cool the council cool'
```
```
[sample 5]
CONTEXT:
repeat with logic:

Q: say pickup a pound of green beans twice, replacing a pound with a bunch for even times and a handful for odd
A:
GOLD CONTINUATION (model must produce):
  >>> 'pickup a handful of green beans pickup a bunch of green beans'
```

---

## Language Understanding

### `hellaswag_zeroshot`  —  REWRITE
*Multiple choice · 0-shot · baseline 25% · delimiter `' '`*  
> Same source, 0-shot variant of hellaswag.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
CHOICES (* = gold):
    [0] is using wrap to wrap a pair of skis.
    [1] is ripping level tiles off.
    [2] is holding a rubik's cube.
  * [3] starts pulling up roofing on a roof.
```
```
[sample 2]
STEM:
Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady stands and lifts the weight over her head.
CHOICES (* = gold):
    [0] swings and lands in her arms.
    [1] pulls the barbell forward.
    [2] pulls a rope attached to the barbell.
  * [3] stands and lifts the weight over her head.
```
```
[sample 3]
STEM:
Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individuals visible in the background. The child and a different man sit in a canoe while the man paddles.
CHOICES (* = gold):
    [0] are then shown paddling down a river in a boat while a woman talks.
    [1] are driving the canoe, they go down the river flowing side to side.
  * [2] sit in a canoe while the man paddles.
    [3] walking go down the rapids, while the man in his helicopter almost falls and goes out of canoehood.
```
```
[sample 4]
STEM:
High jump: A boy is running down a track. The boy lifts his body above the height of a pole.
CHOICES (* = gold):
    [0] runs into a car.
    [1] gets in a mat.
  * [2] lifts his body above the height of a pole.
    [3] stands on his hands and springs.
```
```
[sample 5]
STEM:
High jump: The boy lifts his body above the height of a pole. The boy lands on his back on to a red mat. The boy gets up from the mat.
CHOICES (* = gold):
    [0] turns his body around on the mat.
  * [1] gets up from the mat.
    [2] continues to lift his body over the pole.
    [3] wiggles out of the mat.
```

### `lambada_openai`  —  REWRITE
*Language modeling · 0-shot · baseline 0% · delimiter `' '`*  
> Modern-novel prose (register). Strong signal, scales well -> rewrite to held-out period books, do NOT drop.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
In my palm is a clear stone, and inside it is a small ivory statuette. A guardian angel.

"Figured if you're going to be out at night getting hit by cars, you might as well have some backup."

I look at him, feeling stunned. Like this is some sort of sign. But as I stare at Harlin, his mouth curved in a confident grin, I don't care about signs
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT:
In my palm is a clear stone, and inside it is a small ivory statuette. A guardian angel.

"Figured if you're going to be out at night getting hit by cars, you might as well have some backup."

I look at him, feeling stunned. Like this is some sort of sign. But as I stare at Harlin, his mouth curved in a confident grin, I don't care about
GOLD CONTINUATION (model must produce):
  >>> 'signs'
```
```
[sample 2]
CONTEXT:
Give me a minute to change and I'll meet you at the docks." She'd forced those words through her teeth.

"No need to change. We won't be that long."

Shane gripped her arm and started leading her to the dock.

"I can make it there on my own,
GOLD CONTINUATION (model must produce):
  >>> 'Shane'
```
```
[sample 3]
CONTEXT:
"Only one source I know of that would be likely to cough up enough money to finance a phony sleep research facility and pay people big bucks to solve crimes in their dreams," Farrell concluded dryly.

"What can I say?" Ellis unfolded his arms and widened his hands. "Your tax dollars at work."

Before Farrell could respond, Leila's voice rose from inside the house.

"No insurance?" she wailed. "What do you mean you don't have any
GOLD CONTINUATION (model must produce):
  >>> 'insurance'
```
```
[sample 4]
CONTEXT:
Helen's heart broke a little in the face of Miss Mabel's selfless courage. She thought that because she was old, her life was of less value than the others'. For all Helen knew, Miss Mabel had a lot more years to live than she did. "Not going to happen," replied
GOLD CONTINUATION (model must produce):
  >>> 'Helen'
```
```
[sample 5]
CONTEXT:
Preston had been the last person to wear those chains, and I knew what I'd see and feel if they were slipped onto my skin-the Reaper's unending hatred of me. I'd felt enough of that emotion already in the amphitheater. I didn't want to feel anymore.

"Don't put those on me," I whispered. "Please."

Sergei looked at me, surprised by my low, raspy please, but he put down the
GOLD CONTINUATION (model must produce):
  >>> 'chains'
```

### `hellaswag`  —  REWRITE
*Multiple choice · 10-shot · baseline 25% · delimiter `' '`*  
> Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite).

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady stands and lifts the weight over her head.

Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individuals visible in the background. The child and a different man sit in a canoe while the man paddles.

Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
CHOICES (* = gold):
    [0] is using wrap to wrap a pair of skis.
    [1] is ripping level tiles off.
    [2] is holding a rubik's cube.
  * [3] starts pulling up roofing on a roof.
```
```
[sample 2]
STEM:
Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady stands and lifts the weight over her head.
CHOICES (* = gold):
    [0] swings and lands in her arms.
    [1] pulls the barbell forward.
    [2] pulls a rope attached to the barbell.
  * [3] stands and lifts the weight over her head.
```
```
[sample 3]
STEM:
Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individuals visible in the background. The child and a different man sit in a canoe while the man paddles.
CHOICES (* = gold):
    [0] are then shown paddling down a river in a boat while a woman talks.
    [1] are driving the canoe, they go down the river flowing side to side.
  * [2] sit in a canoe while the man paddles.
    [3] walking go down the rapids, while the man in his helicopter almost falls and goes out of canoehood.
```
```
[sample 4]
STEM:
High jump: A boy is running down a track. The boy lifts his body above the height of a pole.
CHOICES (* = gold):
    [0] runs into a car.
    [1] gets in a mat.
  * [2] lifts his body above the height of a pole.
    [3] stands on his hands and springs.
```
```
[sample 5]
STEM:
High jump: The boy lifts his body above the height of a pole. The boy lands on his back on to a red mat. The boy gets up from the mat.
CHOICES (* = gold):
    [0] turns his body around on the mat.
  * [1] gets up from the mat.
    [2] continues to lift his body over the pole.
    [3] wiggles out of the mat.
```

### `winograd`  —  KEEP
*Schema · 0-shot · baseline 50% · delimiter `' '`*  
> Timeless pronoun resolution; register already period-appropriate.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
The city councilmen refused the demonstrators a permit because the city councilmen feared violence.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT OPTIONS (* = gold), shared continuation = 'feared violence.':
  * [0] The city councilmen refused the demonstrators a permit because the city councilmen
    [1] The city councilmen refused the demonstrators a permit because the demonstrators
```
```
[sample 2]
CONTEXT OPTIONS (* = gold), shared continuation = 'advocated violence.':
    [0] The city councilmen refused the demonstrators a permit because the city councilmen
  * [1] The city councilmen refused the demonstrators a permit because the demonstrators
```
```
[sample 3]
CONTEXT OPTIONS (* = gold), shared continuation = 'is too large.':
  * [0] The trophy doesn't fit into the brown suitcase because the trophy
    [1] The trophy doesn't fit into the brown suitcase because the suitcase
```
```
[sample 4]
CONTEXT OPTIONS (* = gold), shared continuation = 'is too small.':
    [0] The trophy doesn't fit into the brown suitcase because the trophy
  * [1] The trophy doesn't fit into the brown suitcase because the suitcase
```
```
[sample 5]
CONTEXT OPTIONS (* = gold), shared continuation = 'had recieved.':
  * [0] Joan made sure to thank Susan for all the help Joan
    [1] Joan made sure to thank Susan for all the help Susan
```

### `winogrande`  —  KEEP
*Schema · 0-shot · baseline 50% · delimiter `' '`*  
> Timeless; optional light restyle.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Sarah was a much better surgeon than Maria so Maria always got the easier cases.
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
CONTEXT OPTIONS (* = gold), shared continuation = 'always got the easier cases.':
    [0] Sarah was a much better surgeon than Maria so Sarah
  * [1] Sarah was a much better surgeon than Maria so Maria
```
```
[sample 2]
CONTEXT OPTIONS (* = gold), shared continuation = 'always got the harder cases.':
  * [0] Sarah was a much better surgeon than Maria so Sarah
    [1] Sarah was a much better surgeon than Maria so Maria
```
```
[sample 3]
CONTEXT OPTIONS (* = gold), shared continuation = "was't ruined.":
    [0] They were worried the wine would ruin the bed and the blanket, but the blanket
  * [1] They were worried the wine would ruin the bed and the blanket, but the bed
```
```
[sample 4]
CONTEXT OPTIONS (* = gold), shared continuation = 'was too big.':
  * [0] Terry tried to bake the eggplant in the toaster oven but the eggplant
    [1] Terry tried to bake the eggplant in the toaster oven but the toaster
```
```
[sample 5]
CONTEXT OPTIONS (* = gold), shared continuation = 'wakes up late.':
  * [0] At night, Jeffrey always stays up later than Hunter to watch TV because Jeffrey
    [1] At night, Jeffrey always stays up later than Hunter to watch TV because Hunter
```

### `bigbench_language_identification`  —  KEEP
*Multiple choice · 10-shot · baseline 9.1% · delimiter `' '`*  
> Era-neutral (religious-translation sentences period-plausible). Low priority.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Given a sentence, select the correct language among the choices
Sentence: Ñõn ro otemjej i Rom, jitenburu iben Anij, emwij kir ir bwe ren dri kwojarjar: Joij ñõn kom im ainemõn jen Anij Jemer im Iroij Jisõs Kraist.
A. Rote Lole
B. Swedish
C. Marshallese
D. Boharic Coptic
Answer:  C

Given a sentence, select the correct language among the choices
Sentence: Kantyané mau terus niba njaluk kawelasan ngomong: ‘Mbok sabar ta! Utangku bakal tak bayar kabèh!’
A. Eastern Tzutujil
B. Zazaki
C. Bena-bena
D. Caribbean Javanese
Answer:  D

Given a sentence, select the correct language among the choices
Sentence: Chaymanta Apolos uk lugar Acaya shutiqman rinatinqa, Jesuspi kriyiqkunaqa, kusata animachir uk kartata rurar kaĉharanllapa Acayapi kriyiqkunaman, Apolos ĉhatinqa shumaqta samachinanllapapaq. Chaymi Apolos ĉharqa, Dyus akrashan kriyiqkunataqa, kusata yanaparan.
A. Nepali
B. Eastern Maroon Creole
C. Hdi
D. Lambayeque Quechua
Answer:  D
```

**5 sample items** (few-shot prefix omitted):

```
[sample 1]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Chaymanta Apolos uk lugar Acaya shutiqman rinatinqa, Jesuspi kriyiqkunaqa, kusata animachir uk kartata rurar kaĉharanllapa Acayapi kriyiqkunaman, Apolos ĉhatinqa shumaqta samachinanllapapaq. Chaymi Apolos ĉharqa, Dyus akrashan kriyiqkunataqa, kusata yanaparan.
A. Nepali
B. Eastern Maroon Creole
C. Hdi
D. Lambayeque Quechua
Answer:  D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 2]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Ñõn ro otemjej i Rom, jitenburu iben Anij, emwij kir ir bwe ren dri kwojarjar: Joij ñõn kom im ainemõn jen Anij Jemer im Iroij Jisõs Kraist.
A. Rote Lole
B. Swedish
C. Marshallese
D. Boharic Coptic
Answer:  C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 3]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Kantyané mau terus niba njaluk kawelasan ngomong: ‘Mbok sabar ta! Utangku bakal tak bayar kabèh!’
A. Eastern Tzutujil
B. Zazaki
C. Bena-bena
D. Caribbean Javanese
Answer:  D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 4]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Re qava rie mwaiqe mwo kua ri timwa mwiase. Re mwariaranta te mwauraro qina nroravano vutana vaiso. Mwaintai vuaso mwintai nriaso tiro Kotiva qina nrora mwataiso, tuvo.
A. Northern Puebla Nahuatl
B. Apinaye
C. Adioukrou
D. Veqaura
Answer:  D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 5]
STEM:
Given a sentence, select the correct language among the choices
Sentence: A tłumy, które szły przed nim i za nim, wołały: Hosanna Synowi Dawida! Błogosławiony, który przychodzi w imieniu Pana! Hosanna na wysokościach!
A. Upper Tanana
B. Polish
C. Kasua
D. Bosnian
Answer:  B
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```

---

## 5. Audit & adaptation verdicts (editable)

Hand-written; modify freely. **Two independent axes** — keep them separate (conflating them is what produced
the earlier bad drops):

- **Temporal axis (the verdict).** Where does the anachronism live? Register-only -> **REWRITE**; content/fact
  post-1930 -> **FILTER or DROP**; era-neutral -> **KEEP**. This is the only thing the verdict encodes.
- **Signal axis (Section 3).** How much does the task move at a given scale? This is scale-dependent and
  **never a reason to drop** — `winograd`/`jeopardy` look dead at d12 yet come alive at d24.
- A task is dropped only when it fails the *temporal* axis (can't be made fair: `squad`, `cs_algorithms`) or is
  **structurally unscorable at every scale tested** (`boolq`: below chance at d12 *and* d24).

### Reading Comprehension
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `squad` | **DROP** | Content-anachronistic (e.g. Super Bowl 50); cannot restyle a nonexistent event. (swap ruled out) |
| `coqa` | **REWRITE** | Stories era-neutral (kitten Cotton); restyle surface prose to 1930 register. |
| `boolq` | **DROP** | Below chance at d12 AND d24 (62% baseline); does not respond to depth -> structurally unscorable for this model class. |

### Commonsense Reasoning
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `copa` | **KEEP** | Fully timeless causal commonsense; faucets existed in 1930. |
| `commonsense_qa` | **REWRITE** | Timeless reasoning, modern framing (revolving door/bank). [anomaly: drops with depth - watch] |
| `piqa` | **REWRITE+FILTER** | Timeless physical reasoning, modern register/objects. Restyle + drop modern items. |
| `openbook_qa` | **REWRITE** | Timeless commonsense/science; light restyle. |

### World Knowledge
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `jeopardy` | **FILTER** | Many items already pre-1930 (Bacon, Byrd). Date-filter Science/post-1930 facts. |
| `bigbench_qa_wikidata` | **FILTER** | Drop modern entities. ANSWER-side trap: "Novosibirsk -> Russia" should be USSR in 1930. |
| `arc_easy` | **FILTER** | Pre-1930 science fine; drop modern-tech items. |
| `arc_challenge` | **FILTER** | 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor. |

### Symbolic Problem Solving
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `bigbench_dyck_languages` | **KEEP** | Era-neutral symbol manipulation; needs no modern knowledge. Scales with depth (0.065->0.124). Was wrongly dropped on signal. |
| `agi_eval_lsat_ar` | **KEEP** | Era-neutral analytical logic (abstract scheduling); no modern knowledge -> FAIR. Low d12 signal is capacity, not anachronism. |
| `bigbench_cs_algorithms` | **DROP** | Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data. |
| `bigbench_operators` | **KEEP** | Pure abstraction (defined operators), era-neutral. Fairest symbolic task. |
| `bigbench_repeat_copy_logic` | **REWRITE** | Mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens. |

### Language Understanding
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `hellaswag_zeroshot` | **REWRITE** | Same source, 0-shot variant of hellaswag. |
| `lambada_openai` | **REWRITE** | Modern-novel prose (register). Strong signal, scales well -> rewrite to held-out period books, do NOT drop. |
| `hellaswag` | **REWRITE** | Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite). |
| `winograd` | **KEEP** | Timeless pronoun resolution; register already period-appropriate. |
| `winogrande` | **KEEP** | Timeless; optional light restyle. |
| `bigbench_language_identification` | **KEEP** | Era-neutral (religious-translation sentences period-plausible). Low priority. |

### Justified exclusions (the only 3 drops)
| Task | Drop reason | Axis | Evidence |
|------|-------------|------|----------|
| `squad` | Content cannot be restyled (Super Bowl 50 didn't exist) | temporal | passage content post-1930 |
| `bigbench_cs_algorithms` | Modern-CS concept + spurious 0%-baseline | temporal + artifact | flat across depth (0.43->0.41) AND data |
| `boolq` | Below chance at every scale | structural | d12 -0.14/-0.07, d24 -0.06; depth does not help |

### Proposed vintage suite (~19 tasks)
**KEEP** (7): copa, operators, dyck, agi_eval_lsat_ar, winograd, winogrande, language_identification · 
**REWRITE** (8): coqa, commonsense_qa, openbook_qa, piqa, repeat_copy_logic, hellaswag, hellaswag_zeroshot, lambada · 
**FILTER** (4): jeopardy, qa_wikidata, arc_easy, arc_challenge · 
**DROP** (3): squad, cs_algorithms, boolq. (verdict tally from META: {'DROP': 3, 'REWRITE': 7, 'KEEP': 7, 'REWRITE+FILTER': 1, 'FILTER': 4})

### Open decisions
- [ ] Re-validate `random_baseline` empirically for every REWRITE task (esp. hellaswag — adversarial distractors break).
- [ ] **Acceptance test needs depth, not seeds:** keep a task if it separates *across model scale* (d12<d24<d34),
  not by absolute d12 score. Re-run the depth table (3C) on the vintage ladder once d24 vintage exists.
- [ ] **commonsense_qa anomaly:** drops with depth (d12 0.20 -> d24 0.06). Investigate before trusting it.
- [ ] **lambada rewrite source:** held-out period books (not training data) to avoid contamination.
- [ ] Confirm answer-side anachronism handling for qa_wikidata (Russia/USSR-type cases).

