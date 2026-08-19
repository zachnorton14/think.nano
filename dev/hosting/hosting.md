# Hosting

Everything involved in serving the think.nano chat model on the public web, and
an honest account of what is currently broken.

- **[README.md](beam/README.md)** — why the design is shaped this way
- **[RUNBOOK.md](beam/RUNBOOK.md)** — step-by-step setup and day-to-day operation
- **this file** — the whole inventory in one place, plus the open problems

Status as of 2026-08-19: **the deployment works after a fresh deploy and stops
working roughly fifteen minutes later.** The cause is checkpoint (memory
snapshot) restore. It is described in [Problem 1](#problem-1--checkpoint-restore-does-not-work),
is currently worked around rather than fixed, and is the reason this file exists.

---

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
                                  │  container     │  RTX4090, bf16
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
| `bartholomew-iii` | `81223693-5128-45cc-b06e-b143508c16c9` | current |
| `think-nano` | `3e51ff17-adcf-4668-be74-d301bd0d4129` | the pre-rename name; see Problem 3 |
| `think-nano-probe` | `567c2542-3b20-4749-8641-2ef61ae72caa` | CPU dress rehearsal |

### URLs

```
https://bartholomew-iii-e3afdc3.app.beam.cloud        ← publish this one
https://bartholomew-iii-e3afdc3-v2.app.beam.cloud     ← pinned to v2; see Problem 2
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

### Notebooks

All are Colab-first and clone from GitHub, so **uncommitted local changes are
invisible to them**.

| notebook | for |
|---|---|
| `colab_beam_deploy.ipynb` | First-time setup: download, export, upload, deploy. Idempotent. |
| `colab_update_ui.ipynb` | UI-only change. No re-upload, no image rebuild. |
| `colab_beam_debug.ipynb` | Why is it failing. Interrogates a **live** deployment; run before cleanup. Emits a pasteable bundle. |
| `colab_beam_cleanup.ipynb` | Too many deployments. Deletes cruft, stops the current app's versions without deleting the app, never touches the volume unless explicitly armed. |
| `colab_beam_redeploy.ipynb` | Redeploy with preflight checks and post-deploy verification, including the cold-start regression test. |

---

## 4. Configuration reference

All in `config.py`. Both deploy notebooks rewrite a subset at deploy time, so
**what shipped is not necessarily what is committed** — see Problem 7.

| setting | current | meaning |
|---|---|---|
| `APP_NAME` | `bartholomew-iii` | Beam derives the URL from this. Changing it creates a *new app*. |
| `VOLUME_NAME` | `think-nano-weights` | Deliberately not renamed alongside the app. |
| `MOUNT_PATH` | `/vol/model` | Absolute on purpose: a relative mount would shadow the `nanochat` package. |
| `GPU` | `RTX4090` | Single type, not a list. Needs bf16 tensor cores (SM 80+, so not T4/V100). |
| `CHECKPOINT_ENABLED` | **`False`** | Memory snapshot restore. **Disabled as a workaround — see Problem 1.** |
| `KEEP_WARM_SECONDS` | `600` | Idle time before a container shuts down. |
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
| `NANOCHAT_STEP` | `""` | Empty = highest step on the volume. Deploy notebooks pin it to the real number. |
| `NANOCHAT_SYSTEM_PROMPT_FILE` | `""` | Deploy notebooks set `/vol/model/pre1930-companion.txt`. Serving without it gives a different model than the evals measured. |
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
beam deploy dev/hosting/beam/app.py:handler --name bartholomew-iii
```

Or run `colab_beam_redeploy.ipynb`, which does the same with preflight checks.

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

### Current state: worked around, not fixed

`CHECKPOINT_ENABLED = False` in `config.py`. Cold starts become real ~35 s boots
on the path that demonstrably works. The snapshot path is simply never taken.

**This is a mitigation.** The underlying question — why Beam's checkpoint restore
returns a process whose CUDA context is unusable — is unanswered.

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

**The UI check.** `colab_update_ui.ipynb` validated balanced `<script>` tags and
that every `el("...")` id existed in the markup. A JavaScript **syntax error**
passed both. A single bad string literal kills the whole `<script>` block, so no
JS runs at all — and the page still renders, because it is static HTML and CSS.
The composer sits disabled showing its hard-coded
`placeholder="Waiting for the model…"` and nothing ever calls `/health`.
Indistinguishable, from the outside, from a dead backend.

*Fixed:* `colab_beam_redeploy.ipynb` now runs `node --check` on every `<script>`
block and refuses to deploy a file that does not parse.

**The health check.** Covered in Problem 1: `/health` verified that Python
objects existed, not that the GPU worked.

*Fixed:* `/health` now performs a bounded one-element CUDA add.

The general lesson worth keeping: **a check that cannot fail is not a check.**
Both of these passed on files that were completely broken.

---

## Problem 5 — no cold-start test existed

Every test in the setup — `smoke_test.py`, the notebook verification cells,
opening the page by hand — ran against a container the deploy had just started
and `keep_warm_seconds` was holding up. The failure in Problem 1 is in the *next*
boot, so a deployment could pass every check and be dead twenty minutes later.

*Fixed:* `colab_beam_redeploy.ipynb` has a final cell that waits out
`KEEP_WARM_SECONDS + 2 min`, lets the container die, then re-checks `/health` and
streams a generation on the genuinely cold container. It is the only part of the
tooling that says anything about whether the deployment survives.

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

## Problem 7 — deploy-time config rewriting

Both deploy notebooks rewrite `config.py` **inside their Colab clone**, setting
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

`colab_beam_debug.ipynb` now reads `beam logs --help`, extracts any `--*-id`
options and tries each against the matching field — but on the run that was
captured, no invocation produced output. **Container logs have not been
successfully read at any point in this investigation**, which is a significant
part of why Problem 1 took so long: every diagnosis had to be made from outside,
through HTTP.

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

**3. Run `colab_beam_debug.ipynb`** with `APP_URL` set. It produces a pasteable
bundle covering deployments, CORS, health, volume contents with sizes, GPU
availability and a timed streaming generation.

**4. Do not trust a passing test on a warm container.** See Problem 5.

### Things repeatedly ruled out

Worth not re-investigating without new evidence:

- The volume and weights. Verified intact at every check.
- GPU capacity. `RTX4090 ● ready` throughout.
- CORS. Clean; Beam's edge supplies the headers correctly.
- The model itself. Loads, reports the right config and `val_bpb`, and generates
  correctly on a freshly booted container.

---

## Cost

At ~$0.66–0.69/hr for RTX4090: roughly 0.6¢ per cold start, ~11.5¢ per
ten-minute idle keep-warm window, tenths of a cent per reply. A reader asking
four questions over ten minutes costs 12–18¢. Nothing runs when nobody is there —
unless `MIN_CONTAINERS = 1`, which is ~$16.50/day flat.

`MAX_CONTAINERS = 3` is a deliberate spend ceiling; concurrent readers queue
rather than starting a fourth GPU.

```bash
beam deployment list
beam deployment stop <id>      # stop serving; nothing can wake it
beam deployment start <id>     # resume
beam deployment delete <id>    # remove entirely
```
