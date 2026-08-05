# autoresearch

A port of [karpathy/autoresearch](https://github.com/karpathy/autoresearch) onto
think.nano's pre-1930s book corpus. An agent edits one file, trains for exactly five
minutes, checks whether `val_bpb` improved, keeps or discards, and repeats — roughly 12
experiments an hour, unattended.

This is deliberately **separate from the experiment harness** in `scripts/` and
`configs/`. There are no configs, no W&B, no Hugging Face artifacts, and no checkpoint
lineage here. Results are a shortlist of hypotheses to try in a real
`configs/base/*.json` run, not results in their own right.

## Files

| File | Who edits it |
|---|---|
| `prepare.py` | Nobody. Fixed constants, data prep, tokenizer, token cache, dataloader, and the `evaluate_bpb` metric. |
| `train.py` | The agent. GPT model, Muon + AdamW optimizer, training loop. |
| `program.md` | You. The agent's instructions — this is the real thing you iterate on. |
| `run.sh` | Nobody, normally. One-time box bring-up: GPU check, token cache, baseline run. |
| `results.tsv` | The agent. One row per experiment. Untracked by git. |

## Branches

This never lands on `dev` or `master`.

- **`autoresearch`** holds the scaffolding above and nothing else. Improvements to
  `program.md` or `prepare.py` are committed here.
- **`autoresearch-<tag>`** is one run, branched from `autoresearch`. The agent commits
  every experiment to it, so the branch is a full record of what was tried. Start each
  new run from `autoresearch`, not from a previous tag — otherwise you inherit a
  `train.py` that a hundred experiments have already chewed on.

Upstream names run branches `autoresearch/<tag>`, which is not available here: git refs
are paths, so a branch named `autoresearch` and a branch named `autoresearch/aug5`
cannot coexist. Hence the dash. Rename the scaffolding branch to `autoresearch-base` if
you would rather have the upstream naming.

## Data

`jbduran/think-dataset-clean` — 473 public parquet shards, ~218M chars each, one
`text` column. `shard_00472` is pinned as validation and never trained on.

The corpus stores **whole books as single rows** (median ~537K chars). Two consequences
shaped `prepare.py`:

- **The tokenizer samples a random window per book**, not the head, or the vocab would
  be trained on title pages and OCR front matter. This mirrors `--sampling random` in
  `scripts/tok_train.py`.
- **Everything is pretokenized once into a flat `uint16` stream.** Upstream
  autoresearch packs documents into 2048-token rows, which is meaningless when the
  median document is ~180K tokens. Flat concatenation also keeps tokenizer throughput
  from becoming a confound between experiments that change batch size.

`prepare.py --num-shards 40` produces roughly 2.7B train tokens against the ~500M a
five-minute run consumes, so no experiment wraps the corpus. If a config trains several
times faster, re-run with more shards rather than letting runs repeat data.

## Cache provenance

`~/.cache/autoresearch/` is the same path — with the same `shard_NNNNN.parquet` naming —
that upstream autoresearch uses for a different corpus, so a reused disk could otherwise
train on the wrong data without saying anything. Each stage records what built it:

- `data/provenance.json` — the dataset URL. Shards from another corpus, or shards with
  no provenance file at all, are **refused** with an instruction to delete the cache.
  Nothing is deleted automatically, because that could be 3 GB you wanted.
- `tokenizer/provenance.json` — dataset, vocab size, split pattern, and the sampling
  settings. A mismatch retrains the tokenizer from scratch.
- `pretok/meta.json` — dataset, a SHA-256 fingerprint of the whole tokenizer directory,
  and the exact set of parquet shards consumed. Any change rebuilds the token stream.

That last one is what makes `--num-shards` work on a second pass: adding shards changes
the recorded set, so the cache invalidates and the stream is rebuilt over everything.
A run with nothing changed reuses the cache and does no work. If anything looks wrong,
`rm -rf ~/.cache/autoresearch` and re-run is always the correct reset.

> `val_bpb` here is **not** comparable to upstream autoresearch's numbers, nor to
> `summary.json` from a harness run — packing scheme shifts the BPB scale (see the note
> at `scripts/experiment.py:1105-1108`). Every number in `results.tsv` comes from the
> same frozen function, which is all the loop needs.

## Running it

Rent **one** H100 SXM with ~200 GB disk. This is single-GPU; none of the 8-GPU NVLink
gating in `runs/clean1930s-d24-r12.sh` applies. The existing Vast image
`ghcr.io/zachnorton14/think-nano-vast:cu128-torch291-<lock-sha>` already satisfies every
dependency — autoresearch adds none.

```bash
git clone -b autoresearch https://github.com/zachnorton14/think.nano && cd think.nano
git checkout -b autoresearch-<tag>

bash autoresearch/run.sh          # GPU check -> ~3.1 GB download -> tokenize -> baseline run
```

`run.sh` picks up `/opt/think-nano-venv/bin/python` inside the container and falls back
to `uv run python` elsewhere; override with `AUTORESEARCH_PYTHON`. Use `NUM_SHARDS` to
change how much data it pulls. No credentials are needed — the dataset is public and
nothing is uploaded.

Then start the agent under `tmux` so it survives a disconnect, and prompt:

```
Hi have a look at autoresearch/program.md and let's kick off a new experiment!
let's do the setup first.
```

## Sanity checks after `prepare.py`

```bash
python - <<'PY'
import json, os, numpy as np, sys
sys.path.insert(0, "autoresearch")
import prepare
meta = prepare.load_pretok_meta()
print(f"train {meta['train_tokens']:,} tokens | val {meta['val_tokens']:,} tokens")
tok = prepare.Tokenizer.from_directory()
arr = np.memmap(os.path.join(prepare.PRETOK_DIR, "train_00000.bin"), mode="r", dtype=np.uint16)
print(repr(tok.decode([int(t) for t in arr[:200]])))
PY
```

It should read as period prose. If it reads as title pages, catalogue entries, or OCR
noise, the tokenizer sampling is wrong and every downstream number is suspect.

Two back-to-back baseline runs should agree on `val_bpb` to about 1e-3. A wider spread
means the metric cannot rank experiments and `EVAL_TOKENS` needs to go up before the
loop starts.
