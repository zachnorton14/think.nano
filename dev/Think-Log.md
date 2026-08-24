# Think Experiment Log

A running summary of experiments and findings for the Think dataset work.

Experiments mirror the closed issues in [zachnorton14/think.nano](https://github.com/zachnorton14/think.nano/issues?q=is%3Aissue+is%3Aclosed). Ordered by experiment number, most recent number at the top. Result data is pulled from each issue's comments; dates are left as `TBD` where only the close date is known.

A recurring theme across these experiments (made explicit in EXP007): **at the d12 scale, CORE is dominated by seed noise and Val BPB is the reliable metric.** Read the early CORE comparisons with that caveat.

---

## Anachronism detection via vintage-model loss

*2026-07-15*

Groundwork for a synthetic Q&A pipeline. The plan for synthetic data is to source answers from pretrain passages and generate questions from those answers. The open question was whether anachronistic generated questions can be detected automatically instead of by hand review. This tests whether a vintage model's per-token loss is a usable anachronism detector, before any pipeline is built around it.

### Setup
- Scorer: `think-d12-1ep-65sh-r30` **base** checkpoint, step 6300. A base (pretrain-only) checkpoint is required here. The SFT checkpoint is trained on the authentic pairs, so it has memorized the reference set and would report an artificially tight authentic distribution.
- Authentic bucket: 256 opening questions from the authentic-pre1930 SFT set (held-out split).
- Anachronistic bucket: 36 hand-authored probes in three kinds — `lexical` (post-1930 vocabulary: television, DNA), `conceptual` (period-safe words, modern concept: Big Bang, WWII), `register` (period-safe topic, modern phrasing: "quick summary of…", "TL;DR").
- Metrics, all in bits per byte: `mean` (whole question) and `peak` (mean of the top-3 word bits/byte). Peak exists because a single anachronistic word spikes only a couple of words and gets averaged away by the mean.
- Delta variant: vintage bits/byte minus GPT-2's bits/byte on the same words. Scores are aligned word by word rather than token by token, because the two tokenizers split text differently and per-token loss is not comparable across vocabularies.
- Tooling: `scripts/anachronism_eval.py`, `scripts/anachronism_probe.py`, and `score_word_bits` in `nanochat/loss_eval.py`. Forward passes only, no generation, so it runs on a MacBook (MPS) in under a minute.

### Goal
Decide whether loss-based filtering is worth building into the synthetic pipeline.

### Results

AUC is the probability that an anachronistic question scores higher than an authentic one (0.5 = no signal). Recall is measured at the authentic p95 threshold, i.e. accepting that ~5% of authentic questions get wrongly flagged.

| Metric | AUC | Recall @ p95 |
|---|---:|---:|
| vintage_mean | 0.736 | 0.17 |
| vintage_peak | 0.807 | 0.36 |
| delta_mean | 0.899 | 0.42 |
| **delta_peak** | **0.933** | **0.67** |

Vintage-only scoring has real signal but is limited by a specific defect: authentic period questions contain rare archaic vocabulary, so they score high on their own merits. That widens the authentic distribution (p10–p90 of 2.70–4.49, pushing the p95 threshold to 4.87) until almost no anachronism clears it. The signal was there; the usable operating point was not.

Subtracting a modern model's loss addresses exactly that. Text that is merely rare and hard is surprising to both models and cancels out; text that is anachronistic is surprising only to the vintage model and survives the subtraction.

| Metric | authentic p10 / p50 / p90 |
|---|---|
| vintage_peak | 2.702 / 3.321 / 4.490 |
| delta_peak | 0.703 / 1.251 / 1.868 |
| delta_mean | −0.225 / **0.163** / 0.787 |

Authentic questions have a `delta_mean` median of 0.163 and a negative p10 — they cancel to approximately zero. This is the direct confirmation that the subtraction removes the vocabulary-rarity component rather than shifting every score equally. The authentic spread tightens from 1.79 to 1.17 wide, and the distance between the anachronistic and authentic medians roughly doubles relative to that spread.

`delta_peak` by probe kind:

| Kind | AUC | Recall @ p95 |
|---|---:|---:|
| lexical | 0.992 | 0.93 |
| conceptual | 0.939 | 0.45 |
| register | 0.839 | 0.50 |

Peak beat mean in every configuration, confirming that localized scoring matters more than average surprise.

### Efficacy

The approach works, with clear limits.

- It is a **coarse filter**. At a 5% false-positive rate it catches about two thirds of anachronisms. It belongs in a filter stack as one signal, not as the sole gate.
- Its strength is **weakest where it is needed most**. It is near-perfect on lexical anachronism (AUC 0.992), but grounding answers in pretrain passages already prevents most lexical anachronism, so that capability is largely redundant. It is weakest on register (AUC 0.839, 50% recall), which is the failure mode a modern generator is most likely to introduce. Useful there, but it will miss about half.
- The **delta is not optional**. Vintage-only scoring at 0.36 recall is marginal; the delta nearly doubles it to 0.67. A production filter should use two models.

### Caveats

- 36 probes total, only 10 of them register, so the per-kind numbers are imprecise.
- The probes are hand-authored guesses at anachronism, not samples of real generator output. Real synthetic questions will likely drift more subtly than "TL;DR". This is the largest gap in the experiment.
- GPT-2 (124M, 2019) is a weak modern reference. A stronger one should sharpen the cancellation, so 0.933 is probably a floor rather than a ceiling.
- One vintage checkpoint. Whether the authentic-tail defect behaves the same on the clean1930s lineage is untested.
- Contamination appears mild: authentic questions score high rather than low under the base model, which is what we would expect if it had not memorized them.

### Conclusion

Loss-based anachronism filtering is viable and worth building, as one component of a filter rather than the whole thing, and only in its two-model delta form. Next steps in priority order: replace the authored probes with real generated questions; try a stronger modern reference model; re-run on the larger vintage model once it exists. Both `--checkpoint-dir` and `--modern-hf-path` swap in without code changes.

---

## EXP011 — Cleaned dataset performance ([#18](https://github.com/zachnorton14/think.nano/issues/18))

*2026-07-13*

Run validation tests across cleaned and uncleaned datasets to gauge model performance.

### Goal
Val BPB is sketchy across datasets. While this metric does normalize tokenizer differences, our models validate on the final shard in our dataset. Because this shard is different between the cleaned and unclean it means our validation BPB scores between the cleaned and original dataset are hard to make conclusions from. This experiment is meant to give us a way of doing cross-dataset analysis so we can see whether or not our cleaning is doing what we want.

### Setup
- Run tags: `think-d12-r11.25`, `thinkcleaned-d12-r11.25`
- Run val BPB completion for both clean and original-based models through the other dataset's validation shard, to fill out the matrix:

| _Validation bpb_ | Original Shard | Cleaned Shard |
|---|---|---|
| **Original Model (A)** | ~1.05198 | ? |
| **Clean Model (B)** | ? | 1.06085 |

**What each result would mean**:

- *B beats A on the clean val shard*: Meaningful. Can't be explained as home-field advantage, because A saw that same kind of prose in training. It would mean the tokens A spent on headers/OCR junk were worse than useless. Cleaning bought real quality on the text we care about.
- *A beats B on the original val shard*: Expected and uninformative. Probably means that A learned to predict page numbers and running headers whereas B never saw them.
- *A beats B on the clean val shard*: A worrying result. It could suggest the extra junk tokens didn't hurt (maybe even acted as regularization or extra diverse data), and the cleaning pipeline cost usable training tokens for nothing.
- *B beats A on the original val shard*: Would be striking overkill. Clean model better even on dirty text it never trained on. Strong win for cleaning, but would be unexpected.

### Notes
A further dataset cleaning is being prepared as this test is being explored. Once the final cleaned dataset with stripped footers and anachronism filters applied is completed, this test can be ran again against the other shards.

The validation shard for the cleaned datasets is proportionally smaller to the amount of cleaning done. In reality, the size of the shard doesn't matter. What is worth considering is the composition. Because validation uses a prefix of the shard's documents in order, this means that cleaner sets likely extend further into the text, leaving out the garbled headers and footnotes that contaminate the documents. In this way, the val sets aren't document-for-document aligned. Hopefully this shouldn't matter since the models are scored on identical token streams.

### Results

| _Validation bpb_ | Original Shard | Cleaned Shard |
|---|---|---|
| **Original Model (A)** | ~1.05198 | 1.0814 |
| **Clean Model (B)** | 1.1045 | 1.06085 |

The results we expected came out to be true. Look at how the models performed on the cleaned validation shard. Since model A trained on all the same prose plus junk — B wins (1.0609 vs 1.0814; −0.0205 bpb). This isn't just noise because this difference is 7 times larger than the per-token deltas (#10) which were obviously real differences. The tokens A spent learning headers and OCR garble was replaced by text that is actually good for the model. The cleaning (the primitive version, by the way) actually converted wasted time into quality.

A stark difference in the clean model validating on the original (1.1045) vs the cleaned (1.06085) shard shows that when the model isn't given boilerplate and OCR trash it does significantly worse at trying to validate a garbled shard. In other words, the model is less likely to output useless tokens.

It's also worth noting that when the original model validates the clean (1.0814) vs original (1.0519) shards it confirms our suspicion that the dataset did affect model scoring. For _the same_ model, the dirty shard scores better. This must mean that the removed garbage is easier to predict and was deflating the original dataset's validation numbers. Our original concern was that the cleaned model had worse validation scores, but this shows that's not something to worry about — the cleaned shard is just harder to predict.

**Extended with the clean-1930s dataset:**

| _Validation bpb_ | Original Shard | Clean v1 Shard | Clean-1930s Shard |
|---|---|---|---|
| **Original Model (A)** | ~1.05198 | 1.0814 | 1.078169 |
| **Clean v1 Model (B)** | 1.1045 | 1.06085 | 1.057347 |
| **Clean-1930s Model (C)** | 1.10582 | 1.062820 | 1.05961 |

What we see is cleaning still winning big, yet the new clean-1930s dataset did not improve on the previous clean version. The two clean-trained models beat the dirty model A by ~0.02 bpb (A 1.0782 vs B 1.0573 vs C 1.0596). However, down every fixed column, model B (old clean v1) edges out model C (new clean-1930s):

- on original text: 1.1045 vs 1.1058 (B better by 0.0013)
- on clean-v1 text: 1.0609 vs 1.0628 (B better by 0.0019)
- on clean-1930s text: 1.0573 vs 1.0596 (B better by 0.0023)

**Note:** model C was run with 4 special tokens removed from the vocabulary, allowing for four additional merges. This, in theory, should have lowered bpb, if anything, but regardless the test is not one-for-one with this caveat. The findings are still interesting nonetheless.

---

## EXP010 — Longer context length ([#17](https://github.com/zachnorton14/think.nano/issues/17))

*2026-07-13*

Run our small r11.25 with a doubled context length: 2048 → 4096 → 8192.

### Goal
The modern web-based dataset, Common Crawl (raw version), averages roughly a few hundred tokens per document. Looking at the modern literature-based dataset, FineWeb, this corpus averages something like 1500 tokens per document. Only a mild increase. Compare this with our dataset, think-dataset, which averages about 150k tokens per document. A monstrous difference. While researchers today grow their context length sequentially in midtraining, usually beginning with 2048 and ending with enormous context lengths such as 128k up to 1M, what if we turned this on its head for our model? What happens when we increase our context length from the beginning? Will it complement our data's abnormally large average lengths?

### Setup
- Run tags: `think-d12-r11.25-ctx4096`, `think-d12-r11.25-ctx8192`
- This model is identical to a typical r11.25 which we've ran a few times now (see #12 and #10). Because of the increased context length, however, `device_batch_size` had to be cut in half to keep `total_batch_size` at 524,288 tokens. This could introduce non-trivial noise.

### Notes
According to Claude, training overhead (purely FLOPs) increases marginally as we increase our depth (d12 → d24, etc.):

> Interaction with context length: the attention-scores term is ≈ 6·L·T·d per
> token (causal), so its share of total FLOPs is roughly T/(12·d_model):
> - d12, T=2048: ~22% overhead; T=4096: ~44%
> - d24, T=4096: ~22%
> - d36, T=4096: ~15%
>
> So doubling context gets relatively cheaper as the model gets wider — at d24
> your ctx4096 experiment costs about the same relative overhead as ctx2048 does
> at d12. If the long-document hypothesis pans out at d12, scaling it up doesn't
> compound the cost.

It will be interesting to compare run times between models to see if larger contexts correspond to longer run times. If it too is marginal, then we can potentially incorporate larger context lengths into upcoming d24 model with non-negligible gains at minimal cost.

The typical rationale for increasing context-length gradually is to avoid bottlenecking compute early through attention's quadratic algorithm. Start small when it's cheap, then only at the final stages, when necessary, increase aggressively so the model learns how to use its large context window. With this in mind, compute and memory usage need to be analyzed closely to see if this experiment has any merit at all. This is assuming we see positive eval results.

### Results — ctx4096

CORE Score: **0.0644** &nbsp;|&nbsp; Val BPB: **1.033690**

While CORE decreases dramatically compared to `think-d12-r11.25-run1` (0.079172 → 0.064402), we've already proven CORE to be a pretty unreliable metric, at least for small parameter models (#12). What is a concrete improvement is our val bpb score (1.05198 → 1.03369). However, is this a large enough improvement to warrant using this context length at larger model depths (ie. d24)? Let's see what our diagnostics show between the two runs:

|  | r11.25 | ctx4096 | change |
|---|---|---|---|
| Steps / tokens | 2,632 / 1.238B | same | - |
| Training FLOPs | 1.099e18 | 1.379e18 | +25.5% |
| Median step time | 2.65s | 3.02s | +14% |
| Tokens / sec | ~198k | ~173.5k | -12.4% |
| MFU | 56.3% | 61.9% | +5.6 pts |
| Peak GPU Memory | 15,862 MiB | 15,867 MiB | +5 MiB (~0%) |

The FLOPs accounting shows the attention term doubling added ~25% to total training FLOPs, but wall-clock only grew ~14% (≈1h59m vs ≈1h44m of pure training) because MFU rose from 56% to 62% — the extra attention compute runs efficiently, so you pay less in time than in FLOPs. Memory usage changed trivially.

A further metric was devised at the token level to see how the models effectively use context and to determine learned representations. This "per-token loss" is charted:

| Position | Baseline (ctx2048) | ctx4096 | Δ |
|---|---|---|---|
| 0–255 | 1.1255 | 1.1301 | +0.0046 |
| 256–511 | 1.0637 | 1.0657 | +0.0021 |
| 512–767 | 1.0507 | 1.0496 | −0.0011 |
| 768–1023 | 1.0457 | 1.0431 | −0.0026 |
| 1024–1279 | 1.0383 | 1.0366 | −0.0017 |
| 1280–1535 | 1.0331 | 1.0298 | −0.0033 |
| 1536–1791 | 1.0308 | 1.0281 | −0.0027 |
| 1792–2047 | 1.0276 | 1.0245 | −0.0031 |
| 2048–2303 | — | 1.0203 | — |
| 2304–2559 | — | 1.0179 | — |
| 2560–2815 | — | 1.0179 | — |
| 2816–3071 | — | 1.0207 | — |
| 3072–3327 | — | 1.0171 | — |
| 3328–3583 | — | 1.0150 | — |
| 3584–3839 | — | 1.0124 | — |
| 3840–4095 | — | 1.0101 | — |

My hypothesis was that at a larger context length the model could better learn the representations for each token. The per-token loss differentials for positions 0–2047 would corroborate this hypothesis. The verdict on the hypothesis, however: no, the long-context training did not improve short-range representations. Averaged over positions 0–2047 the two models are a statistical tie (1.104 vs 1.106, difference well inside bucket noise). If anything there's a whisper of the "context-allocation tax" at very early positions, though every individual early-bucket gap is also within noise.

What the data does show is a clean crossover around position ~1500: from there the ctx4096 model pulls ahead and keeps improving out to 4096, where its best buckets (~1.04) beat anything the baseline achieves anywhere. So, doubling context bought genuinely better predictions deep into long documents at zero cost to short-context quality, zero memory cost, and ~14% wall-clock — but it didn't transfer backward into better general representations at d12 scale. The mechanical-averaging effect explains the rest of the headline bpb gap (1.075 vs 1.099).

### Results — ctx8192

CORE Score: **0.072** &nbsp;|&nbsp; Val BPB: **1.01273**

Val BPB continues to drop by decent numbers. The results show, though, that this number comes from purely mechanical advantages rather than a better model.

Overall val bpb: 1.0519 (2048) → 1.0337 (4096) → 1.0127 (8192). The per-doubling improvement looks like it's growing (−0.0182 then −0.0210), which is backwards from diminishing returns. That's a tell that it's an averaging effect. When you line up only the positions all three share (512–1792), the story inverts, however:

**Per-token loss**

| Region | ctx2048 | ctx4096 | ctx8192 |
|---|---|---|---|
| pos 0–255 (tax) | 1.1255 | 1.1301 | 1.1346 |
| pos 256–511 | 1.0637 | 1.0657 | 1.0679 |
| matched avg 512–1792 | 1.0377 | 1.0353 | 1.0353 |
| deep tail (4096→7936) | — | — | descends to 0.984 |

On matching tokens, the longer context model sees no improvement. Context doubling did nothing for short/mid-range prediction quality. The decreased validation comes from the latter half of tokens which have greater context. In fact, the short range issues grow as the context length increases. Position 0–255 is now +0.0091 from +0.0046 at ctx4096. This is because more model capacity is spent learning long range representations. So the original hope for short range performance increases from longer context is actually backwards; the evidence is that performance declines.

**Comparing runs**

| Metric | ctx2048 | ctx4096 | ctx8192 |
|---|---|---|---|
| Step time | 2.65s | 3.02s (+14%) | ~3.8s (+43%) |
| Total train time | 1.74 hr | 1.98 hr (+14%) | ~2.49 hr (+43%) |
| Throughput | 198k tok/s | 173.5k tok/s (−12%) | ~138k tok/s (−30%) |
| MFU | 56.3% | 61.9% (+10%) | ~65% (+15%) |
| Total FLOPs | 1.099e18 | 1.379e18 (+25%) | ~1.94e18 (+76%) |
| Overall val BPB | 1.0519 | 1.0337 (−1.7%) | 1.0127 (−3.7%) |

| Doubling | Δ step time | Δ FLOPs | Δ overall BPB | Δ matched-position BPB |
|---|---|---|---|---|
| 2048 → 4096 | +14% | +25% | −0.0182 | −0.0024 |
| 4096 → 8192 | +25% | +41% | −0.0210 | ~0.0000 |

### Conclusion

Is a context-length increase worth it? The answer isn't obvious given the cost. The clear result is that increasing context length does not result in a radically more intelligent model. The eye-catching val bpb results are somewhat deceiving as the model can pad its stats by doing much better at later tokens. There is no early-token improvement, which is really what we care about. Our model is realistically going to be chatted with in short, quick bursts, with little need for long context.

**4096 is warranted, 8192 is surely not.**

---

## EXP009 — Train on alternate data shards ([#14](https://github.com/zachnorton14/think.nano/issues/14))

*2026-06-17*

A robustness check on the corpus itself: train the same configuration on a different subset (shards) of the Think dataset to see how much dataset quality varies across the corpus.

### Setup
- Run tag: `think-d12-r20-2epoch` (alt-44-shard collection, `think-d12-r20-alt44`)
- Model: d12, r20, same parameters as the original r20-44sh run, different shard subset.

### Goal
See how much the quality of our dataset differs at different subsets of the corpus.

### Results

| Run | CORE | Val BPB |
|---|---:|---:|
| Original r20 (sh472 validation) | 0.0801 | 1.059793 |
| Alt-44 shards | 0.07747 | 1.073976 |

Validation was done on the same shard (472) for both models, so the comparison is apples-to-apples on Val BPB.

The alternate shard collection made the model **worse at autocompleting the validation shard** (Val BPB 1.0740 vs. 1.0598, a ~0.014 gap). So which shards we train on *does* move the validation metric by a non-trivial margin. The CORE drop is noted but not trusted on its own (see EXP007). Practically, this matters less than it looks: larger production models will train on the whole dataset, so shard selection is mostly a small-scale artifact rather than a lasting lever.

---

## EXP007 — Train the same model multiple times ([#12](https://github.com/zachnorton14/think.nano/issues/12))

*2026-06-22*

Repeat one configuration end to end three times, changing only the random seed, to measure run-to-run variance from seeding, sampling, and local minima. This is the experiment that recalibrated how we read every other result.

### Setup
- Run tags: `think-d12-1ep-sh25-r11-run1`, `-run2`, `-run3`
- Model: d12, 25 shards, r11 (~1.2B target tokens using only ~12 of the 25 shards), chosen for speed over r20.
- Required modifying `base_train` to support custom seeding so the runs differ only by seed.

### Goal
Quantify how much the model's results depend on local minima, randomness, and sampling — whether a given CORE result is signal or a one-off.

### Results

| | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| CORE | 0.068268 | 0.066879 | 0.079172 |
| Val BPB | 1.05198 | 1.05139 | 1.05047 |
| Final Val | 1.10265 | 1.10182 | 1.10162 |

Val BPB across the three seeds: **1.051280 ± 0.000755**.

![EXP007 run-to-run variance](figures/think-d12-run-variance.png)

Two findings, both important:

- **CORE is unreliable at d12.** The same recipe, reseeded, produces CORE from 0.0669 to 0.0792 — a swing wider than the gaps between most *distinct* experiments. CORE cannot rank d12 models.
- **Val BPB is stable.** The same three seeds land within 0.0015 of each other (CV ≈ 0.07%), making it our trustworthy discriminator.

The implication reaches backward: earlier CORE-based conclusions (e.g. EXP004) may have been reading variance. A follow-up note also flagged that re-validating the original r11.25 model gave Val BPB 1.0598 vs. run1's 1.0520 (~0.008 apart, ~11σ) — larger than seed noise should allow, suggesting there is variance *beyond* the RNG and that the "baseline" and the re-runs may not be bit-identical configs despite the label.

---

## EXP006 — r20 model on IB dataset with weight decay 0.42 ([#6](https://github.com/zachnorton14/think.nano/issues/6))

*2026-06-26*

Tests whether more aggressive regularization helps on the lower-quality vintage data. Weight decay raised from the nanochat default 0.28 to 0.42 on an otherwise standard r20 IB run. This issue also carries the consolidated cross-experiment comparison and the seed-variance analysis.

### Setup
- Run tag: `think-d12-1ep-44sh-r20-wd42`
- Model: d12, r20, same training shards as the original IB model
- Weight decay: 0.42 (vs. nanochat default 0.28)

### Goal
Find whether higher weight decay has a significant impact on model performance. Rationale: vintage data is lower quality and less educational than Climbmix, so heavier regularization may help.

### Results

**wd42 r20 run:** CORE 0.0791, Val BPB **1.0196**.
**wd42 r11 run:** Val BPB **?**.

Consolidated comparison across configs (the three baseline re-runs are the seed-variance probe):

| Run | ratio | CORE | Val BPB | Tag |
|---|---:|---:|---|---|
| Baseline | r20 | 0.0801 | 1.0598 | *N/A* |
| Baseline re-run (seed 1) | r11 | 0.0792 | 1.0520 | think-d12-r11.25-run1 |
| Baseline re-run (seed 2) | r11 | 0.0669 | 1.0514 | think-d12-r11.25-run2 |
| Baseline re-run (seed 3) | r11 | 0.0683 | 1.0505 | think-d12-r11.25-run3 |
| r30-4500 | r20 | 0.0793 | 1.0643 | think-d12-1ep-65sh-r30 |
| Subset | r20 | 0.0775 | 1.0740 | think-d12-r20-alt44 |
| 2 epochs | r11 | 0.0872 | 1.0625 | think-d12-r20-2epoch |
| **wd42** | r20 | **0.0791** | **1.0196** | think-d12-1ep-44sh-r20-wd42 |
| **wd42** | r11 | **?** | **?** | think-d12-1ep-25sh-r11-wd42 |

**Seed-variance metrics (3 identical-config re-runs):**

| Metric | Mean | Std (n−1) | Range | CV |
|---|---:|---:|---:|---:|
| CORE | 0.07147 | 0.00673 | 0.01230 | 9.42% |
| Val BPB | 1.05130 | 0.00075 | 0.00150 | 0.07% |

![EXP006 seed-variance comparison](figures/exp006-seed-variance.png)

The seed cluster shows CORE's noise band (range 0.0123) is *wider* than the spread between every distinct experiment in the table — so CORE rankings that separate configs by less than ~0.012 are reading noise. Val BPB's band is ~130× tighter in relative terms and cleanly separates real effects.

On Val BPB, **wd42 is the standout: 1.0196, the lowest of any run at similar parameters**, tens of seed-σ below the baseline cluster — far too large to be noise. We can't claim wd42 improves CORE-measured capability (CORE is uninformative at d12), but the Val BPB improvement is real, and Val BPB is our best d12 metric. The only CORE result large enough to maybe trust is the 2-epoch run (0.0872), sitting ~0.6σ above the top of the seed band — weak evidence, worth re-seeding. In order to confirm our hypothesis, we decided to run an r11 run with the weight decay of 42.

### Conclusion

Higher weight decay (0.42) meaningfully improves Val BPB on the vintage data. Adopt it as a candidate default for vintage runs; CORE remains too noisy to corroborate at this scale.

---

## EXP005 — r12 model on an 80% IB / 20% Climbmix dataset ([#7](https://github.com/zachnorton14/think.nano/issues/7))

*2026-06-15*

Isolates *recency* from *quality* as the explanation for the CORE gap between our vintage r12 and nanochat's r12, by blending a little modern data (Climbmix) into the vintage corpus.

### Setup
- Run tag: `ib80climb20-d12-1ep-26sh-r12`
- Model: d12, r12, same training shards as the original model (not all IB shards used)
- Data: 80% IB books + 20% Climbmix, merged via the `merged-data` branch (tokenizer not saved, retrained each run)
- Validation: one validation shard from each dataset, combined at the given ratio

### Goal
Determine whether the CORE-score gap vs. nanochat's r12 is due to the time cutoff (recency) rather than data quality. Hypothesis: if CORE rises a lot while Val BPB barely moves, the gain is content recency, not quality.

### Results

CORE Score: **0.1003** &nbsp;|&nbsp; Val BPB: **1.17**

Per-source validation breakdown:

| Validation source | Val BPB |
|---|---:|
| Combined shard | 1.1702 |
| Climbmix | 1.0073 |
| IB Books | 1.2085 |

![EXP005 validation BPB curve](figures/exp005-bpb-curve.png)

CORE jumped ~50% (0.0673 → 0.1003) while combined Val BPB barely moved (1.19 sample → 1.17). That pattern supports the hypothesis: **the CORE gap vs. nanochat is primarily the lack of modern data, not data quality.** Caveat: the run trained on IB books for the first ~2000 steps and only then introduced Climbmix — you can see Val BPB rise around step 2000 — and by then LR decay meant Climbmix was learned at a much lower learning rate. So the result is suggestive, not airtight. (CORE magnitude itself is also subject to the EXP007 noise caveat.)

---

## EXP004 — r12, 2 epochs on the IB dataset ([#5](https://github.com/zachnorton14/think.nano/issues/5))

*Date: 2026-06-19*

Tests reuse vs. fresh data: does training two epochs over a smaller amount of data beat one epoch over more?

### Setup
- Run tag: `think-d12-r20-2epoch` (labeled r20 at init by mistake; this is the r12 / 2-epoch run, d12)
- Model: d12, r12, 2 full epochs. A faulty config led to ~800 extra steps and ~0.4B more tokens than intended.

### Goal
Find whether more epochs over less total data beat a single epoch over more data. Going-in expectation: worse than r20, since fresh data usually beats reuse.

### Results

CORE Score: **0.0872** &nbsp;|&nbsp; Val BPB: **1.106**

At matched step count the 2-epoch model performed **significantly better** than the original 1-epoch r20 — against the prediction. Some of the gain is a scheduler artifact (the longer total-step plan kept the LR higher at the matched step), but the improvement is too large to dismiss. Takeaway: more passes over existing data can match or beat pumping in new unique data; epoch count is a real knob for future configs.

> ⚠️ Revisited by EXP007: the CORE-based part of this win may be inflated by CORE's seed variance. The author later flagged this experiment specifically as one whose CORE findings can no longer be fully trusted. The Val BPB / scheduler reasoning still stands.

---

## EXP003 — r30 model on the IB dataset (ratio scout) ([#4](https://github.com/zachnorton14/think.nano/issues/4))

*Date: 2026-06-19*

Ran a d12 base pretraining run on the Think dataset with a target ratio of 30, then evaluated several intermediate checkpoints to quickly scout whether the best stopping region was closer to r12, r20, r26, or r30.

W&B run: [think-d12-1ep-65sh-r30](https://wandb.ai/jbduran-thinkingmachinesncsu/think.nano/runs/6465e19b/overview?nw=nwuserjbduran)

### Setup
- Run tag: `think-d12-1ep-65sh-r30`
- Checkpoints evaluated: 2500, 3500, 4000, 4500, 5500, 6300
- Metrics: full CORE and full validation BPB

The goal was a cheap scout, not a final scaling law.

### Goal
Find the best data-to-parameter ratio for our model.

### Notes
Caveat: one r30 schedule with frequent checkpoints is not a fair stand-in for independent r12/r16/r20/r26 runs — the LR only warmed up and never decayed for the earlier ratios, so a standalone r15 would beat the r30's checkpoint at the r15 mark.

### Results

| Step | Ratio | EFLOPs | CORE | Val BPB |
|---:|---:|---:|---:|---:|
| 2500 | 11.90 | 1.1627 | 0.04720 | 1.14370 |
| 3500 | 16.67 | 1.6278 | 0.06823 | 1.10496 |
| 4000 | 19.05 | 1.8604 | 0.06920 | 1.08422 |
| 4500 | 21.43 | 2.0929 | 0.07931 | 1.06425 |
| 5500 | 26.19 | 2.5580 | 0.08353 | 1.01587 |
| 6300 | 30.00 | 2.9301 | 0.08956 | 0.99446 |

![Think d12 ratio scout](figures/think-d12-ratio-scout.png)

![EXP003 CORE vs Val BPB frontier](figures/think-d12-core-vs-bpb.png)

The results do not support r12 as the right stopping point: Val BPB improved monotonically through r30 and CORE improved overall, so r12 is too low for this dataset/model. But it isn't clean enough to conclude r30 is correct, because all checkpoints come from one r30 LR schedule. CORE is also not the cleanest signal here — the Think corpus is older books while parts of CORE reward modern knowledge; Val BPB is the more direct dataset-fit signal.

### Conclusion

A useful scout, not a definitive scaling-law experiment. Practical takeaway: stick near r20 while the dataset and architecture are still moving — more ratio sweeps now would waste A100 time. Once stable, rerun a cleaner analysis with independent schedules around r16, r20, r24/r26, r30. For now r20 is a conservative, cheaper-than-r30 default near where quality started strengthening.

---

## EXP002 — IB books baseline ([#10](https://github.com/zachnorton14/think.nano/issues/10))

*2026-06-08*

Our second vintage model and the foundation for most later experiments: a nanochat base trained on a new 40B dataset filtered from Institutional Books.

### Setup
- Dataset: [think-dataset](https://huggingface.co/datasets/jbduran/think-dataset) (40B, filtered from Institutional Books by OCR quality, time cutoff 1930)
- Original source: [Institutional Books](https://huggingface.co/papers/2506.08300)
- Ran at both r11.25 (2362 steps; standard for r12 is ~2520) and r20 (4200 steps)

### Goal
Establish a baseline for the vintage IB dataset on the nanochat base.

### Results

| Config | Steps | CORE | Val BPB |
|---|---:|---:|---:|
| r11.25 | 2362 | 0.0673 | 1.098954 |
| r20 | 4200 | 0.0801 | 1.059793 |

This is the reference point for every vintage experiment (EXP003–EXP009). r20 beats r11.25 on both metrics, consistent with the EXP003 scout that r12 is too low a stopping ratio. The r20 numbers (CORE 0.0801 / Val BPB 1.0598) become the "baseline" anchor in EXP006's comparison table — though EXP007 later flagged that this anchor may not be bit-identical to the seed re-runs labeled the same.

---

## EXP001 — r12 model on the Gutenberg dataset ([#8](https://github.com/zachnorton14/think.nano/issues/8))

*2026-05-18*

Our first vintage model: an r12 model on an unfiltered Gutenberg corpus, built on the nanochat foundation.

### Setup
- Dataset: [gutenberg-english-text](https://huggingface.co/datasets/osvoorhe/gutenberg-english-text) (unfiltered)
- Model: [nanochat-gutenberg-d12](https://huggingface.co/osvoorhe/nanochat-gutenberg-d12), d12, r12
- Timeline: 5/29/2026 added pretokenization and first complete run; 6/1/2026 improved data ratio (r4, 8 sequence heads → r12, 24 sequence heads)

### Goal
Get a first vintage model running end to end on the nanochat foundation.

### Results

CORE Score: **0.0549**

Mostly a pipeline-shakeout on raw, unfiltered data, and the lowest CORE of the vintage models. It motivated the move to the filtered Institutional Books corpus in EXP002, where quality could be controlled by OCR filtering and a 1930 time cutoff.

---

## EXP000 — r12 nanochat baseline ([#9](https://github.com/zachnorton14/think.nano/issues/9))

*2026-05-15*

The modern-data control: nanochat at r12 / d12 on Climbmix, giving every vintage experiment a baseline to compare against.

### Setup
- Framework: [nanochat](https://github.com/karpathy/nanochat)
- Dataset: [climbmix-400b-shuffle](https://huggingface.co/datasets/karpathy/climbmix-400b-shuffle)
- Model: d12, r12
- First nanochat run: 5/22/2026

### Goal
Produce a modern-data baseline for comparison against the vintage models.

### Notes
At equal training time the vintage models cannot match this model's performance — the comparison is for orientation, not a fair contest.

### Results

CORE Score: **0.1479**

This is the modern-data CORE ceiling the vintage runs are measured against (0.1479 vs. ~0.05–0.10 for the vintage models). The gap between this and the vintage r12 is exactly what EXP005 attributes largely to data *recency* rather than quality — its 80/20 blend recovered CORE to 0.1003, roughly two-thirds of the way back.
