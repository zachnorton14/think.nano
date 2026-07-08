import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CELLS_DIR = ROOT / "cells_runner"
OUT = ROOT / "think_dataset_clean_1930s.ipynb"


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")


def code(fname: str) -> str:
    return read_text(CELLS_DIR / fname)


def cell(cell_type, source):
    return {
        "cell_type": cell_type,
        "metadata": {},
        "source": source.splitlines(keepends=True),
        **({"execution_count": None, "outputs": []} if cell_type == "code" else {}),
    }


def markdown(s): return cell("markdown", s)
def code_cell(s): return cell("code", s)


def validate_notebook_shape(nb):
    required = {"cells", "metadata", "nbformat", "nbformat_minor"}
    assert not (required - set(nb)), f"missing {required - set(nb)}"
    assert nb["nbformat"] == 4
    for i, c in enumerate(nb["cells"]):
        assert c.get("cell_type") in {"markdown", "code"}, i
        assert "source" in c, i


md_title = """# Anachronism filter (1930s): thin runner for the `scripts/` pipeline

This notebook is a **thin orchestrator**. All the real logic lives in standalone
Python scripts that are stored in the destination dataset repo under `scripts/`.
The notebook uploads them to Hugging Face, clones the repo, and runs each stage as
its own process. This keeps the heavy code (the 460+ term banned list, the fast
matcher, the shard loop) out of the notebook and versioned alongside the data.

- Source:      [`jbduran/think-dataset-clean`](https://huggingface.co/datasets/jbduran/think-dataset-clean)
- Destination: [`jbduran/think-dataset-clean-1930s`](https://huggingface.co/datasets/jbduran/think-dataset-clean-1930s) (created on first run)
- Method: Michael Hla's keyword-filter approach (drop a whole document that mentions
  anything post-1930), seeded from croqaz/vintage-ft-v1 `banned.txt` and adjusted
  from a 1900 to a 1930 cutoff via an allow-list.

## The pipeline scripts (in `scripts/`)

| Script | Stage | What it does |
|---|---|---|
| `config.py` | — | Shared settings (repos, cutoff, scan window). Imported by all; reads env overrides. |
| `common.py` | — | HF auth, `HfApi`, repo/shard helpers. |
| `wipe.py` | 0 | Guarded clean command: delete generated shards/stats/hits/report. |
| `build_list.py` | 1 | Build + count + upload the banned list to `_banned/`. |
| `filter_lib.py` | 2 | Fast matcher (`compile_matchers`, `scan_text`, `should_drop`). |
| `run_filter.py` | 3 | Resumable shard loop: scan, drop whole docs, write shard + stats + hit log. |
| `report.py` | 4 | Aggregate report + README; ranks which terms fired. |

## How state passes between stages

Each script is its own process. They share settings through `config.py` (with env
overrides set in the bootstrap cell) and share the banned list through HF: Stage 1
uploads `_banned/banned_list.txt`; Stages 3 and 4 download it and rebuild the matcher.
That makes every stage independently runnable and naturally resumable.

## Performance note

The matcher deliberately avoids a 400+ term regex alternation (which is
seconds-per-book on multi-MB OCR text). It uses set membership for single words,
first-token gating for phrases, and a capped head+tail scan window — about 35x
faster with identical results. This runs comfortably on a **plain CPU** runtime;
no GPU, no high-RAM needed.
"""

md_bootstrap = """## 1. Install, authenticate, configure

Installs dependencies, logs into Hugging Face (add a **write** token as a Colab
secret named `HF_TOKEN`), exports config as environment variables for the scripts,
and creates the destination repo.
"""

md_push = """## 2. Push scripts to HF and clone

Bring the local `scripts/` folder into this Colab session first (drag-and-drop the
folder into the file browser on the left, or mount Google Drive). This cell uploads
it to `scripts/` in the destination repo, then clones the repo so every stage runs
from a clean checkout. Re-running re-syncs the scripts and pulls the latest.
"""

