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
| 1 | `squad` | Reading Comprehension | 10570 | **REWRITE+FILTER** | 30.9% of items carry a post-1930 year (full scan). Filter those, restyle remaining Wikipedia register. Same kind as boolq/coqa. |
| 2 | `coqa` | Reading Comprehension | 7983 | **REWRITE+FILTER** | 26.8% post-1930 years (full scan). Stories partly era-neutral but passages skew modern; filter + restyle. |
| 3 | `boolq` | Reading Comprehension | 3270 | **REWRITE+FILTER** | MOST temporal task: 40.6% post-1930 years (full scan). Heavy filter + restyle. NB: below chance through d24 -> may not score until d34 (signal-axis watch). |
| 4 | `copa` | Commonsense Reasoning | 100 | **KEEP** | Full scan: 0% post-1930 years. Timeless causal commonsense. |
| 5 | `commonsense_qa` | Commonsense Reasoning | 1221 | **KEEP** | Full scan: 0.1% post-1930 years -> essentially era-neutral (you were right). Optional light filter of ~3.5% modern-framed items. [depth anomaly: watch] |
| 6 | `piqa` | Commonsense Reasoning | 1838 | **REWRITE+FILTER** | 0% years but modern register/objects. Restyle; light item filter. |
| 7 | `openbook_qa` | Commonsense Reasoning | 500 | **REWRITE** | 0% years; timeless commonsense/science; light restyle of register. |
| 8 | `jeopardy` | World Knowledge | 2117 | **FILTER** | 11.7% post-1930 years (full scan). Date-filter; many items already pre-1930 (Bacon, Byrd). |
| 9 | `bigbench_qa_wikidata` | World Knowledge | 20321 | **FILTER** | Text scan clean (0.1% years) but modernity is in ENTITY IDENTITY (people born post-1930) -> needs entity-dating, NOT text filtering. Different problem than squad. |
| 10 | `arc_easy` | World Knowledge | 2376 | **FILTER** | 0.5% years; pre-1930 science fine; drop modern-tech items. |
| 11 | `arc_challenge` | World Knowledge | 1172 | **FILTER** | 0.7% years; 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor. |
| 12 | `bigbench_dyck_languages` | Symbolic Problem Solving | 1000 | **DROP** | Low construct value + likely OUT-OF-DISTRIBUTION for a books-trained vintage model (bracket sequences never appear in 1930 prose). Drop on construct/OOD grounds (not anachronism). |
| 13 | `agi_eval_lsat_ar` | Symbolic Problem Solving | 230 | **KEEP** | Full scan: 0% post-1930 years. Era-neutral analytical logic -> FAIR (you were right). Optional light filter of ~5% modern-topic passages. |
| 14 | `bigbench_cs_algorithms` | Symbolic Problem Solving | 1320 | **DROP** | Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data. |
| 15 | `bigbench_operators` | Symbolic Problem Solving | 210 | **KEEP** | Pure abstraction (defined operators), era-neutral. (100% "modern" in scan = false positive on the word "compute".) |
| 16 | `bigbench_repeat_copy_logic` | Symbolic Problem Solving | 32 | **REWRITE** | 0% years; mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens. |
| 17 | `hellaswag_zeroshot` | Language Understanding | 10042 | **REWRITE** | Same source, 0-shot variant of hellaswag. |
| 18 | `lambada_openai` | Language Understanding | 5153 | **REWRITE** | 0.2% years but modern-novel REGISTER. Strong signal, scales well -> rewrite to held-out period books, do NOT drop. |
| 19 | `hellaswag` | Language Understanding | 10042 | **REWRITE** | Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite). |
| 20 | `winograd` | Language Understanding | 273 | **KEEP** | Timeless pronoun resolution; register already period-appropriate. |
| 21 | `winogrande` | Language Understanding | 1267 | **KEEP** | Timeless; optional light restyle. |
| 22 | `bigbench_language_identification` | Language Understanding | 10000 | **KEEP** | Era-neutral (religious-translation sentences period-plausible). Low priority. |

**Verdict legend:** KEEP = era-neutral, use as-is · REWRITE = restyle register, content fine · FILTER = date-drop anachronistic items, keep rest · DROP = anachronistic / impossible / structurally unscorable.

**Only 2 DROPs, on non-anachronism grounds:** `cs_algorithms` (modern-CS concept + spurious baseline) and `dyck_languages` (low construct value + out-of-distribution for a books model). Everything temporally-loaded is *adaptable* via FILTER/REWRITE rather than dropped — including `squad` and `boolq`, now treated like `coqa` (heavy-temporal passage tasks). `commonsense_qa`, `agi_eval_lsat_ar` confirmed era-neutral by the full scan below.

### Temporal audit — full-benchmark scan (every item)

To justify the verdicts without eyeballing 5 questions, every item in each task is scanned for a **post-1930
year** (the reliable signal) and for **modern keywords** (noisy — see caveats). This is 100% coverage, not a sample.

| Task | N | post-1930 yr | % | modern kw % | Verdict | reading |
|------|---|--------------|---|-------------|---------|---------|
| `squad` | 10570 | 3261 | 30.9% | 13.3% | **REWRITE+FILTER** | heavy |
| `coqa` | 7983 | 2142 | 26.8% | 10.6% | **REWRITE+FILTER** | heavy |
| `boolq` | 3270 | 1326 | 40.6% | 8.6% | **REWRITE+FILTER** | heavy |
| `copa` | 100 | 0 | 0.0% | 0.0% | **KEEP** | clean |
| `commonsense_qa` | 1221 | 1 | 0.1% | 2.2% | **KEEP** | clean |
| `piqa` | 1838 | 0 | 0.0% | 1.6% | **REWRITE+FILTER** | clean |
| `openbook_qa` | 500 | 0 | 0.0% | 0.8% | **REWRITE** | clean |
| `jeopardy` | 2117 | 248 | 11.7% | 0.1% | **FILTER** | heavy |
| `bigbench_qa_wikidata` | 20321 | 27 | 0.1% | 0.1% | **FILTER** | clean |
| `arc_easy` | 2376 | 12 | 0.5% | 1.1% | **FILTER** | clean |
| `arc_challenge` | 1172 | 8 | 0.7% | 1.0% | **FILTER** | clean |
| `bigbench_dyck_languages` | 1000 | 0 | 0.0% | 0.0% | **DROP** | clean |
| `agi_eval_lsat_ar` | 230 | 0 | 0.0% | 5.2% | **KEEP** | clean |
| `bigbench_cs_algorithms` | 1320 | 0 | 0.0% | 0.0% | **DROP** | clean |
| `bigbench_operators` | 210 | 0 | 0.0% | 0.0% | **KEEP** | clean |
| `bigbench_repeat_copy_logic` | 32 | 0 | 0.0% | 0.0% | **REWRITE** | clean |
| `hellaswag_zeroshot` | 10042 | 43 | 0.4% | 9.7% | **REWRITE** | clean |
| `lambada_openai` | 5153 | 8 | 0.2% | 0.9% | **REWRITE** | clean |
| `hellaswag` | 10042 | 43 | 0.4% | 9.7% | **REWRITE** | clean |
| `winograd` | 273 | 0 | 0.0% | 0.0% | **KEEP** | clean |
| `winogrande` | 1267 | 0 | 0.0% | 1.7% | **KEEP** | clean |
| `bigbench_language_identification` | 10000 | 315 | 3.1% | 0.1% | **KEEP** | some |

**How to read it:**
- **Years are trustworthy; keyword % is not.** `operators` would show ~100% on a naive keyword scan because the
  prompt literally says "compute" — excluded here. Lean on the year column.
- **heavy** (>10% post-1930 years): `boolq` 40.6%, `squad` 30.9%, `coqa` 26.8%, `jeopardy` 11.7%, `hellaswag` 13.4% kw.
  These need real FILTER + REWRITE, not light touches.
- **clean** (<1% years): all KEEP tasks + `commonsense_qa` (0.1%), `agi_eval_lsat_ar` (0%), `piqa`/`openbook` (0%).
  This is the empirical "pass through KEEP for temporal content" you asked for — they pass.
- **The blind spot:** `qa_wikidata` scans 0.1% but its modernity is in *entity identity* (people born post-1930),
  invisible to text regex. So **no, it is NOT the same detectable story as squad** — it needs entity-dating (NER +
  birth/founding dates), a harder filter. squad/boolq wear their dates in the text; wikidata hides them in names.

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
- `squad` (REWRITE+FILTER, N=10570): Monotonic (0.02->0.03->0.05) -> small but real.
- `hellaswag` (REWRITE, N=10042): Tiny but clean monotonic climb (0.038->0.042->0.048).
- `arc_easy` (FILTER, N=2376): Climbs then plateaus (0.08->0.10->0.10).
- `commonsense_qa` (KEEP, N=1221): Flat ~0.14 -> capacity-bound, not data-bound at d12.
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
| temporally-loaded (REWRITE/FILTER/DROP) | 12 | **+0.121** |
| era-neutral (KEEP) | 7 | +0.023 (within noise) |

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

## 4. The 22 benchmarks — samples as the model sees them

Each task shows: the **official Gauntlet description**, the full-scan temporal stat, one fully-assembled
prompt (with 2 few-shot for framing), then **8 sample items strided evenly across the whole file** (not the
first 8 — so passage-grouped tasks like SQuAD do not all show one topic), plus any **flagged temporal items**
the scan found. (The scorer shuffles all items with a fixed seed and uses the full set; order does not matter.)

---

## Reading Comprehension

### `squad`  —  REWRITE+FILTER
*Language modeling · 10-shot · baseline 0% · N=10570 · post-1930 years: 3261 (30.9%)*  
> **Gauntlet:** SQuAD (2016): 10,570 short documents (sports news, physics blurbs, US history) + a question; output the exact answer.

