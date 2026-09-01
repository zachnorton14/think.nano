"""Build, validate, and publish the three-config Hugging Face dataset."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    DEFAULT_DATASET_REPO,
    GOLD_ANSWER_PROMPT_VERSION,
    GOLD_JUDGE_PROMPT_VERSION,
    NORMALIZATION_VERSION,
    PAPER_EVENT_COUNT,
    PAPER_GOLD_COUNT,
    PAPER_RECALL_CANDIDATE_COUNT,
    PARSER_VERSION,
    PipelinePaths,
)
from .gold import generate_gold_report, gold_status
from .io import iter_jsonl, read_json, sha256_bytes, write_json, write_jsonl


CONFIG_FILES = {
    "events": "events/test.jsonl",
    "recall_candidates": "recall_candidates/test.jsonl",
    "recall_deepseek_v1": "recall_deepseek_v1/test.jsonl",
}
CORE_FIELDS = {
    "id", "event_year", "event_decade", "event_description", "source_url",
    "source_revision", "source_position", "bpb_prefix", "bpb_target", "recall_question",
}


CC_BY_SA_NOTICE = """HISTORY-EVENT Reconstruction dataset license

The event descriptions and source-derived metadata in this dataset are adapted
from English Wikipedia and are licensed under the Creative Commons
Attribution-ShareAlike 4.0 International license (CC BY-SA 4.0):
https://creativecommons.org/licenses/by-sa/4.0/

Attribution is provided per row by `source_url` and `source_revision`, and in
the dataset card's revision-pinned source table. Share adaptations under the
same or a compatible license and indicate changes. Wikipedia contributors are
the authors of the underlying text.

The reconstruction, filtering, validation, scoring, and packaging code in the
think.nano repository remains licensed under that repository's MIT License.
"""


def _card(source_manifest: dict, package_manifest: dict) -> str:
    counts = package_manifest["counts"]
    source_rows = "\n".join(
        f"| {source['title']} | `{source['revision']}` | {source['revision_timestamp'] or 'recorded in source manifest'} | [revision]({source['url']}) |"
        for source in source_manifest["sources"]
    )
    discrepancy = source_manifest["discrepancy"]["profiles"][source_manifest["selected_profile"]]
    return f"""---
license: cc-by-sa-4.0
language:
- en
task_categories:
- text-generation
pretty_name: HISTORY-EVENT Reconstruction
configs:
- config_name: events
  data_files:
  - split: test
    path: events/test.jsonl
- config_name: recall_candidates
  data_files:
  - split: test
    path: recall_candidates/test.jsonl
- config_name: recall_deepseek_v1
  data_files:
  - split: test
    path: recall_deepseek_v1/test.jsonl
---

# HISTORY-EVENT Reconstruction

