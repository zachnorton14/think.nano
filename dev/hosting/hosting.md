# Hosting

Everything involved in serving the think.nano chat model on the public web, and
an honest account of what is currently broken.

- **[README.md](beam/README.md)** — why the design is shaped this way
- **[RUNBOOK.md](beam/RUNBOOK.md)** — step-by-step setup and day-to-day operation
- **this file** — the whole inventory in one place, plus the open problems

Status as of 2026-08-21. The fifteen-minute failure that this file was written
about was attributed to RTX4090 and fixed by moving back to A10G with
`CHECKPOINT_ENABLED = True`; see [Problem 1](#problem-1--checkpoint-restore-does-not-work).
The live deployment now fails **intermittently** instead, which is unexplained
and, as of this writing, uninvestigated — the current hypothesis is GPU
availability. Everything done since 2026-08-19 is in the changelog directly
below, including a second deployment, `bartholomew-iii-4090`, that is running an
untested configuration.

---

## Changelog — what has been done since this file was written

This file was written on 2026-08-19 in commit `1fd6c3d` and described the account
as it stood that afternoon. Four things have happened since. The numbered
sections and the problem list below have been corrected in place; this is the
narrative, newest last.

### 2026-08-19 — priming turns enabled (`897b007`)

`prompt_ab.py` sends the two `nanochat/prompt_shaping.py` fixes as ordinary API
messages, so both could be measured **against the deployed model without a
deploy**. Over "Hello", "How are you doing" and "Write an essay about
industrialization" (2 samples each): bare collapsed 3/6, punctuation repair alone
still collapsed 2/6, the priming exchange was clean 6/6.

So `NANOCHAT_PRIMING_TURNS = "default"` ships and `NANOCHAT_FIX_PUNCTUATION`
stays off — one variable at a time. `/health` now reports a `prompt_fixes` block,
so any session can be attributed to the config that served it.

### 2026-08-20 — the notebooks were replaced by `ops/` scripts (`7b03e5a`)

All five `colab_*.ipynb` files were deleted and replaced by
`dev/hosting/beam/ops/*.py`. Three of their behaviours were bugs, and each is
fixed by the replacement:

- they cloned from GitHub, so they deployed what was *pushed*. The ops scripts
  deploy the working tree and print the uncommitted files that are about to ship;
- they rewrote `config.py` from their own configuration cell on every run, so a
  stale copy silently reverted whatever had been fixed in git. **`config.py` is
  now the authority** and nothing is rewritten without an explicit flag. This
  retires [Problem 7](#problem-7--deploy-time-config-rewriting) as written;
- they read `/health` and believed it. `redeploy.py` now compares the serving
  process's age against its own container's uptime after every deploy.

### 2026-08-20 — v9 shipped an unimportable handler and took the deployment down

The deploy command this file originally documented —
`beam deploy dev/hosting/beam/app.py:handler` — is the command that causes this
when run from Windows.

The beta9 SDK records every callable it ships as `"<module>:<name>"`, building
the module name in `_map_callable_to_attr` with

```python
os.path.relpath(module.__file__, start=os.getcwd()).replace("/", ".")
```

On Windows `relpath` returns backslashes, so that `.replace` never fires. The
damage is still legible in the deployment records:

```
v9   stub=asgi/deployment/dev\hosting\beam\app:handler     ← cannot be imported
v10  stub=asgi/deployment/beam_app:handler                 ← the fix
```

The Linux container can never import that first module name, so every task died
before the app existed and the edge answered 500 — which looks exactly like a
broken build. The fix is `beam_app.py` at the **repo root**, which has no path
separators to mangle, defining `handler`, `probe_handler` and `load_engine`
itself rather than importing them. It must stay there.

### 2026-08-21 — a second deployment on RTX4090, `bartholomew-iii-4090`

Prompted by intermittent failures of the live deployment, on the hypothesis that
they are caused by GPU availability. **That hypothesis was not investigated** —
what follows is only what was built and measured.

**Observation, ~14:40 UTC.** `beam machine list` reported, in the *Serverless*
column: `A10G ● available`, `RTX4090 ● ready`, `RTX5090 ● ready`. Per
`ops/beamops.py`, `ready` means warm capacity that schedules immediately while
`available` means offered but not necessarily schedulable now. Recorded as an
observation, not a conclusion.

**The live deployment was working at that moment.** `bartholomew-iii` v10 on
A10G answered `/health` 200 in 0.23 s and streamed a correct 16-token
generation. Its `process_age_seconds` was 84 068 against a 600 s keep-warm
window, so that container had been restored from a snapshot rather than booted.

**A second app was created**, deliberately separate so the live one was never
touched, never redeployed and never stopped:

| version | GPU | `CHECKPOINT_ENABLED` | first-boot verification |
|---|---|---|---|
| v1 | RTX4090 | `False` | passed |
| v2 | RTX4090 | **`True`** | passed |

Both passed the full `redeploy.py` verification on their first container: a real
boot (`process_age_seconds` younger than the container's own uptime),
`NVIDIA GeForce RTX 4090`, `torch.bfloat16`, 5.27 GiB, step 42, 7/7 SSE frames,
generation at 32.7 and 27.5 tok/s, and a single `Access-Control-Allow-Origin`.
v1 booted in 34.2 s, v2 in 20.2 s.

After v1's deploy, `/health` returned an edge 500 for roughly two minutes before
any container existed, first answering at ~145 s; `redeploy.py` treats that first
500 as fatal and had to be re-run against the URL once it came up. v2's container
arrived inside the probe's window. An edge 500 in the first minutes after a
deploy is not, on its own, evidence of a broken build.

> **v2 is live on RTX4090 with `CHECKPOINT_ENABLED = True` — the exact
> combination [Problem 1](#problem-1--checkpoint-restore-does-not-work)
> documents as broken — and it has never been through a cold start.** The
> cold-start test was started and **killed during its 720 s idle wait, before it
> ever probed**, so there is no result either way. If Problem 1's account holds,
> v2 will answer `/health` and hang on generation roughly ten idle minutes after
> its deploy. v1 is still active as a rollback, and the live `bartholomew-iii`
> deployment is unaffected either way.

To finish the experiment, idle the 4090 URL out for `KEEP_WARM_SECONDS` plus a
couple of minutes without touching it, then request `/health` **and** a
generation — `redeploy.cold_start_test()` does exactly this. A `/health` that
answers while generation hangs is the signature.

`config.py` was pinned before each deploy and restored afterwards, so the
committed file still reads `APP_NAME = "bartholomew-iii"`, `GPU = "A10G"`,
`CHECKPOINT_ENABLED = True`, and the working tree is clean.

**Environment finding.** `beam.exe` is blocked on the deploy machine by a Windows
Application Control policy — bash reports `Permission denied`, PowerShell reports
`An Application Control policy has blocked this file`. The block is on the
unsigned uv launcher, not on the package; the venv's signed `python.exe` runs
fine, so every invocation becomes

```bash
PYTHONIOENCODING=utf-8 \
  ~/AppData/Roaming/uv/tools/beam-client/Scripts/python.exe -m beam <args>
```

`ops/beamops.py` shells out to a literal `"beam"`, so **every ops script is
unusable** until this is resolved or `ops.stream` is patched to rewrite `cmd[0]`.
A `.bat`/`.cmd` shim on `PATH` does not help: Windows `CreateProcess` only
appends `.exe`.


### 2026-08-21 (evening) — the cold-start problem was measured, root-caused, and fixed

The intermittent failures were never a broken build. Live probes plus the
dashboard logs decomposed a cold start into its real parts, all storage/infra:

- **scheduling**: the A10G request sat PENDING 3m38s once (A10G shows
  `● available`, not `● ready`) — and Beam then **booted it on an RTX4090
  anyway**, twice, despite `GPU = "A10G"` in the stub. The pin is not honored;
- **checkpoint archive**: 6.59 GiB, "cache miss; downloading from workspace
  storage" on essentially every cold boot, at 28–130 MB/s (1–4 min);
- **volume read**: per-worker lottery — 580 MB/s on one worker, 17–28 MB/s on
  another (246s for the 5.25 GiB read, container `0d704c8d`);
- **image layers are lazy-mounted** ("Loaded image took 3µs" for 11 GiB), so
  baking weights into the image does not help a cache-cold worker either — the
  first read streams from the registry. It only wins when the worker's layer
  cache is warm. Empirically Beam reschedules this app onto recently-used
  workers, so it wins most of the time.

**Problem 1 was also confirmed by observation**: two cold restores of
`bartholomew-iii-4090` v2 (RTX4090 + `CHECKPOINT_ENABLED = True`) each left a
container RUNNING 7–9 minutes serving zero bytes — the process wedges before
uvicorn accepts, so even the /health CUDA guard never gets to answer. The 4090
checkpoint experiment is closed: broken, twice observed.

The fix that shipped: `WEIGHTS_SOURCE = "image"` in config.py bakes the bf16
export into the container image (from HF, uploaded once by
`ops/upload_bf16_hf.py`), `CHECKPOINT_ENABLED = False`, `KEEP_WARM_SECONDS =
1800`. Measured on the test app (`bartholomew-iii-4090` v3/v4): two consecutive
scale-to-zero cold starts answered /health in **12.1s and 17.8s**; a
cache-cold worker paid 90s–6 min once, then stayed warm. The old worst case
(10+ min, request timeouts) came from the checkpoint archive plus the slow
worker pool and is gone with checkpointing.

Also found: the reason `beam logs` has never worked (Problem 8) is that
`wss://rt.beam.cloud` rejects its own SNI — reproduced with bare `openssl
s_client`, no Python involved. Beam-side breakage; logs come from the web
dashboard. And three consecutive workers failed with `nvidia-container-cli:
device error: 7: unknown device` before the v1 deploy found a healthy one —
worth including in the support ticket.

## 1. What the thing is

A single FastAPI app, deployed to [Beam](https://beam.cloud) as a serverless ASGI
endpoint with a GPU attached. It serves a chat page at `/` and a streaming
completion API at `/chat/completions`, backed by a d32 nanochat model read off a
Beam Volume.

```
                    browser
                       │
       ┌───────────────┴────────────────┐
       │                                │
 unboundedlab.com                 Beam edge proxy
 (serves its own copy      ┌──────────────┴──────────────┐
  of the chat page,        │  answers OPTIONS itself     │
  <meta api-base>          │  stamps CORS: *             │
  points at Beam) ────────▶│  queues while a container   │
                           │  boots                      │
                           └──────────────┬──────────────┘
                                          │
                                  ┌───────┴────────┐
                                  │  container     │  A10G, bf16
                                  │  app.py:handler│  16 GiB RAM, 2 CPU
                                  │  FastAPI       │
                                  └───────┬────────┘
                                          │ reads once, in on_start
                                  ┌───────┴────────┐
                                  │ Beam Volume    │  think-nano-weights
                                  │ /vol/model     │  mounted read/write
                                  └────────────────┘
```

Key shape decisions, all of which have bitten at least once:

- **The Engine is built in `on_start`**, so the 5.25 GiB read and CUDA init are
  paid per container, not per request.
- **Generation runs on a worker thread**, bridged back to asyncio, so a 20-second
  completion does not block `/health`.
- **One generation at a time**, enforced by an `asyncio.Semaphore(1)`. A single
  model replica on a single CUDA stream cannot usefully interleave.
- **The container scales to zero** after `KEEP_WARM_SECONDS`. This is where the
  current bug lives — see Problem 1.

---

## 2. The Beam account

Workspace `3e131a` (`d16e6fda-3665-4792-be22-7f91c9f9a3b1`).

### Apps

An app is the stable unit. Its `app_id` is what the public hostname is derived
from; deployments and versions come and go beneath it.

| app | app_id | notes |
|---|---|---|
| `bartholomew-iii` | `5797466c-3f91-4e62-83b0-0f395e3dedaa` | current; A10G. (This file first recorded `81223693-…`, which no longer matches `beam deployment list`.) |
| `bartholomew-iii-4090` | `dd6aa6a9-2f89-4840-9d43-b536a1aca6e1` | added 2026-08-21; RTX4090. See the changelog. |
| `think-nano` | `3e51ff17-adcf-4668-be74-d301bd0d4129` | the pre-rename name; see Problem 3 |
| `think-nano-probe` | `567c2542-3b20-4749-8641-2ef61ae72caa` | CPU dress rehearsal |

### URLs

```
https://bartholomew-iii-e3afdc3.app.beam.cloud        ← publish this one
https://bartholomew-iii-e3afdc3-v2.app.beam.cloud     ← pinned to v2; see Problem 2
https://bartholomew-iii-4090-303ef46.app.beam.cloud   ← the RTX4090 deployment
```

The suffix (`e3afdc3`) is **not derivable** from anything `beam deployment list`
exposes — not the deployment id, not the stub id, not the app id. Read it off the
`beam deploy` output and write it down.

### Volume

`think-nano-weights`, mounted at `/vol/model`. Deliberately still carries the old
project name: the weights were uploaded under it, and renaming the volume would
point the deployment at storage that does not exist.

```
think-nano-weights/
├── pre1930-companion.txt                                   2.01 KiB
└── Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2/
    ├── model_000042.pt                                     5.25 GiB
    ├── meta_000042.json                                    6.08 KiB
    └── tokenizer/tokenizer.pkl
```

Step 42 is correct, not truncated: the SFT config sets `save_every: -1`, so only
the final step is written. The 5.25 GiB file size is the check that matters — a
bf16 d32 export is ~5.25 GiB regardless of step number.

**The volume is the expensive thing in this account.** Rebuilding it is an 8.4 GiB
HuggingFace download, a bf16 export needing ~9 GiB of RAM, and a 5.25 GiB upload.
Deployments are disposable; this is not.

### Model being served

```
d32 · n_layer 32 · n_head 16 · n_kv_head 16 · n_embd 2048
sequence_len 4096 · vocab_size 32768 · window_pattern SSSL
val_bpb 0.7037 · stored bfloat16 · ~5.27 GiB resident on GPU
```

Base experiment `Think.Unbounded-d32-v2mix-cont`, SFT suffix
`pre1930-curriculum-c3-robust-v2`.

---

## 3. File inventory

Everything under `dev/hosting/beam/`.

### Deployed into the container

| file | role |
|---|---|
| `app.py` | The deployment. `Image` spec, `@asgi` decorator, `on_start` loader, all routes. |
| `config.py` | Every deploy-time knob. Read on your machine at deploy time, not in the container. |
| `conversation.py` | Prompt rendering and request validation. A port of `scripts/chat_web.py`, decoupled from its argparse globals. |
| `fast_load.py` | Serving-only model loader. Skips the random init of 2.8B parameters that `build_model` does, cutting peak VRAM from ~16 GiB to ~5.5 GiB. |
| `ui_updated.html` | The chat page. Unbounded Labs styling. Currently served. |
| `ui.html` | The original chat page. Kept as a rollback target. |

The container also gets `nanochat/` from the repo root, which is why deploys run
from the repo root rather than from this folder.

### Deploy-time only

| file | role |
|---|---|
| `beamignore.template` | Copy to repo root as `.beamignore`. Without it every deploy uploads `.git` and the whole research tree. |
| `probe_app.py` | CPU-only, model-less rehearsal. Mounts the same volume and adds `/volume`, which reports what a container actually sees. The clean way to separate "weights are wrong" from "no GPU". |
| `export_bf16.py` | Drops optimizer state, casts rank≥2 weights to bf16. 8.37 GiB → 5.25 GiB, bit-identical logits. |
| `fetch_checkpoint.py` | Pulls the right files out of the HuggingFace artifacts repo. |
| `test_export.py` | Five assertions that the bf16 cast and `fast_load` are lossless. Run before exporting. |
| `smoke_test.py` | Exercises a deployed URL: cold start, SSE buffering, TTFT, tokens/sec. Stdlib only. |
| `preview_ui.py` | Local UI preview with faked endpoints. No GPU, no weights, no deploy. |
| `prompt_ab.py` | A/Bs the `prompt_shaping.py` fixes as ordinary API messages against a live deployment, so a prompt change can be measured without deploying it. |

### Ops scripts

`dev/hosting/beam/ops/`. These replaced the five `colab_*.ipynb` notebooks on
2026-08-20; unlike the notebooks they deploy **the working tree**, and they treat
`config.py` as the authority rather than rewriting it.

| script | for |
|---|---|
| `beamops.py` | Shared plumbing: the CLI wrapper, `config.py` read/pin, HTTP probes, the restore check. Not run directly. |
| `deploy.py` | First-time setup: download, export, upload, deploy. Idempotent. |
| `redeploy.py` | Redeploy with preflight and post-deploy verification. `--cold-start-test` is the only check that exercises the restore path; `--bust-snapshot` forces a real boot. |
| `update_ui.py` | UI-only change. No re-upload, no image rebuild. |
| `debug.py` | Why is it failing. Interrogates a **live** deployment; run before cleanup. Emits a pasteable bundle. |
| `cleanup.py` | Too many deployments. Stops the app's old versions, never touches the volume unless explicitly armed. |
| `watch_gpu.py` | Polls serverless GPU capacity over time. |

Also at the **repo root**, and required there:

| file | role |
|---|---|
| `beam_app.py` | The deploy entrypoint. Defines `handler`, `probe_handler` and `load_engine` itself. Must stay at the root — see the v9 entry in the changelog. |

---

## 4. Configuration reference

All in `config.py`, which since 2026-08-20 is **authoritative**: the ops scripts
change it only when you pass the flag that says so, and a value written that way
stays written. (The notebooks it replaced rewrote a subset on every run, which is
what Problem 7 was about.)

| setting | current | meaning |
|---|---|---|
| `APP_NAME` | `bartholomew-iii` | Beam derives the URL from this. Changing it creates a *new app*. |
| `VOLUME_NAME` | `think-nano-weights` | Deliberately not renamed alongside the app. |
| `MOUNT_PATH` | `/vol/model` | Absolute on purpose: a relative mount would shadow the `nanochat` package. |
| `GPU` | `A10G` | Single type, not a list. Needs bf16 tensor cores (SM 80+, so not T4/V100). **Beam does not reliably honor this** — A10G deploys booted on RTX4090 repeatedly on 2026-08-21. With checkpointing off that is harmless; it is in the support ticket. |
| `CHECKPOINT_ENABLED` | `False` | Off since 2026-08-21: the 6.59 GiB archive missed its cache on nearly every cold boot (1–4 min download), and on RTX4090 restore wedges outright (Problem 1, now confirmed). `WEIGHTS_SOURCE = "image"` replaced it. |
| `WEIGHTS_SOURCE` | `image` | Bakes the bf16 export into the container image (from HF, uploaded once by `ops/upload_bf16_hf.py`). Warm-cache cold starts measured at 12–18s; a cache-cold worker pays one slow first boot. `"volume"` is the old path. |
| `KEEP_WARM_SECONDS` | `1800` | Idle time before a container shuts down. Raised from 600 on 2026-08-21: ~$0.33 per wake buys clustered readers out of repeat cold starts. |
| `MIN_CONTAINERS` | `0` | 0 scales to zero. 1 keeps a GPU running, ~$16.50/day. |
| `MAX_CONTAINERS` | `3` | Spend ceiling. Beyond it, readers queue. |
| `CONCURRENT_REQUESTS` | `1` | One request at a time per container. |
| `TASKS_PER_CONTAINER` | `1` | Add a replica once a second request queues. |
| `AUTHORIZED` | `False` | Public URL, no bearer token. |
| `MEMORY` / `CPU` | `16Gi` / `2` | Headroom for staging the checkpoint through host RAM. Beam's 128 MB default is nowhere near enough. |
| `UI_FILE` | `ui_updated.html` | Which page to serve at `/`. |
| `MODEL_TAG` | `Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2` | Names the folder on the volume. |

### Container environment (`CONTAINER_ENV`)

Read inside the container; change these to re-tune without touching code.

| var | committed | notes |
|---|---|---|
| `NANOCHAT_CHECKPOINT_DIR` | `/vol/model/<MODEL_TAG>` | |
| `NANOCHAT_TOKENIZER_DIR` | `/vol/model/<MODEL_TAG>/tokenizer` | |
| `NANOCHAT_STEP` | `42` | Empty = highest step on the volume. Pinned, because the URL is public and dropping a newer checkpoint in would silently change what a citation points at. |
| `NANOCHAT_SYSTEM_PROMPT_FILE` | `/vol/model/pre1930-companion.txt` | Committed since 2026-08-20. Serving without it gives a different model than the evals measured. |
| `NANOCHAT_PRIMING_TURNS` | `default` | Splices an invisible opening exchange whose user turn is unpunctuated. Chosen by A/B — see the changelog. Costs ~40–80 tokens of context per request. |
| `NANOCHAT_FIX_PUNCTUATION` | `""` | Off. Appends a period to unpunctuated visitor turns. Free, but did not fix the collapse on its own. |
| `NANOCHAT_TEMPERATURE` | `0.8` | Per-request overridable. |
| `NANOCHAT_TOP_K` | `50` | |
| `NANOCHAT_MAX_TOKENS` | `512` | |
| `NANOCHAT_REPETITION_PENALTY` | `1.0` | 1.0 = off. |
| `NANOCHAT_REPETITION_WINDOW` | `64` | 0 = penalise the whole response. |
| `HF_HUB_OFFLINE`, `HF_HUB_DISABLE_PROGRESS_BARS`, `TOKENIZERS_PARALLELISM` | | Quieter logs, no stray network calls on cold start. |

---

## 5. HTTP API

### `app.py`

| route | purpose |
|---|---|
| `GET /` | The chat page (`UI_FILE`). |
| `GET /health` | Model info, runtime info, defaults. **This is the wake signal** — the UI's first call returns exactly when the model is ready. Returns 503 with the reason when it is not. |
| `GET /stream-probe` | Six SSE frames 500 ms apart. Proves SSE is not being buffered, with no GPU involved. |
| `POST /chat/completions` | Streaming (SSE) by default; `"stream": false` for a single JSON reply. Accepts `temperature`, `top_k`, `max_tokens`, `repetition_penalty`. A leading `{"role":"system"}` message overrides the persona for that call. |

`/health` returns **200** with a `model` block when healthy, and **503** with an
`error` field when not. The 503 body is the diagnosis:

- `on_start` raised → the field holds the boot traceback
- GPU is not responding → the field says so (see Problem 1)
- container came up without running the loader → the field says that

It also reports `process_age_seconds` next to `keep_warm_seconds`. A process
older than its own keep-warm window cannot merely have idled — it was restored
from a snapshot. That is the only externally visible way to tell the two boot
paths apart.

### `probe_app.py`

Same shapes plus `GET /volume`, which reports the mount as a container sees it —
paths, file sizes, and a `ready_for_app` boolean.

### CORS

Beam's edge proxy answers `OPTIONS` itself and stamps
`Access-Control-Allow-Origin: *` on every response, **without waking a
container**. `app.py` therefore adds no CORS middleware of its own: two sets
produce a header reading `*, *`, which browsers reject outright. Do not "fix"
missing CORS by adding `CORSMiddleware`.

Two consequences worth knowing:

- An `OPTIONS` probe is **not** an existence check. The edge 204s any hostname
  under `*.app.beam.cloud`, deployed or not.
- A hostname with nothing behind it returns `404 {"message": "Not Found"}` from
  the edge; a live one returns `404 {"detail": "Not Found"}` from FastAPI. The
  key name is the tell.

---

## 6. Deploy workflow

```bash
# from the repo root, with .beamignore in place
python dev/hosting/beam/ops/redeploy.py
```

That does preflight, deploys, and verifies the result. The raw form underneath it
is:

```bash
beam deploy beam_app.py:handler --name bartholomew-iii
```

**Deploy `beam_app.py:handler` from the repo root, never
`dev/hosting/beam/app.py:handler`.** The second form ships a handler the
container cannot import when it is run from Windows, and takes the deployment
down without any sign of a build failure — that is what happened to v9 on
2026-08-20, and the changelog has the mechanism.

Things that are true of every deploy:

- The image is cached on Beam and keyed to the package list in `app.py`. A UI or
  code change skips the ~5 minute build.
- Swapping volume contents does **nothing** to a running deployment — the model
  is loaded once in `on_start`, so containers must restart.
- The previous version stays live at its `-vN` URL with its own containers and
  its own warm state. Stop it, or pay for it.
- The UI is read into memory at container start. Editing the file on disk does
  nothing until a redeploy.

---

# Known problems

## Problem 1 — checkpoint restore does not work

**This is the live problem.** Everything else in this section is smaller.

### Symptom

A fresh deploy works. Roughly fifteen minutes later the deployment stops
answering, and stays broken until the next deploy. From a browser the page loads
and then never connects. Reproduced at least four times.

### Mechanism

`CHECKPOINT_ENABLED = True` makes Beam snapshot the container process — including
GPU memory — after `on_start` returns, and restore later cold boots from that
image instead of re-reading 5.25 GiB and re-initialising CUDA. That creates **two
different boot paths**:

| path | when | works? |
|---|---|---|
| real boot | first container after each deploy | yes |
| snapshot restore | every later cold boot | **no** |

With `KEEP_WARM_SECONDS = 600` and `MIN_CONTAINERS = 0`, the second path is first
reached ten idle minutes after a deploy. Deploy, test for a few minutes, walk
away — total elapsed to first failure is about fifteen minutes.

### Why it was so hard to attribute

A restored process gets its Python heap back intact but **not** a working CUDA
context. `/health` used to read `on_start_value` straight out of restored memory
and never touch the GPU, so a fully broken container answered:

```
200 OK in 0.1s   {"status":"ok","ready":true,"busy":false, ...}
```

while every generation hung forever on its first kernel launch. The endpoint used
to check whether the service was alive sat on the wrong side of the GPU boundary
from the thing that was dead. Two full debug cycles were spent on the resulting
contradiction — a healthy `/health` and a generation call that never returned.

### Evidence

- Debug bundle 2026-08-19 16:24 UTC: `/health` 200 in 0.1 s, full model block,
  `vram_gib 5.27`, `boot_seconds 34.5` — a container reporting perfect health.
- A generation request against that same container returned nothing for over six
  minutes and was cancelled.
- The volume, the GPU type, capacity (`RTX4090 ● ready`), CORS and the boot path
  itself were each independently verified as fine.
- The failure interval matches `KEEP_WARM_SECONDS` plus normal testing time.

### Current state: attributed to the GPU, and fixed there

Superseded on 2026-08-19 by commit `1fd6c3d`. The break was bisected to `5be7ae6`
(08-18 10:05), which switched `GPU` from A10G to RTX4090 **in the same commit as
the rename** to `bartholomew-iii`. The rename got the blame; the GPU was the
cause. Everything else was constant across the break: identical image spec,
byte-identical `on_start`, unchanged `MEMORY`/`CPU`/`KEEP_WARM_SECONDS`/
`MIN_CONTAINERS`. One variable moved.

The switch to RTX4090 had been made on a wrong premise — that A10G was not on the
pricing page. It is: `beam machine list` shows A10G under *Serverless*, which is
what this deployment uses. The empty cell was the On-demand column, a different
product.

So `config.py` now carries `GPU = "A10G"` with `CHECKPOINT_ENABLED = True`, and
the fifteen-minute failure has not recurred. A datacenter card and a consumer
card differing on CUDA state save/restore is a plausible shape for this, but it
is an inference, not an observation.

**A second deployment is currently testing exactly this**, on RTX4090 with
`CHECKPOINT_ENABLED = True`, and has not yet been through a cold start — see the
2026-08-21 changelog entry. It is a separate app; the live deployment does not
depend on the outcome.

### What is not known

- Whether the CUDA-context explanation is correct. It is the best fit for the
  evidence, but has not been directly observed: no log from a restored container
  has been captured, because `beam logs` has not produced output for this account
  (Problem 8).
- Whether this is specific to RTX4090, to this torch version (`2.9.1`), to the
  5.25 GiB resident allocation, or general.
- Whether the warmup generation inside `on_start` — which runs real CUDA kernels
  before the snapshot is taken — makes the snapshot harder to restore than it
  would be without it.
- Whether Beam considers this supported. Their docs list RTX4090 among the
  checkpoint-restore GPUs, so on paper it should work.

### To investigate later

1. Capture a boot log from a restored container. Needs `beam logs` working first.
2. Deploy with `CHECKPOINT_ENABLED = True` and hit `/health` after the keep-warm
   window: it now performs a bounded CUDA touch and returns 503 naming the
   device as unresponsive, plus `process_age_seconds` proving restoration.
   **`bartholomew-iii-4090` v2 is already deployed in exactly this state** — this
   step is now just idling it out and probing it, and needs no new deploy.
   That turns a fifteen-minute mystery into one request.
3. Try `on_start` *without* the warmup generation, so the snapshot is taken
   before any CUDA kernel has run.
4. Ask Beam directly, with the `process_age_seconds` evidence.

### Mitigations available

| option | cost | effect |
|---|---|---|
| `CHECKPOINT_ENABLED = False` *(current)* | ~35 s cold starts | Snapshot path never taken. |
| `MIN_CONTAINERS = 1` | ~$16.50/day | Nothing ever cold starts; the path is unreachable. |
| both | both | Belt and braces. Recommended while the cause is unknown. |

---

## Problem 2 — version-pinned `-vN` URLs

Beam issues two URL forms. The unversioned one follows the newest deploy; the
`-vN` one is frozen to a single version.

```
https://bartholomew-iii-e3afdc3.app.beam.cloud       follows the latest deploy
https://bartholomew-iii-e3afdc3-v2.app.beam.cloud    frozen at v2
```

A `-vN` link keeps working only while that exact version is running, so it dies
the moment old versions are stopped — which cleanup does, and which the runbook
recommends after every deploy. This has been in circulation as the "direct link".

**Anything published — the site's `<meta name="api-base">`, a paper, a
message — must use the unversioned form.**

---

## Problem 3 — the rename created a second app

`think-nano` → `bartholomew-iii` did not rename anything. Beam derives the app
from `APP_NAME`, so it created a **new app** with a new `app_id` and a new
hostname, leaving the old one running alongside it.

Consequences that actually happened:

- Two apps, four deployments, plus three probe versions, all `active: true`,
  all holding containers and all billing.
- Any link to a `think-nano-*` URL kept working exactly as long as those
  deployments stayed up, and no longer.
- `beam logs` became ambiguous — errors read from a version nothing routes to.

This is the leading suspect for the *original* breakage, before the checkpoint
problem was isolated. It is unproven: by the time there was good instrumentation,
the state had already been cleaned up.

---

## Problem 4 — checks that do not check

Two separate incidents, same shape: a validation step that looked thorough and
verified the wrong property.

**The UI check.** The UI-update notebook validated balanced `<script>` tags and
that every `el("...")` id existed in the markup. A JavaScript **syntax error**
passed both. A single bad string literal kills the whole `<script>` block, so no
JS runs at all — and the page still renders, because it is static HTML and CSS.
The composer sits disabled showing its hard-coded
`placeholder="Waiting for the model…"` and nothing ever calls `/health`.
Indistinguishable, from the outside, from a dead backend.

*Fixed:* `ops/redeploy.py` (`check_ui`) runs `node --check` on every `<script>`
block and refuses to deploy a file that does not parse. If `node` is unavailable
it says so rather than passing silently.

**The health check.** Covered in Problem 1: `/health` verified that Python
objects existed, not that the GPU worked.

*Fixed:* `/health` now performs a bounded one-element CUDA add.

The general lesson worth keeping: **a check that cannot fail is not a check.**
Both of these passed on files that were completely broken.

---

## Problem 5 — no cold-start test existed

Every test in the setup — `smoke_test.py`, the post-deploy verification,
opening the page by hand — ran against a container the deploy had just started
and `keep_warm_seconds` was holding up. The failure in Problem 1 is in the *next*
boot, so a deployment could pass every check and be dead twenty minutes later.

*Fixed:* `ops/redeploy.py --cold-start-test` waits out `KEEP_WARM_SECONDS + 2
min`, lets the container die, then re-checks `/health` and streams a generation on
the genuinely cold container. It is the only part of the tooling that says
anything about whether the deployment survives.

It is also the check most easily skipped, because it costs twelve minutes of
doing nothing and any stray request to the URL resets the window. The 2026-08-21
RTX4090 experiment in the changelog is currently unresolved for exactly that
reason — the wait was interrupted before it probed.

---

## Problem 6 — `signal.SIGALRM` on a worker thread *(latent, unfixed)*

`nanochat/engine.py` guards calculator evaluation with:

```python
signal.signal(signal.SIGALRM, timeout_handler)
```

`signal.signal` only works on the main thread. `app.py` runs generation on a
worker thread (`threading.Thread(target=produce)`), so if the model ever emits a
`<|python_start|> … <|python_end|>` block, this raises
`ValueError: signal only works in main thread of the main interpreter` instead of
running the calculator.

Low likelihood for a pre-1930s persona, and it surfaces as a visible error frame
rather than a hang, so it has never fired in practice. Fix would be a
thread-safe timeout (a watchdog thread, or dropping the timeout and bounding the
expression instead).

---

## Problem 7 — deploy-time config rewriting *(fixed 2026-08-20)*

**Resolved by the ops scripts.** `config.py` is now the authority: `redeploy.py`
writes into it only for the flags you pass, and prints every line it changed.
`NANOCHAT_STEP` and `NANOCHAT_SYSTEM_PROMPT_FILE` are committed with the values
that actually ship. The original problem, kept because it explains commits made
before that date:

Both deploy notebooks rewrote `config.py` **inside their Colab clone**, setting
`GPU`, `UI_FILE`, `NANOCHAT_STEP`, `NANOCHAT_SYSTEM_PROMPT_FILE`,
`MIN_CONTAINERS`, `KEEP_WARM_SECONDS` and `CHECKPOINT_ENABLED` from notebook
variables. The clone is discarded with the runtime.

So the committed `config.py` is not authoritative about what is deployed. In
particular `NANOCHAT_STEP` and `NANOCHAT_SYSTEM_PROMPT_FILE` are committed empty
and set at deploy time. Commit the values the notebook writes, or a deploy from
another machine will differ.

---

## Problem 8 — `beam logs` invocation is unknown for this account

The runbook documents `beam logs --deployment-id <id>`. That is not the CLI's
actual surface here:

```
Usage: beam logs [OPTIONS]
Error: Got unexpected extra argument (2683f2e5-…)
```

`ops/debug.py` reads `beam logs --help`, extracts any `--*-id`
options and tries each against the matching field — but on the run that was
captured, no invocation produced output. **Container logs have not been
successfully read at any point in this investigation**, which is a significant
part of why Problem 1 took so long: every diagnosis had to be made from outside,
through HTTP.

Two further failures have been seen on the deploy machine since:

- `beam logs` cannot connect at all — the websocket handshake dies with
  `SSLError: TLSV1_UNRECOGNIZED_NAME` (beam-client under Python 3.14);
- as of 2026-08-21 `beam.exe` itself is blocked by a Windows Application Control
  policy, which takes every ops script with it. The workaround is in the
  changelog.

Worth resolving on its own merits before the next incident.

---

## Problem 9 — unpinned dependency ranges *(latent)*

The container image in `app.py` pins torch exactly and everything else loosely:

```python
"torch==2.9.1",
"fastapi>=0.117.1", "uvicorn>=0.36.0", "tiktoken>=0.11.0",
"tokenizers>=0.22.0", "rustbpe>=0.1.0", "filelock",
```

The image is cached and keyed to this list, so in practice the same versions are
reused. But a cache eviction would resolve fresh — potentially across a major
version — and produce a "worked yesterday, broken today" failure with no change
on your side. Pinning costs one ~5 minute image rebuild.

---

## Diagnostic playbook

Start here, in this order.

**1. Ask the deployment.**

```bash
curl -s --max-time 90 https://bartholomew-iii-<suffix>.app.beam.cloud/health \
  | python -m json.tool
```

| response | meaning |
|---|---|
| `200` with a `model` block | Container and GPU both fine. The problem is elsewhere — the site's `api-base`, or a `-vN` URL. |
| `503`, `error` holds a traceback | `on_start` raised. Last line names the failure. |
| `503`, error says the GPU is not responding | Problem 1. Check `checkpoint_enabled` in the same body. |
| `404 {"message": ...}` | Beam's edge. Nothing is deployed at that hostname — wrong URL. |
| `404 {"detail": ...}` | FastAPI. The deployment is live; that path just does not exist. |
| nothing, until the client gives up | No container was scheduled. Capacity, quota, or stale deployments holding containers. |

**2. Check `process_age_seconds` against `keep_warm_seconds`.** Older than the
window means the process was restored from a snapshot rather than booted.

**3. Run `python dev/hosting/beam/ops/debug.py`.** It produces a pasteable
bundle covering deployments, CORS, health, volume contents with sizes, GPU
availability and a timed streaming generation.

**4. Check serverless GPU capacity for the type you are on.**

```bash
beam machine list      # the Serverless column, not On-demand
```

`ready` is warm capacity that schedules immediately; `available` is offered but
not necessarily schedulable now. `beam deploy` warns *"GPU capacity for X is
currently low"* for the second case **and deploys anyway** — containers then
never appear and every request comes back as an edge 500, which looks exactly
like a broken build. `ops/watch_gpu.py` polls this over time.

**5. Do not trust a passing test on a warm container.** See Problem 5. An edge
500 in the first ~2 minutes after a deploy is also normal: no container exists
yet.

### Things repeatedly ruled out

Worth not re-investigating without new evidence:

- The volume and weights. Verified intact at every check.
- CORS. Clean; Beam's edge supplies the headers correctly.
- The model itself. Loads, reports the right config and `val_bpb`, and generates
  correctly on a freshly booted container.

**GPU capacity is no longer on that list.** It was ruled out while the
deployment ran on RTX4090, which was `● ready` throughout. The deployment has
since moved to A10G, and on 2026-08-21 A10G read `● available` rather than
`● ready` while RTX4090 and RTX5090 both read `● ready`. That is the current
hypothesis for the intermittent failures and it has not been investigated.

---

## Cost

These figures are RTX4090's, from when the deployment ran on it: at ~$0.66–0.69/hr,
roughly 0.6¢ per cold start, ~11.5¢ per ten-minute idle keep-warm window, tenths
of a cent per reply. A reader asking four questions over ten minutes costs 12–18¢.
Nothing runs when nobody is there — unless `MIN_CONTAINERS = 1`, which is
~$16.50/day flat.

The live deployment now runs on **A10G**, whose serverless rate has not been
written down here; `beam machine list` prints a price only in the On-demand
column, and A10G's is blank. Treat the numbers above as the right order of
magnitude, not as this deployment's bill.

`MAX_CONTAINERS = 3` is a deliberate spend ceiling; concurrent readers queue
rather than starting a fourth GPU.

```bash
beam deployment list
beam deployment stop <id>      # stop serving; nothing can wake it
beam deployment start <id>     # resume
beam deployment delete <id>    # remove entirely
```
