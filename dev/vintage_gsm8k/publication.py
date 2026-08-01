"""Stage and publish the filtered and rewritten Vintage GSM8K datasets."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import CUTOFF_YEAR, EXPECTED_COUNTS, PipelinePaths
from .data import atomic_write_json, atomic_write_jsonl, read_jsonl, stable_hash
from .pipeline import _current_judges, _load_complete_decisions, _require_full_judge


MIT_LICENSE = """MIT License

Copyright (c) 2026 Jonathan Duran-Ortiz and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _dataset_card(kind: str, counts: dict[str, int]) -> str:
    if kind == "filtered":
        title = "Vintage GSM8K (Filtered)"
        summary = (
            f"A filtered derivative of OpenAI GSM8K for models with knowledge through {CUTOFF_YEAR}. "
            "Rows requiring a post-cutoff contextual rewrite were removed; retained rows are otherwise "
            "unchanged apart from removal of official calculator annotations."
        )
        note = "Filtering changes the official split sizes. Source order and stable IDs are preserved."
    elif kind == "rewritten":
        title = "Vintage GSM8K"
        summary = (
            f"A full-size derivative of OpenAI GSM8K for models with knowledge through {CUTOFF_YEAR}. "
            "Post-cutoff context was minimally rewritten while complete reasoning, calculations, and final answers were preserved."
        )
        note = "The official 7,473/1,319 train/test sizes, order, and stable IDs are preserved."
    else:
        raise ValueError(f"unknown publication kind: {kind}")
    return f"""---
license: mit
language:
- en
task_categories:
- question-answering
pretty_name: {title}
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train.jsonl
  - split: test
    path: data/test.jsonl
---

# {title}

{summary}

- Train rows: {counts['train']:,}
- Test rows: {counts['test']:,}
- Schema: `id`, `question`, `answer`
- Source: [OpenAI GSM8K](https://huggingface.co/datasets/openai/gsm8k), `main` configuration
- License: MIT

{note}

Solutions retain written reasoning and exactly one `#### final_answer`; `<<expression=result>>` calculator annotations are removed.
"""


def _write_distribution(directory: Path, kind: str, rows: dict[str, list[dict]]) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    for split in ("train", "test"):
        atomic_write_jsonl(directory / "data" / f"{split}.jsonl", rows[split])
    counts = {split: len(rows[split]) for split in ("train", "test")}
    (directory / "README.md").write_text(_dataset_card(kind, counts), encoding="utf-8")
    (directory / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "cutoff_year": CUTOFF_YEAR,
        "counts": counts,
        "files": {
            split: {
                "path": f"data/{split}.jsonl",
                "sha256": stable_hash(rows[split]),
            }
            for split in ("train", "test")
        },
    }
    atomic_write_json(directory / "manifest.json", manifest)
    return manifest


def stage_publications(paths: PipelinePaths) -> dict:
    """Build upload-ready filtered and rewritten dataset directories."""
    judges = _current_judges(paths)
    _require_full_judge(paths, judges)
    decisions = _load_complete_decisions(paths, judges)

    filtered: dict[str, list[dict]] = {"train": [], "test": []}
    for split in ("train", "test"):
        for source in read_jsonl(paths.source(split)):
            decision = decisions.get(source["id"])
            if judges[source["id"]]["action"] == "keep" or (
                decision and decision.get("decision") == "keep"
            ):
                filtered[split].append(
                    {key: source[key] for key in ("id", "question", "answer")}
                )

    rewritten: dict[str, list[dict]] = {}
    for split, expected in EXPECTED_COUNTS.items():
        rows = read_jsonl(paths.packaged(split))
        if len(rows) != expected:
            raise RuntimeError(
                f"Packaged rewritten {split} is incomplete: {len(rows)}/{expected}; run verify and package first"
            )
        rewritten[split] = rows

    root = paths.root / "publish"
    manifests = {
        "filtered": _write_distribution(root / "filtered", "filtered", filtered),
        "rewritten": _write_distribution(root / "rewritten", "rewritten", rewritten),
    }
    atomic_write_json(root / "manifest.json", manifests)
    return {"root": str(root), **manifests}


def publish_publications(
    paths: PipelinePaths,
    *,
    namespace: str | None = None,
    filtered_name: str = "vintage-gsm8k-filtered",
    rewritten_name: str = "vintage-gsm8k",
) -> dict:
    """Create/update two public Hugging Face dataset repositories."""
    staged = stage_publications(paths)
    try:
        from dotenv import load_dotenv
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise RuntimeError("Publishing requires python-dotenv and huggingface-hub") from exc
    load_dotenv()
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN is missing from .env")
    api = HfApi(token=token)
    if not namespace:
        identity = api.whoami()
        namespace = identity.get("name") or identity.get("fullname")
    if not namespace:
        raise RuntimeError("Could not resolve the Hugging Face namespace")

    repo_names = {"filtered": filtered_name, "rewritten": rewritten_name}
    repos = {}
    for kind, name in repo_names.items():
        repo_id = f"{namespace}/{name}"
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
        api.update_repo_settings(repo_id=repo_id, repo_type="dataset", private=False)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="dataset",
            folder_path=str(paths.root / "publish" / kind),
            commit_message=f"Publish {kind} Vintage GSM8K dataset",
        )
        repos[kind] = {
            "repo_id": repo_id,
            "url": f"https://huggingface.co/datasets/{repo_id}",
        }
    return {"staged": staged, "repos": repos}