> **Verdict (REWRITE+FILTER):** 30.9% of items carry a post-1930 year (full scan). Filter those, restyle remaining Wikipedia register. Same kind as boolq/coqa.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as "Super Bowl L"), so that the logo could prominently feature the Arabic numerals 50.
Question: Which NFL team represented the NFC at Super Bowl 50?
Answer: Carolina Panthers

Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Fo
[... truncated for this doc ...]
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Denver Broncos'
```
```
[sample 2 of 8 — strided]
CONTEXT:
Context: Tesla invented a steam-powered mechanical oscillator—Tesla's oscillator. While experimenting with mechanical oscillators at his Houston Street lab, Tesla allegedly generated a resonance of several buildings. As the speed grew, it is said that the machine oscillated at the resonance frequency of his own building and, belatedly realizing the danger, he was forced to use a sledge hammer to terminate the experiment, just as the police arrived.:162–164 In February 1912, an article—"Nikola Tesla, Dreamer" by Allan L. Benson—was published in World Today, in which an artist's illustration appears showing the entire earth cracking in half with the caption, "Tesla claims that in a few weeks h
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'the machine oscillated at the resonance frequency of his own building'
```
```
[sample 3 of 8 — strided]
CONTEXT:
Context: In 1854 at Ballarat there was an armed rebellion against the government of Victoria by miners protesting against mining taxes (the "Eureka Stockade"). This was crushed by British troops, but the discontents prompted colonial authorities to reform the administration (particularly reducing the hated mining licence fees) and extend the franchise. Within a short time, the Imperial Parliament granted Victoria responsible government with the passage of the Colony of Victoria Act 1855. Some of the leaders of the Eureka rebellion went on to become members of the Victorian Parliament.
Question: The passage of what act gave Victoria its own government?
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Colony of Victoria Act'
```
```
[sample 4 of 8 — strided]
CONTEXT:
Context: Ctenophores may be abundant during the summer months in some coastal locations, but in other places they are uncommon and difficult to find. In bays where they occur in very high numbers, predation by ctenophores may control the populations of small zooplanktonic organisms such as copepods, which might otherwise wipe out the phytoplankton (planktonic plants), which are a vital part of marine food chains. One ctenophore, Mnemiopsis, has accidentally been introduced into the Black Sea, where it is blamed for causing fish stocks to collapse by eating both fish larvae and organisms that would otherwise have fed the fish. The situation was aggravated by other factors, such as over-fishin
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'over-fishing and long-term environmental changes'
```
```
[sample 5 of 8 — strided]
CONTEXT:
Context: As a result, with the exception of the largest markets, ABC was relegated to secondary status on one or both of the existing stations, usually via off-hours clearances (a notable exception during this time was WKST-TV in Youngstown, Ohio, now WYTV, despite the small size of the surrounding market and its close proximity to Cleveland and Pittsburgh even decades before the city's economic collapse). According to Goldenson, this meant that an hour of ABC programming reported five times lower viewership than its competitors. However, the network's intake of money at the time would allow it to accelerate its content production. Still, ABC's limited reach would continue to hobble it for t
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> '1980s'
```
```
[sample 6 of 8 — strided]
CONTEXT:
Context: According to International Monetary Fund economists, inequality in wealth and income is negatively correlated with the duration of economic growth spells (not the rate of growth). High levels of inequality prevent not just economic prosperity, but also the quality of a country's institutions and high levels of education. According to IMF staff economists, "if the income share of the top 20 percent (the rich) increases, then GDP growth actually declines over the medium term, suggesting that the benefits do not trickle down. In contrast, an increase in the income share of the bottom 20 percent (the poor) is associated with higher GDP growth. The poor and the middle class matter the mo
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'inequality in wealth and income'
```
```
[sample 7 of 8 — strided]
CONTEXT:
Context: can have infinitely many primes only when a and q are coprime, i.e., their greatest common divisor is one. If this necessary condition is satisfied, Dirichlet's theorem on arithmetic progressions asserts that the progression contains infinitely many primes. The picture below illustrates this with q = 9: the numbers are "wrapped around" as soon as a multiple of 9 is passed. Primes are highlighted in red. The rows (=progressions) starting with a = 3, 6, or 9 contain at most one prime number. In all other rows (a = 1, 2, 4, 5, 7, and 8) there are infinitely many prime numbers. What is more, the primes are distributed equally among those rows in the long run—the density of all primes co
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'at most one prime number'
```
```
[sample 8 of 8 — strided]
CONTEXT:
Context: The pound-force has a metric counterpart, less commonly used than the newton: the kilogram-force (kgf) (sometimes kilopond), is the force exerted by standard gravity on one kilogram of mass. The kilogram-force leads to an alternate, but rarely used unit of mass: the metric slug (sometimes mug or hyl) is that mass that accelerates at 1 m·s−2 when subjected to a force of 1 kgf. The kilogram-force is not a part of the modern SI system, and is generally deprecated; however it still sees use for some purposes as expressing aircraft weight, jet thrust, bicycle spoke tension, torque wrench settings and engine output torque. Other arcane units of force include the sthène, which is equivalen
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'sthène'
```

**Flagged temporal items** (first 3 of 3261 with a post-1930 year):
- `2015`: Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American
- `2015`: Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American
- `2015`: Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American

### `coqa`  —  REWRITE+FILTER
*Language modeling · 0-shot · baseline 0% · N=7983 · post-1930 years: 2142 (26.8%)*  
> **Gauntlet:** CoQA (2018): 7,983 passage-based short free-response questions; each passage has a series of related questions with prior Q/A in context; exact match.

> **Verdict (REWRITE+FILTER):** 26.8% post-1930 years (full scan). Stories partly era-neutral but passages skew modern; filter + restyle.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite sad. She often wished she looked like the rest of her family. So one day, when Cotton found a can of the old farmer's orange paint, she used it to paint herself like them. When her mommy and sisters found her they started laughing. 

"What are you doing, Cotton?!" 

"I only wanted to be more like you". 

Cotton's mommy rubbed her face on Cotton's and said "Oh Cotton, but your fur is so pretty and 
[... truncated for this doc ...]
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Once upon a time, in a barn near a farm house, there lived a little white kitten named Cotton. Cotton lived high up in a nice warm place above the barn where all of the farmer's horses slept. But Cotton wasn't alone in her little home above the barn, oh no. She shared her hay bed with her mommy and 5 other sisters. All of her sisters were cute and fluffy, like Cotton. But she was the only white one in the bunch. The rest of her sisters were all orange with beautiful white tiger stripes like Cotton's mommy. Being different made Cotton quite 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'white'
```
```
[sample 2 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: CHAPTER XX 

A BLIZZARD 

A bitter wind searched the poplar bluff where George and his hired man, Grierson, were cutting fuel. Except in the river valleys, trees of any size are scarce on the prairie, but the slender trunks and leafless branches were closely massed and afforded a little shelter. Outside on the open waste, the cold was almost too severe to face, and George once or twice glanced anxiously across the snowy levels, looking for some sign of Edgar, who should have joined them with the team and sledge. It was, however, difficult t
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'the surrounding dimness'
```
```
[sample 3 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: (CNN) -- Marathon man John Isner survived another epic on his return to competitive tennis after his record-breaking 11-hour Wimbledon match. 

The American saved two match points before beating Gilles Muller, from Luxembourg, 4-6 7-6 7-6 to seal his place in the quarterfinals of the Atlanta Tennis Championships. 

It is Isner's first tournament since Wimbledon back in June when his opening round victory over Frenchman Nicolas Mahut in London clocked in as the longest match in tennis history. 

Isner's battle with Mahut stretched over three
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'competitive tennis'
```
```
[sample 4 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: CHAPTER XXVII 

WAITING 

Ingleside, 1st November 1917 

"It is November--and the Glen is all grey and brown, except where the Lombardy poplars stand up here and there like great golden torches in the sombre landscape, although every other tree has shed its leaves. It has been very hard to keep our courage alight of late. The Caporetto disaster is a dreadful thing and not even Susan can extract much consolation out of the present state of affairs. The rest of us don't try. Gertrude keeps saying desperately, 'They must not get Venice--they m
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> '1914'
```
```
[sample 5 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: CHAPTER XXX. HOW THE BRUSHWOOD MEN CAME TO THE CHATEAU OF VILLEFRANCHE. 

It was late ere Alleyne Edricson, having carried Sir Nigel the goblet of spiced wine which it was his custom to drink after the curling of his hair, was able at last to seek his chamber. It was a stone-flagged room upon the second floor, with a bed in a recess for him, and two smaller pallets on the other side, on which Aylward and Hordle John were already snoring. Alleyne had knelt down to his evening orisons, when there came a tap at his door, and Ford entered with 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Sir Nigel'
```
```
[sample 6 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: A new study suggests that early exposure to germs strengthens the immune system. That means letting children get a little dirty might be good for their health later in life. 

The study involved laboratory mice. It found that adult mice raised in a germ-free environment were more likely to develop allergies, asthma and other autoimmune disorders. There are more than eighty disorders where cells that normally defend the body instead attack tissues and organs. 

Richard Blumberg,who led the study,is a professor at Harvard Medical School in Bo
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'Let kids play in a reasonable amount of dirt'
```
```
[sample 7 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Gujarati is an Indo-Aryan language native to the Indian state of Gujarat. It is part of the greater Indo-European language family. Gujarati is descended from Old Gujarati ("circa" 1100–1500 AD). In India, it is the official language in the state of Gujarat, as well as an official language in the union territories of Daman and Diu and Dadra and Nagar Haveli. Gujarati is the language of the Gujjars, who had ruled Rajputana and Punjab. 

According to the Central Intelligence Agency (CIA), 4.5% of the Indian population (1.21 billion according t
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> '4.5%'
```
```
[sample 8 of 8 — strided]
CONTEXT:
Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions.
Story: Las Vegas (, Spanish for "The Meadows"), officially the City of Las Vegas and often known simply as Vegas, is the 28th-most populated city in the United States, the most populated city in the state of Nevada, and the county seat of Clark County. The city anchors the Las Vegas Valley metropolitan area and is the largest city within the greater Mojave Desert. Las Vegas is an internationally renowned major resort city, known primarily for its gambling, shopping, fine dining, entertainment, and nightlife. The Las Vegas Valley as a whole serves 
[... truncated for this doc ...]
GOLD CONTINUATION (model must produce):
  >>> 'No'
```

**Flagged temporal items** (first 3 of 2142 with a post-1930 year):
- `1981`: Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions. Sto
- `1981`: Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions. Sto
- `1981`: Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the previous questions. Sto

### `boolq`  —  REWRITE+FILTER
*Multiple choice · 10-shot · baseline 62% · N=3270 · post-1930 years: 1326 (40.6%)*  
> **Gauntlet:** BoolQ (2019): 3,270 short passages on diverse subjects + a yes/no question, in multiple-choice format.

> **Verdict (REWRITE+FILTER):** MOST temporal task: 40.6% post-1930 years (full scan). Heavy filter + restyle. NB: below chance through d24 -> may not score until d34 (signal-axis watch).

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Passage: Property tax or 'house tax' is a local tax on buildings, along with appurtenant land. It is and imposed on the Possessor (not the custodian of property as per 1978, 44th amendment of constitution). It resembles the US-type wealth tax and differs from the excise-type UK rate. The tax power is vested in the states and is delegated to local bodies, specifying the valuation method, rate band, and collection procedures. The tax base is the annual rental value (ARV) or area-based rating. Owner-occupied and other properties not producing rent are assessed on cost and then converted into ARV by applying a percentage of cost, usually four percent. Vacant land is generally exempt. Central government properties are exempt. Instead a 'service charge' is permissible under executive order. Properties of foreign missions also enjoy tax exemption without requiring reciprocity. The tax is usually accompanied by service taxes, e.g., water tax, drainage tax, conservancy (sanitation) tax, lighting tax, all using the same tax base. The rate structure is flat on rural (panchayat) properties, but 
[... truncated for this doc ...]
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
Passage: All biomass goes through at least some of these steps: it needs to be grown, collected, dried, fermented, distilled, and burned. All of these steps require resources and an infrastructure. The total amount of energy input into the process compared to the energy released by burning the resulting ethanol fuel is known as the energy balance (or ``energy returned on energy invested''). Figures compiled in a 2007 report by National Geographic Magazine point to modest results for corn ethanol produced in the US: one unit of fossil-fuel energy is required to create 1.3 energy units from the resulting ethanol. The energy balance for sugarcane ethanol produced in Brazil is more favorable, wi
[... truncated for this doc ...]
CHOICES (* = gold):
  * [0] no
    [1] yes
```
```
[sample 2 of 8 — strided]
STEM:
Passage: In-N-Out Burger is an American regional chain of fast food restaurants with locations primarily in the American Southwest and Pacific coast. It was founded in Baldwin Park, California in 1948 by Harry Snyder and Esther Snyder. The chain is currently headquartered in Irvine, California and has slowly expanded outside Southern California into the rest of California, as well as into Arizona, Nevada, Utah, Texas, and Oregon. The current owner is Lynsi Snyder, the Snyders' only grandchild.
Question: is in n out only located in california?
Answer: no
CHOICES (* = gold):
  * [0] no
    [1] yes
```
```
[sample 3 of 8 — strided]
STEM:
Passage: A table may have multiple foreign keys, and each foreign key can have a different parent table. Each foreign key is enforced independently by the database system. Therefore, cascading relationships between tables can be established using foreign keys.
Question: can we have multiple foreign keys in a table?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 4 of 8 — strided]
STEM:
Passage: In biology, tissue is a cellular organizational level between cells and a complete organ. A tissue is an ensemble of similar cells and their extracellular matrix from the same origin that together carry out a specific function. Organs are then formed by the functional grouping together of multiple tissues.
Question: is tissue composed of one type of cell?
Answer: no
CHOICES (* = gold):
  * [0] no
    [1] yes
