# Experiment Configs

Git stores immutable experiment specifications. Hugging Face stores runtime
configs, checkpoints, evaluations, and summaries. W&B stores telemetry.

## Stages

- `base/`: pretraining runs.
- `sft/`: supervised fine-tuning recipes with an exact base checkpoint parent.
- `posttrain/`: post-training recipes with exact base and SFT ancestors.

Future base IDs use `<dataset>-d<depth>-<epochs>ep-<shards>sh-r<ratio>`.
Completed historical IDs remain unchanged so their Hugging Face and W&B links
stay stable.

Artifact paths are derived by `scripts.experiment`:

```text
experiments/<base-id>/
  base_checkpoints/
  sft/<sft-id>/checkpoints/
  sft/<sft-id>/posttrain/<posttrain-id>/checkpoints/
```

An experiment ID is immutable. The harness fingerprints the full config and
refuses to reuse an existing local or remote ID with different settings.