An independent, reproducible reconstruction of the HISTORY-EVENT benchmark described in [*The Past is a Foreign Country: Era-Specific Language Models*](https://arxiv.org/abs/2606.02991). This is **not** the authors' official dataset. Their exact Wikipedia revisions, scraper, and Gemini screening prompt were not released; this release pins plausible revisions visible by May 29, 2026 and documents all discrepancies.

## Configurations

| Configuration | Rows | Purpose |
|---|---:|---|
| `events` | {counts['events']:,} | All reconstructed events for BPB surprisingness |
| `recall_candidates` | {counts['recall_candidates']:,} | Descriptions without a standalone four-digit numeral |
| `recall_deepseek_v1` | {counts['recall_deepseek_v1']:,} | DeepSeek answers passing strict year and factual validation |

The paper reports {PAPER_EVENT_COUNT:,}, {PAPER_RECALL_CANDIDATE_COUNT:,}, and {PAPER_GOLD_COUNT:,} rows at the corresponding stages. This reconstruction differs by {counts['events'] - PAPER_EVENT_COUNT:+,}, {counts['recall_candidates'] - PAPER_RECALL_CANDIDATE_COUNT:+,}, and {counts['recall_deepseek_v1'] - PAPER_GOLD_COUNT:+,}. These counts are generated from `manifest.json`, never typed into the package independently.

## Methodology

The pipeline fetches four revision-pinned English Wikipedia century timelines, processes only chronological sections, takes years from 18th-century bullet prefixes (including first years of ranges) and from year headings on the other pages, removes citation/markup and leading month/day labels, and preserves source order. It compares documented parsing profiles to the paper's Figure 4 decade vector and chooses the minimum L1-distance profile. It does not add, delete, or select individual rows to force agreement.

Selected parser profile: `{source_manifest['selected_profile']}` (`{PARSER_VERSION}`, normalization `{NORMALIZATION_VERSION}`). It yields {discrepancy['row_count']:,} events and Figure 4 decade L1 distance {discrepancy['decade_l1_distance']}. See `audit/discrepancy.json` for every per-decade difference.

Recall candidates apply the paper-style regex `(?<!\\d)\\d{{4}}(?!\\d)` to `event_description`. Rejected rows and matching numerals remain in the local pipeline audit.

## DeepSeek reference pipeline

`recall_deepseek_v1` was made with `deepseek-v4-flash` through OpenCode Go's OpenAI-compatible chat endpoint. The model receives the paper's recall question without the gold year. An answer must explicitly state the exact four-digit `event_year` and no conflicting year. A separate DeepSeek call then accepts only correct, specific information beyond the supplied description. Errors are fail-closed and resumable; batches are retried, bisected, and reduced to individual rows. Exact model aliases, endpoint, prompt versions (`{GOLD_ANSWER_PROMPT_VERSION}`, `{GOLD_JUDGE_PROMPT_VERSION}`), usage, cost, and latency are retained in local append-only audits. Replacing the paper's Gemini-3.1-Flash-Lite process means this subset is not expected to contain 1,726 rows.

## Fields

Every configuration includes `id`, `event_year`, `event_decade`, `event_description`, `source_url`, `source_revision`, `source_position`, `bpb_prefix`, `bpb_target`, and `recall_question`. The DeepSeek configuration adds `gold_answer` and `validation`. `source_hash` supports audit and cache integrity.

For BPB, concatenate `bpb_prefix`, one ASCII space, and `bpb_target`; condition on the prefix and score only the semantic target bytes. Do not apply a chat template.

## Sources and attribution

Access basis: revision snapshots visible by May 29, 2026.

| Page | Revision | Revision timestamp | Source |
|---|---:|---|---|
{source_rows}

Wikipedia-derived text is CC BY-SA 4.0. Per-row revision links provide attribution and make the exact source recoverable. Pipeline code is MIT licensed. See `LICENSE` and `audit/source-manifest.json`.

## Reproduction

```bash
uv sync --group dev
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event prepare
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event gold --probe
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event gold --batch-size 8 --workers 64
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event report
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event package
```

Use `runs/history-event-vast.sh` for the revision-pinned BPB evaluation.
"""


def _dataset_rows(path: Path) -> list[dict]:
    return list(iter_jsonl(path))


def package_dataset(paths: PipelinePaths) -> dict:
    if not paths.manifest.exists():
        raise RuntimeError("source manifest is missing; run `prepare` first")
    status = gold_status(paths)
    if not status["complete"]:
        raise RuntimeError(f"gold pipeline is incomplete or has errors: {status}")
    generate_gold_report(paths)
    source_manifest = read_json(paths.manifest)
    rows = {
        "events": _dataset_rows(paths.events),
        "recall_candidates": _dataset_rows(paths.recall_candidates),
        "recall_deepseek_v1": _dataset_rows(paths.gold_rows),
    }
    for name, config_rows in rows.items():
        for row in config_rows:
            missing = CORE_FIELDS - row.keys()
            if missing:
                raise RuntimeError(f"{name}/{row.get('id')} is missing fields: {sorted(missing)}")
        if len({row["id"] for row in config_rows}) != len(config_rows):
            raise RuntimeError(f"{name} contains duplicate ids")
    package_root = paths.package_dir
    for name, relative in CONFIG_FILES.items():
        write_jsonl(package_root / relative, rows[name])
    audit_dir = package_root / "audit"
    write_json(audit_dir / "source-manifest.json", source_manifest)
    write_json(audit_dir / "discrepancy.json", read_json(paths.discrepancy_report))
    write_json(audit_dir / "gold-report.json", status)
    (package_root / "LICENSE").parent.mkdir(parents=True, exist_ok=True)
    (package_root / "LICENSE").write_text(CC_BY_SA_NOTICE, encoding="utf-8")
    manifest = {
        "kind": "independent_history_event_reconstruction",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "license": "CC-BY-SA-4.0",
        "code_license": "MIT",
        "counts": {name: len(config_rows) for name, config_rows in rows.items()},
        "configs": CONFIG_FILES,
        "source_parsed_sha256": source_manifest["parsed_sha256"],
        "parser_version": PARSER_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "gold_answer_prompt_version": GOLD_ANSWER_PROMPT_VERSION,
        "gold_judge_prompt_version": GOLD_JUDGE_PROMPT_VERSION,
    }
    manifest["file_sha256"] = {
        relative: sha256_bytes((package_root / relative).read_bytes())
        for relative in CONFIG_FILES.values()
    }
    write_json(paths.package_manifest, manifest)
    (package_root / "README.md").write_text(_card(source_manifest, manifest), encoding="utf-8")
    validate_package(package_root)
    return manifest


def validate_package(package_root: Path, *, load_datasets: bool = True) -> dict:
    try:
        from huggingface_hub import DatasetCard
    except ImportError as exc:  # pragma: no cover - dependency error
        raise RuntimeError("huggingface_hub is required") from exc
    card = DatasetCard.load(str(package_root / "README.md"))
    card_data = card.data.to_dict()
    configs = {entry["config_name"]: entry for entry in card_data.get("configs", [])}
    if set(configs) != set(CONFIG_FILES):
        raise RuntimeError(f"README config mismatch: {sorted(configs)}")
    manifest = read_json(package_root / "manifest.json")
    observed = {}
    for name, relative in CONFIG_FILES.items():
        path = package_root / relative
        config_path = configs[name]["data_files"][0]["path"]
        if config_path != relative:
            raise RuntimeError(f"README path mismatch for {name}: {config_path}")
        config_rows = list(iter_jsonl(path))
        observed[name] = len(config_rows)
        if observed[name] != manifest["counts"][name]:
            raise RuntimeError(f"manifest count mismatch for {name}")
        if load_datasets:
            from datasets import load_dataset
            loaded = load_dataset("json", data_files={"test": str(path)}, split="test")
            if len(loaded) != observed[name]:
                raise RuntimeError(f"datasets load count mismatch for {name}")
    return {"valid": True, "counts": observed, "license": card_data.get("license")}


def publish_dataset(
    paths: PipelinePaths,
    *,
    repo_id: str = DEFAULT_DATASET_REPO,
    private: bool = False,
) -> dict:
    validate_package(paths.package_dir)
    try:
        from dotenv import load_dotenv
        from huggingface_hub import HfApi
    except ImportError as exc:  # pragma: no cover - dependency error
        raise RuntimeError("python-dotenv and huggingface_hub are required") from exc
    load_dotenv()
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    result = api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(paths.package_dir),
        commit_message="Publish independent HISTORY-EVENT reconstruction",
    )
    return {"repo_id": repo_id, "private": private, "url": str(result)}
