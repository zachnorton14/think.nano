# Experiment Harness

This repository uses one configuration-driven harness for base pretraining,
supervised fine-tuning (SFT), and post-training:

```text
base -> zero or more SFT runs -> zero or more post-training runs per SFT
```

A base run can also branch off another base run, continuing from its weights and
optimizer state with different data and hyperparameters. See
[Branching A Base Run](#branching-a-base-run).

Git stores immutable experiment specifications, Hugging Face stores durable
artifacts, and Weights & Biases stores telemetry and comparisons.

## Repository Structure

```text
configs/
  base/
    <base-experiment-id>.json
  sft/
    <sft-experiment-id>.json
  posttrain/
    <posttrain-experiment-id>.json

dev/
  colab_nanochat_experiment.ipynb
  dataset/
    DATASET_PIPELINE.md
    FILTER_AUDIT.md
    repackage_institutional_books.py
  archive/
    colab_nanochat_pipeline.ipynb

scripts/
  experiment.py
  migrate_hf_experiments.py
```

The `posttrain/` config directory is created when the first post-training
recipe is added; Git does not retain empty directories.

## Artifact Structure

The harness derives local and Hugging Face paths from stage and lineage:

```text
experiments/<base-id>/
  config.json
  run.json
  summary.json
  tokenizer/
  base_checkpoints/
  evals/
  sft/<sft-id>/
    config.json
    run.json
    summary.json
    checkpoints/
    evals/
    posttrain/<posttrain-id>/
      config.json
      run.json
      summary.json
      checkpoints/
      evals/
```

Do not put artifact paths in configs. `scripts.experiment` derives them from
`stage`, `experiment_id`, and `parent`.

## Config Contracts

Every config has:

```json
{
  "schema_version": 1,
  "stage": "base",
  "experiment_id": "think-d12-r11.25",
  "artifacts": {
    "repo": "jbduran/bart-experiments"
  },
  "wandb": {
    "project": "think.nano"
  }
}
```

Base configs also define `dataset`, `tokenizer`, `pretokenize`, and `training`.

SFT configs identify one exact base checkpoint:

```json
{
  "stage": "sft",
  "experiment_id": "smoltalk-mmlu3-gsm8k4-v1",
  "parent": {
    "base_experiment_id": "think-d12-r11.25",
    "checkpoint_step": 2362
  }
}
```

Post-training configs identify the base, SFT recipe, and exact SFT checkpoint:

```json
{
  "stage": "posttrain",
  "experiment_id": "gsm8k-grpo-v1",
  "parent": {
    "base_experiment_id": "think-d12-r11.25",
    "sft_experiment_id": "smoltalk-mmlu3-gsm8k4-v1",
    "checkpoint_step": 1065
  }
}
```

Experiment IDs are immutable. The harness fingerprints the complete config and
refuses to reuse an existing local or remote ID with changed settings.

## Branching A Base Run

A base config with a `branch` block starts from another base run's checkpoint
instead of from random initialization, then trains on its own data with its own
hyperparameters:

```json
{
  "stage": "base",
  "experiment_id": "clean1930s-d12-r12-branch-test",
  "branch": {
    "parent_experiment_id": "1930s-d12-r12-4096ctx-run2",
    "parent_step": 2000,
    "lr_schedule": "continue",
    "load_optimizer": true
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `parent_experiment_id` | required | Base run to resume from. Its config must be in `configs/base/`. |
| `parent_step` | latest complete parent checkpoint | Exact branch point. Auto-detected steps are pinned in `run.json` so a resumed run never silently moves. |
| `lr_schedule` | `"branch"` | `branch` runs a fresh warmup/warmdown across this run's own span and starts its data at the beginning; `continue` picks up the parent's global schedule, data position, and mixture stage where it stopped. |
| `load_optimizer` | `true` | Inherit the parent's optimizer moments. `false` starts with fresh optimizer state. |

`--branch-step` (or `NANOCHAT_BRANCH_STEP`) overrides `parent_step` at the
command line.

What a branch inherits and what it may change:

- Inherited: weights, optimizer state, tokenizer, and the parent's cumulative
  pipeline FLOPs. The model shape (`depth`, `aspect_ratio`, `head_dim`) and the
  vocabulary must match the parent; the harness refuses the run otherwise, before
  any download or GPU work.
- Free to change: dataset or mixture schedule, training horizon, learning rates,
  weight decay, batch sizes, `max_seq_len`, `window_pattern`, FP8, seed, eval
  cadence.
- Omit the `tokenizer` block and the branch reuses the parent's. A block that
  names a different tokenizer, or asks to train one, is rejected: the parent's
  embedding and `lm_head` rows are tied to its vocabulary.

The two `lr_schedule` modes differ in more than the learning rate:

| | `"branch"` (default) | `"continue"` |
|---|---|---|
| Horizon | the config's horizon is this run's own span, appended after the branch step | the config's horizon is the whole schedule, of which the parent already ran part |
| LR, momentum, weight decay | fresh warmup and warmdown over this run's span | resume the parent's position in its schedule |
| Data position | starts at the beginning of this run's token cache | continues the parent's file positions and epoch counts |
| Mixture stage | restarts at stage 0, relative to this run's first step | resumes the stage the parent was in |

Use `branch` for a new training phase on new data, and `continue` to finish a run
under changed settings. A `continue` branch off a mixture run must use `continue`
to stay in the parent's stage; a fresh mixture would replay stage 0 and never
reach the stages the parent had already entered.

A branch is a normal top-level base experiment: its own `experiment_id`,
`experiments/<id>/` artifact tree, W&B run, data, token cache, and evals. Only the
parent's checkpoint is read, from the parent's own directory.

Step numbering continues from the parent, so a branch off step 2362 that trains
500 steps writes `model_002862.pt` last and plots from 2362 on the W&B x-axis.
`stage_training_flops` and `stage_training_tokens` count only what the branch
itself trained; `inherited_parent_flops` carries the rest, and
`cumulative_pipeline_training_flops` is the sum.

`prepare`, `train`, `eval`, and `all` take a branch config unchanged. `plan`
prints the parent beside the new run and marks every value the branch changes:

```bash
python -m scripts.experiment plan \
  --config configs/base/clean1930s-d12-r12-branch-test.json
```

The notebook's "Validate The Prepared Base Run" cell prints the same table. For a
mixture config the planner also reports which stage the branch point falls in.

`configs/base/clean1930s-d12-r12-branch-test.json` is the reference branch: it
picks `1930s-d12-r12-4096ctx-run2` back up at step 2000 and runs its remaining 520
steps with the same data, mixture, and hyperparameters, so its curve should join
the parent's. Every other run's branch config should differ from its parent in
something.

If a branch has already saved its own checkpoints, it resumes those; the parent
is then only lineage metadata. `--fresh` re-branches from the parent.

Future base IDs use:

```text
<dataset>-d<depth>-<epochs>ep-<shards>sh-r<ratio>
```

Existing completed IDs remain unchanged to preserve artifact and W&B links.

## Getting Started

Set the required credentials:

```bash
export HF_TOKEN=...
export WANDB_API_KEY=...
export WANDB_ENTITY=jbduran-thinkingmachinesncsu
export WANDB_PROJECT=think.nano
```

Prepare a base experiment:

```bash
python -m scripts.experiment prepare \
  --config configs/base/think-d12-r20.json
```

Train or resume from the latest complete Hugging Face checkpoint:

```bash
python -m scripts.experiment train \
  --config configs/base/think-d12-r20.json
```

Evaluate and sync runtime artifacts:

```bash
python -m scripts.experiment eval \
  --config configs/base/think-d12-r20.json
```

The same commands accept SFT and post-training configs. `prepare` downloads
and validates the exact parent checkpoint and base tokenizer for downstream
stages.

Use `--fresh` only for a deliberate restart. If complete remote checkpoints
exist, the harness requires `--confirm-fresh` before replacing the run state.

For Colab, edit only `CONFIG_PATH` in
`dev/colab_nanochat_experiment.ipynb`.

## Checkpoints And Resume

A checkpoint is complete only when it contains:

```text
model_<step>.pt
meta_<step>.json
optim_<step>_rank*.pt
```

The watcher uploads only complete, stable checkpoints. Base, SFT, and
post-training all preserve optimizer state. The exact parent step is validated
before downstream training begins.

Optimizer state is sharded per rank, so branching or resuming with
`--nproc-per-node=N` requires shards for ranks `0..N-1` at that step.

`run.json` stores the stable W&B run ID. Resuming training reuses that ID rather
than creating a second telemetry run.

## FLOPs Accounting

The harness records:

- `stage_training_flops`
- `inherited_parent_flops`
- `cumulative_pipeline_training_flops`

Base and SFT use the model's forward-plus-backward FLOPs estimate multiplied by
processed training tokens. Post-training adds optimization FLOPs and rollout
generation FLOPs. Rollout generation uses a forward-only estimate of one third
of training FLOPs per model-token invocation.

Evaluation, tokenizer training, and dataset preparation are excluded.

The `think.nano` W&B workspace compares CORE, ChatCORE, validation BPB, reward,
and pass@k against cumulative training FLOPs and includes stage efficiency and
lineage views.

## Why Core Nanochat Files Changed

The experiment harness cannot remain entirely outside the upstream training
scripts because upstream nanochat assumes one global tokenizer and one global
checkpoint directory.

| File | Required reason |
|---|---|
| `nanochat/tokenizer.py` | Load the tokenizer belonging to a specific base lineage instead of the global cache. |
| `scripts/tok_train.py` | Train from an experiment's dataset directory and write to its tokenizer directory. |
| `scripts/base_train.py` | Accept isolated data/tokenizer/checkpoint paths, use the pretokenized cache, preserve stable W&B identity, record lineage metrics, and start from a parent run's weights and optimizer state when branching. |
| `scripts/base_eval.py` | Evaluate an exact checkpoint and tokenizer, support pretokenized BPB, and emit structured results for `summary.json`. |
| `scripts/chat_eval.py` | Evaluate exact SFT/post-training checkpoint directories and emit structured ChatCORE results. |
| `scripts/chat_sft.py` | Load an exact base parent, save periodic optimizer-complete SFT checkpoints, resume, and record cumulative FLOPs. |
| `scripts/chat_rl.py` | Load an exact SFT parent, save optimizer-complete post-training checkpoints, resume, and account for optimization plus rollout FLOPs. |

These changes preserve the legacy CLI paths when explicit experiment
directories are not supplied.

## Validation

Before merging:

```bash
git diff --check
pytest -q
python -m scripts.experiment --help
python -m scripts.base_train --help
python -m scripts.chat_sft --help
python -m scripts.chat_rl --help
```

Also load every config and notebook as JSON. GPU training and resume should
receive a short Colab smoke test because local unit tests cannot validate CUDA,
distributed optimizer shards, or real W&B/Hugging Face transfers.
