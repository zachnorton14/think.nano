"""Static config for the vintage-CORE adaptation pipeline.

Verdict axis = ANACHRONISM only (see dev/VINTAGE_CORE_BENCHMARK.md). For Artifact A
(`vintage-core-filtered`) the verdict mainly decides: dropped vs included, and how
aggressive the filter prompt should be. Register REWRITE of survivors is Artifact C.
"""
import os

# Location of the upstream CORE eval bundle (downloaded by scripts/base_eval.py).
EVAL_BUNDLE_DIR = os.path.expanduser("~/.cache/nanochat/eval_bundle")

# Where adapted bundles are written.
OUT_FILTERED = os.path.expanduser("~/.cache/nanochat/vintage-core-filtered")
OUT_REWRITTEN = os.path.expanduser("~/.cache/nanochat/vintage-core-rewritten")

# Tasks excluded entirely (cannot be made fair / no construct value).
DROP = {"bigbench_cs_algorithms", "bigbench_dyck_languages"}

# If a benchmark's KEPT count (after regex+LLM filtering) falls below this, it is
# eligible for backfill (regenerate replacements to restore N). Keyed to FINAL N, not original.
BACKFILL_MAX_N = 1300

# Per-task verdict (anachronism axis). REWRITE+FILTER tasks are FILTER-ONLY in Artifact A.
VERDICT = {
    "squad": "REWRITE+FILTER",
    "boolq": "REWRITE+FILTER",
    "coqa": "REWRITE+FILTER",
    "copa": "KEEP",
    "piqa": "REWRITE+FILTER",
    "commonsense_qa": "KEEP",
    "openbook_qa": "REWRITE",
    "jeopardy": "FILTER",
    "bigbench_qa_wikidata": "FILTER",
    "arc_easy": "FILTER",
    "arc_challenge": "FILTER",
    "bigbench_operators": "KEEP",
    "bigbench_dyck_languages": "DROP",
    "bigbench_cs_algorithms": "DROP",
    "bigbench_repeat_copy_logic": "REWRITE",
    "agi_eval_lsat_ar": "KEEP",
    "lambada_openai": "REWRITE",
    "hellaswag": "REWRITE",
    "hellaswag_zeroshot": "REWRITE",
    "winograd": "KEEP",
    "winogrande": "KEEP",
    "bigbench_language_identification": "KEEP",
}

# OpenCode (same OPENCODE_API_KEY for both catalogs). Per-stage endpoint + model:
#   Filter judge -> FREE `deepseek-v4-flash-free` on the **Zen** endpoint (no credits needed).
#   Backfill(A) + rewrite(C) -> `glm-5.2` on the **Go** endpoint (subscription). No Opus.
LLM_API_KEY_ENV = os.environ.get("VINTAGE_LLM_API_KEY_ENV", "OPENCODE_API_KEY")
FILTER_BASE_URL = os.environ.get("VINTAGE_FILTER_BASE_URL", "https://opencode.ai/zen/v1")
FILTER_MODEL = os.environ.get("VINTAGE_FILTER_MODEL", "deepseek-v4-flash-free")
# Fallback when the FREE Zen endpoint throttles: paid OpenCode Go deepseek-v4-flash
# (same key; subscription quota). Auto-engaged per-call after primary retries fail.
FILTER_FALLBACK_BASE_URL = os.environ.get("VINTAGE_FILTER_FALLBACK_BASE_URL", "https://opencode.ai/zen/go/v1")
FILTER_FALLBACK_MODEL = os.environ.get("VINTAGE_FILTER_FALLBACK_MODEL", "deepseek-v4-flash")
REWRITE_BASE_URL = os.environ.get("VINTAGE_REWRITE_BASE_URL", "https://opencode.ai/zen/go/v1")
REWRITE_MODEL = os.environ.get("VINTAGE_REWRITE_MODEL", "glm-5.2")

# Review artifacts live IN THE REPO so they are easy to open and inspect.
REVIEW_DIR = os.path.join(os.path.dirname(__file__), "review")
