# Runbook

Part 1 is one-time setup. Part 2 is what you do afterwards, forever.
For *why* any of it is shaped this way, see [README.md](README.md).

Two machines are involved:

- **weights box** — anywhere the d32 SFT checkpoint lives and Python runs. The
  export is pure CPU work (`torch.load` → cast → `torch.save`) and needs about
  **9 GiB of RAM and no GPU**, so a laptop, a cheap CPU instance, or the vast.ai
  box all work. If the checkpoint only exists on HuggingFace now, pull it here.
- **deploy box** — wherever you run `beam`. Simplest is to make it the same
  machine, since it needs the repo checked out anyway.

**Everything below runs locally** through the scripts in `ops/` —
`uv tool install beam-client` and a `beam configure` is the whole setup, and
[ops/README.md](ops/README.md) has the details.

| script | for |
|---|---|
| `ops/deploy.py` | first-time setup: download, export, upload, deploy. Idempotent; a first run moves ~14 GiB and wants ~9 GiB of RAM, every later run skips straight to the deploy. |
| `ops/redeploy.py` | day-to-day: deploy this working tree, with the assumptions turned into preflight checks, and verify the result rather than trusting that `beam deploy` printed a URL. |
| `ops/debug.py` | *why* is it failing. Interrogates the **live** deployment, so run it before cleanup — a deleted one has nothing to say. Prints a pasteable bundle and a one-line reading. |
| `ops/cleanup.py` | too many deployments. Stops and deletes old versions, keeps the volume, and proves the checkpoint is intact before it touches anything. Dry-runs by default. |

(These replaced a set of `colab_*.ipynb` notebooks. The notebooks rewrote
`config.py` from their own cells on every run, and a stale copy saved in Colab
is what put RTX4090 back on a deployment that git said was A10G — that failure
mode is why nothing here rewrites `config.py` without an explicit flag.)

---

# Part 1 — Setup

### 1. Prove the export is safe  ·  weights box  ·  ~1 min

```bash
pip install torch tokenizers tiktoken rustbpe        # if not already present
python dev/hosting/beam/test_export.py
```

`nanochat/tokenizer.py` imports `tokenizers` at module scope even though this
model uses the rustbpe/tiktoken path, so anything that touches `nanochat.engine`
needs all three. (`export_bf16.py` deliberately needs only torch.)

Builds a tiny d4 model and asserts the fp32 and bf16 versions produce
bit-identical logits and identical greedy token streams, and that `fast_load.py`
matches the stock loader exactly.

**Done when:** five PASS lines. If any fail, stop — do not export the d32.

### 2. Get the checkpoint local  ·  weights box

Skip if it is already on disk. Your base config sets
`artifacts.keep_local_checkpoints: 1`, so it probably only exists on HF.
The tag is already set in `config.py`, so:

```bash
export HF_TOKEN=...
python dev/hosting/beam/fetch_checkpoint.py --out ./ckpt --list-only   # look first
python dev/hosting/beam/fetch_checkpoint.py --out ./ckpt
```

It resolves `Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2` to
`experiments/Think.Unbounded-d32-v2mix-cont/sft/<tag>/checkpoints/`, picks the
newest step that has *both* a model and a meta file, and finds the tokenizer
(checking the SFT prefix, then the base experiment, since a reused tokenizer
lands there). If nothing matches it prints the checkpoint directories that do
exist rather than guessing.

**Done when:** `./ckpt` holds `model_XXXXXX.pt`, `meta_XXXXXX.json` and
`tokenizer/tokenizer.pkl`, and it reports `training_complete: True`.

### 3. Export the serving checkpoint  ·  weights box  ·  ~2 min

```bash
python dev/hosting/beam/export_bf16.py \
  --in-dir  ./ckpt \
  --out-dir ./ckpt-bf16 \
  --tokenizer-dir ./ckpt/tokenizer
```

**Done when:** it prints roughly `8.37 GiB -> 5.25 GiB (37% smaller)` and the
reload verification passes. Note the step number — you will pin it in step 9.

### 4. Confirm the export still talks  ·  weights box (needs a GPU)

```bash
python -m scripts.chat_cli --checkpoint-dir ./ckpt-bf16 \
                           --tokenizer-dir ./ckpt-bf16/tokenizer
```

Skip only if no GPU is available; step 12 catches the same failure, just later
and more expensively.

**Done when:** it answers a question in recognisable pre-1930s voice.

### 5. Install and authenticate Beam  ·  deploy box  ·  ~2 min

```bash
uv tool install beam-client
beam config create          # paste the token from the Beam dashboard
beam machine list           # check RTX4090 is available
```

