"""Stage 4: aggregate report + provenance.

Reads every uploaded per-shard stats file, sums the counts, ranks which banned
terms actually fired (the key audit surface), and writes cleaning_report_1930s.json
plus a README to the destination repo. Safe to run mid-pipeline.

Run:  python scripts/report.py
"""
import json
import re
import time
from collections import Counter

from huggingface_hub import CommitOperationAdd, hf_hub_download

import config
from build_list import load_or_build
from common import api, HF_TOKEN, ensure_dst_repo, list_repo_files_safe


def download_json(path_in_repo):
    local = hf_hub_download(config.DST_REPO, path_in_repo, repo_type="dataset", token=HF_TOKEN)
    with open(local, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ensure_dst_repo()
    banned_terms, meta, tiers = load_or_build()

    files = list_repo_files_safe(config.DST_REPO)
    stat_files = sorted(p for p in files if re.match(r"stats/shard_\d+\.json$", p))
    strip_stat_files = sorted(p for p in files if re.match(r"strip_stats/shard_\d+\.json$", p))
    print(f"Found {len(stat_files):,} filter stat files and {len(strip_stat_files):,} strip stat files.")

    # --- Stage 0.5 footer-strip totals (if that stage has run) ---
    strip_totals = {
        "n_shards_stripped": len(strip_stat_files),
        "n_docs": 0, "n_docs_changed": 0, "n_docs_flagged_unstripped": 0,
        "n_lines_removed": 0, "chars_in": 0, "chars_out": 0,
        "removed_by_pattern": Counter(),
    }
    for sf in strip_stat_files:
        st = download_json(sf)
        for k in ["n_docs", "n_docs_changed", "n_docs_flagged_unstripped",
                  "n_lines_removed", "chars_in", "chars_out"]:
            strip_totals[k] += int(st.get(k, 0))
        strip_totals["removed_by_pattern"].update(st.get("removed_by_pattern", {}))
    top_footers = strip_totals["removed_by_pattern"].most_common(20)
    strip_totals["top_footer_patterns"] = top_footers
    strip_totals["removed_by_pattern"] = dict(strip_totals["removed_by_pattern"])
    strip_totals["chars_removed_pct"] = (
        100.0 * (strip_totals["chars_in"] - strip_totals["chars_out"]) / max(strip_totals["chars_in"], 1)
    )

    totals = {
        "source_repo": config.SRC_REPO,
        "destination_repo": config.DST_REPO,
        "cutoff_year": config.CUTOFF_YEAR,
        "min_banned_hits": config.MIN_BANNED_HITS,
        "banned_list_meta": meta,
        "n_banned_terms": len(banned_terms),
        "n_shards_done": len(stat_files),
        "tier_counts": (meta or {}).get("tier_counts", {}),
        "n_input": 0, "n_kept": 0, "n_removed": 0, "chars_in": 0, "chars_kept": 0,
        "removed_by_term": Counter(), "removed_by_reason": Counter(),
        "boilerplate_hits": Counter(),
    }

    for sf in stat_files:
        st = download_json(sf)
        for k in ["n_input", "n_kept", "n_removed", "chars_in", "chars_kept"]:
            totals[k] += int(st.get(k, 0))
        totals["removed_by_term"].update(st.get("removed_by_term", {}))
        totals["removed_by_reason"].update(st.get("removed_by_reason", {}))
        totals["boilerplate_hits"].update(st.get("boilerplate_hits", {}))

    top_terms = totals["removed_by_term"].most_common(30)
    top_boilerplate = totals["boilerplate_hits"].most_common(20)
    totals["top_firing_terms"] = top_terms
    totals["top_boilerplate_hits"] = top_boilerplate
    totals["removed_by_term"] = dict(totals["removed_by_term"])
    totals["removed_by_reason"] = dict(totals["removed_by_reason"])
    totals["boilerplate_hits"] = dict(totals["boilerplate_hits"])
    totals["docs_removed_pct"] = 100.0 * totals["n_removed"] / max(totals["n_input"], 1)
    totals["docs_kept_pct"] = 100.0 * totals["n_kept"] / max(totals["n_input"], 1)
    totals["chars_kept_pct"] = 100.0 * totals["chars_kept"] / max(totals["chars_in"], 1)
    totals["footer_strip"] = strip_totals
    totals["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print(json.dumps({k: v for k, v in totals.items() if k != "removed_by_term"},
                     indent=2, sort_keys=True))

    config.ensure_dirs()
    report_path = config.OUT_DIR / "cleaning_report_1930s.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(totals, f, indent=2, sort_keys=True)

    top_lines = "\n".join(f"- `{t}`: {c:,}" for t, c in top_terms) or "- (none yet)"
    footer_lines = "\n".join(f"- `{p}`: {c:,}" for p, c in top_footers) or "- (strip stage not run yet)"
    st = strip_totals
    readme = f"""---
dataset_info:
  features:
  - name: text
    dtype: string
---

# think-dataset-clean-1930s

`{config.SRC_REPO}` with a **tiered** anachronism keyword filter applied. A document
is dropped only on strong evidence of post-**{config.CUTOFF_YEAR}** content, which
avoids polysemy false positives (e.g. "compiler of this volume", bee "drone",
birdsong "twitter", the Black Hole of Calcutta):

- **Tier 1** ({totals["tier_counts"].get("tier1", 0)}) — coined well after {config.CUTOFF_YEAR}; **one hit drops** the document.
- **Tier 2** ({totals["tier_counts"].get("tier2", 0)}) — real anachronisms; need **≥2 distinct tier-2/3 hits (≥1 tier-2)** to drop.
- **Tier 3** ({totals["tier_counts"].get("tier3", 0)}) — polysemous / has a pre-{config.CUTOFF_YEAR + 1} sense; **never drops alone**, only corroborates.
- **Strip-only** ({totals["tier_counts"].get("strip", 0)}) + format tells — reproduction/boilerplate (URLs, "all rights reserved", "photocopy"); **never drops**, only logged.

- Banned list size: **{len(banned_terms):,} terms** (+ format-tell patterns)
- Shards completed: {totals["n_shards_done"]:,}
- Input documents: {totals["n_input"]:,}
- Kept: {totals["n_kept"]:,} ({totals["docs_kept_pct"]:.2f}%)
- Removed: {totals["n_removed"]:,} ({totals["docs_removed_pct"]:.2f}%)
- Kept characters: {totals["chars_kept_pct"]:.2f}%

## Stage 0.5 — footer / boilerplate stripping (runs before the filter)

Before the anachronism filter, a line-level pass removes reprint/OCR footer lines
(URLs, "printed in the United States of America", "all rights reserved", photocopy /
print-on-demand colophons, ISBN lines, bare page numbers, library stamps) from each
document, writing the stripped corpus to `{config.STRIP_PREFIX}/`. Whole books are kept;
only footer lines are removed. Docs that would lose more than {int(config.FOOTER_MAX_DOC_LINE_FRAC * 100)}% of their
lines are kept unstripped and flagged.

- Shards stripped: {st["n_shards_stripped"]:,}
- Docs changed: {st["n_docs_changed"]:,} / {st["n_docs"]:,}
- Docs flagged (kept unstripped): {st["n_docs_flagged_unstripped"]:,}
- Footer lines removed: {st["n_lines_removed"]:,}
- Characters removed: {st["chars_removed_pct"]:.2f}%

Top footer patterns:

{footer_lines}

Artifacts: `_banned/` (list + allow-list + audit), `{config.STRIP_PREFIX}/` (footer-stripped
corpus), `strip_stats/` + `strip_samples/` (footer audit), `stats/` (per-shard filter
counts), `hits/` (per-shard hit log), `scripts/` (the pipeline).

Top firing terms:

{top_lines}
"""
    readme_path = config.OUT_DIR / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)

    api.create_commit(
        repo_id=config.DST_REPO, repo_type="dataset",
        operations=[
            CommitOperationAdd("cleaning_report_1930s.json", str(report_path)),
            CommitOperationAdd("README.md", str(readme_path)),
        ],
        commit_message="update 1930s anachronism-filter report",
    )
    print(f"\nUploaded report + README. Banned list: {len(banned_terms):,} terms. "
          f"Removed so far: {totals['n_removed']:,} ({totals['docs_removed_pct']:.2f}%).")


if __name__ == "__main__":
    main()
