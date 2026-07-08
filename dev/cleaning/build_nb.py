import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CELLS_DIR = ROOT / "cells"
OUT = ROOT / "think_dataset_clean.ipynb"


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


md_title = """# Vintage corpus cleaning: `think-dataset` -> `think-dataset-clean`

This notebook refines [`jbduran/think-dataset`](https://huggingface.co/datasets/jbduran/think-dataset) and writes cleaned shards to [`jbduran/think-dataset-clean`](https://huggingface.co/datasets/jbduran/think-dataset-clean).

It follows the practical filters described in Michael Hla's *Machina Mirabilis* write-up and `gpt1900` scripts:

- Blog: https://michaelhla.com/blog/machina-mirabilis.html
- Scripts: https://github.com/michaelhla/gpt1900/tree/master/scripts/pre1900_scripts

Your settled design choices are baked in:

- Keep whole books as single rows.
- Skip Hla's strict post-1900 physics keyword filter, because this corpus intentionally keeps material through the 1930s.
- Use a moderate GPT-2 token log-prior filter: p2.5-p97.5, targeting roughly 5% prior-filter removal.
- Preserve shard shape: each source `shard_XXXXX.parquet` becomes the same destination shard name.

## Pipeline summary

| Stage | Technique | Expected removal | Time estimate | Resumable? |
|---|---:|---:|---:|---:|
| 0 | Guarded clean command: delete generated destination shards/stats | n/a | <1 min | n/a |
| A | Boilerplate and OCR cleanup | mostly shrinks text; rare drops | included in Stage 2 | yes |
| B | Structural filters: length, printable ratio, OCR artifacts | <1-2% | included in Stage 2 | yes |
| C | GPT-2 token log-prior filter | ~5% | included in Stage 2 | yes |
| 1 | Build or load cached prior table and thresholds | n/a | 10-20 min once | yes |
| 2 | Main shard-by-shard cleaning loop | net ~6-10% docs | ~3-5 h CPU Colab | yes |
| 3 | Aggregate report and provenance upload | n/a | 2-5 min | yes |

The notebook records per-shard document counts, character counts, and removals by reason, then uploads an aggregate `cleaning_report.json` to the output dataset.
"""

md_setup = """## Setup and configuration

Installs the Colab dependencies, authenticates to Hugging Face, and defines all thresholds.

Use a Hugging Face write token with access to the `jbduran` namespace. In Colab, the cleanest path is to add it as a secret named `HF_TOKEN`.
"""

md_stage0 = """## Stage 0: Clean command

This is the requested start-from-scratch command. It deletes generated `shard_*.parquet` files and matching `stats/shard_*.json` files from the destination repo.

It is guarded by `CONFIRM_WIPE = False` in the config cell. Leave it false for normal resume behavior. Set it to true only when you want to rebuild the destination dataset from scratch.
"""

md_filters = """## Filter library: Stages A and B

This cell defines the text cleanup and structural filters. It is a compact Colab port of the useful Hla `hf_clean.py` ideas for your one-column book dataset.

### Stage A: boilerplate and OCR cleanup

What it does:

- Removes Google Books, HathiTrust, Project Gutenberg, library-stamp, barcode, call-number, and institutional seal fragments.
- Normalizes unicode and common historical/OCR ligatures.
- Rejoins line-break hyphenation and reflows hard-wrapped lines into paragraphs.
- Removes short front-matter stamp lines that often survive after an OCR title/byline.

Pros: removes high-frequency low-information text that small models tend to memorize. It also makes the prior filter less likely to learn boilerplate as "normal."

Cons: regex cleanup is heuristic. It can miss novel OCR corruption and can rarely trim an unusual title page too aggressively.

Expected effect: usually 1-5% fewer characters, with documents dropped only when cleanup leaves too little text.

### Stage B: structural filters

What it does:

- Drops very short raw documents.
- Drops documents with low printable-character ratio.
- Drops documents with many OCR artifact patterns.
- Drops documents that become too short after cleanup.

Pros: cheap, explainable, and catches broken records before expensive tokenization.

Cons: fixed thresholds are blunt and do not understand genre.

Expected removal: typically <1-2%, since the source has already had an initial rough filter.
"""

md_stage1 = """## Stage 1: Build or load GPT-2 log-prior thresholds

This implements Hla's `prior_filter.py` pattern: tokenize a sample with the GPT-2 tokenizer, count corpus token frequencies, convert them to `log2(count / total)` priors, and score each document by mean token log-prior.

Motivation: very low mean prior often flags rare-token OCR garbage or non-English fragments; very high mean prior often flags repetitive boilerplate or catalog-like text. Good prose tends to sit in the middle.

Pros: no model inference, much cheaper than perplexity filtering, and good at catching statistical outliers that regexes miss.

Cons: it is a quality proxy, not a semantic judge. A legitimate unusual text can be clipped if the band is too narrow.

This notebook uses p2.5-p97.5 for a moderate target of about 5% prior-filter removal. The prior table and thresholds are cached under `_prior/` in the destination repo, so reconnects and reruns load them instead of recomputing.
"""

md_stage2 = """## Stage 2: Main resumable shard loop

For every source shard, the notebook downloads the parquet, cleans and filters every whole-book row, writes a same-named output shard, and uploads the shard plus its stats JSON in one commit.

Resume behavior: if `shard_XXXXX.parquet` already exists in the destination repo, the loop skips it. A crash or Colab disconnect costs at most the shard currently in flight.

Each shard stats file records:

- input documents
- kept documents
- removals by reason
- raw characters
- cleaned characters before prior filtering
- kept characters

Expected result: same shard count and names as the original dataset, with roughly 90-94% of documents/characters retained depending on the actual source distribution.
"""

md_stage3 = """## Stage 3: Aggregate report and provenance

Reads all uploaded per-shard stats, prints exact removal counts and percentages, writes `cleaning_report.json`, and updates the destination repo README.

This stage is safe to run mid-pipeline. It reports whatever shard set has completed so far.
"""

md_footer = """## Notes for reruns

- Disconnected or crashed: rerun the notebook; Stage 1 loads cached priors and Stage 2 skips completed shards.
- Start over: set `CONFIRM_WIPE = True` and run Stage 0. Also set `FORCE_RECOMPUTE_PRIOR = True` if you changed prior sampling or thresholds.
- Too aggressive or too weak: adjust `PRIOR_BAND`. `(1, 99)` removes about 2%; `(5, 95)` removes about 10%.
- Output format: single `text` column parquet shards, same shard names as source, ZSTD compression.
"""


nb = {
    "cells": [
        markdown(md_title),
        markdown(md_setup),
        code_cell(code("cell1_install.py")),
        code_cell(code("cell2_config.py")),
        markdown(md_stage0),
        code_cell(code("cell3_wipe.py")),
        markdown(md_filters),
        code_cell(code("cell4_cleanlib.py")),
        markdown(md_stage1),
        code_cell(code("cell5_prior.py")),
        markdown(md_stage2),
        code_cell(code("cell6_main.py")),
        markdown(md_stage3),
        code_cell(code("cell7_report.py")),
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
