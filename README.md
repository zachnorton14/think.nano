# ThinkGenesis — nanochat d12 experiment log

Every version here is a clone of [karpathy/nanochat](https://github.com/karpathy/nanochat) trained at **depth 12** (~286M params; `n_embd=768`, 12 layers, vocab 32,768). They all aim at the same compute-optimal d12 horizon — **~1.32B training tokens (~2,520 steps × 524,288-token batches)**. What changes between versions is the **dataset**, the **tokenization strategy** (on-the-fly vs pre-tokenized), where the **code, data, and checkpoints are stored**, and crucially **how much unique data was available** relative to that 1.32B-token horizon.

The arc: a vanilla ClimbMix clone (`shit_gpt`) → port to Project Gutenberg (`1.0`) → add pre-tokenization (`2.0`) → scale the data and move storage to HuggingFace (`2.5`) → raise the token target to ~1.5B and move the code to GitHub (`3.0`, current).

---

## shit_gpt — the reference run

A faithful, unmodified nanochat clone used as the baseline.

- **Dataset:** ClimbMix (`karpathy/climbmix-400b-shuffle`) — general web text.
- **Tokenization:** none up front — nanochat's default dataloader tokenizes raw text **on the fly** during training.
- **Storage:** Google Drive (the `nanochat_cache` dir is symlinked to Drive).
- **Data & shards:** 8 train shards of ClimbMix parquet (raw text), plus 1 val shard.
- **Training:** ~1.32B tokens in roughly **1 epoch**, ~110 min ETA at ~56% MFU.
- **Takeaway:** the baseline. Establishes the ~286M-param d12 setup and the ~120 min / ~56% MFU target that later Gutenberg runs aim to match.

## Gutenberg 1.0 (`gutenbergv1.ipynb`)

First port from ClimbMix web text to Project Gutenberg books.

- **Dataset:** Project Gutenberg (`sedthh/gutenberg_english`).
- **Tokenization:** none up front — still tokenized **on the fly**.
- **Storage:** Google Drive (clone, data, tokenizer, and checkpoints all live on Drive via symlink).
- **Data & shards:** the **full corpus split into 8 equal shards** (raw text) — so each shard is large (~corpus/8).
- **Training:** standard d12 run over the (large) corpus.
- **Takeaway:** proves the Gutenberg pipeline end-to-end, but on-the-fly tokenization of book-length documents is slow, which motivated pre-tokenization next.

## Gutenberg 2.0 (`gutenbergv2.ipynb`)

Introduces **pre-tokenization** — the corpus is tokenized once into a flat `uint16` `.bin` stream, so the training loop reads tokens directly (keeps the GPU fed → hits the ETA target).

- **Dataset:** Project Gutenberg (`sedthh/gutenberg_english`).
- **Tokenization:** **pre-tokenized** flat `uint16` `.bin` shards (no per-step tokenization).
- **Storage:** Google Drive (everything).
- **Data & shards:** corpus resharded into 100, but only **8 of 100 shards staged** ≈ **~264M unique tokens** — well short of the 1.32B horizon.
- **Training:** 2,520 steps = ~1.32B tokens trained, but over only ~264M unique tokens → **5 epochs** (the epoch counter flipped roughly every ~500 steps).
- **Takeaway:** pre-tokenization successfully recovered the ETA target, but too little *unique* data meant the model saw the same ~264M tokens 5× — heavy repetition. The fix is more data.

## Gutenberg 2.5 (`gutenberg2.5.ipynb`) — HuggingFace storage

Keeps pre-tokenization, scales the data to cover the horizon, and moves data + checkpoint storage off Drive onto HuggingFace.

- **Dataset:** Project Gutenberg (`sedthh/gutenberg_english`).
- **Tokenization:** **pre-tokenized** flat `uint16` `.bin` shards (tokenized locally each session from the raw text).
- **Storage:** **HuggingFace.** A *dataset* repo holds the raw Gutenberg text; a *model* repo holds the tokenizer + all checkpoints (pushed every save, auto-resume on reconnect). Google Drive holds only the notebook + helper scripts.
- **Data & shards:** **40 of 100 shards** ≈ **~1.32B tokens** — enough to cover the horizon in ~1 epoch.
- **Training:** ~1.32B tokens in **~1 epoch**; checkpoints stream to the HF model repo so a Colab disconnect resumes cleanly.
- **Takeaway:** sufficient unique data (no more 5× repetition) and durable, Drive-free storage for data and checkpoints. **Superseded by 3.0**, which also moves the code (notebook + scripts) off Drive onto GitHub.

## Gutenberg 3.0 (`gutenberg.ipynb`) — the current model

The current setup. Keeps 2.5's pre-tokenized, HuggingFace-backed pipeline, raises the token target to **~1.5B**, and moves the **code** off Google Drive: the notebook, helper scripts, and `nanochat` package now live in this **`think.nano` GitHub repo**, cloned fresh each session. Drive is gone entirely.

- **Dataset:** Project Gutenberg (`sedthh/gutenberg_english`).
- **Tokenization:** **pre-tokenized** flat `uint16` `.bin` shards (tokenized locally each session).
- **Storage:** **HuggingFace** for data + checkpoints (as in 2.5); **GitHub** (`think.nano`) for the notebook, helper scripts, and `nanochat` package, cloned each session. **No Google Drive.**
- **Data & target:** **~1.5B-token target** (`TARGET_TOKENS`), up from 2.5's ~1.32B, pre-tokenized from the full ~3.3B corpus — a wider data margin for a better tokens-to-parameter ratio and zero repetition.
- **Training:** the d12 run streams from the ~1.5B-token pool; checkpoints push to the HF model repo every save for clean auto-resume on a Colab disconnect.
- **Takeaway:** the current model — durable HF storage for data/checkpoints, version-controlled code on GitHub (no Drive), and a token target that comfortably exceeds the training horizon.

---

## Comparison

| Version | Params (d12) | Approx tokens (unique data) | Shards | Tokens/shard (approx) | Training reads |
|---|---|---|---|---|---|
| shit_gpt | ~286M | ~1.3B+ (ClimbMix) | 8 | ~165M | raw text (on-the-fly) |
| Gutenberg 1.0 | ~286M | ~3.3B (full corpus) | 8 | ~412M | raw text (on-the-fly) |
| Gutenberg 2.0 | ~286M | ~264M (8 of 100) | 8 | ~33M | tokenized (pre-tok) |
| Gutenberg 2.5 | ~286M | ~1.32B (40 of 100) | 40 | ~33M | tokenized (pre-tok) |
| Gutenberg 3.0 | ~286M | ~1.5B target (of ~3.3B avail.) | ~46 of 100 | ~33M | tokenized (pre-tok) |

**Notes**

- **All five are d12 (~286M params)** — the parameter column is constant by design; only data/tokenization/storage change.
- **Token counts are approximate.** For the raw-text rows they're text-token estimates; the full Gutenberg corpus (~3.3B tokens) is inferred from Gutenberg 2.0's 8-of-100 shards ≈ 264M tokens.
- **All five train to the same ~1.32B-token / ~2,520-step horizon** (set by `base_train`'s `--target-param-data-ratio`, default 12). The "unique data" column is what explains the epoch behavior: **Gutenberg 2.0 had only ~264M unique tokens → ~5 epochs**, **Gutenberg 2.5 has ~1.32B → ~1 epoch**, and **Gutenberg 3.0's ~1.5B pool → a sub-1-epoch pass with headroom**. Note `TARGET_TOKENS` sizes the pre-tokenized pool, *not* the training horizon — to actually train more tokens you'd raise `--target-param-data-ratio` (or pass `--num-iterations`).
- **"Training reads"** is what the training loop actually consumes: `shit_gpt` and `1.0` stream raw text and tokenize it on the fly; `2.0`, `2.5`, and `3.0` read pre-tokenized `uint16` `.bin` files. (ClimbMix and Gutenberg are both distributed as raw text; the pre-tokenization step is what differs.)