**Done when:** `beam machine list` returns without an auth error.

### 6. Add the ignore file  ·  deploy box  ·  10 sec

```bash
cp dev/hosting/beam/beamignore.template .beamignore
```

Not optional. Beam syncs the working directory on every deploy; without this it
uploads `.git` and everything else in the tree. It must sit at the **repo root**,
because the container needs `nanochat/` on its path — deploying from
`dev/hosting/beam/` alone would not work.

**Done when:** `.beamignore` exists next to `pyproject.toml`.

### 7. Create the volume and upload  ·  deploy box  ·  ~5 min

The volume folder is named after the model tag, so a second model can sit beside
this one and switching between them is an env change rather than an overwrite.

```bash
TAG=Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2

beam volume create think-nano-weights
beam cp ./ckpt-bf16 beam://think-nano-weights/$TAG
beam cp configs/system_prompts/pre1930-companion.txt beam://think-nano-weights/
```

Target layout, all under the volume root:

```
<TAG>/model_XXXXXX.pt
<TAG>/meta_XXXXXX.json
<TAG>/tokenizer/tokenizer.pkl
pre1930-companion.txt
```

Note the volume is `think-nano-weights` while the app is `bartholomew-iii`.
That is deliberate: the weights were uploaded under the old name and renaming
the volume would point the deployment at storage that does not exist.

**Done when:** `beam ls think-nano-weights/$TAG` and
`beam ls think-nano-weights/$TAG/tokenizer` both show the files above. Wait 60
seconds before the next step — volume writes take that long to become visible to
other containers.

No Docker image is involved here, and none is needed anywhere in this setup —
see the note at the end of Part 2.

### 8. Point the config at the persona  ·  deploy box

In [config.py](config.py), inside `CONTAINER_ENV`:

```python
"NANOCHAT_SYSTEM_PROMPT_FILE": "/vol/model/pre1930-companion.txt",
```

The C3-robust SFT was trained with a system prompt. Serving without one gives
you a different model than your evals measured.

### 9. Pin the step  ·  deploy box

Also in `CONTAINER_ENV`:

```python
"NANOCHAT_STEP": "9600",   # whatever step 3 reported
```

Leaving it blank means "highest step on the volume", so a future upload would
silently change what a published link points at.

### 10. Dress rehearsal on CPU  ·  deploy box  ·  ~5 min, costs cents

```bash
beam deploy beam_app.py:probe_handler --name bartholomew-iii-probe   # from the repo root
python dev/hosting/beam/smoke_test.py <printed-url>
curl <printed-url>/volume
```

No GPU, no model — but it exercises the deploy pipeline, the `.beamignore`, the
volume mount, the auth setting, and whether SSE survives Beam's proxy.

**Done when:**
- the sync takes seconds, not minutes → `.beamignore` works
- `/volume` reports `"ready_for_app": true` and an empty `problems` list
- `smoke_test.py` says frames arrive incrementally → SSE is not buffered
- the URL opens in a **private browser window** without a token → public
- the UI's wake panel, streaming and footer all render

Then open the URL and click around. When satisfied:
`beam deployment list` → `beam deployment delete <probe-id>`.

### 11. Deploy for real  ·  deploy box  ·  ~10 min

```bash
beam deploy beam_app.py:handler --name bartholomew-iii   # from the repo root
```

The entrypoint is the shim at the repo root, never
`dev/hosting/beam/app.py:handler` directly -- see the Windows note in
[ops/README.md](ops/README.md) for why a subdirectory entrypoint deployed from
Windows produces a stub the container cannot import.

**Done when:** it prints a URL. Save two forms of it:

| use | URL |
|---|---|
| **for a paper / anything public** | `https://bartholomew-iii-<id>.app.beam.cloud` — no version suffix, always serves the latest deploy |
| for pinning an exact build | `https://bartholomew-iii-<id>-v1.app.beam.cloud` |

Drop the `-vN` suffix for anything you publish. Every redeploy increments the
version, so a `-v1` link in a paper freezes at your first attempt.

### 12. Smoke test the real thing  ·  deploy box  ·  ~2 min, then again after 10

```bash
python dev/hosting/beam/smoke_test.py https://bartholomew-iii-<id>.app.beam.cloud
```

**Then wait ten minutes and run it again.** `CHECKPOINT_ENABLED = True` means
Beam snapshots the container after `on_start`, but the snapshot takes up to 3
minutes to capture and up to 5 more to propagate. The first run measures an
unsnapshotted boot; the second measures what your readers will actually get.
Every redeploy resets this, so always measure late.

**Done when:** both runs pass, and you have written down the *second* cold-start
number.