md_wipe = """## 3. Stage 0 — clean command (optional, guarded)

Only deletes anything if you edit the cell to set `CONFIRM_WIPE=1`. Use it to
rebuild the dataset from scratch. Leave as-is for a normal resumable run.
"""

md_build = """## 4. Stage 1 — build the banned list

Builds the list (croqaz seed + 1930 allow-list + post-1930 extras), prints the
**total term count**, and uploads it to `_banned/`. Subsequent runs load the cached
list unless you set `FORCE_REBUILD_LIST=1`.
"""

md_dry = """## 7. Stage 3 — anachronism filter dry run (one shard)

Runs the tiered anachronism filter on the **footer-stripped** layer (`stripped/`).
**Run this first** on one shard, then open `hits/shard_00000.jsonl` on HF and check
that the dropped documents are genuine anachronisms, not false positives. If a term
over-fires, adjust its tier in `scripts/build_list.py`, rebuild the list (Stage 1
with `FORCE_REBUILD_LIST=1`), and try again.
"""

md_full = """## 8. Stage 3 — anachronism filter full run (all remaining shards)

Once the dry-run hit log looks right, run this to process everything. Completed
shards are skipped, so it resumes automatically after any Colab disconnect — just
re-run this cell until it reports nothing remaining. Each shard prints kept/removed
counts and a running ETA.
"""

md_strip_dry = """## 5. Stage 0.5 — strip footers (dry run, one shard)

Footer/boilerplate removal runs **before** the anachronism filter. This line-level
pass removes reprint/OCR footer lines — URLs, "printed in the United States of
America", "all rights reserved", photocopy / print-on-demand colophons, ISBN lines,
bare page numbers, library stamps — from each document, writing the stripped corpus
to `stripped/` in the destination repo. Whole books are kept; only footer lines go.

**Run this first (one shard).** Then open `strip_samples/shard_00000.jsonl` on HF and
confirm only genuine footer lines were removed — not book text. Docs that would lose
more than 30% of their lines are kept unstripped and flagged (an over-strip guard).
"""

md_strip_full = """## 6. Stage 0.5 — strip footers (full run)

Once the strip samples look right, strip the rest of the corpus. Already-stripped
shards are skipped, so re-run after any disconnect until the whole corpus is done.
Only then move on to the anachronism filter below, which reads the `stripped/` layer.
"""

md_report = """## 9. Stage 4 — aggregate report

Summarizes all completed shards, ranks the top firing terms and the top footer
patterns (your audit surfaces), and writes `cleaning_report_1930s.json` + `README.md`
to the destination repo. Safe to run at any point during the run.
"""


nb = {
    "cells": [
        markdown(md_title),
        markdown(md_bootstrap),
        code_cell(code("cell1_bootstrap.py")),
        markdown(md_push),
        code_cell(code("cell2_push_scripts.py")),
        markdown(md_wipe),
        code_cell(code("cell3_wipe.py")),
        markdown(md_build),
        code_cell(code("cell4_build_list.py")),
        markdown(md_strip_dry),
        code_cell(code("cell4b_strip_footers.py")),
        markdown(md_strip_full),
        code_cell(code("cell4c_strip_all.py")),
        markdown(md_dry),
        code_cell(code("cell5_run_filter.py")),
        markdown(md_full),
        code_cell(code("cell6_run_all.py")),
        markdown(md_report),
        code_cell(code("cell7_report.py")),
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10"},
        "colab": {"provenance": [], "toc_visible": True},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

validate_notebook_shape(json.loads(read_text(OUT)))
n_code = sum(1 for c in nb["cells"] if c["cell_type"] == "code")
n_md = sum(1 for c in nb["cells"] if c["cell_type"] == "markdown")
print(f"Wrote {OUT}")
print(f"cells: {len(nb['cells'])} ({n_code} code, {n_md} markdown) - validated OK")
