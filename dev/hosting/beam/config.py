"""
Deploy-time configuration, shared by app.py and probe_app.py.

These values are read on your machine when `beam deploy` runs, not inside the
container. The probe deployment imports the same constants so that what it
rehearses -- volume name, mount path, auth mode, container env -- is the same
configuration the real deployment will use, rather than a lookalike that can
drift out of sync.
"""

# Beam derives the public URL from this. Changing it creates a NEW
# deployment at a new URL; the old one keeps running until stopped.
# VOLUME_NAME deliberately does NOT change -- the weights are already
# uploaded under that name.
APP_NAME = "bartholomew-iii"
VOLUME_NAME = "think-nano-weights"

# Absolute, and deliberately not "./nanochat": a relative mount would land next
# to the synced source tree and shadow the `nanochat` Python package.
MOUNT_PATH = "/vol/model"

# A single type, not a list. Beam refuses to deploy with
#   "Checkpoints are yet not supported between multiple GPUs"
# when CHECKPOINT_ENABLED is set and `gpu` names more than one type -- and the
# @asgi signature takes a single GpuTypeAlias anyway (only @endpoint accepts a
# list). Checkpoint restore is worth more than an availability fallback, so pin
# one and let the deploy queue if that type is briefly unavailable.
#
# Whatever you pick must satisfy two independent constraints:
#   * bf16 tensor cores, i.e. SM 80+  -> rules out T4 and V100 (see README)
#   * checkpoint restore support      -> Beam lists RTX4090, H100 and A10G
# RTX4090 is the cheapest tier Beam lists ($0.69/hr serverless), has 24 GiB
# against a ~9 GiB peak, and is on the checkpoint-restore list. A10G is not
# on the current pricing page at all, so do not name it. H100 also qualifies
# but costs 5x for a model that does not need it.
GPU = "RTX4090"

# THE cold-start fix. Beam snapshots the process -- including GPU memory --
# after on_start returns, and later cold boots restore from that image instead
# of re-reading 5.25 GiB and re-initialising CUDA.
#
# Two things to know:
#   * a snapshot takes up to 3 minutes to capture and up to 5 minutes to
#     propagate to other servers, so the first boot after each deploy is still
#     slow and the speedup appears a few minutes later;
#   * it is re-captured on every deploy, so measure with smoke_test.py ~10
#     minutes after deploying, not immediately.
CHECKPOINT_ENABLED = True

# ~10 min. Longer than the 5 min first draft: the whole point is that a reader
# who pauses to think, or a reviewer who opens the link twice, does not pay a
# second cold start. With CHECKPOINT_ENABLED the downside of guessing low is
# smaller, but idle time is cheap relative to a bad first impression.
KEEP_WARM_SECONDS = 600

# One request at a time per container: a single model replica cannot usefully
# interleave them, and queueing is more honest than thrashing.
CONCURRENT_REQUESTS = 1

# --- Autoscaling -------------------------------------------------------------
# Each container is a full model replica, so scaling out is scaling GPUs.
#
# MIN_CONTAINERS = 0 means everything scales to zero and readers occasionally
# pay a cold start. Set it to 1 to eliminate cold starts entirely -- one
# RTX4090 runs continuously at $0.69/hr, about $16.50/day. That is the right
# trade for the week a paper is under review, and the wrong one for the other
# fifty-one. If you do set it to 1, `beam deployment stop` the *previous*
# versions after redeploying, or you will pay for each of them.
MIN_CONTAINERS = 0

# The spend ceiling. With TASKS_PER_CONTAINER = 1, Beam adds a replica once more
# than one request is queued, up to this many.
MAX_CONTAINERS = 3
TASKS_PER_CONTAINER = 1

# False = public URL, no bearer token. Flip to True for a private demo.
AUTHORIZED = False

# Headroom for staging the checkpoint through host RAM before it lands on the GPU.
# Beam's default is 128 MB, which is nowhere near enough.
MEMORY = "16Gi"
CPU = 2

# Which chat UI to serve at GET /. Both files live in this folder; switching is
# a one-word change plus a deploy, and the old one stays available to roll back
# to. ui_updated.html carries the Unbounded Labs styling.
UI_FILE = "ui_updated.html"

# The experiment this deployment serves. Derived from
#   configs/base/Think.Unbounded-d32-v2mix-cont.json  (experiment_id)
#   configs/sft/pre1930-curriculum-c3-robust-v2.json  (experiment_suffix)
# which scripts/experiment.py joins with a hyphen. fetch_checkpoint.py uses
# these to find the right files on HuggingFace.
BASE_EXPERIMENT_ID = "Think.Unbounded-d32-v2mix-cont"
MODEL_TAG = "Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2"

# Read inside the container. Change these to re-tune without touching code.
CONTAINER_ENV = {
    # Where the checkpoint lives inside the volume. The folder is named after
    # the model tag so a second model can be uploaded beside it without either
    # overwriting the other, and switching between them is an env change.
    "NANOCHAT_CHECKPOINT_DIR": f"{MOUNT_PATH}/{MODEL_TAG}",
    "NANOCHAT_TOKENIZER_DIR": f"{MOUNT_PATH}/{MODEL_TAG}/tokenizer",
    # Empty => whichever step is highest on the volume. Pin it to an exact step
    # before the URL goes in a paper: otherwise dropping a newer checkpoint into
    # the volume silently changes what the citation points at.
    "NANOCHAT_STEP": "",
    # Set this once the persona file is on the volume, e.g.
    # f"{MOUNT_PATH}/pre1930-companion.txt". The C3-robust SFT was trained with
    # a system prompt; serving without one gives you a different model than your
    # evals measured.
    "NANOCHAT_SYSTEM_PROMPT_FILE": "",
    # Unpunctuated-input handling (nanochat/prompt_shaping.py). Both default off
    # so the deployment keeps behaving exactly as the evals measured until you
    # deliberately turn one on, and both are independent.
    #   NANOCHAT_FIX_PUNCTUATION: "1" appends the missing sentence-final mark
    #     to each visitor turn before it is tokenized. Which mark is a heuristic
    #     ("." unless the clause opens like a question). Free: no extra context,
    #     no extra latency, and the visitor's casing is left alone.
    #   NANOCHAT_PRIMING_TURNS: "default" for the built-in exchange, or a path to
    #     a JSON file on the volume (upload configs/priming_turns/*.json beside
    #     the persona file). Splices an invisible opening exchange whose user
    #     turn is unpunctuated, so the model sees the shape answered well. Costs
    #     ~40-80 tokens of context on every request.
    "NANOCHAT_FIX_PUNCTUATION": "",
    "NANOCHAT_PRIMING_TURNS": "",
    # Sampling defaults; each is overridable per request.
    "NANOCHAT_TEMPERATURE": "0.8",
    "NANOCHAT_TOP_K": "50",
    "NANOCHAT_MAX_TOKENS": "512",
    "NANOCHAT_REPETITION_PENALTY": "1.0",
    "NANOCHAT_REPETITION_WINDOW": "64",
    # Quieter logs, and no stray network calls from the HF stack on cold start.
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "HF_HUB_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
}
