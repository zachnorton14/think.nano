"""
Synthetic pre-1930 SFT dataset, one Task per route.
https://huggingface.co/datasets/zachnorton03/synthetic-pre1930-sft

The dataset is organized into ten task "routes", each its own folder of part-*.jsonl
shards. Each route is exposed here as a Pre1930Route(route=...) Task, so the SFT recipe
can schedule per-route epochs (mirroring the mmlu_epochs / gsm8k_epochs pattern).

Row shapes (see the dataset card):
  - single-turn routes: {"question": ..., "answer": ...}
  - multiturn_qa:       {"conversations": [{"role","content"}, ...]}
Both are normalized to the nanochat {"messages": [...]} conversation format.

The route folders are read directly from the Hub (huggingface_hub), not via
datasets.load_dataset, to sidestep Hub feature-inference. Set HF_TOKEN in the training
environment (the repo is not readable anonymously here).
"""

import json
import random
from functools import lru_cache

from huggingface_hub import HfApi, hf_hub_download
from tasks.common import Task

DATASET = "zachnorton03/synthetic-pre1930-sft"

# The ten route subsets (folder names in the dataset repo).
ROUTES = (
    "knowledge_qa",
    "multiturn_qa",
    "reasoning_qa",
    "stem_reasoning",
    "narrative_grounded",
    "narrative_fiction",
    "opinion_qa",
    "how_to_qa",
    "verse_qa",
    "composition_qa",
)


@lru_cache(maxsize=None)
def _load_rows(route):
    """Download + parse every part-*.jsonl shard of a route, shuffled once (seed 42).
    Cached per route so the N per-epoch Task copies share a single parse."""
    api = HfApi()
    shards = sorted(f for f in api.list_repo_files(DATASET, repo_type="dataset")
                    if f.startswith(f"{route}/") and f.endswith(".jsonl"))
    rows = []
    for f in shards:
        path = hf_hub_download(DATASET, f, repo_type="dataset")
        with open(path, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    random.Random(42).shuffle(rows)
    return rows


class Pre1930Route(Task):
    """ One route of the synthetic pre-1930 SFT dataset as a conversation Task. """

    def __init__(self, route, split="train", val_size=256, **kwargs):
        super().__init__(**kwargs)
        assert route in ROUTES, f"unknown route {route!r}; choose from {ROUTES}"
        self.route = route
        rows = _load_rows(route)
        val_size = min(val_size, len(rows) // 2)
        self.rows = rows[val_size:] if split == "train" else rows[:val_size]

    def num_examples(self):
        return len(self.rows)

    def get_example(self, index):
        row = self.rows[index]
        convs = row.get("conversations")
        if convs:                                     # multiturn_qa
            messages = [{"role": m["role"], "content": m["content"]} for m in convs]
        else:                                         # single-turn Q/A
            messages = [
                {"role": "user", "content": row["question"]},
                {"role": "assistant", "content": row["answer"]},
            ]
        assert len(messages) >= 2 and messages[0]["role"] == "user"
        for i, m in enumerate(messages):
            expected = "user" if i % 2 == 0 else "assistant"
            assert m["role"] == expected and isinstance(m["content"], str)
        return {"messages": messages}
