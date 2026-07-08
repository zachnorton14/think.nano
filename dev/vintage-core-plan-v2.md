# Vintage CORE — Benchmark Adaptation Pipeline

## Context

Build a 1930-cutoff ("vintage") version of the CORE metric so our institutional-books models
(d12 → d24 → d34) get a low-noise quality signal that isn't confounded by *temporal/register
mismatch*. The per-benchmark audit in `dev/VINTAGE_CORE_BENCHMARK.md` (KEEP / REWRITE / FILTER /
DROP, from a 100%-corpus temporal scan) is the input. This plan turns it into an offline
pipeline emitting adapted eval bundles with bounded human review.

**Two bundles, kept separate on purpose** (to isolate register effect across models):
- **filtered bundle — `vintage-core-filtered` (THIS PLAN).** Every benchmark passes through both
  filters; anachronistic items removed. Large tasks keep survivors as modern prose (smaller N).
  Low-N tasks get filtered-out items **replaced** (Opus) to hold N. Drops: cs_algorithms, dyck.
- **restyle bundle — `vintage-core-restyle` (downstream of the filtered bundle).** A **pure stylistic restyle of the filtered bundle's
  items** (SAME item set → the filtered and restyle bundles differ only in register, a clean A/B for measuring the register effect
  across models). Model: **GLM 5.2 / 4.6** (or DeepSeek V4 Pro). Built after the filtered bundle; cheap (restyle only).

## Model access (provider-agnostic)

Every LLM stage calls a **configurable OpenAI-compatible `endpoint + key`** — provider/credit source is
config, not design. Hard requirement: **raw API access with OUR own minimal system prompt**, never an agent
TUI (Claude Code / OpenCode-agent / web), which inject muddying system prompts and can't batch.
- **Recommended backend: OpenCode Zen/Go** (~$10/mo, one `sk-` key, OpenAI-compatible): **DeepSeek V4 Flash
  free** (filter) + **GLM** (backfill/rewrite). Clean + batchable. Caveats: 5-hour rate limits (throttle the
  big batches) and aggregator quant risk → if no-quant matters for the filter, use DeepSeek-direct instead.
- **Filter judge:** DeepSeek **V4 Flash** (free via OpenCode, or DeepSeek-direct/OpenRouter-DeepSeek-pinned
  for no-quant). ~$2.60 per full pass at API rates; free via OpenCode. No cap on filtering.
- **Backfill/restyle:** **GLM 5.2/4.6** (or Opus/DeepSeek V4 Pro) via the same clean endpoint.

## Decisions locked
- **Both filters run on EVERY kept benchmark, including KEEP-labeled tasks** (regex prescan → LLM
  judge). KEEP tasks are expected to lose ~0 items, but still pass through to catch lurking temporal items.
- **filtered bundle backfills = replacements for filtered-OUT questions, for tasks with N ≤ ~1300** (backfill
  to hold N). Generated with **Opus 4.8 via the clean API** (see "Opus strategy"). Tasks with N > ~1300
  keep survivors as modern prose at reduced N (no backfill).
- **Review gates: exactly 8 samples per benchmark at each gate** (filter-out reasons; backfill pairs).
- **restyle bundle model = GLM 5.2** (trusted for style+accuracy, "right below Opus"); DeepSeek V4 Pro fallback.
- **Exact-match scorer: accept the undercount** (no change to `core_eval.py`); the 31% vs 37% bias is
  consistent across all our models so relative comparison is unaffected.
- **v1 safeguards: answer-preservation check + decontamination scan.** (repeat_copy_logic kept, not dropped.)

## Sourcing & decontamination (AmericanStories)

Two distinct roles:
- **Check target = the TRAINING corpus** (`jbduran/think-dataset` institutional books, <1930) — NOT the
  val shard. Decontamination = overlap with what the model learned from. Build a 13-gram hash set / bloom
  filter of training shards (DCLM `min_ngram_size=13`); scan the final bundle's items; report/flag hits.
