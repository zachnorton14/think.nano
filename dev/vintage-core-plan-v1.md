# Vintage CORE — Benchmark Adaptation Pipeline

## Context

We are building a 1930-cutoff ("vintage") version of the CORE metric so we can get a
low-noise quality signal for our institutional-books models (d12 → d24 → d34) without
penalizing them for *temporal/register mismatch* rather than capability. The audit in
`dev/VINTAGE_CORE_BENCHMARK.md` established, per benchmark, **where the anachronism lives**
(KEEP / REWRITE / FILTER / DROP) from a full-corpus temporal scan. This plan turns that
audit into an offline pipeline that emits adapted eval bundles, with bounded human review.

We produce **two bundles, kept separate on purpose** so we can measure the register
effect across models:

- **filtered bundle — `vintage-core-filtered` (PRIMARY, build first).** Filter every benchmark
  to remove post-1930 / anachronistic items. Large register-heavy tasks keep their
  survivors *as-is* (modern prose, smaller N). Low-N tasks get backfill/rewrite to hold N.
- **restyle bundle — `vintage-core-restyle` (LATER).** Full Opus restyle of every survivor
  into 1930 register, preserving semantics + gold answers + original N where possible.
  Directly comparable to original CORE. Cost-gated (see below).

Comparing the filtered bundle (modern prose) vs the restyle bundle (vintage prose) on the same models isolates how much of a
score gap is register vs. capability.

## Models & cost (decided)

