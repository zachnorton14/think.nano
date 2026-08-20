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
#   * checkpoint restore that actually works -> see below, and do not trust the
#     published support list on this one
#
# DO NOT CHANGE THIS TO RTX4090. It was RTX4090 from 2026-08-18 10:05 (commit
# 5be7ae6) until 2026-08-19, and in that window CHECKPOINT_ENABLED restore was
# broken: a restored container came back with its Python heap intact and its
# CUDA context dead, so /health answered 200 in a millisecond while the first
# real generation hung forever. Ten idle minutes after each deploy the container
# scaled to zero, the next boot restored instead of booting, and the deployment
# went dark -- roughly fifteen minutes after every deploy, four times running.
#
# The switch was made on a wrong premise ("A10G is not on the current pricing
# page"). It is: `beam machine list` shows A10G as available under *Serverless*,
# which is what this deployment uses. The empty cell is the On-demand column,
# a different product. Beam's docs do list RTX4090 as checkpoint-capable; it
# empirically is not, at least here. A10G is a datacenter card and RTX4090 is a
# consumer one, and CUDA state save/restore is exactly the kind of feature that
# splits along that line.
#
# Everything else was held constant across the break: identical image spec,
# byte-identical on_start, unchanged MEMORY/CPU/KEEP_WARM_SECONDS/MIN_CONTAINERS.
# One variable moved.
#
# H100 also qualifies but costs 5x for a model that does not need it.
GPU = "A10G"

# THE cold-start fix, and it only works on the right GPU -- see the GPU note.
#
# Beam snapshots the process -- including GPU memory -- after on_start returns,
# and later cold boots restore from that image instead of re-reading 5.25 GiB
# and re-initialising CUDA. So there are two boot paths, and they can fail
# independently:
#
#   * the FIRST boot after a deploy is a real boot, ~150s on this volume;
#   * every LATER cold boot restores the snapshot, which is the whole point.
#
# With MIN_CONTAINERS = 0 and KEEP_WARM_SECONDS = 600, the restore path is first
# taken ten idle minutes after a deploy. That means **a fresh deploy tells you
# nothing about whether this works.** Test it by idling the container out --
# `ops/redeploy.py --cold-start-test` does exactly that, and it is the only
# check in the whole setup that exercises this.
#
# Two things to know about timing:
#   * a snapshot takes up to 3 minutes to capture and up to 5 minutes to
#     propagate, so the first cold start after a deploy may still be slow;
#   * it is NOT reliably re-captured on every deploy -- see below.
#
# THE SNAPSHOT OUTLIVES A REDEPLOY. The cache is keyed by app name, not by
# version: Beam mounts it at /checkpoint-model-cache-<APP_NAME>, and a new
# version can restore a *previous* version's process image. On 2026-08-20 that
# happened in the open: v7 deployed with GPU = "A10G", and the container serving
# it reported "NVIDIA GeForce RTX 4090" from /health because it had restored
# v6's process rather than booting. Everything /health reads out of
# on_start_value -- gpu_name, booted_at, vram, boot_seconds -- was replayed
# memory describing a deployment that had already been replaced.
#
# The evidence was arithmetic: process_age_seconds was 1694 while the container
# it lived in had been up for 947 seconds. A process cannot predate its own
# container by twelve minutes, so that container never ran on_start. That
# comparison is the only externally visible way to tell the two boot paths
# apart, and `ops/redeploy.py` makes it after every deploy.
#
# Redeploying does not clear a stale image. Force a real boot instead:
#
#     python dev/hosting/beam/ops/redeploy.py --bust-snapshot
#
# which deploys once with CHECKPOINT_ENABLED = False, verifies the container
# really booted, then deploys again with it back on so the next snapshot is
# captured on the GPU you actually meant.
#
# If a restore ever comes back broken again, the signature is: /health answers
# 200 in milliseconds while generation hangs forever, because a restored process
# keeps its Python heap and loses its CUDA context. /health now guards against
# that -- it touches the GPU before claiming health, and reports
# process_age_seconds so you can tell a restored process from a booted one.
#
# If cold starts matter more than the money, MIN_CONTAINERS = 1 below removes
# them entirely and does not depend on any of this working.
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
    # Empty => whichever step is highest on the volume. Pinned, because the URL
    # is public: dropping a newer checkpoint into the volume would otherwise
    # silently change what a citation points at. 42 is what is deployed and what
    # the volume holds; `ops/redeploy.py --step auto` moves it to the newest.
    "NANOCHAT_STEP": "42",
    # The C3-robust SFT was trained with a system prompt, so serving without one
    # gives you a different model than your evals measured. This was blank in git
    # for a long time while every deployment ran with it set, because both Colab
    # notebooks wrote the path in at deploy time and nothing wrote it back here.
    # Committed now: what is in this file is what ships.
    "NANOCHAT_SYSTEM_PROMPT_FILE": f"{MOUNT_PATH}/pre1930-companion.txt",
    # Unpunctuated-input handling (nanochat/prompt_shaping.py). Both default off
    # so the deployment keeps behaving exactly as the evals measured until you
    # deliberately turn one on, and both are independent.
    #   NANOCHAT_FIX_PUNCTUATION: "1" appends a period to each visitor turn
    #     that ends without punctuation, before it is tokenized. Free: no extra
    #     context, no extra latency, and nothing the visitor typed is edited.
    #   NANOCHAT_PRIMING_TURNS: "default" for the built-in exchange, or a path to
    #     a JSON file on the volume (upload configs/priming_turns/*.json beside
    #     the persona file). Splices an invisible opening exchange whose user
    #     turn is unpunctuated, so the model sees the shape answered well. Costs
    #     ~40-80 tokens of context on every request.
    # A/B against the live endpoint (prompt_ab.py, 2026-08-19): bare collapsed
    # 3/6, repaired-only still collapsed 2/6, primed was clean 6/6 -- so priming
    # ships on and punctuation repair stays off, one variable at a time.
    "NANOCHAT_FIX_PUNCTUATION": "",
    "NANOCHAT_PRIMING_TURNS": "default",
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