```
```
[sample 5 of 8 — strided]
STEM:
Passage: A table may have multiple foreign keys, and each foreign key can have a different parent table. Each foreign key is enforced independently by the database system. Therefore, cascading relationships between tables can be established using foreign keys.
Question: can i have multiple foreign keys in a table?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 6 of 8 — strided]
STEM:
Passage: At the annual meeting in Oslo on 29 June - 2 July 1992, chaired by Mr. Sten Lundbo, it was agreed to expand the scope of the MTCR to include nonproliferation of unmanned aerial vehicles (UAVs) for all weapons of mass destruction. Prohibited materials are divided into two Categories, which are outlined in the MTCR Equipment, Software, and Technology Annex. Membership has grown to 35 nations, with India joining on 27th of June 2016 adhering to the MTCR Guidelines unilaterally.
Question: is india a member of missile technology control regime?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 7 of 8 — strided]
STEM:
Passage: The United States Post Office issued the Statue of Liberty Forever stamp on December 1, 2010. The stamp shows the replica of the Statue of Liberty (Liberty Enlightening the World) located at the New York-New York Hotel and Casino on the Las Vegas Strip rather than the original Statue of Liberty in New York. The error was not noticed until March 2011. The error was identified by Sunipix, a stock photo agency in Texas. Ten and a half billion of the error stamps were produced. The mistake is the largest run of an error on a postage stamp.
Question: is the lady liberty stamp a forever stamp?
Answer: yes
CHOICES (* = gold):
    [0] no
  * [1] yes
```
```
[sample 8 of 8 — strided]
STEM:
Passage: In April 2017, it was announced that the series had been renewed for a third season of 20 episodes. The first half of ten episodes premiered on March 20, 2018. In June 2018, Freeform canceled the series after three seasons, but ordered two extra episodes to properly conclude the series' story; the second half of the third season is set to air in early 2019. As of May 15, 2018, 43 episodes of Shadowhunters have aired, concluding the first half of the third season.
Question: will there be a season 5 of shadowhunters?
Answer: no
CHOICES (* = gold):
  * [0] no
    [1] yes
```

**Flagged temporal items** (first 3 of 1326 with a post-1930 year):
- `2006`: Passage: All biomass goes through at least some of these steps: it needs to be grown, collected, dried, fermented, distilled, and burned. All of these
- `1978`: Passage: Property tax or 'house tax' is a local tax on buildings, along with appurtenant land. It is and imposed on the Possessor (not the custodian o
- `2014`: Passage: Harry Potter and the Escape from Gringotts is an indoor steel roller coaster at Universal Studios Florida, a theme park located within the Un

---

## Commonsense Reasoning

### `copa`  —  KEEP
*Multiple choice · 0-shot · baseline 50% · N=100 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** COPA (2011): 100 cause/effect 2-choice questions; pick the more plausible cause or effect of a premise.

> **Verdict (KEEP):** Full scan: 0% post-1930 years. Timeless causal commonsense.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
The man turned on the faucet, therefore water flowed from the spout.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
The man turned on the faucet, therefore water flowed from the spout.
CHOICES (* = gold):
    [0] the toilet filled with water.
  * [1] water flowed from the spout.
```
```
[sample 2 of 8 — strided]
STEM:
The player caught the ball, because her teammate threw it to her.
CHOICES (* = gold):
  * [0] her teammate threw it to her.
    [1] her opponent tried to intercept it.
```
```
[sample 3 of 8 — strided]
STEM:
The girl refused to eat her vegetables, therefore her father took away her dessert.
CHOICES (* = gold):
    [0] her father told her to drink her milk.
  * [1] her father took away her dessert.
```
```
[sample 4 of 8 — strided]
STEM:
The pair of students came under scrutiny by the teacher, because their responses on the assignment were identical.
CHOICES (* = gold):
    [0] the students both received excellent grades.
  * [1] their responses on the assignment were identical.
```
```
[sample 5 of 8 — strided]
STEM:
The key was missing from my pants pocket, because the pocket had a hole.
CHOICES (* = gold):
  * [0] the pocket had a hole.
    [1] the pants were new.
```
```
[sample 6 of 8 — strided]
STEM:
The tree branch landed in the river, therefore the branch moved downstream.
CHOICES (* = gold):
  * [0] the branch moved downstream.
    [1] the river's current became stronger.
```
```
[sample 7 of 8 — strided]
STEM:
The woman read the newspaper, therefore she discovered the outcome of the election.
CHOICES (* = gold):
  * [0] she discovered the outcome of the election.
    [1] she casted a vote in the election.
```
```
[sample 8 of 8 — strided]
STEM:
The woman was in a bad mood, therefore she told her friend to leave her alone.
CHOICES (* = gold):
    [0] she engaged in small talk with her friend.
  * [1] she told her friend to leave her alone.
```

### `commonsense_qa`  —  KEEP
*Multiple choice · 10-shot · baseline 20% · N=1221 · post-1930 years: 1 (0.1%)*  
> **Gauntlet:** CommonsenseQA (2019): 1,221 four-choice questions on basic commonsense about everyday items.

> **Verdict (KEEP):** Full scan: 0.1% post-1930 years -> essentially era-neutral (you were right). Optional light filter of ~3.5% modern-framed items. [depth anomaly: watch]

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
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
[sample 2 of 8 — strided]
STEM:
Question: I'm having some food at my party, what will I need to serve it?
Choices:
A. zoo
B. bowl
C. kitchen
D. spoon
Answer: D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 3 of 8 — strided]
STEM:
Question: What do you ask a child to do when you first meet her?
Choices:
A. count to ten
B. costume
C. state name
D. dress herself
Answer: C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 4 of 8 — strided]
STEM:
Question: John didn't mind getting in line.  It was what game after that he hated.  The time, the sore feet. He did not like doing what?
Choices:
A. have to wait for
B. standing in line
C. less confusion
D. being ordered
Answer: B
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 5 of 8 — strided]
STEM:
Question: If you have a large satchel with you when you fly you'll be asked to store it where?
Choices:
A. airport
B. luggage compartment
C. room
D. clothing store
Answer: B
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 6 of 8 — strided]
STEM:
Question: If a storey contained a panoramic view, what kind of structure would it be in?
Choices:
A. storey book
B. mall
C. tall building
D. book of stories
Answer: C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 7 of 8 — strided]
STEM:
Question: Why are dogs often known as man's best friend?
Choices:
A. aggressive
B. friendly
C. very loyal
D. very smart
Answer: C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 8 of 8 — strided]
STEM:
Question: What is another name for a disk for storing information?
Choices:
A. computer store
B. computer to store data
C. computer hard drive
D. usb mouse
Answer: C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```

**Flagged temporal items** (first 1 of 1 with a post-1930 year):
- `2000`: Question: John had a massive debt to 50 million dollars. Compared to that, Leo's 2000 dollar debt seemed what? Choices: A. dwarf B. inconsequential C.

### `piqa`  —  REWRITE+FILTER
*Multiple choice · 10-shot · baseline 50% · N=1838 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** PIQA (2019): 1,838 physical-commonsense 2-choice questions.

> **Verdict (REWRITE+FILTER):** 0% years but modern register/objects. Restyle; light item filter.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: dresser

Answer: finish, woodgrain with  bobby pin

Question: To fight Ivan Drago in Rocky for sega master system.

Answer: You have to defeat Apollo Creed and Clubber Lang first.

Question: How do I ready a guinea pig cage for it's new occupants?

Answer: Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
Question: How do I ready a guinea pig cage for it's new occupants?

Answer: Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
CHOICES (* = gold):
  * [0] Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
    [1] Provide the guinea pig with a cage full of a few inches of bedding made of ripped jeans material, you will also need to supply it with a water bottle and a food dish.
```
```
[sample 2 of 8 — strided]
STEM:
Question: How can I sweat less?

Answer: Use laser hair removal because according to dermatologist Mary Lupo, MD, although its purpose is getting rid of hair, it works great for getting rid of excessive sweat in the underarm area, too: “I find that it leads to less sweat production and decreases odor too, because your hair accumulates more bacteria than your skin.”
CHOICES (* = gold):
    [0] Use laser eye surgery because according to dermatologist Mary Lupo, MD, although its purpose is getting rid of hair, it works great for getting rid of excessive sweat in the underarm area, too: “I fin
[... truncated for this doc ...]
  * [1] Use laser hair removal because according to dermatologist Mary Lupo, MD, although its purpose is getting rid of hair, it works great for getting rid of excessive sweat in the underarm area, too: “I fi
[... truncated for this doc ...]
```
```
[sample 3 of 8 — strided]
STEM:
Question: To make a simple chili recipe, a cook would need to have,

Answer: beef, beans, tomatoes, peppers, dried chilies, onions, garlic, broth and water.
CHOICES (* = gold):
  * [0] beef, beans, tomatoes, peppers, dried chilies, onions, garlic, broth and water.
    [1] beef, milk, cheese, bell pepper, curry powder and yellow mustard for seasoning.
```
```
[sample 4 of 8 — strided]
STEM:
Question: how do you flex?

Answer: show your muscles.
CHOICES (* = gold):
  * [0] show your muscles.
    [1] lay down.
```
```
[sample 5 of 8 — strided]
STEM:
Question: How can I keep a piece of paper from sliding around on a table?

Answer: Take masking tape and tape down the edges of the paper to hold it into place.
CHOICES (* = gold):
  * [0] Take masking tape and tape down the edges of the paper to hold it into place.
    [1] Use magnets on either side of the table to hold down the paper.
```
```
[sample 6 of 8 — strided]
STEM:
Question: smoke

Answer: can mark air with color
CHOICES (* = gold):
    [0] can mark paper with color
  * [1] can mark air with color
```
```
[sample 7 of 8 — strided]
STEM:
Question: To improve engine efficiency,

Answer: replace your car's air filter every 20,000 miles.
CHOICES (* = gold):
    [0] replace your car's transmission every 20,000 miles.
  * [1] replace your car's air filter every 20,000 miles.
```
```
[sample 8 of 8 — strided]
STEM:
Question: Where can I buy a tennis ball

Answer: You can purchase a tennis ball at any sports store
CHOICES (* = gold):
  * [0] You can purchase a tennis ball at any sports store
    [1] You can purchase a tennis racket at any sports store
```

### `openbook_qa`  —  REWRITE
*Multiple choice · 0-shot · baseline 25% · N=500 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** OpenBookQA (2018): 500 four-choice questions on basic physical/scientific intuition about common objects.

> **Verdict (REWRITE):** 0% years; timeless commonsense/science; light restyle of register.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to quit eating lunch out
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to quit eating lunch out
CHOICES (* = gold):
    [0] make more phone calls
  * [1] quit eating lunch out
    [2] buy less with monopoly money
    [3] have lunch with friends
```
```
[sample 2 of 8 — strided]
STEM:
Decaying vegetation is part of the process that enables gas powered motors to operate
CHOICES (* = gold):
    [0] enables nuclear power to function
    [1] enables to emitting of light beams
  * [2] enables gas powered motors to operate
    [3] enables windmills to power electric grids
```
```
[sample 3 of 8 — strided]
STEM:
transplanting seedling oaks has a positive impact on the environment
CHOICES (* = gold):
    [0] fuel costs
    [1] the economy
    [2] housing value
  * [3] the environment
```
```
[sample 4 of 8 — strided]
STEM:
a large cluster of humans, dogs, apple trees, atmosphere and more can be called a community
CHOICES (* = gold):
    [0] army of ants
  * [1] a community
    [2] a toy store
    [3] a shopping mall
```
```
[sample 5 of 8 — strided]
STEM:
What can cause people to crash their car? Seeing a solar eclipse
CHOICES (* = gold):
  * [0] Seeing a solar eclipse
    [1] Using their turn signals
    [2] Driving the speed limit
    [3] Keeping their eyes on the road
```
```
[sample 6 of 8 — strided]
STEM:
Dead plants are easier to find in January
CHOICES (* = gold):
  * [0] January
    [1] July
    [2] May
    [3] September
```
```
[sample 7 of 8 — strided]
STEM:
In solid phase matter has a/an concrete configuration
CHOICES (* = gold):
  * [0] concrete configuration
    [1] ambiguous form
    [2] shapeless form
    [3] radioactive glow
```
```
[sample 8 of 8 — strided]
STEM:
Some animals use a liquid coming from their skin to adjust to heat
CHOICES (* = gold):
    [0] cold
    [1] water
  * [2] heat
    [3] humidity