- **Source for any GENERATED/REBUILT items = `dell-research-harvard/AmericanStories`** (historical
  newspapers; period-appropriate AND never trained on — user has parquets). Sourcing backfill (and, later,
  the lambada rebuild in restyle bundle) from AmericanStories makes those items **contamination-free by
  construction**, so the scan is just a safety net (expect ~0 hits for filtered original CORE items, which
  are modern-sourced and won't appear in <1930 books).

## Opus rewrite strategy (clean & simple)

Do NOT use Claude Code or claude.ai web — both inject large system prompts that bias outputs.
Call the **Anthropic Messages API directly** (or OpenRouter→Anthropic) with our own minimal system
prompt: define the 1900–1930 restyle persona, "preserve meaning + correct answer + every option
exactly, add/remove no facts, output JSON", + 2–3 period-prose exemplars, `temperature=0`, prompt-cache
the static prefix. Same `requests`/`ThreadPoolExecutor`/JSON-schema scaffold as `dev/gen_synthetic_data.py`.
filtered bundle backfill volume is small (~hundreds–1.5k items) → clean API ~$20–50, so skip the subscription.

## Verdict map (20 kept / 2 dropped — from `dev/VINTAGE_CORE_BENCHMARK.md`)

- **DROP (excluded):** `bigbench_cs_algorithms`, `bigbench_dyck_languages` (+ candidate `repeat_copy_logic`, N=32).
- **KEEP (filter runs, ~0 removed):** copa, operators, agi_eval_lsat_ar, winograd, winogrande,
  language_identification, commonsense_qa.
- **FILTER (remove modern items, survivors as-is):** jeopardy, qa_wikidata, arc_easy, arc_challenge.
- **REWRITE+FILTER (survivors are register-heavy):** squad, boolq, coqa, piqa, openbook_qa,
  hellaswag, hellaswag_zeroshot, lambada. *In filtered bundle these are filter-only (modern prose kept);
  register rewrite of these is restyle bundle.*

## Reuse (existing infra)

- **`dev/gen_synthetic_data.py`** — OpenRouter client pattern (requests + ThreadPoolExecutor + JSON
  schema + `OPENROUTER_API_KEY` from `.env`). Copy, swap model id + provider pin.
- **`dev/dataset/FILTER_AUDIT.md`** — per-item `audit_metadata.jsonl` pattern (item, verdict, reason).
- **Bundle format** — `~/.cache/nanochat/eval_bundle/`: `eval_data/*.jsonl` + `core.yaml` +
  `eval_meta_data.csv`. Scorer `nanochat/core_eval.py` + `scripts/base_eval.py` UNCHANGED; we swap the bundle.
- **`dev/gen_vintage_core_doc.py`** — reuse `YEAR_RE`/`MODERN_RE`/`temporal_scan` for the regex prescan.

## Pipeline (new package, e.g. `dev/vintage_core/`)

Task-type-aware throughout (MC / schema / language_modeling differ in structure). **Process benchmarks in
ascending N (smallest first)** so prompts are calibrated cheaply on copa (100)/repeat_copy (32) before
squad (10.5k)/wikidata (20k). Generation gates use **preview-then-commit per benchmark**: do 8 first →
review → approve/tune the prompt → only then process the rest of that benchmark (never spend a full
benchmark on an untuned prompt). Each stage resumable.

1. **load** — read each kept task `.jsonl`; skip drops; order tasks by N ascending.
2. **regex prescan** — attach `regex_year_flag` per item (reuse `temporal_scan`).
3. **llm_filter** (DeepSeek V4 Flash) — per item `{keep: bool, reason: str}` via JSON schema, temp 0.
   Calibrate the (largely universal) filter prompt on the 2–3 smallest benchmarks first, then run all.
   Catches semantic/entity anachronism regex misses — esp. **qa_wikidata** (people born post-1930 have no
   year in text; the judge dates the entity from world knowledge). Write `audit_metadata.jsonl`.
4. **REVIEW GATE 1** — per benchmark (smallest first), **8 filtered-OUT items + reasons** (weight
   qa_wikidata). Approve or edit filter prompt → re-run that benchmark (cheap).
5. **backfill** (GLM/Opus, clean API) — for tasks **N ≤ ~1300** that lost items: **preview 8** replacements
   in the *same task-type structure* (preserve choices/gold) → Gate 2 → then generate the rest to restore N.
   **Free-form period prompt** (no source passage); cleanliness verified by the decontam scan (stage 9).
   Tasks N > ~1300: accept reduced N.
6. **answer-preservation check (automated, 100%)** — every generated item: gold index unchanged, choice
   count unchanged, gold string present + unique, answer not leaked into stem. Reject + retry failures.
7. **REVIEW GATE 2 (preview-then-commit)** — the 8-item preview from stage 5 (original → replacement pairs);
   approve/tune before committing the benchmark's full backfill.
8. **repackage** — write `vintage-core-filtered/` bundle: `eval_data/*.jsonl` + `vintage_core.yaml` +
   `eval_meta_data.csv` with recomputed `random_baseline` per task. Emit a crosswalk of item ids so
   **restyle bundle can restyle the SAME items** for a clean filtered/restyle register comparison.
9. **decontamination scan** — 13-gram bloom filter of the `jbduran/think-dataset` training shards; flag any
   final-bundle item that overlaps. Free-form/AmericanStories-sourced items should yield ~0 hits; catches surprises.

**restyle bundle (after the filtered bundle):** same pipeline shape but a single restyle stage over the filtered bundle's items — smallest-first,
preview-8-then-commit per benchmark, answer-preservation check, repackage to `vintage-core-restyle/`.
Special-case **lambada** (restyle can change the predictable last word → reconstruct from AmericanStories or
keep filter-only) and **re-validate HellaSwag's baseline** empirically (rewrite breaks adversarial distractors).

## Verification

1. **Dry-run stats first** (mirror `--dry-run-stats`): per task print kept/removed/projected-N before spending.
2. **Smoke test**: stages 3–7 on `--max-items 20` for 2–3 tasks; confirm audit jsonl, review files, mini-bundle.
3. **Schema check**: `python -m scripts.base_eval --model-tag d12 --eval core --max-per-task 50` against the
   new bundle dir loads + scores with no code change.
4. **Sanity signal**: full d12 run; KEEP-task scores ≈ original; filtered tasks lose ~the scanned %.
5. **(if decontam in scope)** n-gram overlap scan of the final bundle vs the institutional-books training corpus.

## Decided (filtered bundle fully specified)

Provider-agnostic OpenAI-compatible endpoints (OpenCode Zen/Go recommended: free DeepSeek V4 Flash + GLM,
clean batchable key) · filter = DeepSeek V4 Flash on ALL tasks incl. KEEP · backfill N ≤ ~1300, free-form
period prompt (GLM/Opus) · accept exact-match undercount · answer-preservation + decontamination in scope ·
repeat_copy kept · process smallest-N first · preview-8-then-commit per benchmark at both gates ·
8 review samples/benchmark · **restyle bundle = stylistic restyle of the filtered bundle's items** (same set), built after the filtered bundle.

## Open items — restyle bundle (plan separately, next)

- **lambada special case:** stylistic restyle can change the predictable last word — reconstruct from
  AmericanStories (held-out period) or keep filter-only; not a generic rewrite.
- **HellaSwag baseline re-validation:** rewrite breaks adversarial distractor calibration → re-validate empirically.
- **Rate-limit throttling:** if using OpenCode's 5-hour windows, spread the big-benchmark restyle batches.
