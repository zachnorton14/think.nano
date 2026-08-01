---
license: mit
language:
- en
task_categories:
- question-answering
pretty_name: Vintage GSM8K (Filtered)
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train.jsonl
  - split: test
    path: data/test.jsonl
---

# Vintage GSM8K (Filtered)

A filtered derivative of OpenAI GSM8K for models with knowledge through 1930. Rows requiring a post-cutoff contextual rewrite were removed; retained rows are otherwise unchanged apart from removal of official calculator annotations.

- Train rows: 6,600
- Test rows: 1,185
- Schema: `id`, `question`, `answer`
- Source: [OpenAI GSM8K](https://huggingface.co/datasets/openai/gsm8k), `main` configuration
- License: MIT

Filtering changes the official split sizes. Source order and stable IDs are preserved.

Solutions retain written reasoning and exactly one `#### final_answer`; `<<expression=result>>` calculator annotations are removed.