### 13. Put the true number in the UI  ·  deploy box

[ui.html](ui.html) currently says *"It usually takes about 20 seconds."* Replace
that with what step 12 measured, then redeploy (step 11 again). A labelled wait
with an honest number reads as engineering; with a wrong number it reads as
broken — which is the whole point of having the panel.

---

# Part 2 — Using it

## Normal use

**Just open the URL.** First visit of a session waits ~20–40s on the wake panel;
everything after that is immediate, for 5 minutes after the last request.

**Before a demo or a talk,** open the URL yourself two minutes early. That pays
the cold start so your audience never sees it. Or `curl -s <url>/health >
/dev/null` from anywhere.

**Check what is deployed:**

```bash
curl -s https://bartholomew-iii-<id>.app.beam.cloud/health | python -m json.tool
```

Reports step, model config, val_bpb, GPU type, VRAM in use, and the container's
own boot time.

**Use it as an API:**

```bash
curl -N -X POST https://bartholomew-iii-<id>.app.beam.cloud/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"What is the wireless telegraph?"}]}'
```

Add `"stream": false` for a single JSON reply, or `"temperature"`, `"top_k"`,
`"max_tokens"`, `"repetition_penalty"` to override the defaults per request. A
leading `{"role":"system",...}` message overrides the persona for that call.

## Watching it

```bash
beam deployment list                     # id, version, status
beam logs --deployment-id <id>           # boot lines, prompts, errors
```

The boot line is worth knowing by eye:

```
[boot] ready in 24.3s (load 21.1s, warmup 3.2s, 5.25 GiB allocated)
```

If `GiB allocated` is much above 5.25 you are serving an un-exported checkpoint.

## Changing things

| you want to | do this |
|---|---|
| change the persona | edit the text file, `beam cp` it to the volume, wait 60s, redeploy |
| change sampling defaults | edit `CONTAINER_ENV` in `config.py`, redeploy |
| change the idle window | edit `KEEP_WARM_SECONDS` in `config.py`, redeploy |
| serve a different model | `fetch_checkpoint.py --model-tag <other>`, export, `beam cp` to `beam://think-nano-weights/<other-tag>`, set `MODEL_TAG` and `NANOCHAT_STEP` in `config.py`, redeploy |
| change the UI or server code | redeploy |
| roll back | the old version is still live at its `-vN` URL; redeploy the old code to make it latest again |

Redeploy is always the same command:

```bash
python dev/hosting/beam/ops/redeploy.py     # deploys the line below, then verifies it
beam deploy beam_app.py:handler --name bartholomew-iii    # from the repo root
```

The entrypoint is `beam_app.py` at the repo root because the SDK records the
handler by its defining file's path, and on Windows a path under
`dev/hosting/beam/` is recorded with backslashes — a module the Linux container
can never import (this is what killed v9 on 2026-08-20). A root-level file
deploys identically from every OS; [ops/README.md](ops/README.md) has the
details.

The unversioned URL follows the new version automatically. Note that swapping
volume contents alone does **nothing** to a running deployment — the model is
loaded once in `on_start`, so containers must restart. Expect ~10 minutes of
slow cold starts after each deploy while a snapshot captures and propagates.

**A redeploy does not reliably discard the old memory snapshot.** The cache is
keyed by app name, not by version — Beam mounts it at
`/checkpoint-model-cache-bartholomew-iii` — so a new version can come back
running a *previous* version's process, replaying the heap that `on_start` built
under whatever GPU and config were live then. On 2026-08-20 a deployment
configured for A10G served from a container reporting RTX4090 for exactly this
reason. The tell is arithmetic: `process_age_seconds` from `/health` was greater
than the container's own uptime, which is only possible if that container never
ran `on_start`. `ops/redeploy.py` makes that comparison after every deploy;
`ops/redeploy.py --bust-snapshot` clears a stale image by deploying once with
checkpointing off before turning it back on.

## Cold starts and scaling

Set in [config.py](config.py):

| knob | now | what it does |
|---|---|---|
| `CHECKPOINT_ENABLED` | `True` | snapshots the container after `on_start`; later boots restore GPU memory instead of reloading. The main fix. |
| `KEEP_WARM_SECONDS` | `600` | how long a container idles before shutting down |
| `MIN_CONTAINERS` | `0` | set to `1` to never scale to zero — no cold starts ever, ~$16.50/day on RTX4090 |
| `MAX_CONTAINERS` | `3` | spend ceiling; beyond it readers queue |
| `TASKS_PER_CONTAINER` | `1` | add a replica once a second request is queued |

**If you are still cold starting on every visit,** work down this list:

