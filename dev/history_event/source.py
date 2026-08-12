"""Fetch and parse the four revision-pinned Wikipedia timeline pages."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    BPB_PREFIX,
    FOUR_DIGIT_FILTER_VERSION,
    MEDIAWIKI_API,
    NORMALIZATION_VERSION,
    PAPER_DECADE_COUNTS,
    PAPER_DECADES,
    PAPER_EVENT_COUNT,
    PAPER_RECALL_CANDIDATE_COUNT,
    PARSER_VERSION,
    RECALL_TEMPLATE,
    SOURCE_PAGES,
    PipelinePaths,
    revision_url,
)
from .io import read_json, row_hash, sha256_bytes, write_json, write_jsonl


FOUR_DIGIT_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")
HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
BULLET_RE = re.compile(r"^(\*+)\s*(.*)$")
YEAR_RE = re.compile(r"(?<!\d)(1[789]\d{2}|20(?:0\d|1\d|2[0-5]))(?!\d)")
LEADING_EVENT_YEAR_RE = re.compile(r"^(1[789]\d{2}|20(?:0\d|1\d|2[0-5]))(?![\dA-Za-z])")
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
LEADING_DATE_RE = re.compile(
    rf"^(?:{MONTHS})(?:\s+\d{{1,2}})?(?:\s*[–—-]\s*(?:(?:{MONTHS})\s+)?\d{{1,2}})?\s*:\s*",
    re.IGNORECASE,
)
STOP_HEADINGS = {
    "see also", "references", "further reading", "external links", "notes", "bibliography"
}


class SourceError(RuntimeError):
    pass


def _strip_balanced_templates(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    return text


def visible_text(wikitext: str) -> str:
    """Reduce the limited timeline wikitext vocabulary to displayed prose."""
    text = re.sub(r"<ref\b[^>/]*>.*?</ref\s*>", "", wikitext, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<ref\b[^>]*/\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = _strip_balanced_templates(text)
    text = re.sub(r"\[\[(?:File|Image):.*?\]\]", "", text, flags=re.IGNORECASE)

    def replace_link(match: re.Match[str]) -> str:
        body = match.group(1)
        return body.rsplit("|", 1)[-1]

    text = re.sub(r"\[\[([^\[\]]+)\]\]", replace_link, text)
    text = re.sub(r"\[(?:https?://\S+)(?:\s+([^\]]+))?\]", lambda m: m.group(1) or "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = html.unescape(text).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def heading_year(raw_heading: str) -> int | None:
    match = YEAR_RE.search(visible_text(raw_heading))
    return int(match.group(0)) if match else None


def _normalize_description(
    raw: str, *, century: int, boundary_heading_year: int | None = None
) -> tuple[int | None, str]:
    text = visible_text(raw)
    if century == 18:
        match = LEADING_EVENT_YEAR_RE.match(text)
        if not match:
            if boundary_heading_year is None:
                return None, ""
            year = boundary_heading_year
        else:
            year = int(match.group(0))
            colon = text.find(":", match.end())
            if colon < 0:
                return None, ""
            text = text[colon + 1 :].strip()
    else:
        year = None
        text = LEADING_DATE_RE.sub("", text).strip()
    text = text.rstrip().rstrip(".").strip()
    return year, text


def parse_page(wikitext: str, *, century: int, profile: str) -> list[dict]:
    """Parse one page. Profiles differ only in defensible nested-list handling."""
    if profile not in {"top_level", "event_bullets", "all_event_bullets"}:
        raise ValueError(f"unknown parser profile: {profile}")
    current_year: int | None = None
    boundary_heading_year: int | None = None
    chronological = False
    nested_event_parent = False
    rows: list[dict] = []
    for line_number, line in enumerate(wikitext.splitlines(), 1):
        heading = HEADING_RE.match(line.strip())
        if heading:
            label = visible_text(heading.group(2)).strip().lower()
            if len(heading.group(1)) == 2 and label in STOP_HEADINGS:
                chronological = False
                current_year = None
                continue
            possible_year = heading_year(heading.group(2))
            if century == 18:
                decade_match = re.search(r"(17\d0)s", label)
                if decade_match:
                    chronological = True
                    boundary_heading_year = None
                elif label == "1800":
                    chronological = True
                    boundary_heading_year = 1800
                elif len(heading.group(1)) == 2:
                    chronological = False
                    boundary_heading_year = None
            elif possible_year is not None and (century - 1) * 100 <= possible_year <= century * 100:
                current_year = possible_year
                chronological = True
            continue
        if not chronological:
            continue
        bullet = BULLET_RE.match(line)
        if not bullet:
            continue
        depth, raw = len(bullet.group(1)), bullet.group(2)
        event_year, description = _normalize_description(
            raw, century=century, boundary_heading_year=boundary_heading_year
        )
        if depth == 1:
            nested_event_parent = century != 18 and event_year is None and not description
        if profile == "top_level" and depth != 1:
            continue
        if profile == "event_bullets" and depth != 1 and not nested_event_parent:
            continue
        if century != 18:
            event_year = current_year
        if event_year is None or not description:
            continue
        if not (1700 <= event_year <= 2025):
            continue
        rows.append({
            "event_year": event_year,
            "event_description": description,
            "source_line": line_number,
            "list_depth": depth,
        })
    return rows


def decade_counts(rows: list[dict]) -> dict[int, int]:
    counts = Counter((row["event_year"] // 10) * 10 for row in rows)
    return {decade: counts.get(decade, 0) for decade in PAPER_DECADES}


def compare_to_paper(rows: list[dict]) -> dict:
    observed = decade_counts(rows)
    differences = {
        str(decade): observed[decade] - expected
        for decade, expected in zip(PAPER_DECADES, PAPER_DECADE_COUNTS)
    }
    return {
        "row_count": len(rows),
        "paper_row_count": PAPER_EVENT_COUNT,
        "row_count_difference": len(rows) - PAPER_EVENT_COUNT,
        "observed_decade_counts": {str(key): value for key, value in observed.items()},
        "paper_decade_counts": dict(zip(map(str, PAPER_DECADES), PAPER_DECADE_COUNTS)),
        "decade_differences": differences,
        "decade_l1_distance": sum(abs(value) for value in differences.values()),
        "exact_match": len(rows) == PAPER_EVENT_COUNT and all(value == 0 for value in differences.values()),
    }


def _fetch_revision(page: dict, destination: Path, timeout: float = 60.0) -> tuple[str, dict]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode({
        "action": "query",
        "prop": "revisions",
        "revids": page["revision"],
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    })
    request = urllib.request.Request(
        f"{MEDIAWIKI_API}?{query}",
        headers={"User-Agent": "think.nano HISTORY-EVENT reconstruction (research)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception as exc:
        if destination.exists():
            text = destination.read_text(encoding="utf-8")
            return text, {"offline_snapshot": True, "timestamp": None}
        raise SourceError(f"could not fetch Wikipedia revision {page['revision']}: {exc}") from exc
    try:
        revision = payload["query"]["pages"][0]["revisions"][0]
        text = revision["slots"]["main"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError(f"unexpected MediaWiki response for revision {page['revision']}") from exc
    destination.write_text(text, encoding="utf-8")
    return text, {"offline_snapshot": False, "timestamp": revision.get("timestamp")}


def prepare(paths: PipelinePaths, *, refresh: bool = False) -> dict:
    """Fetch sources, choose the documented closest profile, and materialize rows."""
    previous_timestamps: dict[str, str | None] = {}
    if paths.manifest.exists():
        for source in read_json(paths.manifest).get("sources", []):
            previous_timestamps[str(source.get("revision"))] = source.get("revision_timestamp")
    sources: list[tuple[dict, str, dict, Path]] = []
    for page in SOURCE_PAGES:
        snapshot = paths.raw_dir / f"timeline-{page['century']}-oldid-{page['revision']}.wiki"
        if snapshot.exists() and not refresh:
            text = snapshot.read_text(encoding="utf-8")
            fetch_meta = {
                "offline_snapshot": True,
                "timestamp": previous_timestamps.get(str(page["revision"])),
            }
        else:
            text, fetch_meta = _fetch_revision(page, snapshot)
        sources.append((page, text, fetch_meta, snapshot))

    candidates: dict[str, list[dict]] = {}
    for profile in ("top_level", "event_bullets", "all_event_bullets"):
        combined: list[dict] = []
        for page_index, (page, text, _, _) in enumerate(sources):
            for page_position, row in enumerate(parse_page(text, century=page["century"], profile=profile)):
                combined.append({
                    **row,
                    "source_page_index": page_index,
                    "source_page_position": page_position,
                    "source_title": page["title"],
                    "source_url": revision_url(page["title"], page["revision"]),
                    "source_revision": str(page["revision"]),
                })
        candidates[profile] = combined

    comparisons = {name: compare_to_paper(rows) for name, rows in candidates.items()}
    selected_profile = min(
        candidates,
        key=lambda name: (
            comparisons[name]["decade_l1_distance"],
            abs(comparisons[name]["row_count_difference"]),
            name,
        ),
    )
    selected = candidates[selected_profile]
    events: list[dict] = []
    for index, source_row in enumerate(selected):
        description = source_row["event_description"]
        year = source_row["event_year"]
        event = {
            "id": f"history-event-{index:06d}",
            "event_year": year,
            "event_decade": (year // 10) * 10,
            "event_description": description,
            "source_url": source_row["source_url"],
            "source_revision": source_row["source_revision"],
            "source_position": {
                "page": source_row["source_page_index"],
                "event": source_row["source_page_position"],
                "line": source_row["source_line"],
                "list_depth": source_row["list_depth"],
            },
            "bpb_prefix": BPB_PREFIX,
            "bpb_target": f"{description}. This took place in {year}.",
            "recall_question": RECALL_TEMPLATE.format(event_description=description),
        }
        event["source_hash"] = row_hash(event, ("event_year", "event_description", "source_revision"))
        events.append(event)

    candidates_out: list[dict] = []
    rejections: list[dict] = []
    for event in events:
        matches = FOUR_DIGIT_RE.findall(event["event_description"])
        if matches:
            rejections.append({**event, "four_digit_matches": matches})
        else:
            candidates_out.append(event)

    write_jsonl(paths.events, events)
    write_jsonl(paths.recall_candidates, candidates_out)
    write_jsonl(paths.four_digit_rejections, rejections)
    discrepancy = {
        "selected_profile": selected_profile,
        "selection_rule": "minimum decade L1 distance, then minimum absolute row-count difference",
        "profiles": comparisons,
        "warning": None if comparisons[selected_profile]["exact_match"] else (
            "No implemented defensible profile exactly reproduced the paper; observed rows are retained without forcing."
        ),
    }
    write_json(paths.discrepancy_report, discrepancy)
    parsed_hash = sha256_bytes("".join(event["source_hash"] for event in events).encode("ascii"))
    manifest = {
        "kind": "independent_history_event_reconstruction",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "four_digit_filter_version": FOUR_DIGIT_FILTER_VERSION,
        "selected_profile": selected_profile,
        "source_order": [page["title"] for page, _, _, _ in sources],
        "sources": [
            {
                **page,
                "revision": str(page["revision"]),
                "url": revision_url(page["title"], page["revision"]),
                "revision_timestamp": meta["timestamp"],
                "raw_sha256": sha256_bytes(text.encode("utf-8")),
                "snapshot": str(snapshot.relative_to(paths.root)),
            }
            for page, text, meta, snapshot in sources
        ],
        "parsed_sha256": parsed_hash,
        "counts": {
            "events": len(events),
            "recall_candidates": len(candidates_out),
            "four_digit_rejections": len(rejections),
            "paper_events": PAPER_EVENT_COUNT,
            "paper_recall_candidates": PAPER_RECALL_CANDIDATE_COUNT,
        },
        "discrepancy": discrepancy,
    }
    write_json(paths.manifest, manifest)
    return manifest
