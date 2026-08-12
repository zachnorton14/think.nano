import json

import pytest

from dev.history_event.config import (
    GOLD_ANSWER_PROMPT_VERSION,
    GOLD_JUDGE_PROMPT_VERSION,
    PipelinePaths,
)
from dev.history_event.io import append_jsonl, read_json, write_json, write_jsonl
from dev.history_event.publication import package_dataset, validate_package


def full_event(index: int) -> dict:
    year = 1901 + index
    description = f"An event number {index}"
    return {
        "id": f"history-event-{index:06d}",
        "event_year": year,
        "event_decade": 1900,
        "event_description": description,
        "source_url": "https://en.wikipedia.org/w/index.php?title=Timeline&oldid=1",
        "source_revision": "1",
        "source_position": {"page": 0, "event": index, "line": index + 1, "list_depth": 1},
        "bpb_prefix": "What do you think about the following event:",
        "bpb_target": f"{description}. This took place in {year}.",
        "recall_question": f"Do you know about the following event: {description}?",
        "source_hash": f"hash-{index}",
    }


def seed_source(paths: PipelinePaths) -> list[dict]:
    rows = [full_event(0), full_event(1)]
    write_jsonl(paths.events, rows)
    write_jsonl(paths.recall_candidates, rows)
    write_json(paths.discrepancy_report, {
        "selected_profile": "event_bullets",
        "profiles": {"event_bullets": {"row_count": 2, "decade_l1_distance": 2342}},
    })
    write_json(paths.manifest, {
        "parsed_sha256": "abc",
        "selected_profile": "event_bullets",
        "sources": [{
            "title": "Timeline",
            "revision": "1",
            "revision_timestamp": "2026-05-01T00:00:00Z",
            "url": rows[0]["source_url"],
        }],
        "discrepancy": {
            "profiles": {"event_bullets": {"row_count": 2, "decade_l1_distance": 2342}}
        },
    })
    return rows


def audit_record(row: dict, stage: str, **extra) -> dict:
    return {
        "id": row["id"],
        "source_hash": row["source_hash"],
        "stage": stage,
        "status": "ok",
        "prompt_version": (
            GOLD_ANSWER_PROMPT_VERSION if stage == "answer" else GOLD_JUDGE_PROMPT_VERSION
        ),
        "model": "deepseek-v4-flash",
        "canonical_model_family": "deepseek-v4-flash",
        "endpoint": "https://opencode.ai/zen/go/v1/chat/completions",
        **extra,
    }


def test_package_refuses_incomplete_gold(tmp_path):
    paths = PipelinePaths(tmp_path)
    seed_source(paths)
    with pytest.raises(RuntimeError, match="gold pipeline is incomplete"):
        package_dataset(paths)


def test_package_generates_counts_license_and_loadable_hf_configs(tmp_path):
    paths = PipelinePaths(tmp_path)
    rows = seed_source(paths)
    for row in rows:
        append_jsonl(paths.answer_audit, audit_record(
            row, "answer", answer=f"It happened in {row['event_year']} with specific facts.",
            year_accepted=True,
        ))
        append_jsonl(paths.judge_audit, audit_record(
            row, "judge", accepted=row["id"].endswith("0"), reason="checked",
        ))
    manifest = package_dataset(paths)
    assert manifest["counts"] == {
        "events": 2, "recall_candidates": 2, "recall_deepseek_v1": 1
    }
    assert read_json(paths.package_manifest)["counts"] == manifest["counts"]
    readme = (paths.package_dir / "README.md").read_text(encoding="utf-8")
    assert "| `events` | 2 |" in readme
    assert "deepseek-v4-flash" in readme
    assert "independent" in readme.lower()
    assert "CC BY-SA 4.0" in (paths.package_dir / "LICENSE").read_text(encoding="utf-8")
    validated = validate_package(paths.package_dir)
    assert validated["valid"] is True
    assert validated["counts"] == manifest["counts"]