1. Are you measuring within ~10 minutes of a deploy? The snapshot has not
   propagated yet. Wait and re-measure.
2. Is `keep_warm_seconds` shorter than the gap between your visits? At 600s, a
   visit every 15 minutes cold starts every time. Raise it, or set
   `MIN_CONTAINERS = 1`.
3. Are there multiple deployment versions live? Each has its own containers and
   its own warm state — traffic to the unversioned URL only warms the latest.
   `beam deployment list`, then stop the old ones.
4. Check the boot log. If it still says ~25s with `checkpoint_enabled=True` well
   after a deploy, the snapshot is not being used; that is worth asking Beam
   about directly.

**For a review period or a demo day,** `MIN_CONTAINERS = 1` is the honest
answer. It costs about $16.50/day and makes the question disappear. Set it back
to 0 afterwards, and stop the old deployment versions when you do — each one
with `min_containers` set keeps its own GPU running.

## Do I need a Docker image?

No — not for the weights, and not for the app.

**For the weights:** they go into a Beam Volume with `beam cp`. That is plain
file storage, no container involved. Docker images are the wrong tool for a
5 GiB file that changes independently of your code.

**For the app:** Beam builds the container for you from the `Image(...)`
declaration in `app.py` — a Python version and a package list. You never write a
Dockerfile, never run `docker build`, and never push to a registry. Beam does
support `Image().from_dockerfile("./Dockerfile")` and private registries if you
ever need system-level dependencies that `add_commands` cannot express, but
nothing here does.

The one place a Docker-shaped idea is worth considering is baking the weights
*into* the image, since image loading is unbilled and host-cached while
`on_start` is billed. Even then you would use `Image().add_commands([...])` to
fetch them during the build, not a Dockerfile. It is a real optimisation but a
worse day-to-day workflow — every weight change becomes an image rebuild — and
`CHECKPOINT_ENABLED` addresses the same problem more cheaply.

## Cost control

Nothing runs when nobody is using it. You are billed for `on_start`, for
generation, and for the 10-minute keep-warm window — not for machine startup or
image pulls.

Rough figures at ~$0.69/hr: **~0.6¢** per cold start, **~11.5¢** per idle
keep-warm window, a few tenths of a cent per reply. A reader who asks four
questions over ten minutes costs **12–18¢**.

```bash
beam deployment stop <id>     # stop serving; nothing can wake it
beam deployment start <id>    # resume
beam deployment delete <id>   # remove entirely
```

`MAX_CONTAINERS = 3` is a deliberate spend ceiling — concurrent
readers queue rather than starting a second GPU. Raise it in `config.py` only if
you would rather queue less than pay less.

## Troubleshooting

**Start here.** `on_start` failures used to surface as an opaque 500 from
whichever route touched the missing state first, with the real traceback visible
only in `beam logs`. `app.py` now catches them and serves them, so the first
question is answered by one request:

```bash
curl -s <url>/health | python -m json.tool
```

| what comes back | what it means |
|---|---|
| `200` with a `model` block | the container is fine; whatever is broken is not the deployment |
| `503` with an `error` field | `on_start` raised, and that field is the traceback — its last line names the failure |
| nothing, until the client gives up | no container was ever scheduled: GPU capacity, account quota, or stale deployments holding the containers |

The chat page shows the same 503 body in its wake panel, so a reader-facing
failure now says what went wrong instead of "Could not reach the model".


| symptom | cause | fix |
|---|---|---|
| 401 / 403 | `AUTHORIZED = True` | set `False` in `config.py`, redeploy |
| `FileNotFoundError` on `model_*.pt` in boot logs | volume path wrong, or you deployed within 60s of `beam cp` | `curl <probe-url>/volume`, or re-check `beam ls` |
| reply appears all at once, not word by word | SSE buffered somewhere | UI already falls back automatically; confirm with `/stream-probe` |
| KV cache dtype error at first request | GPU without bf16 (T4/V100) | set `GPU = "RTX4090"` in `config.py` |
| `torch.cuda.is_available()` False in logs | host driver older than CUDA 12.8 | pin an older torch in `app.py`'s image |
| `Checkpoints are yet not supported between multiple GPUs` | `GPU` is a list while `CHECKPOINT_ENABLED` is True | pin one type, e.g. `GPU = "RTX4090"` |
| deploy takes minutes to sync | `.beamignore` missing at repo root | step 6 |
| answers feel wrong vs your evals | no system prompt loaded | check the `[boot] system prompt: N chars` line |
| cold start much worse than 40s | volume read throughput | try `checkpoint_enabled=True` on the `@asgi` decorator |
