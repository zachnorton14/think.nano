# Nanochat experiments

Run a complete experiment:

```bash
python -m scripts.experiment all --config experiments/think-d12-r20.json
```

Run phases independently:

```bash
python -m scripts.experiment prepare --config experiments/think-d12-r20.json
python -m scripts.experiment train --config experiments/think-d12-r20.json
python -m scripts.experiment eval --config experiments/think-d12-r20.json
python -m scripts.experiment report
```

Each experiment gets isolated data, tokenizer, token cache, checkpoints, and
evaluation results under `$NANOCHAT_BASE_DIR/experiments/<experiment-id>`.
Native validation BPB should only be compared between runs that use the same
dataset and validation policy. Use CORE for cross-dataset comparisons.

To test another Hugging Face dataset, copy `hf-stream-template.json` and change
the dataset repository, split, and text column. No source edit is required.
