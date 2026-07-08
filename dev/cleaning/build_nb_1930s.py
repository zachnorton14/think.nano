import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CELLS_DIR = ROOT / "cells_1930s"
OUT = ROOT / "think_dataset_clean_1930s.ipynb"


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")


def code(fname: str) -> str:
    return read_text(CELLS_DIR / fname)


def cell(cell_type: str, source: str) -> dict:
    return {
        "cell_type": cell_type,
        "metadata": {},
        "source": source.splitlines(keepends=True),
        **({"execution_count": None, "outputs": []} if cell_type == "code" else {}),
    }


def markdown(source: str) -> dict:
    return cell("markdown", source)


def code_cell(source: str) -> dict:
    return cell("code", source)


def validate_notebook_shape(nb: dict) -> None:
    required = {"cells", "metadata", "nbformat", "nbformat_minor"}
    missing = required - set(nb)
    if missing:
        raise ValueError(f"Notebook is missing required keys: {sorted(missing)}")
    if nb["nbformat"] != 4:
        raise ValueError("Notebook nbformat must be 4")
    for i, c in enumerate(nb["cells"]):
        if c.get("cell_type") not in {"markdown", "code"}:
            raise ValueError(f"Cell {i} has invalid cell_type")
        if "source" not in c:
            raise ValueError(f"Cell {i} is missing source")


md_title = """# Anachronism filter: `think-dataset-clean` -> `think-dataset-clean-1930s`

This notebook applies an **anachronism keyword filter** to the already-cleaned corpus
[`jbduran/think-dataset-clean`](https://huggingface.co/datasets/jbduran/think-dataset-clean)
and writes the result to
[`jbduran/think-dataset-clean-1930s`](https://huggingface.co/datasets/jbduran/think-dataset-clean-1930s)
(created automatically on first run).

It closes a gap the previous notebook does not cover: a book *published* before 1930 can still
contain modern content -- an editor's foreword, a modern footnote, or reprint/digitization
boilerplate -- that mentions things which did not exist yet. Michael Hla calls out exactly this
failure mode (a translator's foreword in a Boltzmann book that mentioned Einstein/relativity):

- Blog: https://michaelhla.com/blog/machina-mirabilis.html
- Scripts: https://github.com/michaelhla/gpt1900/tree/master/scripts/pre1900_scripts

This is Hla's cheapest filter -- a compiled-regex sweep per document, no tokenization -- so the
full pass over the corpus is minutes-to-about-an-hour, not the many hours the log-prior stage took.

## Settled design choices

- **Cutoff is after 1930** (1930 and earlier is kept). The seed lists
  ([croqaz/vintage-ft-v1 `banned.txt`](https://huggingface.co/datasets/croqaz/vintage-ft-v1/blob/main/banned.txt)
  and Hla's physics keywords) target a **1900** cutoff, so their entries for radio, aeroplane,
  Einstein, relativity, quantum, X-ray, etc. are legitimate by 1930 and are **removed via an
  allow-list** before use.
- **Drop the whole document** on any hit (Hla's "one Einstein = scrapped" rule).
- **Conservative / high-precision**: only unambiguously post-1930 terms are banned; borderline
  words (television, plastic, rocket) are kept. The upstream GPT-2 log-prior filter is the backstop.
- **Keyword pass only**: no re-tokenization, no structural re-run -- the input is already clean.
- **Whole books preserved unchanged**; only whole documents are ever removed.
- **Same shard shape**: each source `shard_XXXXX.parquet` becomes the same destination shard name.

## Pipeline summary

| Stage | Cell | Technique | Expected removal | Time estimate | Resumable? |
|---|---|---|---:|---:|---:|
| 0 | Clean command | Guarded delete of generated shards/stats/hits (and optionally the banned list) | n/a | <1 min | n/a |
| 1 | Build banned list | Curate seed (croqaz + Hla) -> strip pre-1931-legit terms via allow-list -> add post-1930 terms + format-tell regexes; count and upload to HF | n/a | <1 min (cached after) | yes (cached on HF) |
| 2 | Filter functions | `scan_text` (one alternation regex + format tells) and `should_drop` (Hla's rule) | n/a | instant | n/a |
| 3 | Main shard loop | For each shard: scan every doc, drop whole docs with hits, write shard + stats + per-shard hit log | ~1-5% docs (audit the hit log) | ~5-60 min for the full corpus | yes (per shard) |
| 4 | Aggregate report | Sum per-shard stats, rank which terms fired, upload report + README | n/a | 2-5 min | yes |

Every dropped document is logged per shard in `hits/shard_*.jsonl` (which terms matched which doc),
and the final report ranks which banned terms actually fired -- the main surface for auditing
false positives.
"""

