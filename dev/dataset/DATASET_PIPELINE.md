# Dataset Sharding & Processing Guide

Use this as the contract for building nanochat pretraining shards.

## Shard Contract

- Emit `shard_{index:05d}.parquet`, sorted lexicographically.
- Training shards come first; the final shard is validation.
- Training parquet schema stays **single-column `text: string`**.
- Use ZSTD-3, `use_dictionary=False`, `write_statistics=False`.
- For book-scale documents, keep `row_group_size=64`; target `250_000_000` chars per shard.
- Keep per-document metadata out of training shards. Store audit rows separately.

## Premium Institutional Books Filter

Default target is a smaller, cleaner English corpus:

- `text_by_page_gen` only.
- `language_gen == "eng"`.
- English proportion in `language_distribution_gen >= 0.90`.
- parsed year `< 1930`; reject undated and invalid/continuing date types.
- `ocr_score_src >= 90`.
- `ocr_score_gen >= 90`.
- `abs(ocr_score_src - ocr_score_gen) <= 10`.
- `text_analysis_gen.text_by_page_gen.tokenizability_score >= 95`.
- reject only pathological fragments: `<500` o200k tokens, `<2000` chars, `<3` pages, or very low sentence count.
- dedup with `barcode_src` and `likely_duplicates_barcodes_gen`.

Do not reject legitimate short works just because they are short.

## Resume And Upload Safety

On Colab, use local SSD for shards and Drive for state:

```bash
--output-dir /content/base_data_books
--state-dir /content/drive/MyDrive/nanochat_state
```

With `--upload-incremental`, the script uploads shard batches before promoting barcodes into durable state. Each batch includes a recovery manifest so a restart can recover uploaded shards instead of overwriting remote files. The script also checks remote shard indexes and refuses unsafe overwrites.

## Required Verification

1. Run `--dry-run-stats` first. Compare old broad, premium strict, and relaxed premium pass counts.
2. Run a small `--max-rows` smoke test and confirm:
   - parquet schema is `text: string`
   - `manifest.json` exists
   - `README.md` exists
   - `audit_metadata.jsonl` exists
   - state lives under `--state-dir`
3. Full run only against a new private HF dataset repo.

Recommended full command:

```bash
python dev/dataset/repackage_institutional_books.py \
  --output-dir /content/base_data_books \
  --state-dir /content/drive/MyDrive/nanochat_state \
  --chars-per-shard 250000000 \
  --shuffle-buffer-gb 20 \
  --upload-incremental \
  --upload-batch 50 \
  --repo-id jbduran/think-institutional-books-premium
```
