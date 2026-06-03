# Institutional Books Premium Filter Audit

Source: arXiv:2506.08300, "Institutional Books 1.0".

## Relevant Report Findings

- Use `text_by_page_gen`: it is the post-processed OCR text.
- `ocr_score_src` is the source OCR quality score.
- `ocr_score_gen` is the Pleias OCRoscope score.
- English post-processed tokenizability averages about `97`; a premium cutoff should be near `95`, not `70`.
- Very low English tokenizability, especially `<30`, surfaces table/graph/music-sheet OCR failures.
- `language_distribution_gen` is needed because `language_gen == "eng"` can still include mixed-language books.
- `date_types_src`, `page_count_src`, `token_count_o200k_base_gen`, and `text_analysis_gen` are useful quality gates.

## Implemented Premium Defaults

- `language_gen == "eng"`.
- English proportion `>= 0.90`.
- parsed year `< 1930`; reject undated/invalid date types.
- `ocr_score_src >= 90`.
- `ocr_score_gen >= 90`.
- OCR disagreement `<= 10`.
- `text_by_page_gen` tokenizability `>= 95`.
- reject only pathological tiny fragments: `<500` tokens, `<2000` chars, `<3` pages, or very low sentence count.
- keep training shards text-only; write per-document audit metadata separately.

## Live Checks

Metadata-only sample over first 25 rows:

- old broad filter: `15/25` rows passed.
- premium strict: `5/25` rows passed.
- relaxed premium: `8/25` rows passed.

Smoke tests confirmed:

- output parquet schema is `text: string`.
- Drive-style `--state-dir` works separately from `--output-dir`.
- `audit_metadata.jsonl` is written.
- forced-val smoke committed val barcodes correctly.

## Direction

Build a smaller premium English pretraining corpus in a new private HF repo. Run `--dry-run-stats` before the full build and do not reuse the corrupted earlier repo.