```

---

## World Knowledge

### `jeopardy`  —  FILTER
*Language modeling · 10-shot · baseline 0% · N=2117 · post-1930 years: 248 (11.7%)*  
> **Gauntlet:** Jeopardy (2022): 2,117 questions across Literature, American/World History, Word Origins, Science; output the exact answer.

> **Verdict (FILTER):** 11.7% post-1930 years (full scan). Date-filter; many items already pre-1930 (Bacon, Byrd).

**Full prompt as scored (showing 2 of 10 few-shot):**

```
WORLD HISTORY: Accused of accepting bribes, Francis Bacon was imprisoned in this forbidding complex in 1621
Answer: Tower of London

WORLD HISTORY: More than 250,000 died in fighting before France granted this African nation independence July 3, 1962
Answer: Algeria

WORLD HISTORY: This Navy commander flew from a base at Little America to the South Pole & back Nov. 28-29, 1929
Answer: Admiral Richard Byrd
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
WORLD HISTORY: This Navy commander flew from a base at Little America to the South Pole & back Nov. 28-29, 1929
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Admiral Richard Byrd'
```
```
[sample 2 of 8 — strided]
CONTEXT:
WORLD HISTORY: Around 284 B.C. Zenodotus of Ephesus became the first superintendant of this citys library
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Alexandria'
```
```
[sample 3 of 8 — strided]
CONTEXT:
AMERICAN HISTORY: WWI sales of Liberty these, whose posters showed the statue, raised more than $15 billion
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'bonds'
```
```
[sample 4 of 8 — strided]
CONTEXT:
LITERATURE: This title home of a Hawthorne tale has an elm-tree of wide circumference, rooted before the door
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'The House of the Seven Gables'
```
```
[sample 5 of 8 — strided]
CONTEXT:
LITERATURE: This R.D. Blackmore novel begins in Exmoor, in the county of Somerset, in the year 1673
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Lorna Doone'
```
```
[sample 6 of 8 — strided]
CONTEXT:
SCIENCE: 2000 news: the Gunnison sage grouse isnt just another northern sage grouse, but a new one of this classification
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'species'
```
```
[sample 7 of 8 — strided]
CONTEXT:
WORD ORIGINS: This Austrian physicists name is now synonymous with a measurement of the speed of sound
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Mach'
```
```
[sample 8 of 8 — strided]
CONTEXT:
WORD ORIGINS: The name of these beauty devices comes from etuis -- small decorative cases that once held them
Answer:
GOLD CONTINUATION (model must produce):
  >>> 'Tweezers'
```

**Flagged temporal items** (first 3 of 248 with a post-1930 year):
- `1962`: WORLD HISTORY: More than 250,000 died in fighting before France granted this African nation independence July 3, 1962 Algeria
- `1946`: WORLD HISTORY: On May 9, 1946 this countrys King Victor Emmanuel abdicated in favor of his son Umberto Italy
- `1943`: WORLD HISTORY: At a 1943 meeting in this N. African city, FDR & Churchill agreed to an invasion of the soft underbelly of the Axis Casablanca

### `bigbench_qa_wikidata`  —  FILTER
*Language modeling · 10-shot · baseline 0% · N=20321 · post-1930 years: 27 (0.1%)*  
> **Gauntlet:** BIG-bench wikidata (2022): 20,321 factual completions from Wikipedia (e.g. "The country of citizenship of X is").

> **Verdict (FILTER):** Text scan clean (0.1% years) but modernity is in ENTITY IDENTITY (people born post-1930) -> needs entity-dating, NOT text filtering. Different problem than squad.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
The country of Novosibirsk is Russia

The country of citizenship of Isabel Martínez de Perón is Argentina

The native language of Daniel Schneidermann is French
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
The native language of Daniel Schneidermann is
GOLD CONTINUATION (model must produce):
  >>> 'French'
```
```
[sample 2 of 8 — strided]
CONTEXT:
The country of citizenship of Gustav Vigeland is
GOLD CONTINUATION (model must produce):
  >>> 'Norway'
```
```
[sample 3 of 8 — strided]
CONTEXT:
The country of Miyazaki Prefecture is
GOLD CONTINUATION (model must produce):
  >>> 'Japan'
```
```
[sample 4 of 8 — strided]
CONTEXT:
The religion of Sudirman is
GOLD CONTINUATION (model must produce):
  >>> 'Islam'
```
```
[sample 5 of 8 — strided]
CONTEXT:
The team position of Dontrelle Willis is
GOLD CONTINUATION (model must produce):
  >>> 'pitcher'
```
```
[sample 6 of 8 — strided]
CONTEXT:
The languages spoken, written or signed by Jaber al-Ahmad al-Sabah is
GOLD CONTINUATION (model must produce):
  >>> 'Arabic'
```
```
[sample 7 of 8 — strided]
CONTEXT:
The language of Death of a Salesman is
GOLD CONTINUATION (model must produce):
  >>> 'English'
```
```
[sample 8 of 8 — strided]
CONTEXT:
The country of Chūgoku region is
GOLD CONTINUATION (model must produce):
  >>> 'Japan'
```

**Flagged temporal items** (first 3 of 27 with a post-1930 year):
- `1960`: The country of 1960 Summer Olympics is Italy
- `1968`: The country of 1968 Olympics Black Power salute is Mexico
- `1968`: The country of University of Paris (1896-1968) is France

### `arc_easy`  —  FILTER
*Multiple choice · 10-shot · baseline 25% · N=2376 · post-1930 years: 12 (0.5%)*  
> **Gauntlet:** ARC-Easy (2019): 2,376 four-choice grade 3-9 science questions; basic science world knowledge.

> **Verdict (FILTER):** 0.5% years; pre-1930 science fine; drop modern-tech items.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: Which piece of safety equipment is used to keep mold spores from entering the respiratory system?
Answer: breathing mask

Question: Meiosis is a type of cell division in which germ cells divide to produce haploid cells. Where does meiosis occur?
Answer: ovary cells

Question: Which statement best explains why photosynthesis is the foundation of most food webs?
Answer: Sunlight is the source of energy for nearly all ecosystems.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
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
[sample 2 of 8 — strided]
STEM:
Question: Which of the following is performed by the quality control division of a company that is manufacturing a chair?
Answer: inspecting the finish
CHOICES (* = gold):
    [0] applying the varnish
    [1] assembling the parts
    [2] cutting the material
  * [3] inspecting the finish
```
```
[sample 3 of 8 — strided]
STEM:
Question: At concentrations of 0.1-1 µg/ml colchicine, a natural plant product, can cause the mitotic arrest of dividing cells at metaphase through disrupting the spindle apparatus. Colchicine interferes with which of these cell functions during cell division?
Answer: microtubule organization of spindle fibers
CHOICES (* = gold):
  * [0] microtubule organization of spindle fibers
    [1] DNA synthesis of spindle protein
    [2] membrane transport of spindle fibers
    [3] RNA synthesis of spindle protein
```
```
[sample 4 of 8 — strided]
STEM:
Question: Which tool would be most useful for observing the details of an insect's wings?
Answer: hand lens
CHOICES (* = gold):
    [0] thermometer
    [1] balance
  * [2] hand lens
    [3] graduated cylinder
```
```
[sample 5 of 8 — strided]
STEM:
Question: A student is reading the nutritional information on a box of cereal. It says that a single serving contains 215 calories. Which type of energy is being measured by this unit?
Answer: chemical
CHOICES (* = gold):
    [0] kinetic
  * [1] chemical
    [2] electrical
    [3] mechanical
```
```
[sample 6 of 8 — strided]
STEM:
Question: If the results of an experiment do not support the hypothesis, the scientist will most likely do all of the following except
Answer: change data to support the hypothesis.
CHOICES (* = gold):
    [0] check for errors in the experimental procedure.
    [1] repeat the experiment.
  * [2] change data to support the hypothesis.
    [3] ask new questions.
```
```
[sample 7 of 8 — strided]
STEM:
Question: When rock particles settle at the bottom of the ocean, they can continue to be buried by other particles. The process of cementation of these particles forms
Answer: sedimentary rocks.
CHOICES (* = gold):
    [0] molten rocks.
    [1] igneous rocks.
  * [2] sedimentary rocks.
    [3] metamorphic rocks.
```
```
[sample 8 of 8 — strided]
STEM:
Question: Which part of a sunflower plant absorbs water and nutrients?
Answer: Roots
CHOICES (* = gold):
  * [0] Roots
    [1] Stems
    [2] Leaves
    [3] Flowers
```

**Flagged temporal items** (first 3 of 12 with a post-1930 year):
- `2001`: Question: In 2001, NASA launched a probe to investigate very low-energy radiation emitted when the universe began. What part of the electromagnetic sp
- `1977`: Question: Jesus learned that a space probe named Voyager 1 was launched from Earth in 1977. It will take Voyager 1 more than 500 years to travel 1 lig
- `2013`: Question: Which statement is an inference? A thermometer shows that the air temperature is 56°F. A mineral sample of galena produced a gray-black stre

### `arc_challenge`  —  FILTER
*Multiple choice · 10-shot · baseline 25% · N=1172 · post-1930 years: 8 (0.7%)*  
> **Gauntlet:** ARC-Challenge (2019): four-choice grade 3-9 science questions needing scientific knowledge + procedural reasoning.

> **Verdict (FILTER):** 0.7% years; 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor.

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Question: A group of engineers wanted to know how different building designs would respond during an earthquake. They made several models of buildings and tested each for its ability to withstand earthquake conditions. Which will most likely result from testing different building designs?
Answer: buildings will be made safer

Question: The end result in the process of photosynthesis is the production of sugar and oxygen. Which step signals the beginning of photosynthesis?
Answer: Chlorophyll in the leaf captures light energy.

Question: An astronomer observes that a planet rotates faster after a meteorite impact. Which is the most likely effect of this increase in rotation?
Answer: Planetary days will become shorter.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
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
[sample 2 of 8 — strided]
STEM:
Question: Which of these meals would give you most of the nutrients that you need?
Answer: Bread, vegetables, and fish
CHOICES (* = gold):
    [0] Meat, milk, and a piece of chocolate
  * [1] Bread, vegetables, and fish
    [2] Vegetables, fruits, and water
    [3] Meat, fish, and bread
```
```
[sample 3 of 8 — strided]
STEM:
Question: A researcher uses several procedures to separate a rock sample into different chemicals. A mass of 50 grams of one chemical is produced. If this chemical cannot be separated into other chemicals, then it is best described as
Answer: an element.
CHOICES (* = gold):
    [0] a compound.
    [1] a mixture.
    [2] a solution.
  * [3] an element.
```
```
[sample 4 of 8 — strided]
STEM:
Question: When a mixture of oxygen and hydrogen is ignited in a test tube, the reaction shown occurs. Hydrogen + Oxygen -> Water + Energy What happens to the total mass of the contents of the test tube?
Answer: The total mass remains the same.
CHOICES (* = gold):
    [0] The total mass increases.
    [1] The total mass decreases.
  * [2] The total mass remains the same.
    [3] Part of the mass is changed to heat energy.
```
```
[sample 5 of 8 — strided]
STEM:
Question: In which direction do the roots of plants grow?
Answer: in the direction of water and the pull of gravity
CHOICES (* = gold):
    [0] in the direction of moisture only
    [1] in the direction of the pull of gravity only
  * [2] in the direction of water and the pull of gravity
    [3] in the direction of water and away from the pull of gravity
```
```
[sample 6 of 8 — strided]
STEM:
Question: How are warm-blooded animals different from cold-blooded animals?
Answer: Warm-blooded animals normally maintain a fairly constant internal temperature at all air temperatures.
CHOICES (* = gold):
    [0] Warm-blooded animals have a higher metabolism in warm weather.
    [1] Warm-blooded animals are more aggressive in captivity.
    [2] Warm-blooded animals always have a higher blood temperature.
  * [3] Warm-blooded animals normally maintain a fairly constant internal temperature at all air temperatures.
```
```
[sample 7 of 8 — strided]
STEM:
Question: The ability to roll the tongue in humans is coded by the dominant allele R. The inability to roll the tongue is coded by the recessive allele r. A man with an RR allele combination for the trait produces a zygote with a woman with an rr allele combination for the trait. Which allele combination could occur in the zygote?
Answer: Rr
CHOICES (* = gold):
    [0] R
    [1] rr
  * [2] Rr
    [3] RR
```
```
[sample 8 of 8 — strided]
STEM:
Question: A ball is thrown downward onto a concrete floor and bounces upward. What supplies the upward force that makes the ball bounce?
Answer: the floor
CHOICES (* = gold):
  * [0] the floor
    [1] the pull of gravity
    [2] the air friction on the ball
    [3] the person that throws the ball
```

