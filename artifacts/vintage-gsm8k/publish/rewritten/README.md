---
license: mit
language:
- en
task_categories:
- question-answering
pretty_name: Vintage GSM8K
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train.jsonl
  - split: test
    path: data/test.jsonl
---

# Vintage GSM8K

A full-size derivative of OpenAI GSM8K for models with knowledge through 1930. Post-cutoff context was minimally rewritten while complete reasoning, calculations, and final answers were preserved.

- Train rows: 7,473
- Test rows: 1,319
- Schema: `id`, `question`, `answer`
- Source: [OpenAI GSM8K](https://huggingface.co/datasets/openai/gsm8k), `main` configuration
- License: MIT

The official 7,473/1,319 train/test sizes, order, and stable IDs are preserved.

Solutions retain written reasoning and exactly one `#### final_answer`; `<<expression=result>>` calculator annotations are removed.
