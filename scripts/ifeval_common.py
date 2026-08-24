"""Shared, resumable JSONL helpers for IFEval runs."""

import json
import os
from pathlib import Path


def read_inputs(path, expected_rows=None):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    if not rows:
        raise ValueError("IFEval input must contain at least one row")
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError(
            f"IFEval input must contain exactly {expected_rows} rows, found {len(rows)}"
        )
    keys = [int(row["key"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("IFEval input keys are not unique")
    prompts = [row["prompt"] for row in rows]
    if len(set(prompts)) != len(prompts):
        raise ValueError("IFEval input prompts are not unique")
    return rows


def read_completed(path, model_id):
    destination = Path(path)
    completed = {}
    if not destination.exists():
        return completed
    for line_number, line in enumerate(destination.read_text().splitlines(), 1):
        if not line:
            continue
        row = json.loads(line)
        if row.get("model_id") != model_id:
            raise ValueError(
                f"{destination}:{line_number} belongs to {row.get('model_id')!r}, "
                f"not {model_id!r}"
            )
        key = int(row["key"])
        if key in completed:
            raise ValueError(f"Duplicate completed IFEval key {key} in {destination}")
        completed[key] = row
    return completed


def append_result(path, result):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def merge_shards(input_path, shard_paths, output_path, model_id):
    inputs = read_inputs(input_path)
    expected = {int(row["key"]): row["prompt"] for row in inputs}
    merged = {}
    for shard in shard_paths:
        for key, row in read_completed(shard, model_id).items():
            if key in merged:
                raise ValueError(f"IFEval key {key} appears in more than one shard")
            if expected.get(key) != row.get("prompt"):
                raise ValueError(f"Prompt mismatch for IFEval key {key}")
            merged[key] = row
    missing = sorted(set(expected) - set(merged))
    extra = sorted(set(merged) - set(expected))
    if missing or extra:
        raise ValueError(f"Incomplete IFEval merge: missing={missing}, extra={extra}")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for source in inputs:
            handle.write(json.dumps(merged[int(source["key"])], ensure_ascii=False) + "\n")
    os.replace(temporary, destination)
    return destination