**Flagged temporal items** (first 3 of 8 with a post-1930 year):
- `2003`: Question: In 2003, Maryland power plants produced 56% of the electricity used in the state by burning coal and 5% of the electricity using hydropower.
- `1995`: Question: Wolves, which are top predators, were eliminated from Yellowstone National Park in the 1930s. In 1995, wolves were reintroduced into Yellows
- `1997`: Question: In Nevada's Black Desert on October 15, 1997, Andy Green traveled a measured distance at an average speed of 339 meters per second in a jet-

---

## Symbolic Problem Solving

### `bigbench_dyck_languages`  —  DROP
*Language modeling · 10-shot · baseline 0% · N=1000 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** BIG-bench dyck languages (2022): 1,000 complete-the-sequence questions; output the tokens that balance a parens/braces expression.

> **Verdict (DROP):** Low construct value + likely OUT-OF-DISTRIBUTION for a books-trained vintage model (bracket sequences never appear in 1930 prose). Drop on construct/OOD grounds (not anachronism).

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: [ < < { } > [ { [ ] ( ( ( ( < ( ( ) ) > ) ) ) [ ] ) } ] { } < [ { ( { < ( ) > } ) } ( ) ] > > {
Output:
GOLD CONTINUATION (model must produce):
  >>> '} ]'
```
```
[sample 2 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: { ( ( [ [ [ ( { } < < [ { [ { { } } ] } ] > > ) ] { } ( { ( < < ( < < > > ) > > ) } [ ( ( ( [ ( < > ) ] ) ) { [ [ ( ) ] ] } { } ) ] < { } > ) ] { < { [ [ ] ] } > } ] ) ) [ { [ ] }
Output:
GOLD CONTINUATION (model must produce):
  >>> '] }'
```
```
[sample 3 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: < { [ ] } [ < { } > ] < [ ] > { } [ [ ] < ( [ ] < > < [ < > ] > ) >
Output:
GOLD CONTINUATION (model must produce):
  >>> '] >'
```
```
[sample 4 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: ( [ ( ) [ < ( { } { ( { [ ] } ) [ ] } { ( ) } ) > ] ] ) ( ) ( < ( ( )
Output:
GOLD CONTINUATION (model must produce):
  >>> ') > )'
```
```
[sample 5 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: { { ( { < < [ { [ [ ] ] < < [ ] > > } ] > > < [ [ [ ] ( < > ) ] ] > < { } > < { [ ] } > } ) } } ( ) [ [ [
Output:
GOLD CONTINUATION (model must produce):
  >>> '] ] ]'
```
```
[sample 6 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: { ( ( ) ) { < > { ( [ [ { } ] [ ( ) ] ] ) } [ { { { ( < [ ] > ) } { < > } } }
Output:
GOLD CONTINUATION (model must produce):
  >>> '] } }'
```
```
[sample 7 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: < { } > ( { < { } > } ) (
Output:
GOLD CONTINUATION (model must produce):
  >>> ')'
```
```
[sample 8 of 8 — strided]
CONTEXT:
Complete the rest of the sequence, making sure that the parentheses are closed properly. 

Input: [ { < < ( { { { ( [ [ ( [ ] ) { ( { { ( < ( ( ) < < { < < > > } > > ) > ) } } ) } ] ] ) } } } ) > > { { { { } } } } ( { ( { ( ( ) ) } ) } ) } ( ( < ( ) > )
Output:
GOLD CONTINUATION (model must produce):
  >>> ') ]'
```

### `agi_eval_lsat_ar`  —  KEEP
*Multiple choice · 3-shot · baseline 20% · N=230 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** AGI Eval LSAT-AR (2023): 230 four-choice LSAT analytical-reasoning logic puzzles.

> **Verdict (KEEP):** Full scan: 0% post-1930 years. Era-neutral analytical logic -> FAIR (you were right). Optional light filter of ~5% modern-topic passages.

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
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
[sample 2 of 8 — strided]
STEM:
Passage: A loading dock consists of exactly six bays numbered 1 through 6 consecutively from one side of the dock to the other. Each bay is holding a different one of exactly six types of cargo—fuel, grain, livestock, machinery, produce, or textiles. The following apply: The bay holding grain has a higher number than the bay holding livestock. The bay holding livestock has a higher number than the bay holding textiles. The bay holding produce has a higher number than the bay holding fuel. The bay holding textiles is next to the bay holding produce.
Q: Which one of the following must be false?
Choices:
A.) The bay holding livestock is next to the bay holding fuel.
B.) The bay holding produce 
[... truncated for this doc ...]
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 3 of 8 — strided]
STEM:
Passage: Exactly eight books—F, G, H, I, K, L, M, O—are placed on a bookcase with exactly three shelves—the top shelf, the middle shelf, and the bottom shelf. At least two books are placed on each shelf. The following conditions must apply: More of the books are placed on the bottom shelf than the top shelf. I is placed on the middle shelf. K is placed on a higher shelf than F. O is placed on a higher shelf than L. F is placed on the same shelf as M.
Q: Which one of the following could be a complete and accurate list of the books placed on the bottom shelf?
Choices:
A.) G, H, K
B.) G, H, L, M
C.) F, M
D.) F, H, M
Answer: D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 4 of 8 — strided]
STEM:
Passage: Exactly five witnesses—Franco, Garcia, Hong, Iturbe, and Jackson—are to be scheduled to testify at a hearing that is to take exactly three days of one week—Monday, Tuesday, and Wednesday. Each witness testifies on exactly one day of the hearing. The schedule must meet the following conditions: Franco does not testify on the same day that Garcia testifies. Iturbe testifies on Wednesday. Exactly two witnesses testify on Tuesday. Hong does not testify on Monday. At least one witness testifies on Monday.
Q: Which one of the following CANNOT be true of the schedule?
Choices:
A.) Jackson is scheduled to testify on Tuesday and two witnesses are scheduled to testify on Monday.
B.) Garcia is
[... truncated for this doc ...]
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 5 of 8 — strided]
STEM:
Passage: Exactly five movies are showing at the repertory theater this evening: a horror film, a mystery, a romance, a sci-fi film, and a western. Each movie is shown exactly once, on one of the theater's three screens: screens 1, 2, and 3. Screens 1 and 2 show two movies each, one beginning at 7 P.M. and the other at 9 P.M.; screen 3 shows exactly one movie, at 8 P.M. The following conditions apply to this evening's schedule: The western begins at some time before the horror film does. The sci-fi film is not shown on screen 3. The romance is not shown on screen 2. The horror film and the mystery are shown on different screens.
Q: Which one of the following CANNOT be an accurate list of the 
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 6 of 8 — strided]
STEM:
Passage: A detective is trying to determine the order in which a criminal recruited seven accomplices—Peters, Quinn, Rovero, Stanton, Tao, Villas, and White. In addition to discovering that the suspect recruited the accomplices one at a time, the detective has established the following: Stanton was recruited neither immediately before nor immediately after Tao. Quinn was recruited earlier than Rovero. Villas was recruited immediately before White. Peters was recruited fourth.
Q: f Quinn was recruited immediately before Rovero, then Stanton CANNOT have been recruited
Choices:
A.) first
B.) fifth
C.) seventh
D.) second
Answer: D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 7 of 8 — strided]
STEM:
Passage: During the weeklong grand opening of a new antique shop, the antique dealer will auction exactly one antique per day for six consecutive days—June 1st through June 6th. The antiques to be auctioned are: a harmonica, a lamp, a mirror, a sundial, a table, and a vase. The following conditions apply: The sundial is not auctioned on June 1st. If the harmonica is auctioned on an earlier date than the lamp, then the mirror is also auctioned on an earlier date than the lamp. The sundial is auctioned on an earlier date than the mirror and also on an earlier date than the vase. The table is auctioned on an earlier date than the harmonica or on an earlier date than the vase, but not both.
Q: W
[... truncated for this doc ...]
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 8 of 8 — strided]
STEM:
Passage: Three real estate companies—RealProp, Southco, and Trustcorp—are considering trading buildings with one another. Each building they own is categorized as either class 1, class 2, or class 3, depending on its approximate value: RealProp owns the Garza Tower (class 1), the Yates House (class 3), and the Zimmer House (class 3). Southco owns the Flores Tower (class 1) and the Lynch Building (class 2). Trustcorp owns the King Building, the Meyer Building, and the Ortiz Building, all of which are class 2. Each trade must be of exactly one of the following three kinds: Trading one building for one other building of the same class Trading one class 1 building for two class 2 buildings Tradi
[... truncated for this doc ...]
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```

### `bigbench_cs_algorithms`  —  DROP
*Language modeling · 10-shot · baseline 0% · N=1320 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** BIG-bench CS algorithms: execute classic CS algorithms (e.g. longest common subsequence, recursion).

> **Verdict (DROP):** Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data.

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: ZUIEJOBQXVLXBMVOOMNJQSHJPY OVCOZNKRCXBYSMWOPRWMXIPCMRKX
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '8'
```
```
[sample 2 of 8 — strided]
CONTEXT:
Given two strings, determine the length of the longest common subsequence.

Strings: ZNQKNXIHMPRXGQHIJGBJPW JKINUIUWRJCO
Length of longest common subsequence:
GOLD CONTINUATION (model must produce):
  >>> '5'
```
```
[sample 3 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: } } ) ) ) ) } ( ] ) [ } ) } } } ) ) ) )
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Invalid'
```
```
[sample 4 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: } ) ( } { ] } ( ) (
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Invalid'
```
```
[sample 5 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: [ } [ ] ( ) { ] ( )
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Invalid'
```
```
[sample 6 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: { } { ( ( { } ) ) }
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Valid'
```
```
[sample 7 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: ( [ { } ] [ ( ) ( [ { [ ] { } } ] ) ] )
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Valid'
```
```
[sample 8 of 8 — strided]
CONTEXT:
Determine whether the given sequence of parentheses is properly matched.

Sequence: [ ] [ ] { [ ( ) [ ] [ ] ] } [ ) [ } [ ]
Valid/Invalid?
GOLD CONTINUATION (model must produce):
  >>> 'Invalid'
```

### `bigbench_operators`  —  KEEP
*Language modeling · 10-shot · baseline 0% · N=210 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** BIG-bench operators (2022): 210 questions that define new math operators; compute an expression using them (math abstraction).

> **Verdict (KEEP):** Pure abstraction (defined operators), era-neutral. (100% "modern" in scan = false positive on the word "compute".)

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
op i is either the half of i when i is even, or its double when it is not.
op (op 17) =
GOLD CONTINUATION (model must produce):
  >>> '17'
```
```
[sample 2 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
i op j is the addition of i and j.
35 op 58 =
GOLD CONTINUATION (model must produce):
  >>> '93'
```
```
[sample 3 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
op i is the ith odd positive number.
op 1 =
GOLD CONTINUATION (model must produce):
  >>> '1'
```
```
[sample 4 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
i op j keeps the j first digits of i.
125690 op 4 =
GOLD CONTINUATION (model must produce):
  >>> '1256'
```
```
[sample 5 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
op n1 n2 ... nn multiplies the n listed numbers.
op 2 3 5 7 =
GOLD CONTINUATION (model must produce):
  >>> '210'
```
```
[sample 6 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
op i j selects i when less than j, j otherwise.
op 35 58 =
GOLD CONTINUATION (model must produce):
  >>> '35'
```
```
[sample 7 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
i op j is the product of j copies of i.
-1 op 4 =
GOLD CONTINUATION (model must produce):
  >>> '1'
```
```
[sample 8 of 8 — strided]
CONTEXT:
Given the definition of the op operator, compute the result.
i op1 j is the product of i and j; op2 i j selects i when greater than j, j otherwise.
op2 (8 op1 6) (12 op1 4) =
GOLD CONTINUATION (model must produce):
  >>> '48'
```

### `bigbench_repeat_copy_logic`  —  REWRITE
*Language modeling · 10-shot · baseline 0% · N=32 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** BIG-bench repeat-copy-logic: instruction-following — repeat phrases according to logical rules.

> **Verdict (REWRITE):** 0% years; mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens.

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
repeat with logic:

Q: A watermelon has seven seeds. Repeat they're delicious once for every seed
A:
GOLD CONTINUATION (model must produce):
  >>> "they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious they're delicious"
```
```
[sample 2 of 8 — strided]
CONTEXT:
repeat with logic:

Q: say pickup a pound of green beans twice, replacing a pound with a bunch for even times and a handful for odd
A:
GOLD CONTINUATION (model must produce):
  >>> 'pickup a handful of green beans pickup a bunch of green beans'
```
```
[sample 3 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Seven times please repeat The School of Music
A:
GOLD CONTINUATION (model must produce):
  >>> 'The School of Music The School of Music The School of Music The School of Music The School of Music The School of Music The School of Music'
```
```
[sample 4 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Repeat historic church building twice, but after every word also say wow
A:
GOLD CONTINUATION (model must produce):
  >>> 'historic wow church wow building wow historic wow church wow building wow'
```
```
[sample 5 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Twice repeat inhabitants in the urban area and then three times live in walking distance
A:
GOLD CONTINUATION (model must produce):
  >>> 'inhabitants in the urban area inhabitants in the urban area live in walking distance live in walking distance live in walking distance'
```
```
[sample 6 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Repeat cheese seven times; every third say whiz
A:
GOLD CONTINUATION (model must produce):
  >>> 'cheese cheese cheese whiz cheese cheese cheese whiz cheese'
```
```
[sample 7 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Say the botanical gardens are five times. If the time divides evenly by two add beautiful, or by three add wonderful. Otherwise say great.
A:
GOLD CONTINUATION (model must produce):
  >>> 'the botanical gardens are great the botanical gardens are beautiful the botanical gardens are wonderful the botanical gardens are beautiful the botanical gardens are great'
```
```
[sample 8 of 8 — strided]
CONTEXT:
repeat with logic:

Q: Repeat squiggly line twice after the phrase can you draw
A:
GOLD CONTINUATION (model must produce):
  >>> 'can you draw squiggly line squiggly line'
```

---

## Language Understanding

### `hellaswag_zeroshot`  —  REWRITE
*Multiple choice · 0-shot · baseline 25% · N=10042 · post-1930 years: 43 (0.4%)*  
> **Gauntlet:** HellaSwag (2019), zero-shot variant.

> **Verdict (REWRITE):** Same source, 0-shot variant of hellaswag.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
CHOICES (* = gold):
    [0] is using wrap to wrap a pair of skis.
    [1] is ripping level tiles off.
    [2] is holding a rubik's cube.
  * [3] starts pulling up roofing on a roof.
```
```
[sample 2 of 8 — strided]
STEM:
Making a cake: A persons hands are seen laying clay out onto a cake and begins painting objects on the side. The woman puts the decorations around the cake and continues decorating more objects on the side.
CHOICES (* = gold):
    [0] continues painting and cuts areas across the cake.
    [1] continues painting until there is no more clay left on the cake.
    [2] turns around the painting pushing it down to the side.
  * [3] puts the decorations around the cake and continues decorating more objects on the side.
```
```
[sample 3 of 8 — strided]
STEM:
Drum corps: Several percussionists stand on a field. They march in place on the field. They are drumming in sync. A woman walks by with a video camera.
CHOICES (* = gold):
    [0] continuously hits a high note.
    [1] is talking again in front of a tent.
    [2] in a black robe sings in a room.
  * [3] walks by with a video camera.
```
```
[sample 4 of 8 — strided]
STEM:
Personal Care and Style: How to make blue eyes pop. Apply concealer under your eyes. Blue eyes can easily get lost in dark undereye circles, and this is especially noticeable with a natural look. Apply concealer around and under your eyes to put the focus on them, not your circles! Try using a salmon-colored concealer to hide the bluish tones in your skin. If you only need light coverage, dot the concealer along your undereye, then blend with your fingers or a makeup sponge. If you have very dark circles, apply a layer of concealer in an inverted triangle shape under your eye.
CHOICES (* = gold):
    [0]  Use a dark shade of eyeshadow as your shadow. In the morning, put on a dark shade of eyeshadow on your darker circles.
    [1] Let the concealer dry for at least a couple of minutes on your skin.. Clean under your eyes with an eyelid primer.
    [2] This will help blend out the dark circles. You can also choose a bright color like pink for blues and red for green eyes.
  * [3] If you only need light coverage, dot the concealer along your undereye, then blend with your fingers or a makeup sponge. If you have very dark circles, apply a layer of concealer in an inverted triang
[... truncated for this doc ...]
```
```
[sample 5 of 8 — strided]
STEM:
Health: How to do hand stretches for carpal tunnel. Do the prayer stretch. Stretches alone will not resolve an issue you have with carpal tunnel, but combined with effective treatments, they can help you to relieve moderate symptoms. The prayer stretch can help you to increase blood-flow to the median nerve. Try the prayer stretch for early relief of carpal tunnel pain, and to reduce sensations of numbness and tingling. Begin with your palms pressed together in front of your chest, below your chin.
CHOICES (* = gold):
  * [0] Try the prayer stretch for early relief of carpal tunnel pain, and to reduce sensations of numbness and tingling. Begin with your palms pressed together in front of your chest, below your chin.
    [1] Perform the prayer stretch first, then hold an arm out out to one side, palm facing downward. With your other hand, slowly rotate your head out to one side to put pressure on the median nerve.
    [2] Prayer stretches are done both day and night, monday through friday. You should rest your foot until fatigue and discomfort is no longer noticeable.
    [3] There are many different types of foot stretches that you can do depending on the severity of your symptoms. The dianc's ashtanga stretch is effective because it involves the thumb to stretch the liga
[... truncated for this doc ...]
```
```
[sample 6 of 8 — strided]
STEM:
Youth: How to ask a guy to a school dance. Determine whether or not he already has a date. This will save you a great deal of time and trouble, and give you enough time to find another potential date if necessary. If you are unsure, then ask one of his friends or someone in his social circle. Try to figure this out before asking him out. If he has a girlfriend, then he is probably going with her.
CHOICES (* = gold):
    [0] Don't feel bad if you didn't know. If the guy has a date already, it will make it a lot easier to find him after the dance.
    [1] If he already has a date set up, then find out if it is to be a date.. Determine whether he only has friends, or if he doesn't have any at all.
    [2] The idea is to find someone else to spend time with that you can count on, to help you get into a mood that is conducive to dancing.. Be specific about who will be dancing.
  * [3] Try to figure this out before asking him out. If he has a girlfriend, then he is probably going with her.
```
```
[sample 7 of 8 — strided]
STEM:
Personal Care and Style: How to accessorize a summer white outfit. Don a straw sun hat. Straw has a natural appeal for summer, and the sun hat is a classic design that adds whimsical charm to your outfit. Try the straw hat in bold colors, like yellow or pink, or go for something softer, like coral or turquoise. You can also wear them in darker staples, like navy or red. Bucket hats and newsboy caps are fitting looks for warm weather as long as the material and color are light.
CHOICES (* = gold):
    [0]  A straw hat was made for an umbrella, so your hat will most likely fit more in the sun. This is even more amusing if you wear the brimmed hat for a beach-style look.
    [1]  Pair a simple one piece dress with a floor length black or dark blue skirt. For more casual parties, a simple dress is the easiest option for summer.
  * [2] You can also wear them in darker staples, like navy or red. Bucket hats and newsboy caps are fitting looks for warm weather as long as the material and color are light.
    [3]  Straw hats can be purchased in a multitude of colors online, making it an excellent accessory to add a minimalist look to your outfit. If you want an hourglass look, try wearing a straw hat that's no
[... truncated for this doc ...]
```
```
[sample 8 of 8 — strided]
STEM:
Family Life: How to tell if your teen is being abused. Pay attention to your teen dressing inappropriately. If you suspect that your teen is being beaten by someone in their life, you will want to pay close attention to their dress code. While all teens have different styles and preferences, be on the lookout for any clothing that is out of the norm for your child.  For instance, your teen may try to hide the signs of abuse (e.g. scratches, burns, bruises, bite marks, broken bones, etc.
CHOICES (* = gold):
    [0] Try to figure out why they are dressing something that is frowned upon.. Understand why your child is acting different.
    [1] Read the following as a rule for determining your teen's behaviour. You may notice your teen dressing in odd outfits that could indicate that they are on a date.
  * [2]  For instance, your teen may try to hide the signs of abuse (e.g. scratches, burns, bruises, bite marks, broken bones, etc.
    [3]  Ask your teen if they have black tights (with stripper straps) or baggy jeans (without strippers straps). The more comfortably you can be around your teenager, the better.
```

**Flagged temporal items** (first 3 of 43 with a post-1930 year):
- `2008`: Clean and jerk: At the 2008 olympics, a man prepares to lift a loaded barbell. He bends down and works his way up with great effort, finally lifting t
- `2010`: Running a marathon: The words "dathan ritzenhein nyc marathon 2010" appear on a black screen. Still images of pyramids in egypt are shown and then the
- `2012`: Calf roping: Clips of both of men talking and clips of them riding horses and wrangling calves play and rotate between the two of them. The outro vide

### `lambada_openai`  —  REWRITE
*Language modeling · 0-shot · baseline 0% · N=5153 · post-1930 years: 8 (0.2%)*  
> **Gauntlet:** LAMBADA (2016): 5,153 book passages; read the first N-1 words and predict the final word — requires full-passage context.

> **Verdict (REWRITE):** 0.2% years but modern-novel REGISTER. Strong signal, scales well -> rewrite to held-out period books, do NOT drop.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
In my palm is a clear stone, and inside it is a small ivory statuette. A guardian angel.

"Figured if you're going to be out at night getting hit by cars, you might as well have some backup."

I look at him, feeling stunned. Like this is some sort of sign. But as I stare at Harlin, his mouth curved in a confident grin, I don't care about signs
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT:
In my palm is a clear stone, and inside it is a small ivory statuette. A guardian angel.

"Figured if you're going to be out at night getting hit by cars, you might as well have some backup."

I look at him, feeling stunned. Like this is some sort of sign. But as I stare at Harlin, his mouth curved in a confident grin, I don't care about
GOLD CONTINUATION (model must produce):
  >>> 'signs'
```
```
[sample 2 of 8 — strided]
CONTEXT:
I'll bring you a plate when it's done,” said Jason.
"Is she making her famous garlic cheese toast to go with that lasagna?" asked Vasquez.
"Yes, I guess this means you want double?" asked Jason.
"You are such a wise young man.  Don't bother to bring Timms any, he isn't a connoisseur of fine cuisine like I am," said
GOLD CONTINUATION (model must produce):
  >>> 'Vasquez'
```
```
[sample 3 of 8 — strided]
CONTEXT:
He took his phone and opened it while walking outside. They were in such a secluded area no one would ever find them. They were tucked back in the wilderness of the Rocky Mountains, an hour outside of Colorado Springs. Derrik placed a call. 
“Hello?” Adara said franticly into the phone.
“Adara, don’t say my name, this is
GOLD CONTINUATION (model must produce):
  >>> 'Derrik'
```
```
[sample 4 of 8 — strided]
CONTEXT:
"If you ask me, Lucas was not-lying. His words weren't exactly false, but for someone who wants our help, the boy isn't really what you would call forthcoming."

Lucas hadn't ever explicitly said that the people after him weren't a threat. He'd never said that they weren't
GOLD CONTINUATION (model must produce):
  >>> 'dangerous'
```
```
[sample 5 of 8 — strided]
CONTEXT:
He looked to be about forty years old, with a dark, heavy beard and an unruly mat of graying hair. He was dressed in a ragged red union suit and held an ancient muzzle-loading rifle in his hands. In the dim lamplight, Jason caught a glimpse of a woman and several children huddled together in the middle of the single-room hut.
"I never heard of no Vigilance Committee," Bowles said
GOLD CONTINUATION (model must produce):
  >>> 'gruffly'
```
```
[sample 6 of 8 — strided]
CONTEXT:
I’m suffering from quite a lot of timelag as it is and I don’t need a headache on top of that.”
“Thank you,” Clint said, clambering into the car. “Now drive us to the Fez.”
“What?”
“I said, ‘Now drive us to the
GOLD CONTINUATION (model must produce):
  >>> 'Fez'
```
```
[sample 7 of 8 — strided]
CONTEXT:
“It must have gotten tangled in your hair.”
She groaned, wishing she had worn a braid instead of letting her hair hang loose.
“Move away from her!” Margaret snapped and shoved him aside.
Jessica shrieked and stumbled against him.  Boy, that hurt!
“Her hair is attached to me,” he told
GOLD CONTINUATION (model must produce):
  >>> 'Margaret'
```
```
[sample 8 of 8 — strided]
CONTEXT:
“Yes, Grandmother, and don’t worry, I won’t forget my water when I go wander.”
Her brothers laughed a little only because the comment was so cute. 
“Wonderful my little Wanderer, because I would hate to think of you forgetting an important rule like that.”
“I would never forget the rules,
GOLD CONTINUATION (model must produce):
  >>> 'Grandmother'
```

**Flagged temporal items** (first 3 of 8 with a post-1930 year):
- `2014`: A second meal was served in the late afternoon. If you are interested in learning more about the Medieval period, head over to the author’s website, w
- `1937`: That's why it was also easy to arrange a meeting between her and Gideon. He traveled back last night to the year 1937, to meet Margaret Tilney at our 
- `2016`: “You’ve been asleep for more than four hours,” said Roman. “How generous,” I said. “What? You want to sleep all day?” I crawled out of the bed and sli

### `hellaswag`  —  REWRITE
*Multiple choice · 10-shot · baseline 25% · N=10042 · post-1930 years: 43 (0.4%)*  
> **Gauntlet:** HellaSwag (2019): 10,042 four-choice scenarios; pick the most plausible continuation.

> **Verdict (REWRITE):** Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite).

**Full prompt as scored (showing 2 of 10 few-shot):**

```
Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady stands and lifts the weight over her head.

Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individuals visible in the background. The child and a different man sit in a canoe while the man paddles.

Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
STEM:
Roof shingle removal: A man is sitting on a roof. He starts pulling up roofing on a roof.
CHOICES (* = gold):
    [0] is using wrap to wrap a pair of skis.
    [1] is ripping level tiles off.
    [2] is holding a rubik's cube.
  * [3] starts pulling up roofing on a roof.
```
```
[sample 2 of 8 — strided]
STEM:
Making a cake: A persons hands are seen laying clay out onto a cake and begins painting objects on the side. The woman puts the decorations around the cake and continues decorating more objects on the side.
CHOICES (* = gold):
    [0] continues painting and cuts areas across the cake.
    [1] continues painting until there is no more clay left on the cake.
    [2] turns around the painting pushing it down to the side.
  * [3] puts the decorations around the cake and continues decorating more objects on the side.
```
```
[sample 3 of 8 — strided]
STEM:
Drum corps: Several percussionists stand on a field. They march in place on the field. They are drumming in sync. A woman walks by with a video camera.
CHOICES (* = gold):
    [0] continuously hits a high note.
    [1] is talking again in front of a tent.
    [2] in a black robe sings in a room.
  * [3] walks by with a video camera.
```
```
[sample 4 of 8 — strided]
STEM:
Personal Care and Style: How to make blue eyes pop. Apply concealer under your eyes. Blue eyes can easily get lost in dark undereye circles, and this is especially noticeable with a natural look. Apply concealer around and under your eyes to put the focus on them, not your circles! Try using a salmon-colored concealer to hide the bluish tones in your skin. If you only need light coverage, dot the concealer along your undereye, then blend with your fingers or a makeup sponge. If you have very dark circles, apply a layer of concealer in an inverted triangle shape under your eye.
CHOICES (* = gold):
    [0]  Use a dark shade of eyeshadow as your shadow. In the morning, put on a dark shade of eyeshadow on your darker circles.
    [1] Let the concealer dry for at least a couple of minutes on your skin.. Clean under your eyes with an eyelid primer.
    [2] This will help blend out the dark circles. You can also choose a bright color like pink for blues and red for green eyes.
  * [3] If you only need light coverage, dot the concealer along your undereye, then blend with your fingers or a makeup sponge. If you have very dark circles, apply a layer of concealer in an inverted triang
[... truncated for this doc ...]
```
```
[sample 5 of 8 — strided]
STEM:
Health: How to do hand stretches for carpal tunnel. Do the prayer stretch. Stretches alone will not resolve an issue you have with carpal tunnel, but combined with effective treatments, they can help you to relieve moderate symptoms. The prayer stretch can help you to increase blood-flow to the median nerve. Try the prayer stretch for early relief of carpal tunnel pain, and to reduce sensations of numbness and tingling. Begin with your palms pressed together in front of your chest, below your chin.
CHOICES (* = gold):
  * [0] Try the prayer stretch for early relief of carpal tunnel pain, and to reduce sensations of numbness and tingling. Begin with your palms pressed together in front of your chest, below your chin.
    [1] Perform the prayer stretch first, then hold an arm out out to one side, palm facing downward. With your other hand, slowly rotate your head out to one side to put pressure on the median nerve.
    [2] Prayer stretches are done both day and night, monday through friday. You should rest your foot until fatigue and discomfort is no longer noticeable.
    [3] There are many different types of foot stretches that you can do depending on the severity of your symptoms. The dianc's ashtanga stretch is effective because it involves the thumb to stretch the liga
[... truncated for this doc ...]
```
```
[sample 6 of 8 — strided]
STEM:
Youth: How to ask a guy to a school dance. Determine whether or not he already has a date. This will save you a great deal of time and trouble, and give you enough time to find another potential date if necessary. If you are unsure, then ask one of his friends or someone in his social circle. Try to figure this out before asking him out. If he has a girlfriend, then he is probably going with her.
CHOICES (* = gold):
    [0] Don't feel bad if you didn't know. If the guy has a date already, it will make it a lot easier to find him after the dance.
    [1] If he already has a date set up, then find out if it is to be a date.. Determine whether he only has friends, or if he doesn't have any at all.
    [2] The idea is to find someone else to spend time with that you can count on, to help you get into a mood that is conducive to dancing.. Be specific about who will be dancing.
  * [3] Try to figure this out before asking him out. If he has a girlfriend, then he is probably going with her.
```
```
[sample 7 of 8 — strided]
STEM:
Personal Care and Style: How to accessorize a summer white outfit. Don a straw sun hat. Straw has a natural appeal for summer, and the sun hat is a classic design that adds whimsical charm to your outfit. Try the straw hat in bold colors, like yellow or pink, or go for something softer, like coral or turquoise. You can also wear them in darker staples, like navy or red. Bucket hats and newsboy caps are fitting looks for warm weather as long as the material and color are light.
CHOICES (* = gold):
    [0]  A straw hat was made for an umbrella, so your hat will most likely fit more in the sun. This is even more amusing if you wear the brimmed hat for a beach-style look.
    [1]  Pair a simple one piece dress with a floor length black or dark blue skirt. For more casual parties, a simple dress is the easiest option for summer.
  * [2] You can also wear them in darker staples, like navy or red. Bucket hats and newsboy caps are fitting looks for warm weather as long as the material and color are light.
    [3]  Straw hats can be purchased in a multitude of colors online, making it an excellent accessory to add a minimalist look to your outfit. If you want an hourglass look, try wearing a straw hat that's no
[... truncated for this doc ...]
```
```
[sample 8 of 8 — strided]
STEM:
Family Life: How to tell if your teen is being abused. Pay attention to your teen dressing inappropriately. If you suspect that your teen is being beaten by someone in their life, you will want to pay close attention to their dress code. While all teens have different styles and preferences, be on the lookout for any clothing that is out of the norm for your child.  For instance, your teen may try to hide the signs of abuse (e.g. scratches, burns, bruises, bite marks, broken bones, etc.
CHOICES (* = gold):
    [0] Try to figure out why they are dressing something that is frowned upon.. Understand why your child is acting different.
    [1] Read the following as a rule for determining your teen's behaviour. You may notice your teen dressing in odd outfits that could indicate that they are on a date.
  * [2]  For instance, your teen may try to hide the signs of abuse (e.g. scratches, burns, bruises, bite marks, broken bones, etc.
    [3]  Ask your teen if they have black tights (with stripper straps) or baggy jeans (without strippers straps). The more comfortably you can be around your teenager, the better.
```

**Flagged temporal items** (first 3 of 43 with a post-1930 year):
- `2008`: Clean and jerk: At the 2008 olympics, a man prepares to lift a loaded barbell. He bends down and works his way up with great effort, finally lifting t
- `2010`: Running a marathon: The words "dathan ritzenhein nyc marathon 2010" appear on a black screen. Still images of pyramids in egypt are shown and then the
- `2012`: Calf roping: Clips of both of men talking and clips of them riding horses and wrangling calves play and rotate between the two of them. The outro vide

### `winograd`  —  KEEP
*Schema · 0-shot · baseline 50% · N=273 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** Winograd Schema (2012): 273 pronoun-resolution scenarios; pick the semantically valid anaphora resolution.

> **Verdict (KEEP):** Timeless pronoun resolution; register already period-appropriate.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
The city councilmen refused the demonstrators a permit because the city councilmen feared violence.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'feared violence.':
  * [0] The city councilmen refused the demonstrators a permit because the city councilmen
    [1] The city councilmen refused the demonstrators a permit because the demonstrators
```
```
[sample 2 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'is very successful.':
    [0] Pete envies Martin because Pete
  * [1] Pete envies Martin because Martin
```
```
[sample 3 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'is very hurt.':
  * [0] Bob paid for Charlie's college education, but now Charlie acts as though it never happened. Bob
    [1] Bob paid for Charlie's college education, but now Charlie acts as though it never happened. Charlie
```
```
[sample 4 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'on Thursday.':
    [0] Joe has sold his house and bought a new one a few miles away. He will be moving into the old house
  * [1] Joe has sold his house and bought a new one a few miles away. He will be moving into the new house
```
```
[sample 5 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = '.':
    [0] The foxes are getting in at night and attacking the chickens. I shall have to guard the foxes
  * [1] The foxes are getting in at night and attacking the chickens. I shall have to guard the chickens
```
```
[sample 6 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'got full of coffee.':
  * [0] I couldn't find a spoon, so I tried using a pen to stir my coffee. But that turned out to be a bad idea, because the pen
    [1] I couldn't find a spoon, so I tried using a pen to stir my coffee. But that turned out to be a bad idea, because the coffee
```
```
[sample 7 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'back, the woman smiled at the girl.':
    [0] Patting the woman's
  * [1] Patting the girl's
```
```
[sample 8 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'had stolen the watch.':
    [0] Carol believed that Rebecca regretted that Carol
  * [1] Carol believed that Rebecca regretted that Rebecca
```

### `winogrande`  —  KEEP
*Schema · 0-shot · baseline 50% · N=1267 · post-1930 years: 0 (0.0%)*  
> **Gauntlet:** Winogrande (2012): 1,267 Winograd-style scenarios at larger scale and broader domains.

> **Verdict (KEEP):** Timeless; optional light restyle.

**Full prompt as scored (0-shot task, no few-shot prefix):**

```
Sarah was a much better surgeon than Maria so Maria always got the easier cases.
```

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'always got the easier cases.':
    [0] Sarah was a much better surgeon than Maria so Sarah
  * [1] Sarah was a much better surgeon than Maria so Maria
```
```
[sample 2 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'is a tree cutter.':
    [0] At work, Mary uses a broiler a lot, but Rebecca uses a chainsaw. That's because Mary
  * [1] At work, Mary uses a broiler a lot, but Rebecca uses a chainsaw. That's because Rebecca
```
```
[sample 3 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'was too fluid.':
    [0] Ben had to drain both water and oil down the sink, but the oil
  * [1] Ben had to drain both water and oil down the sink, but the water
```
```
[sample 4 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'to get a job.':
    [0] Benjamin had less piercings than Jeffrey did so it was harder for Benjamin
  * [1] Benjamin had less piercings than Jeffrey did so it was harder for Jeffrey
```
```
[sample 5 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'was more petty.':
    [0] The doctor couldn't treat the arm infection, but was able to handle the ear ache. The arm infection
  * [1] The doctor couldn't treat the arm infection, but was able to handle the ear ache. The ear ache
```
```
[sample 6 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'could fill her glass with water.':
    [0] Betty gave the full pitcher to Rachel so Betty
  * [1] Betty gave the full pitcher to Rachel so Rachel
```
```
[sample 7 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'is currently unemployed.':
  * [0] Tanya recently finished filling out a job application but not Megan because Tanya
    [1] Tanya recently finished filling out a job application but not Megan because Megan
```
```
[sample 8 of 8 — strided]
CONTEXT OPTIONS (* = gold), shared continuation = 'has more brighter color.':
    [0] She chose the black car over the green car, because the black car
  * [1] She chose the black car over the green car, because the green car
```

### `bigbench_language_identification`  —  KEEP
*Multiple choice · 10-shot · baseline 9.1% · N=10000 · post-1930 years: 315 (3.1%)*  
> **Gauntlet:** BIG-bench language identification: identify the language of a sentence among multiple-choice options.

> **Verdict (KEEP):** Era-neutral (religious-translation sentences period-plausible). Low priority.

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

**8 sample items, strided across the file** (few-shot prefix omitted):

```
[sample 1 of 8 — strided]
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
[sample 2 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: —Panetocapitsapare Barrabás, jai.
A. Hindi
B. Guahibo
C. Alyawarr
D. Bariba
Answer:  B
CHOICES (* = gold):
    [0] A
  * [1] B
    [2] C
    [3] D
```
```
[sample 3 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Ma den sma disi e taki takru fu ala sani san den no sabi. Neleki meti di no man denki, den sabi soso den sani san den skin e firi fu du. Èn na den sani dati e broko den neki.
A. Sranan
B. Zulu
C. North Tairora
D. Saint Lucian Creole French
Answer:  A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 4 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Nochi ni tlamantli tlen ta tijmati nelía yejyectzi,
A. Eastern Huasteca Nahuatl
B. Tuvinian
C. Lezgian
D. Catalan
Answer:  A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 5 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: inti cuyayllapaj achicyashanno cachun.»
A. Sanskrit-HarvardKyoto
B. Kombio Wampukuamp
C. Tabasco Chontal
D. Huallaga Huanuco Quechua
Answer:  D
CHOICES (* = gold):
    [0] A
    [1] B
    [2] C
  * [3] D
```
```
[sample 6 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Ta yasanapuya ꞌabehega yaluyaluwagu nuwanuwana ma Yehoba ꞌina nuwatuhu yapaihowa,
A. Bunama
B. Azeri
C. Basque 1571
D. Ottoman Turkish
Answer:  A
CHOICES (* = gold):
  * [0] A
    [1] B
    [2] C
    [3] D
```
```
[sample 7 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Me'iye su, Pol omo Jerusalem ma'e iyei ne toteye. Sosu omo Efesus arunatiyei ne toteye. Le pani Masedonia ma'e pani Akaia ma'e awera'iyenatiyei ne toteye. Sosu le apou te'eye, “Mo'o su, ane omo
A. Japanese
B. Caribbean Javanese
C. Saniyo-Hiyewe
D. Lingua Franca Nova
Answer:  C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```
```
[sample 8 of 8 — strided]
STEM:
Given a sentence, select the correct language among the choices
Sentence: Ᵽan jimero waf, ban mati júju jibaj wo ; ᵽan ñer jiilo gailo gal emuh bugan bi ebaj wo. Ᵽan jísilaet mal ebaj waf, ban mati júju jibaj wo ; ñer ᵽan jírig n’jitaj, bare mati jibaj wáfowaf ni wo jimaŋ me, mata jícinut wo Aláemit.
A. Nend
B. Yaminahua
C. Bandial
D. Arapesh
Answer:  C
CHOICES (* = gold):
    [0] A
    [1] B
  * [2] C
    [3] D
```

**Flagged temporal items** (first 3 of 315 with a post-1930 year):
- `2010`: Given a sentence, select the correct language among the choices Sentence: Say Parañaque et unaan ya klase siyudad ed luyag na Metro Manila, Filipinas.
- `1969`: Given a sentence, select the correct language among the choices Sentence: मार्च, 1969 नै परलीका गांव में जलम्या डॉ. सत्यनारायण सोनी राजस्थानी रा चर्चि
- `2015`: Given a sentence, select the correct language among the choices Sentence: Nictam neta ki ici nokosiw Avant les rues, Chloé Leriche e ki ocitatc ni api

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
| `squad` | **REWRITE+FILTER** | 30.9% of items carry a post-1930 year (full scan). Filter those, restyle remaining Wikipedia register. Same kind as boolq/coqa. |
| `coqa` | **REWRITE+FILTER** | 26.8% post-1930 years (full scan). Stories partly era-neutral but passages skew modern; filter + restyle. |
| `boolq` | **REWRITE+FILTER** | MOST temporal task: 40.6% post-1930 years (full scan). Heavy filter + restyle. NB: below chance through d24 -> may not score until d34 (signal-axis watch). |

### Commonsense Reasoning
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `copa` | **KEEP** | Full scan: 0% post-1930 years. Timeless causal commonsense. |
| `commonsense_qa` | **KEEP** | Full scan: 0.1% post-1930 years -> essentially era-neutral (you were right). Optional light filter of ~3.5% modern-framed items. [depth anomaly: watch] |
| `piqa` | **REWRITE+FILTER** | 0% years but modern register/objects. Restyle; light item filter. |
| `openbook_qa` | **REWRITE** | 0% years; timeless commonsense/science; light restyle of register. |

### World Knowledge
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `jeopardy` | **FILTER** | 11.7% post-1930 years (full scan). Date-filter; many items already pre-1930 (Bacon, Byrd). |
| `bigbench_qa_wikidata` | **FILTER** | Text scan clean (0.1% years) but modernity is in ENTITY IDENTITY (people born post-1930) -> needs entity-dating, NOT text filtering. Different problem than squad. |
| `arc_easy` | **FILTER** | 0.5% years; pre-1930 science fine; drop modern-tech items. |
| `arc_challenge` | **FILTER** | 0.7% years; 1930 physics fine. Only general benchmark TypewriterLM reported -> goal-(b) anchor. |

### Symbolic Problem Solving
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `bigbench_dyck_languages` | **DROP** | Low construct value + likely OUT-OF-DISTRIBUTION for a books-trained vintage model (bracket sequences never appear in 1930 prose). Drop on construct/OOD grounds (not anachronism). |
| `agi_eval_lsat_ar` | **KEEP** | Full scan: 0% post-1930 years. Era-neutral analytical logic -> FAIR (you were right). Optional light filter of ~5% modern-topic passages. |
| `bigbench_cs_algorithms` | **DROP** | Modern CS concept (LCS/DP) a 1930 model cannot hold; also a spurious 0%-baseline artifact, flat across depth AND data. |
| `bigbench_operators` | **KEEP** | Pure abstraction (defined operators), era-neutral. (100% "modern" in scan = false positive on the word "compute".) |
| `bigbench_repeat_copy_logic` | **REWRITE** | 0% years; mechanics timeless; surface vocab anachronistic (python/data tokens). Restyle tokens. |

### Language Understanding
| Task | Verdict | Rationale (temporal axis) |
|------|---------|----------------------------|
| `hellaswag_zeroshot` | **REWRITE** | Same source, 0-shot variant of hellaswag. |
| `lambada_openai` | **REWRITE** | 0.2% years but modern-novel REGISTER. Strong signal, scales well -> rewrite to held-out period books, do NOT drop. |
| `hellaswag` | **REWRITE** | Flagship "HellaSwag 1930". Re-validate baseline (adversarial distractors break on rewrite). |
| `winograd` | **KEEP** | Timeless pronoun resolution; register already period-appropriate. |
| `winogrande` | **KEEP** | Timeless; optional light restyle. |
| `bigbench_language_identification` | **KEEP** | Era-neutral (religious-translation sentences period-plausible). Low priority. |

### Justified exclusions (the only 2 drops)
| Task | Drop reason | Axis | Evidence |
|------|-------------|------|----------|
| `bigbench_cs_algorithms` | Modern-CS concept (LCS/DP) + spurious 0%-baseline | temporal + artifact | flat across depth (0.43->0.41) AND data; 0% post-1930 years but the *task itself* is post-1930 |
| `bigbench_dyck_languages` | Low construct value + out-of-distribution | construct/OOD | bracket sequences never occur in 1930 prose; tests nothing we value in a "smart" model |

*(squad and boolq, previously dropped, are reinstated as REWRITE+FILTER — they are adaptable like coqa. boolq
carries a signal-axis caveat: below chance through d24, so it may not score until d34.)*

### Proposed vintage suite (~20 tasks)
**KEEP** (6): copa, operators, agi_eval_lsat_ar, winograd, winogrande, language_identification · 
**REWRITE / REWRITE+FILTER** (9): squad, boolq, coqa, piqa, openbook_qa, repeat_copy_logic, hellaswag, hellaswag_zeroshot, lambada · 
**FILTER** (4): jeopardy, qa_wikidata, arc_easy, arc_challenge · 
**KEEP (light filter)**: commonsense_qa · 
**DROP** (2): cs_algorithms, dyck. (verdict tally from META: {'REWRITE+FILTER': 4, 'KEEP': 7, 'REWRITE': 5, 'FILTER': 4, 'DROP': 2})

### LAMBADA rewrite — how much held-out text?

LAMBADA = predict the final word of a ~4-5 sentence passage, where the last *sentence* alone is insufficient.
To rebuild it from period books:
- **Eval set:** you do NOT need all 5,153 items. Per the noise analysis, N~1,000-2,000 gives a tight score
  (even ~500 is serviceable). At ~75 words/passage that is **~75k-150k words (~100k-200k tokens)** in the final set.
- **Screening pool:** the original LAMBADA kept only passages where the last sentence alone fails to predict the
  word -- roughly a 1-in-10 to 1-in-30 yield. So screen **~15k-60k candidate passages ~ 1-4.5M tokens** of
  held-out period prose to harvest ~1.5k good items. A few dozen period books cover it.
- **If you skip the strict filter** (just predict the last word of a paragraph), you need only the ~1.5k passages
  directly (~150k tokens) -- cheaper, but it tests less long-range dependency.
- **Must be held out of training** (reserve the slice before pretraining) or you measure memorization, not skill.

### Open decisions
- [ ] Re-validate `random_baseline` empirically for every REWRITE task (esp. hellaswag — adversarial distractors break).
- [ ] **Acceptance test needs depth, not seeds:** keep a task if it separates *across model scale* (d12<d24<d34),
  not by absolute d12 score. Re-run the depth table (3C) on the vintage ladder once d24 vintage exists.
- [ ] **boolq:** confirm it clears its 62% baseline at d34 before relying on it; else revisit DROP.
- [ ] **commonsense_qa anomaly:** drops with depth (d12 0.20 -> d24 0.06). Investigate before trusting it.
- [ ] **qa_wikidata entity-dating:** build a NER + birth/founding-date filter (text scan misses modern entities).
- [ ] Confirm answer-side anachronism handling for qa_wikidata (Russia/USSR-type cases).