- **Filter judge:** DeepSeek V4 Flash via OpenRouter. ~$2.60 per *full* pass over all
  ~78.7k items (no cap on filtering — it's cheap). Re-runs after prompt tweaks are ~$2.60 each.
- **Rewrite/backfill:** **Claude Opus 4.8.**
  - filtered bundle rewrite volume ≈ ~2.4k items (~0.25M output tokens) → **subscription is plenty**
    (or Opus API ~$20–30).
  - restyle bundle full (~78.7k items, ~12.5M output) → **subscription insufficient** (>1 month of
    quota, weekly caps, ToS-gray for bulk). Use **Opus API**: ~**$1,100 full** or ~**$360 capped at 2k/task**.
- Opus API reference pricing ~$15/M input, ~$75/M output (confirm current before restyle bundle).

## Verdict map (from `dev/VINTAGE_CORE_BENCHMARK.md`, 20 kept / 2 dropped)

- **DROP (2, excluded entirely):** `bigbench_cs_algorithms`, `bigbench_dyck_languages`.
- **KEEP (era-neutral, filter ~nothing):** copa, operators, agi_eval_lsat_ar, winograd,
  winogrande, language_identification, commonsense_qa (light filter of ~3.5%).
- **FILTER (remove modern items, keep survivors as-is):** jeopardy, qa_wikidata, arc_easy, arc_challenge.
- **REWRITE / REWRITE+FILTER (register restyle of survivors):** squad, boolq, coqa, piqa,
  openbook_qa, repeat_copy_logic, hellaswag, hellaswag_zeroshot, lambada.
- **Rewrite applies ONLY to REWRITE-verdict tasks.** FILTER/KEEP tasks are short Q&A with
  neutral register → no rewrite. (Resolves the "where do rewrites apply" confusion.)

## Reuse (existing infra — do not rebuild)

- **`dev/gen_synthetic_data.py`** — copy its OpenRouter client pattern: `requests` +
  `ThreadPoolExecutor` for concurrency + JSON-schema structured output + `OPENROUTER_API_KEY`
  from `.env`. Same pattern, swap model id (DeepSeek for filter, Claude for rewrite).
- **`dev/dataset/FILTER_AUDIT.md`** — mirror its per-item audit pattern: write a separate
  `audit_metadata.jsonl` (item, regex_flag, verdict, reason) rather than inlining in the data.
- **Bundle format** — `~/.cache/nanochat/eval_bundle/`: per-task `.jsonl` under `eval_data/`,
  `core.yaml` task manifest, `eval_meta_data.csv` baselines. Loader/scorer in
  `nanochat/core_eval.py` + `scripts/base_eval.py` stay UNCHANGED — we only swap the bundle.

## Pipeline (new script, e.g. `dev/vintage_core/build.py` + a small package)

Stages, each resumable and writing artifacts to disk:

1. **load** — read each kept task's `.jsonl` from the eval bundle (skip the 2 drops).
2. **regex prescan** — reuse `YEAR_RE`/`MODERN_RE` from `dev/gen_vintage_core_doc.py`
   (`temporal_scan`); attach a `regex_year_flag` to each item. Cheap signal fed into the judge.
3. **llm_filter** (DeepSeek Flash) — per item → `{keep: bool, reason: str}` via JSON schema.
   Handles semantic/entity anachronism the regex misses (esp. `qa_wikidata` people/places).
   Write `audit_metadata.jsonl` for every item.
4. **REVIEW GATE 1 (hard stop)** — emit a review file of **8 filtered-OUT items/task with
   reasons** (extra coverage for `qa_wikidata`). Human approves or edits the filter prompt → rerun.
5. **backfill_lowN** (Opus) — for low-N tasks that fall below target after filtering, generate
   period-appropriate replacement items in the *same format* (preserve choices/gold structure).
6. **rewrite** (Opus) — restyle survivors into 1930 register. **Semantics, gold answer, and
   choice order are held FIXED** (style only — this is why Opus, given the accuracy worry).
   filtered bundle: only the small REWRITE tasks (piqa/openbook/repeat_copy) + backfills.
   restyle bundle: all survivors (separate run, API, cost-gated).
7. **REVIEW GATE 2 (hard stop)** — emit **8 (original → rewritten) pairs/task**. Human checks
   answer-preservation + period fidelity → approve or edit rewrite prompt → rerun.
8. **repackage** — write adapted `eval_data/*.jsonl` + `vintage_core.yaml` + `eval_meta_data.csv`.
   Recompute `random_baseline` per task (esp. any task whose choice count changed; re-validate
   hellaswag empirically since rewrite breaks adversarial distractor calibration). Emit TWO
   bundles: `vintage-core-filtered` and (later) `vintage-core-restyle`, plus a crosswalk of
   which original items were dropped (so the filtered and restyle bundles can be aligned for comparison).

## Verification

1. **Dry-run stats first** (mirror `repackage_institutional_books.py --dry-run-stats`): per task,
   print kept/removed counts and projected N before spending on LLM calls.
2. **Smoke test**: run stages 3–6 on `--max-items 20` for 2–3 tasks; confirm audit jsonl,
   review files, and a valid mini-bundle are produced.
3. **Schema check**: adapted bundle loads via `scripts/base_eval.py` unchanged — run
   `python -m scripts.base_eval --model-tag d12 --eval core --max-per-task 50` against the new
   bundle dir and confirm it scores without errors.
4. **Sanity signal**: full vintage-core-filtered run on d12; expect KEEP-task scores ≈ original
   (we didn't touch them) and filtered tasks to lose ~the scanned %.
5. **Register-effect check** (after restyle bundle): run a modern model (GPT-2 family in the bundle)
   on filtered bundle vs restyle bundle — modern model should drop on the restyle bundle, confirming the rewrite bites.

## Phasing & open items

- **Phase 1 = filtered bundle** (filter-all + low-N rewrite/backfill on Opus subscription). Cheap, fully
  decided. Build this first.
- **Phase 2 = restyle bundle** (full vintage rewrite). **Open decision: budget/scope** — full original
  N (~$1,100 Opus API) vs capped 2k/task (~$360). Recommend capped-N first; revisit full-N if the
  register signal looks worth it.
- **qa_wikidata** needs entity-dating by the LLM judge (regex-blind); give it extra review weight in
  Gate 1, and confirm answer-side anachronism handling (e.g. "Novosibirsk → Russia" should be USSR in 1930).
- **commonsense_qa** depth anomaly (d12 0.20 → d24 0.06) is unrelated to this pipeline but flagged
  before trusting it as signal.
