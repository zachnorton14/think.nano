# Post-training Configs

Post-training configs identify both ancestors:

```json
{
  "stage": "posttrain",
  "experiment_id": "recipe-id",
  "parent": {
    "base_experiment_id": "base-id",
    "sft_experiment_id": "sft-id",
    "checkpoint_step": 1000
  }
}
```

`posttrain` is the umbrella stage. The current dispatcher uses `scripts.chat_rl`;
future methods can add their own recipe-specific command without changing the
artifact hierarchy.
