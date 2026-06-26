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

# Below this N, filtered-out items are backfilled (regenerated) to hold N constant.
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

# Provider-agnostic OpenAI-compatible LLM endpoint. Defaults = OpenCode Zen (verified:
# key works directly, no CLI install). Override any of these via env.
# Filter judge (cheap classification): DeepSeek V4 Flash. Backfill/rewrite: GLM 5.2.
LLM_BASE_URL = os.environ.get("VINTAGE_LLM_BASE_URL", "https://opencode.ai/zen/v1")
LLM_API_KEY_ENV = os.environ.get("VINTAGE_LLM_API_KEY_ENV", "OPENCODE_API_KEY")
FILTER_MODEL = os.environ.get("VINTAGE_FILTER_MODEL", "deepseek-v4-flash")
REWRITE_MODEL = os.environ.get("VINTAGE_REWRITE_MODEL", "glm-5.2")
