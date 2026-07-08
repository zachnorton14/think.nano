def download_json_file(path_in_repo):
    local = hf_hub_download(DST_REPO, path_in_repo, repo_type="dataset", token=HF_TOKEN)
    with open(local, "r", encoding="utf-8") as f:
        return json.load(f)


files = list_repo_files_safe(DST_REPO)
stat_files = sorted([p for p in files if re.match(r"stats/shard_\d+\.json$", p)])
print(f"Found {len(stat_files):,} completed shard stat files.")

totals = {
    "n_shards_done": len(stat_files),
    "n_input": 0,
    "n_kept": 0,
    "n_removed": 0,
    "chars_raw": 0,
    "chars_after_clean_before_prior": 0,
    "chars_kept": 0,
    "removed_by_reason": Counter(),
    "source_repo": SRC_REPO,
    "destination_repo": DST_REPO,
    "prior_thresholds": PRIOR_THRESHOLDS,
    "settings": {
        "min_chars_raw": MIN_CHARS_RAW,
        "min_chars_clean": MIN_CHARS_CLEAN,
        "min_printable": MIN_PRINTABLE,
        "max_ocr_artifacts": MAX_OCR_ARTIFACTS,
        "prior_band": list(PRIOR_BAND),
        "whole_books_kept": True,
        "post_1900_physics_filter": "skipped for 1930s cutoff",
    },
}

for sf in tqdm(stat_files, desc="stats"):
    st = download_json_file(sf)
    for k in ["n_input", "n_kept", "n_removed", "chars_raw", "chars_after_clean_before_prior", "chars_kept"]:
        totals[k] += int(st.get(k, 0))
    totals["removed_by_reason"].update(st.get("removed_by_reason", {}))

totals["removed_by_reason"] = dict(totals["removed_by_reason"])
totals["docs_removed_pct"] = 100.0 * totals["n_removed"] / max(totals["n_input"], 1)
totals["docs_kept_pct"] = 100.0 * totals["n_kept"] / max(totals["n_input"], 1)
totals["chars_kept_pct_vs_raw"] = 100.0 * totals["chars_kept"] / max(totals["chars_raw"], 1)
totals["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

print(json.dumps(totals, indent=2, sort_keys=True))

report_path = OUT_DIR / "cleaning_report.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(totals, f, indent=2, sort_keys=True)

readme = f"""---
dataset_info:
  features:
  - name: text
    dtype: string
---

# think-dataset-clean

Cleaned version of `jbduran/think-dataset`, produced with a Colab notebook based on Michael Hla's Machina Mirabilis / gpt1900 filtering approach.

Design choices:

- Whole books are preserved as rows.
- The post-1900 physics keyword filter is skipped because this dataset intentionally keeps texts up to the 1930s.
- A moderate GPT-2 token log-prior band is used: p{PRIOR_BAND[0]}-p{PRIOR_BAND[1]}.
- Each source shard maps to one output shard of the same basename.

Current report:

- Shards completed: {totals["n_shards_done"]:,}
- Input documents seen: {totals["n_input"]:,}
- Kept documents: {totals["n_kept"]:,} ({totals["docs_kept_pct"]:.2f}%)
- Removed documents: {totals["n_removed"]:,} ({totals["docs_removed_pct"]:.2f}%)
- Kept characters vs raw: {totals["chars_kept_pct_vs_raw"]:.2f}%

Removal reasons:

{chr(10).join(f"- {reason}: {count:,}" for reason, count in sorted(totals["removed_by_reason"].items(), key=lambda x: -x[1]))}
"""

readme_path = OUT_DIR / "README.md"
with open(readme_path, "w", encoding="utf-8") as f:
    f.write(readme)

api.create_commit(
    repo_id=DST_REPO,
    repo_type="dataset",
    operations=[
        CommitOperationAdd(path_in_repo="cleaning_report.json", path_or_fileobj=str(report_path)),
        CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(readme_path)),
    ],
    commit_message="update cleaning report",
)

print("Uploaded cleaning_report.json and README.md.")
