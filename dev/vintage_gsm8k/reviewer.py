"""Validate and apply an independent review proposal to the canonical decision gate."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .config import PipelinePaths
from .data import atomic_write_jsonl, read_jsonl


VALID_PROPOSALS = {"keep", "rewrite", "manual"}


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
