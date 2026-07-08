"""Shared configuration for the 1930s anachronism-filter pipeline.

Importable with no side effects (no auth, no network, no prompts). Every stage
script imports this so settings stay in one place. Values can be overridden via
environment variables so the notebook/CLI can tweak a run without editing code.
"""
import os
from pathlib import Path


def _env(name, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _env_int(name, default):
    v = os.environ.get(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


# --- Repositories -----------------------------------------------------------
# SRC_REPO / SRC_PREFIX = where the FILTER (run_filter.py) reads its input. After
# the footer-strip stage this points at the stripped layer:
#   SRC_REPO=jbduran/think-dataset-clean-1930s  SRC_PREFIX=stripped
SRC_REPO = _env("SRC_REPO", "jbduran/think-dataset-clean")
SRC_PREFIX = _env("SRC_PREFIX", "")  # subfolder in SRC_REPO to read shards from ("" = root)
DST_REPO = _env("DST_REPO", "jbduran/think-dataset-clean-1930s")

# --- Footer-strip stage (Stage 0.5) -----------------------------------------
# Reads the clean corpus, removes footer/boilerplate lines, writes stripped shards
# under STRIP_PREFIX/ in DST_REPO. The filter then reads that stripped layer.
STRIP_SRC_REPO = _env("STRIP_SRC_REPO", "jbduran/think-dataset-clean")
STRIP_PREFIX = _env("STRIP_PREFIX", "stripped")   # output subfolder for stripped shards
# Guardrails against over-stripping:
FOOTER_MAX_LINE_CHARS = _env_int("FOOTER_MAX_LINE_CHARS", 200)   # only strip short lines,
#   unless a footer pattern covers most of the line (see footer_lib).
FOOTER_MAX_DOC_LINE_FRAC = float(_env("FOOTER_MAX_DOC_LINE_FRAC", "0.30"))  # if a doc would
#   lose more than this fraction of its lines, keep it UNSTRIPPED and flag it.

# --- Cutoff / filter policy -------------------------------------------------
CUTOFF_YEAR = _env_int("CUTOFF_YEAR", 1930)      # anything AFTER this is anachronistic
MIN_BANNED_HITS = _env_int("MIN_BANNED_HITS", 1)  # 1 = Hla's rule: one hit scraps the doc

# --- Scan window ------------------------------------------------------------
# Anachronistic content (modern forewords, footnotes, copyright/ISBN pages,
# digitization boilerplate) sits at the FRONT of a book, occasionally the back --
# essentially never buried mid-chapter. Scanning a capped head + tail keeps
# per-document cost bounded even for multi-MB OCR books. Set SCAN_CHARS=0 to scan
# the entire document (much slower on big books).
SCAN_CHARS = _env_int("SCAN_CHARS", 300_000)      # head window; 0 => whole doc
SCAN_TAIL_CHARS = _env_int("SCAN_TAIL_CHARS", 50_000)  # tail window; 0 => none

# --- Output parquet settings (match source so shards stay ~same size) -------
ROW_GROUP_SIZE = _env_int("ROW_GROUP_SIZE", 64)
COMPRESSION = _env("COMPRESSION", "zstd")
COMPRESSION_LEVEL = _env_int("COMPRESSION_LEVEL", 3)

# --- Run controls -----------------------------------------------------------
# Process at most this many shards per invocation (0 => all remaining). Handy for
# a first-shard dry run: DRY_RUN_LIMIT=1 python scripts/run_filter.py
DRY_RUN_LIMIT = _env_int("DRY_RUN_LIMIT", 0)
FORCE_REBUILD_LIST = _env("FORCE_REBUILD_LIST", "0") == "1"

# Upload batching. Each HF commit has fixed latency (~40s), which dominates the
# per-shard time. Committing BATCH_SIZE shards' files in ONE commit amortizes that
# across the whole batch -- e.g. 20 shards/commit turns 473 commits into ~24.
# A crash loses only the CURRENT (uncommitted) batch's uploads; those shards are
# simply reprocessed on resume (they were never written to the repo), so resume
# stays correct. Set BATCH_SIZE=1 to commit per shard (the old behavior).
BATCH_SIZE = max(1, _env_int("BATCH_SIZE", 20))

# --- Local working directories ----------------------------------------------
WORK_DIR = Path(_env("WORK_DIR", "/content/think_1930s_work"))
SRC_CACHE = WORK_DIR / "source"
OUT_DIR = WORK_DIR / "out"
BANNED_DIR = WORK_DIR / "banned"
STRIP_OUT_DIR = WORK_DIR / "stripped"


def ensure_dirs():
    for d in (SRC_CACHE, OUT_DIR, BANNED_DIR, STRIP_OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
