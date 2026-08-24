# Bartholomew

The training codebase for **Bartholomew** — short for **Bartholomew III** — a 2.8B-parameter language model whose knowledge ends in
**1930**. It is trained from scratch on pre-1930 public-domain books, with no modern text anywhere
in the corpus, to study what a model learns when its entire world is historical.

📝 [Read the write-up](https://www.unboundedlab.com/blog/bartholomew) · 🌐 [Unbounded Labs](https://unboundedlab.com)

This is a fork of [nanochat](https://github.com/karpathy/nanochat) extended with a
configuration-driven experiment harness, a data-mixture scheduler for midtraining, and evaluation
suites adapted to a 1930 knowledge cutoff.

## How it fits together

A three-stage corpus chain feeds pretraining, a STEM-focused corpus is blended in during
midtraining while the learning rate decays, and a curriculum SFT pass makes the result
conversational.

```
Institutional Books 1.0
  → bartholomew-dataset-v1 → v2 → v3        pretraining corpus (~23B tokens)
       ↓ (subject tags)
  → bartholomew-midtrain                     pre-1930 STEM (~604M tokens)
       ↓
  → bartholomew (2.8B base) → bartholomew-sft      0% → 21% → 45% midtrain, then curriculum SFT
```

## Repositories

### Models

| Repo | What it is |
|---|---|
| [bartholomew](https://huggingface.co/jbduran/bartholomew) | The final base model — 2.8B params, weights only |
| [bartholomew-sft](https://huggingface.co/jbduran/bartholomew-sft) | The instruction-tuned model |
| [bartholomew-experiments](https://huggingface.co/jbduran/bartholomew-experiments) | All 39 training runs, checkpoints, and evaluations |

### Datasets

| Repo | What it is |
|---|---|
| [bartholomew-dataset-v1](https://huggingface.co/datasets/jbduran/bartholomew-dataset-v1) | Pre-1930 books from Institutional Books, OCR/language/date filtered |
| [bartholomew-dataset-v2](https://huggingface.co/datasets/jbduran/bartholomew-dataset-v2) | v1 de-boilerplated, log-prior filtered |
| [bartholomew-dataset-v3](https://huggingface.co/datasets/jbduran/bartholomew-dataset-v3) | v2 with the tiered anachronism filter — the pretraining corpus |
| [bartholomew-midtrain](https://huggingface.co/datasets/zachnorton03/bart-midtrain) | Pre-1930 STEM corpus, pipeline, and training mixtures |
| [synthetic-pre1930-sft](https://huggingface.co/datasets/zachnorton03/synthetic-pre1930-sft) | ~416K synthetic SFT rows across eleven task routes |
| [authentic-pre1930-sft-conversational](https://huggingface.co/datasets/zachnorton03/authentic-pre1930-sft-conversational) | SFT rows from 27 public-domain texts |
| [vintage-sft-robustness](https://huggingface.co/datasets/zachnorton03/vintage-sft-robustness) | Robustness rows — typos, malformed input, era questions |

### Evaluation

| Repo | What it is |
|---|---|
| [vintage-core](https://huggingface.co/datasets/jbduran/vintage-core) | CORE benchmark, period-adapted |
| [vintage-gsm8k](https://huggingface.co/datasets/jbduran/vintage-gsm8k) | GSM8K rewritten for a 1930 cutoff |
| [vintage-gsm8k-filtered](https://huggingface.co/datasets/jbduran/vintage-gsm8k-filtered) | GSM8K variant dropping rows that needed rewrites |
| [history-event-reconstruction](https://huggingface.co/datasets/jbduran/history-event-reconstruction) | HISTORY-EVENT benchmark reconstruction |

### Data pipelines

| Repo | What it is |
|---|---|
| [bartholomew-dataset-scripts](https://github.com/OwenVoorhees/bart-dataset-scripts) | Cleaning pipeline producing dataset v2 and v3 |
| [bartholomew-midtrain-scripts](https://github.com/OwenVoorhees/bart-midtrain-scripts) | Midtrain pipeline and mixture construction |
| [vintage-core](https://github.com/OwenVoorhees/vintage-core) | Builder for the period-adapted CORE benchmark |

## Documentation

| Document | Contents |
|---|---|
| [EXPERIMENTS.md](EXPERIMENTS.md) | **Start here.** The experiment harness: config contracts, lineage rules, artifact paths, branching |
| [dev/dataset/DATASET_PIPELINE.md](dev/dataset/DATASET_PIPELINE.md) | How the pretraining corpus was assembled |
| [dev/dataset/FILTER_AUDIT.md](dev/dataset/FILTER_AUDIT.md) | Filter-by-filter audit of what each stage removed |
| [dev/hosting/hosting.md](dev/hosting/hosting.md) | Deployment overview |
| [dev/hosting/beam/RUNBOOK.md](dev/hosting/beam/RUNBOOK.md) | Operational runbook for the hosted chat endpoint |
| [dev/Think-Log.md](dev/Think-Log.md) · [dev/LOG.md](dev/LOG.md) | Running research logs |
| [dev/LEADERBOARD.md](dev/LEADERBOARD.md) | Run comparison table |

Experiments are specified as immutable JSON in Git, their artifacts live on Hugging Face, and
telemetry goes to Weights & Biases. Experiment IDs are fingerprinted and cannot be reused.

## Repository layout

### `nanochat/` — the training library

The model and training core: `gpt.py` and `resformer_gpt.py` (architectures), `engine.py`,
`optim.py`, `dataloader.py` / `pretok_dataloader.py`, `mixture.py` (the midtrain ratio scheduler),
`tokenizer.py`, `fp8.py`, `flash_attention.py`, `checkpoint_manager.py`, plus evaluation
(`core_eval.py`, `loss_eval.py`), `prompt_shaping.py`, and reporting.

### `scripts/` — command-line entrypoints

One script per stage. `experiment.py` is the harness driver; `base_train.py`, `chat_sft.py` and
`chat_rl.py` cover the training stages; `tok_train.py` / `tok_eval.py` handle the tokenizer;
`pretok_think.py` pre-tokenizes shards. Evaluation and inspection live in `base_eval.py`,
`chat_eval.py`, `anachronism_eval.py` / `anachronism_probe.py`, the `ifeval_*` suite, and the
probe scripts. `chat_cli.py` / `chat_web.py` talk to a trained model.

### `configs/` — immutable run specifications

| Subfolder | Contents |
|---|---|
| `base/` | 34 pretraining and midtraining run configs, including `Think.Unbounded-d32.json` and its repair `Think.Unbounded-d32-v2mix-cont.json` |
| `sft/` | 24 fine-tuning recipes, including the `pre1930-curriculum-*` family |
| `ifeval/` | Instruction-following eval suite definitions |
| `priming_turns/`, `system_prompts/` | Conversational priming and system prompt for the pre-1930 companion persona |

### `runs/` — shell drivers

One script per named run, wiring a config to a machine — the `Think.Unbounded-d32*` runs, the
ablations, plus utility drivers (`speedrun.sh`, `scaling_laws.sh`, `miniseries.sh`).

### `tasks/` — evaluation and SFT task adapters

Standard benchmarks (`arc`, `mmlu`, `gsm8k`, `humaneval`, `smoltalk`, `spellingbee`) alongside the
project's own `authentic-pre1930.py`, `synth-pre1930.py`, and `customjson.py` loaders.

### `dev/` — research working material

| Subfolder | Contents |
|---|---|
| *(root)* | Research logs, the leaderboard, Colab notebooks for experiments/chat/tokenizer, scaling analysis, synthetic data generation |
| `dataset/` | Corpus pipeline documentation and the Institutional Books repackaging script |
| `figures/` | Figures for the write-up — token waterfall, docs-vs-tokens, removal composition, bpb curves |
| `hosting/` | Beam deployment: app, bf16 export, fast loading, chat UI, and an `ops/` toolkit for deploy, redeploy, cleanup, and GPU watching |
| `providers/` | Vast.ai container — Dockerfile and image build script |
| `archive/`, `vintage_core_colab/` | Superseded pipeline notebook; Vintage-CORE reference-model notebook |

### Root files

`EXPERIMENTS.md` (harness contract), `beam_app.py` (hosted deployment entrypoint),
`pyproject.toml` + `uv.lock` + `.python-version` (environment), and `LICENSE`.

### `.github/workflows/`, `.claude/`

CI builds the Vast.ai training image; `.claude/skills/` holds an agent skill for reading arXiv
papers.

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Unbounded Labs](https://unboundedlab.com).