md_setup = """## Setup and configuration

Installs Colab dependencies, authenticates to Hugging Face, defines the cutoff/thresholds, and
**creates the destination dataset repo** (`create_repo(..., exist_ok=True)` -- a no-op on later runs).

Use a Hugging Face **write** token with access to the `jbduran` namespace. In Colab, add it as a
secret named `HF_TOKEN`. No GPT-2 tokenizer is needed for this notebook.
"""

md_stage0 = """## Stage 0: Clean command (start from scratch)

Deletes generated `shard_*.parquet`, `stats/shard_*.json`, and `hits/shard_*.jsonl` files (and,
if `WIPE_BANNED_LIST = True`, the `_banned/` list) from the destination repo.

Guarded by `CONFIRM_WIPE = False` in the config cell. Leave it false for normal resume behavior;
set it true only when you want to rebuild the destination dataset from scratch.
"""

md_stage1 = """## Stage 1: Build (or load) the banned list

This is the heart of the notebook. It constructs the list of terms whose presence marks a document
as post-1930, then uploads it to `_banned/` in the destination repo.

**How the list is built:**

1. **Seed** -- an embedded set of post-1900 anachronisms condensed from croqaz's `banned.txt` (its
   D1 "hard veto" list) and Hla's post-1900 physics keywords. Embedded rather than fetched so the
   notebook is reproducible and offline-safe.
2. **Allow-list (`ALLOW_1930`)** -- terms that are legitimate at a **1930** cutoff and are therefore
   **removed** from the seed: aviation (aeroplane, aircraft, airport), comms/media (radio, wireless,
   telephone, cinema, phonograph), and the physics that is native to the 1900s-1930s (Einstein,
   relativity, quantum mechanics, photon, electron, atom, isotope, X-ray, radioactivity). This is
   the same reasoning that led you to skip Hla's physics filter in the first notebook.
3. **Extra post-1930 terms (`EXTRA_1930_BANNED`)** -- unambiguously post-1930 additions the seed may
   miss: neutron (1932), positron (1932), deuterium (1931), nuclear fission (1938), cyclotron (1932),
   electron microscope (1931-33), transistor, computer/internet-era terms, WWII/Cold-War geopolitics,
   NASA/FBI/CIA, ISBN, xerox, etc.
4. **Format tells (regex)** -- extremely high-precision markers of modern reprints/digitizations
   regardless of topic: `(c) 19[3-9]\\d`/`20\\d\\d` copyright dates, `ISBN`, `www.`, `http(s)://`,
   `*.com`, Library of Congress cataloging-in-publication, "printed in the United States of America",
   Project Gutenberg license phrasing, email addresses.

**Final list** = (seed - allow-list) + extra. It is deduped, lowercased, sorted, **counted** (the
total is printed and stored), and uploaded with an allow-list and an audit of what was removed/added.

**Pros:** transparent, cheap, and reproducible; the allow-list makes the 1900->1930 adjustment
explicit and auditable. **Cons:** a keyword list is blunt -- false positives are the main risk with a
late cutoff, which is why every hit is logged and the top firing terms are reported.

**Resume:** if `_banned/banned_list.txt` already exists on HF (and `FORCE_REBUILD_LIST` is false), the
cached list is loaded instead of rebuilt.
"""

