# ---------------------------------------------------------------------------
# AGGREGATE REPORT + PROVENANCE
#
# Reads every uploaded per-shard stats file, sums the counts, ranks which banned
# terms actually fired (the key audit surface), and writes cleaning_report_1930s.json
# plus a README to the destination repo. Safe to run mid-pipeline -- it reports
# whatever shard set has completed so far.
# ---------------------------------------------------------------------------


def download_json_file(path_in_repo):
    local = hf_hub_download(DST_REPO, path_in_repo, repo_type="dataset", token=HF_TOKEN)
    with open(local, "r", encoding="utf-8") as f:
        return json.load(f)


files = list_repo_files_safe(DST_REPO)
stat_files = sorted([p for p in files if re.match(r"stats/shard_\d+\.json$", p)])
print(f"Found {len(stat_files):,} completed shard stat files.")

totals = {
    "source_repo": SRC_REPO,
    "destination_repo": DST_REPO,
    "cutoff_year": CUTOFF_YEAR,
    "min_banned_hits": MIN_BANNED_HITS,
    "banned_list_meta": BANNED_META,
    "n_banned_terms": len(BANNED_TERMS),
    "n_format_tells": len(FORMAT_RES),
    "n_shards_done": len(stat_files),
    "n_input": 0,
    "n_kept": 0,
    "n_removed": 0,
    "chars_in": 0,
    "chars_kept": 0,
    "removed_by_term": Counter(),
    "removed_by_kind": Counter(),
}

for sf in tqdm(stat_files, desc="aggregating stats"):
    st = download_json_file(sf)
    for k in ["n_input", "n_kept", "n_removed", "chars_in", "chars_kept"]:
        totals[k] += int(st.get(k, 0))
    totals["removed_by_term"].update(st.get("removed_by_term", {}))
    totals["removed_by_kind"].update(st.get("removed_by_kind", {}))

top_terms = totals["removed_by_term"].most_common(30)
totals["top_firing_terms"] = top_terms
totals["removed_by_term"] = dict(totals["removed_by_term"])
totals["removed_by_kind"] = dict(totals["removed_by_kind"])
totals["docs_removed_pct"] = 100.0 * totals["n_removed"] / max(totals["n_input"], 1)
totals["docs_kept_pct"] = 100.0 * totals["n_kept"] / max(totals["n_input"], 1)
totals["chars_kept_pct"] = 100.0 * totals["chars_kept"] / max(totals["chars_in"], 1)
totals["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

print(json.dumps({k: v for k, v in totals.items() if k != "removed_by_term"},
                 indent=2, sort_keys=True))

report_path = OUT_DIR / "cleaning_report_1930s.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(totals, f, indent=2, sort_keys=True)

top_lines = "\n".join(f"- `{t}`: {c:,}" for t, c in top_terms) or "- (none yet)"
readme = f"""---
dataset_info:
  features:
  - name: text
    dtype: string
---

# think-dataset-clean-1930s

`jbduran/think-dataset-clean` with an additional **anachronism keyword filter**
applied. This drops whole documents that contain any term that could only have
been written after **{CUTOFF_YEAR}** (modern editor forewords, footnotes, reprint
boilerplate, etc.), following Michael Hla's keyword-filter approach from
*Machina Mirabilis* / `gpt1900`.

Design choices:

- Cutoff is **after {CUTOFF_YEAR}** (1930 and earlier is kept). The seed lists
  (croqaz `banned.txt`, Hla physics terms) target a 1900 cutoff, so terms that
  are legitimate by 1930 -- radio, aeroplane, Einstein, relativity, quantum,
  X-ray, etc. -- were removed via an allow-list.
- **Conservative / high-precision** policy: only unambiguously post-1930 terms
  are banned; borderline words are kept. The upstream GPT-2 log-prior filter is
  the statistical backstop.
- A document is dropped when it contains **>= {MIN_BANNED_HITS}** distinct banned
  signal(s) (Hla's "one hit scraps it" rule).
- Whole books are preserved unchanged; only whole documents are ever removed.
- Each source `shard_XXXXX.parquet` maps to the same destination shard name.

Artifacts:

- `_banned/banned_list.txt` -- the final banned term list (**{len(BANNED_TERMS):,} terms**).
- `_banned/allow_list.txt` -- terms deliberately kept (pre-1931-legit).
- `_banned/removed_from_seed.json` -- audit of what was stripped/added vs the seed.
- `_banned/list_meta.json` -- list build metadata.
- `stats/shard_*.json` -- per-shard counts and removal reasons.
- `hits/shard_*.jsonl` -- per-shard hit log: every dropped doc and the terms that matched.

Current report:

- Banned list size: **{len(BANNED_TERMS):,} terms** + {len(FORMAT_RES)} format-tell patterns
- Shards completed: {totals["n_shards_done"]:,}
- Input documents: {totals["n_input"]:,}
- Kept documents: {totals["n_kept"]:,} ({totals["docs_kept_pct"]:.2f}%)
- Removed documents: {totals["n_removed"]:,} ({totals["docs_removed_pct"]:.2f}%)
- Kept characters: {totals["chars_kept_pct"]:.2f}%

Top firing terms:

{top_lines}
"""

readme_path = OUT_DIR / "README.md"
with open(readme_path, "w", encoding="utf-8") as f:
    f.write(readme)

api.create_commit(
    repo_id=DST_REPO,
    repo_type="dataset",
    operations=[
        CommitOperationAdd(path_in_repo="cleaning_report_1930s.json", path_or_fileobj=str(report_path)),
        CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(readme_path)),
    ],
    commit_message="update 1930s anachronism-filter report",
)

print("\nUploaded cleaning_report_1930s.json and README.md.")
print(f"Banned list size: {len(BANNED_TERMS):,} terms.")
print(f"Docs removed so far: {totals['n_removed']:,} "
      f"({totals['docs_removed_pct']:.2f}%) across {totals['n_shards_done']:,} shards.")
