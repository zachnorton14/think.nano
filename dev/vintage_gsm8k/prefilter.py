"""Tiered regex prefilter based on the linked Vintage CORE banned-list policy."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone

from .config import (
    PREFILTER_VERSION,
    REGEX_POLICY_DATASET,
    REGEX_POLICY_FILES,
    PipelinePaths,
)
from .data import atomic_write_json, atomic_write_jsonl, post_cutoff_years, read_jsonl, stable_hash


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    # Catch ordinary inflections such as DVD(s), iPhone(s), download(s), and website(s).
    suffix = r"(?:s|es)?" if term[-1:].isalpha() and not term.casefold().endswith("s") else ""
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}{suffix}(?![A-Za-z0-9])", re.IGNORECASE)


def scan_row(
    row: dict,
    tiers: dict[str, int | str],
    policy_revision: str,
    patterns: dict[str, re.Pattern] | None = None,
) -> dict:
    question, answer = row["question"], row["answer"]
    patterns = patterns or {term: _term_pattern(term) for term in tiers}
    hits = []
    strip_hits = []
    for term, tier in tiers.items():
        pattern = patterns[term]
        locations = []
        if pattern.search(question):
            locations.append("question")
        if pattern.search(answer):
            locations.append("solution")
        if not locations:
            continue
        hit = {"term": term, "tier": tier, "locations": locations}
        if tier == "strip":
            strip_hits.append(hit)
        else:
            hits.append(hit)

    tier1 = [hit for hit in hits if hit["tier"] == 1]
    tier2 = [hit for hit in hits if hit["tier"] == 2]
    supporting = [hit for hit in hits if hit["tier"] in {2, 3}]
    # Questions carry the temporal premise. Restricting this heuristic to the question avoids
    # reading solution phrases such as "results in 6000" or "multiply by 2000" as dates.
    years = sorted(set(post_cutoff_years(question)))
    triggered = bool(years or tier1 or (tier2 and len(supporting) >= 2))
    reasons = []
    if years:
        reasons.append(f"contextual post-1930 year(s): {years}")
    if tier1:
        reasons.append("tier-1: " + ", ".join(hit["term"] for hit in tier1))
    if tier2 and len(supporting) >= 2:
        reasons.append("corroborating tier-2/3: " + ", ".join(hit["term"] for hit in supporting))
    if not reasons:
        reasons.append("no high-confidence tiered regex trigger")
    return {
        "id": row["id"],
        "split": row["split"],
        "index": row["index"],
        "source_hash": row["source_hash"],
        "prefilter_version": PREFILTER_VERSION,
        "policy_revision": policy_revision,
        "action": "flag" if triggered else "clear",
        "reason": "; ".join(reasons),
        "hits": hits,
        "strip_hits": strip_hits,
        "post_cutoff_years": years,
    }


def scan_rows(rows: list[dict], tiers: dict[str, int | str], policy_revision: str = "test") -> list[dict]:
    patterns = {term: _term_pattern(term) for term in tiers}
    return [scan_row(row, tiers, policy_revision, patterns) for row in rows]


def _load_or_fetch_policy(paths: PipelinePaths, revision: str) -> dict:
    if paths.regex_policy.exists():
        return json.loads(paths.regex_policy.read_text(encoding="utf-8"))
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError("huggingface-hub is required; run `uv sync --group dev`") from exc
    resolved_revision = HfApi().dataset_info(REGEX_POLICY_DATASET, revision=revision).sha
    downloaded = {
        filename: hf_hub_download(
            repo_id=REGEX_POLICY_DATASET,
            repo_type="dataset",
            filename=filename,
            revision=resolved_revision,
        )
        for filename in REGEX_POLICY_FILES
    }
    with open(downloaded["_banned/tiers.json"], encoding="utf-8") as handle:
        tiers = json.load(handle)
    with open(downloaded["_banned/list_meta.json"], encoding="utf-8") as handle:
        metadata = json.load(handle)
    policy = {
        "dataset": REGEX_POLICY_DATASET,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "tiers": tiers,
        "metadata": metadata,
        "policy_hash": stable_hash({"tiers": tiers, "metadata": metadata}),
    }
    atomic_write_json(paths.regex_policy, policy)
    return policy


def prefilter(paths: PipelinePaths, *, policy_revision: str = "main") -> dict:
    if not paths.manifest.exists():
        raise RuntimeError("Run `python -m dev.vintage_gsm8k prepare` before prefiltering")
    policy = _load_or_fetch_policy(paths, policy_revision)
    tiers = policy["tiers"]
    all_results = {}
    for split in ("train", "test"):
        rows = read_jsonl(paths.source(split))
        results = scan_rows(rows, tiers, policy["resolved_revision"])
        atomic_write_jsonl(paths.regex(split), results)
        all_results[split] = results

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prefilter_version": PREFILTER_VERSION,
        "policy_dataset": REGEX_POLICY_DATASET,
        "policy_revision": policy["resolved_revision"],
        "policy_hash": policy["policy_hash"],
        "policy_rule": policy.get("metadata", {}).get("drop_rule"),
        "splits": {
            split: {
                "rows": len(results),
                "flagged": sum(row["action"] == "flag" for row in results),
                "clear": sum(row["action"] == "clear" for row in results),
            }
            for split, results in all_results.items()
        },
    }
    atomic_write_json(paths.regex_manifest, summary)

    flags = [row for split in ("train", "test") for row in all_results[split] if row["action"] == "flag"]
    term_counts = Counter(hit["term"] for row in flags for hit in row["hits"])
    lines = [
        "# Vintage GSM8K regex prefilter",
        "",
        f"Policy revision: `{policy['resolved_revision']}`",
        "",
        f"Policy: {summary['policy_rule']}",
        "",
        "This is a recall aid, not a final verdict. Strip-only terms never trigger, and every row still goes to the LLM judge.",
        "",
        f"Train flagged: {summary['splits']['train']['flagged']} / {summary['splits']['train']['rows']}",
        "",
        f"Test flagged: {summary['splits']['test']['flagged']} / {summary['splits']['test']['rows']}",
        "",
        "## Most common triggering terms",
        "",
    ]
    lines.extend(f"- `{term}`: {count}" for term, count in term_counts.most_common(30))
    lines.extend(["", "## Flagged rows", ""])
    lines.extend(f"- `{row['id']}` — {row['reason']}" for row in flags)
    paths.regex_markdown.parent.mkdir(parents=True, exist_ok=True)
    paths.regex_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
