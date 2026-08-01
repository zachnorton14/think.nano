"""Validate and apply an independent review proposal to the canonical decision gate."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .config import REWRITE_PROMPT_VERSION, PipelinePaths
from .data import (
    append_jsonl,
    atomic_write_jsonl,
    read_jsonl,
    read_latest_by_id,
    stable_hash,
    validate_candidate,
)


VALID_PROPOSALS = {"keep", "rewrite", "manual"}
SPLITS = ("train", "test")


def apply_subagent_review(
    paths: PipelinePaths,
    proposal_path: Path | None = None,
    override_path: Path | None = None,
) -> dict:
    proposal_path = proposal_path or (paths.review_dir / "subagent-review.jsonl")
    override_path = override_path or (paths.review_dir / "reviewer-overrides.jsonl")
    decisions = read_jsonl(paths.decisions)
    proposals = read_jsonl(proposal_path)
    overrides = read_jsonl(override_path)

    decision_ids = [row.get("id") for row in decisions]
    proposal_ids = [row.get("id") for row in proposals]
    duplicate_ids = sorted(
        row_id for row_id, count in Counter(proposal_ids).items() if row_id and count > 1
    )
    missing = sorted(set(decision_ids) - set(proposal_ids))
    extra = sorted(set(proposal_ids) - set(decision_ids))
    invalid = sorted(
        row.get("id", "<missing-id>")
        for row in proposals
        if row.get("proposed_decision") not in VALID_PROPOSALS
        or not isinstance(row.get("reason"), str)
        or not row.get("reason", "").strip()
    )
    if duplicate_ids or missing or extra or invalid or len(proposals) != len(decisions):
        raise RuntimeError(
            "Invalid subagent review: "
            f"duplicates={len(duplicate_ids)}, missing={len(missing)}, "
            f"extra={len(extra)}, invalid={len(invalid)}, "
            f"rows={len(proposals)}/{len(decisions)}"
        )

    by_id = {row["id"]: row for row in proposals}
    override_ids = [row.get("id") for row in overrides]
    duplicate_overrides = sorted(
        row_id for row_id, count in Counter(override_ids).items() if row_id and count > 1
    )
    invalid_overrides = sorted(
        row.get("id", "<missing-id>")
        for row in overrides
        if row.get("id") not in by_id
        or row.get("decision") not in VALID_PROPOSALS
        or not isinstance(row.get("reason"), str)
        or not row.get("reason", "").strip()
        or ("mode" in row and row.get("mode") not in {"surface", "date"})
    )
    if duplicate_overrides or invalid_overrides:
        raise RuntimeError(
            "Invalid reviewer overrides: "
            f"duplicates={len(duplicate_overrides)}, invalid={len(invalid_overrides)}"
        )
    overrides_by_id = {row["id"]: row for row in overrides}
    merged = []
    for decision in decisions:
        proposal = by_id[decision["id"]]
        override = overrides_by_id.get(decision["id"])
        merged.append(
            {
                **decision,
                "decision": override["decision"] if override else proposal["proposed_decision"],
                "reason": (override["reason"] if override else proposal["reason"]).strip(),
                "mode": override.get("mode", decision.get("mode")) if override else decision.get("mode"),
                "reviewed_by": "human-review-override" if override else "artifact-review-subagent",
                "review_risk_tags": proposal.get("risk_tags", []),
            }
        )
    atomic_write_jsonl(paths.decisions, merged)
    counts = Counter(row["decision"] for row in merged)
    return {
        "proposal_path": str(proposal_path),
        "override_path": str(override_path),
        "overrides": len(overrides),
        "decisions_path": str(paths.decisions),
        "rows": len(merged),
        "counts": dict(sorted(counts.items())),
    }


def apply_manual_rewrites(paths: PipelinePaths, input_path: Path | None = None) -> dict:
    """Validate reviewed manual candidates and append accepted audit records."""

    input_path = input_path or (paths.review_dir / "manual-rewrites.jsonl")
    proposed = read_jsonl(input_path)
    proposal_ids = [row.get("id") for row in proposed]
    duplicates = sorted(
        row_id for row_id, count in Counter(proposal_ids).items() if row_id and count > 1
    )
    latest = {
        row_id: record
        for split in SPLITS
        for row_id, record in read_latest_by_id(paths.rewrites(split)).items()
    }
    manual_ids = {row_id for row_id, row in latest.items() if row.get("status") == "manual"}
    missing = sorted(manual_ids - set(proposal_ids))
    extra = sorted(set(proposal_ids) - manual_ids)
    if duplicates or missing or extra or len(proposed) != len(manual_ids):
        raise RuntimeError(
            "Invalid manual rewrite set: "
            f"duplicates={len(duplicates)}, missing={len(missing)}, "
            f"extra={len(extra)}, rows={len(proposed)}/{len(manual_ids)}"
        )

    sources = {
        row["id"]: row for split in SPLITS for row in read_jsonl(paths.source(split))
    }
    decisions = read_latest_by_id(paths.decisions)
    invalid: list[tuple[str, list[str]]] = []
    accepted: list[tuple[str, dict]] = []
    for row in proposed:
        row_id = row["id"]
        source = sources[row_id]
        decision = decisions[row_id]
        candidate = {
            key: row.get(key) for key in ("question", "answer", "calculations")
        }
        mode = row.get("mode", decision["mode"])
        validation_exceptions = row.get("validation_exceptions", [])
        if mode not in {"surface", "date"}:
            errors = ["manual rewrite mode must be surface or date"]
        elif not isinstance(validation_exceptions, list) or not all(
            isinstance(item, str) for item in validation_exceptions
        ):
            errors = ["validation_exceptions must be a list of strings"]
        else:
            errors = validate_candidate(
                source,
                candidate,
                mode,
                validation_exceptions=validation_exceptions,
            )
        if not isinstance(row.get("reason"), str) or not row.get("reason", "").strip():
            errors.append("manual rewrite requires a nonempty review reason")
        if errors:
            invalid.append((row_id, errors))
            continue
        decision_hash = stable_hash(
            {
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "mode": decision.get("mode"),
            }
        )
        accepted.append(
            (
                source["split"],
                {
                    "id": row_id,
                    "split": source["split"],
                    "index": source["index"],
                    "source_hash": source["source_hash"],
                    "decision_hash": decision_hash,
                    "candidate_hash": stable_hash(candidate),
                    "prompt_version": REWRITE_PROMPT_VERSION,
                    "model": "manual-review",
                    "endpoint": "local-review",
                    "mode": mode,
                    "validation_exceptions": validation_exceptions,
                    "accepted": True,
                    "status": "manual_accepted",
                    "errors": [],
                    "candidate": candidate,
                    "review_reason": row["reason"].strip(),
                    "base_attempt": row.get("base_attempt"),
                    "completed_at": pipeline_utc_now(),
                },
            )
        )
    if invalid:
        details = "; ".join(f"{row_id}: {', '.join(errors)}" for row_id, errors in invalid[:10])
        raise RuntimeError(f"Invalid manual rewrite candidates ({len(invalid)}): {details}")
    for split, record in accepted:
        append_jsonl(paths.rewrites(split), [record])
    return {
        "input_path": str(input_path),
        "accepted": len(accepted),
        "splits": dict(sorted(Counter(split for split, _ in accepted).items())),
    }


def pipeline_utc_now() -> str:
    # Kept local to avoid importing pipeline.py back into the review module.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