md_stage2 = """## Stage 2: Filter functions

Defines `scan_text` and `should_drop`.

- `scan_text(text)` runs **one compiled whole-word alternation regex** over the entire banned term
  list (a single fast pass), plus each high-precision **format-tell** regex, and returns the distinct
  terms and kinds that matched.
- `should_drop(terms)` applies Hla's rule: drop the document when it contains at least
  `MIN_BANNED_HITS` distinct banned signals (default 1).

No text is mutated -- kept documents are written through unchanged, so this stage only ever removes
whole books. The cell ends with a self-check asserting a modern sample is dropped and a vintage
sample (radio, aeroplane, relativity, 1928) survives.
"""

md_stage3 = """## Stage 3: Main resumable shard loop

For every source shard: download the parquet, scan every whole-book row, drop documents with hits,
and write a same-named output shard plus its stats JSON and a **per-shard hit log**
(`hits/shard_XXXXX.jsonl`, one line per dropped document listing the terms that matched) -- all in a
single commit.

**Resume:** if `shard_XXXXX.parquet` already exists in the destination repo, the shard is skipped. A
crash or Colab disconnect costs at most the shard in flight.

**Per-item ETA:** after each shard the loop prints kept/removed counts, elapsed time, a running
average of seconds/shard, and an ETA for the remaining shards, plus that shard's top firing terms.

**Dry run:** `DRY_RUN_LIMIT` defaults to `1` -- process a single shard first, inspect its hit log on
HF to confirm the hits are real anachronisms (not false positives), then set `DRY_RUN_LIMIT = None`
and re-run to process the rest (completed shards are skipped).

**Shard sizes** stay close to the source because only whole documents are dropped and each shard is
re-written with the same compression and row-group settings.
"""

md_stage4 = """## Stage 4: Aggregate report and provenance

Reads all uploaded per-shard stats, sums the counts, and **ranks which banned terms actually fired**
-- the primary audit surface for spotting a term that is over-removing. Writes
`cleaning_report_1930s.json` and refreshes the destination README, including the total banned-list
size and the top firing terms.

Safe to run mid-pipeline: it reports whatever shard set has completed so far.
"""

md_footer = """## Notes for reruns

- **Disconnected or crashed:** rerun the notebook; Stage 1 loads the cached banned list and Stage 3
  skips completed shards.
- **Audit before committing to the full run:** keep `DRY_RUN_LIMIT = 1`, run one shard, open
  `hits/shard_00000.jsonl` on HF. If a common word over-fires, add it to `ALLOW_1930` (or remove it
  from `EXTRA_1930_BANNED`), set `FORCE_REBUILD_LIST = True`, rerun Stage 1, then continue.
- **Start over:** set `CONFIRM_WIPE = True` (and `WIPE_BANNED_LIST = True` to also drop the list) and
  run Stage 0.
- **Stricter/looser:** raise `MIN_BANNED_HITS` to require more distinct hits before dropping a doc
  (reduces false positives at the cost of some contamination risk).
- **Output format:** single `text` column parquet shards, same shard names as source, ZSTD compression.
"""


nb = {
    "cells": [
        markdown(md_title),
        markdown(md_setup),
        code_cell(code("cell1_install.py")),
        code_cell(code("cell2_config.py")),
        markdown(md_stage0),
        code_cell(code("cell3_wipe.py")),
        markdown(md_stage1),
        code_cell(code("cell_build_list.py")),
        markdown(md_stage2),
        code_cell(code("cell_filter.py")),
        markdown(md_stage3),
        code_cell(code("cell_main.py")),
        markdown(md_stage4),
        code_cell(code("cell_report.py")),
        markdown(md_footer),
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
