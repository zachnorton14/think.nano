"""Resumable per-event target BPB scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .bpb import aggregate_scores
from .config import BPB_SCORER_VERSION
from .io import append_jsonl, iter_jsonl, write_json
from .models import MODEL_SPECS, load_adapter


def _latest_scores(path: Path, model_id: str, revision: str) -> dict[str, dict]:
    latest = {}
    for record in iter_jsonl(path):
        if (
            record.get("model_id") == model_id
            and record.get("model_revision") == revision
            and record.get("scorer_version") == BPB_SCORER_VERSION
        ):
            latest[record["id"]] = record
    return latest


def score_events(
    *,
    model_id: str,
    events_path: Path,
    output_dir: Path,
    cache_dir: Path,
    device: str = "cuda",
    limit: int | None = None,
    adapter=None,
) -> dict:
    if model_id not in MODEL_SPECS:
        raise ValueError(f"unknown model: {model_id}")
    spec = MODEL_SPECS[model_id]
    events = list(iter_jsonl(events_path))
    if limit is not None:
        events = events[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    scores_path = output_dir / "events.jsonl"
    latest = _latest_scores(scores_path, model_id, spec["revision"])
    pending = [
        row for row in events
        if not (
            (cached := latest.get(row["id"]))
            and cached.get("status") == "ok"
            and cached.get("source_hash") == row["source_hash"]
        )
    ]
    if adapter is None and pending:
        adapter, provenance = load_adapter(model_id, cache_dir, device=device)
    else:
        provenance = {
            "model_id": model_id,
            "display_name": spec["display_name"],
            "repo_id": spec["repo_id"],
            "revision": spec["revision"],
            "checkpoint": spec.get("checkpoint"),
            "runtime_revision": (spec.get("runtime") or {}).get("revision"),
            "cutoff_year": spec["cutoff_year"],
            "dtype": "bfloat16",
            "quantization": None,
            "chat_template": False,
        }
    for row in pending:
        base = {
            "id": row["id"],
            "event_year": row["event_year"],
            "event_decade": row["event_decade"],
            "source_hash": row["source_hash"],
            "model_id": model_id,
            "model_revision": spec["revision"],
            "scorer_version": BPB_SCORER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            score = adapter.score(row["bpb_prefix"], row["bpb_target"])
            record = {**base, "status": "ok", **score}
        except Exception as exc:
            record = {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:2000]}
        append_jsonl(scores_path, record)

    latest = _latest_scores(scores_path, model_id, spec["revision"])
    selected = [latest[row["id"]] for row in events if row["id"] in latest]
    errors = [row for row in selected if row.get("status") == "error"]
    valid = [row for row in selected if row.get("status") == "ok"]
    summary = {
        "model": provenance,
        "scorer_version": BPB_SCORER_VERSION,
        "events_requested": len(events),
        "events_scored": len(valid),
        "unresolved_errors": len(errors),
        "complete": len(valid) == len(events) and not errors,
        "metrics": aggregate_scores(valid, spec["cutoff_year"]) if valid else None,
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "run-manifest.json", {
        **summary,
        "events_path": str(events_path.resolve()),
        "output_path": str(scores_path.resolve()),
    })
    return summary
