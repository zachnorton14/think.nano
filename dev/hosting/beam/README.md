# Hosting think.nano on Beam

Everything here is what you do **before** a GPU is switched on. The order matters:
each step is cheap and catches a class of failure that is expensive to discover
once a GPU container is booting.

**[RUNBOOK.md](RUNBOOK.md) is the step-by-step**: 13 setup steps, then how to
operate it. This file is the reasoning behind those steps — read it once, then
work from the runbook.

| file | what it is |
| --- | --- |
| `RUNBOOK.md` | setup checklist + day-to-day operations |
| `fetch_checkpoint.py` | resolves the model tag to HuggingFace paths and downloads model + meta + tokenizer |
| `export_bf16.py` | builds the serving checkpoint: strips optimizer state, casts rank ≥ 2 weights to bf16 |
| `fast_load.py` | serving-only loader that skips `to_empty` + `init_weights` — the second-biggest cold-start win |
| `test_export.py` | proves that cast is lossless — bit-identical logits, on CPU, in seconds |
| `conversation.py` | prompt rendering + request validation (ported from `scripts/chat_web.py`) |
| `config.py` | deploy-time settings — GPU, volume, auth, keep-warm, container env |
| `app.py` | the real Beam deployment: Engine built in `on_start`, weights off a Volume |
| `../../../beam_app.py` | the deploy entrypoint, at the repo root — see the Windows note in [ops/README.md](ops/README.md) for why it must live there |
| `probe_app.py` | CPU-only dress rehearsal — same routes, no model, no GPU, costs cents |
| `ui.html` | the original chat UI, kept for rollback |
| `ui_updated.html` | current UI — Unbounded Labs styling, details/sampling panel |
| `preview_ui.py` | local mock server for reviewing a UI with no GPU or deployment |
| `smoke_test.py` | post-deploy battery: cold start, SSE buffering, TTFT, tok/s |
| `beamignore.template` | copy to the repo root as `.beamignore` before the first deploy |
| `ops/` | operational scripts run from a laptop: deploy, redeploy, debug, cleanup — see [ops/README.md](ops/README.md) |

---

## Corrections to the starting assumptions

The four points in the brief are right in direction. Four details are off, and
they change what you should do.

**The bf16 export saves ~37%, not 50%.** `GPT.init_weights()` already casts
`transformer.wte` and every `value_embeds` entry to `COMPUTE_DTYPE`
(`gpt.py:263-266`), so a third of your d32 checkpoint is bf16 on disk today. The
exact split, from the d32 config (depth 32 → `n_embd` 2048, 16 heads, head_dim
128, vocab 32768):

| | params | on disk |
| --- | ---: | ---: |
| already bf16 (`wte`, 16 × `value_embeds`) | 1.14 B | 2.13 GiB |
| fp32 (`lm_head`, 32 blocks, gates) | 1.68 B | 6.25 GiB |
| **total now** | **2.82 B** | **8.37 GiB** |
| **after export** | 2.82 B | **5.25 GiB** |

That 1.68 B figure is `scaling_params` in
`configs/base/Think.Unbounded-d32-v2mix-cont.json`, to the parameter — the
config is counting exactly the tensors this export halves. Still very much worth
doing; just budget ~5.3 GiB of transfer and VRAM, not 4.

**Do not use a T4.** `nanochat/common.py:_detect_compute_dtype` only selects
bf16 on SM 80+; a T4 is SM 75 and falls back to fp32, but
`nanochat/engine.py:217` hardcodes the KV cache to bf16 on any CUDA device. That
mismatch is a crash, not a slowdown. Of Beam's serverless tiers that leaves
**A10G (24 GiB, SM 86)** or **RTX4090 (24 GiB, SM 89)**. Peak VRAM works out
around 8–9 GiB — 5.25 for weights, ~1 GiB of KV cache at 4096 context, and a
~1 GiB spike during prefill when `forward` materialises `(1, T, 32768)` logits —
so 24 GiB is comfortable. `config.py` pins exactly one (`A10G`). Beam may
satisfy that request with a physical RTX4090; `/health` reports the card that
actually ran. Explicit RTX4090 requests repeatedly landed on an unhealthy
serverless worker during the 2026-08-21 release test, while A10G-requested
containers booted correctly. Beam also rejects a deploy with
"Checkpoints are yet not supported between multiple GPUs" when
`checkpoint_enabled` is set and `gpu` names more than one type. The `@asgi`
signature takes a single type anyway; only `@endpoint` accepts a list.

**`authorized` defaults to `True`.** Beam's `@asgi` requires an
`Authorization: Bearer` header unless you say otherwise, which means a link in a
paper would return 401. `app.py` sets `AUTHORIZED = False` — confirm it in a
private browser window before you publish the URL anywhere.

**`memory` defaults to 128 MB.** That is not a typo in the SDK. Loading a 5 GiB
checkpoint needs real host RAM; `app.py` asks for 16 GiB and 2 CPUs.

Two things confirmed in your favour: `rustbpe` publishes manylinux wheels on
PyPI for cp310–cp313, so the image needs no Rust toolchain; and Beam does not
bill for machine startup or image pulls — only for `on_start`, request handling,
and the keep-warm window.

---

## The steps themselves

They live in **[RUNBOOK.md](RUNBOOK.md)** — 13 numbered setup steps with a
"done when" for each, then day-to-day operation. Deliberately kept in one place
so there is no second copy to drift. The rest of this file explains why those
steps are what they are.

## What `app.py` does that the brief did not cover

**Generation runs on a worker thread.** `Engine.generate` is a synchronous CUDA
loop. Iterating it directly inside an async handler — which is what
`scripts/chat_web.py` does — pins the event loop for the whole completion, so
`/health` cannot answer while anyone is mid-answer. Since `/health` is exactly
what the UI uses to detect that the model is awake, and what a platform health
check would use, `app.py` bridges the generator to asyncio through a queue.

**Client disconnects stop generation.** If a reader closes the tab, the thread is
signalled to stop rather than running to `max_tokens` on your money.

**One generation at a time,** enforced by a semaphore and by
`concurrent_requests=1`. A single replica on a single stream cannot parallelise;
queueing is more honest than thrashing. If the paper gets traffic, raise
`max_containers` in the autoscaler — each container is a full model replica.

**`kernels` is not installed.** `nanochat/flash_attention.py` only reaches for
Flash Attention 3 on Hopper (`major == 9`) and falls back to SDPA everywhere
else. On A10G/RTX4090 the package would be dead weight that also pulls a kernel
from the HF Hub at import time — i.e. network I/O inside billed `on_start`. If
you later move to an H100, add `kernels` to the image *and* pre-bake the kernel
into the image rather than fetching it on every cold start.

**The volume mounts at `/vol/model`, absolutely.** A relative mount like
`./nanochat` — which Beam's docs use as the example style — would land beside
the synced source tree and shadow the `nanochat` Python package.

**`on_start` warms the kernels.** It generates 8 throwaway tokens so CUDA kernel
selection happens during boot instead of inside the first visitor's request.

---

## Cold starts

Beam splits a cold boot into three phases: container start (< 1s), image load
(unbilled), and application start — your `on_start`, which is billed and which
is where essentially all of the time goes. Six levers, in order of size:

**1. `WEIGHTS_SOURCE = "image"`** (set in `config.py`). The bf16 export is baked
into an image layer so a warm-image worker reads it from local disk instead of
depending on highly variable Beam Volume throughput. A worker that has never
seen the layer can still spend roughly a minute pulling it; the UI retries
transient Beam 500/502/504 wake-up responses for up to 120 seconds.

**2. `fast_load.py` instead of `build_model`.** The stock loader builds the
model on meta, calls `to_empty(device)` — which allocates all 2.82B parameters
at their declared fp32 dtypes, ~10.5 GiB of VRAM — then `init_weights()` to
random-initialise every one of them, then `load_state_dict(assign=True)` to
throw all of it away. For training that is correct, because `init_weights` is
where the initialisation scheme lives. For serving it is pure cost: ~10.5 GiB of
allocation plus 2.8B parameters of RNG, discarded. `fast_load.py` assigns the
checkpoint's tensors straight onto the meta model and materialises only the
rotary cos/sin buffers, which are `persistent=False` and so absent from the
state dict. Peak VRAM during load drops from ~16 GiB to ~5.5 GiB.
`test_export.py` asserts the two paths produce identical parameters, identical
rotary tables and identical logits.

**3. `checkpoint_enabled=False`.** RTX4090 restores repeatedly returned a live
Python heap with a dead CUDA context, and snapshot state can outlive a deploy.
Do not turn this back on because the support table says it is available; only a
repeated scale-to-zero generation test can prove it works for this app.

**4. `keep_warm_seconds`,** now 1800. This does not make a cold start faster; it
makes them rarer, which is the same thing to a reader.

**5. `min_containers = 1`** removes cold starts entirely by never scaling to
zero. At the 2026-08-21 listed rates for the requested A10G plus 2 CPU and 16
GiB RAM, that is about **$1.75/hr or $42/day**. That is a deliberate launch-day
choice, not the default for sparse traffic.
If you set it, `beam deployment stop` the older versions after each redeploy —
otherwise every version keeps its own warm container running.

**6. Warm up at a realistic prompt length.** Attention selects different kernels
for a 2-token prefill than for a 400-token one, so the original token-sized
warmup left the first real request paying for kernel selection anyway. The
persona alone is ~400 tokens, so `on_start` now warms on system prompt + a
sample question. Snapshotting inverts the usual advice here: because everything
`on_start` does is captured, it is worth doing *more* work there, not less.

### One consequence of snapshotting worth knowing

The Python `random` module's state is part of the process image. Every container
restored from the same snapshot therefore starts with an identical RNG stream —
so seeding per-request sampling from `random.randint` would hand the same seed
sequence to every replica, and two readers on two fresh containers asking the
same question would get byte-identical answers. `app.py` seeds from
`os.urandom` instead, which is not restored from the snapshot.

### Considered and not implemented

**Machine pools** (`pool=` on the decorator) reserve dedicated machines. They
remove scheduling contention, not load time, and bill continuously while
reserved — so they are `MIN_CONTAINERS = 1` with extra steps, at this scale.

**safetensors** instead of a pickled state dict allows a zero-copy,
direct-to-GPU load and would plausibly take 20–40% off the read. It is not worth
it *yet*: with checkpoint restore working, that read happens roughly once per
deploy, and adopting it means the export is no longer a checkpoint directory
`scripts/chat_cli` can open — which costs you the cheapest verification step in
the runbook. Revisit if `[load] read weights` in the boot log turns out to
dominate and snapshots disappoint.

**Baking the weights into the container image** moves 5.25 GiB from the billed
application-start phase to the unbilled, host-cached image-load phase. Real, but
every weight change becomes an image rebuild, and `CHECKPOINT_ENABLED` addresses
the same problem without that.

**Trimming the image** got one easy win — `psutil` is a nanochat dependency but
is not on the serving import path, so it is gone. `tokenizers` cannot go the
same way even though this model uses the rustbpe/tiktoken tokenizer, because
`nanochat/tokenizer.py` imports it unconditionally at module scope.

## Autoscaling

Every container is a full model replica, so scaling out is scaling GPUs:

```python
QueueDepthAutoscaler(min_containers=0, max_containers=1, tasks_per_container=1)
```

With `tasks_per_container=1` and `concurrent_requests=1`, one container serves
one generation at a time and Beam adds a replica once a second request is
queued, up to `max_containers`. `MAX_CONTAINERS = 1` is the spend ceiling: a
second simultaneous reader queues instead of starting another full GPU. That is
appropriate for 5-10 visitors/day; raise it only if queueing becomes observable.

Note that scaling out does *not* avoid cold starts: replica two boots cold when
it is created.

## Cost

At Beam's 2026-08-21 listed rates, budget against the *requested* A10G class:
$1.05 GPU + $0.38 for 2 CPU + $0.32 for 16 GiB RAM = about **$1.75/hr** while a
container is billable. A full 30-minute idle tail is therefore about **$0.88**.

With 5-10 visitors/day and none at night, the conservative case where every
visitor arrives more than 30 minutes after the previous one is roughly
**$31-$61 for the first week**, plus a small amount for boot and generation.
Visits inside one 30-minute window share the same container, so clustered
traffic costs less. `MAX_CONTAINERS = 1` prevents a second replica from doubling
the burn. Machine startup and image pulls are not billed; `on_start`, requests,
and the warm window are.

---

## Known unknowns

1. **SSE passthrough.** Undocumented by Beam. Step 4 answers it for ~2¢, and both
   the server and the UI already handle the bad case.
2. **Cold image placement.** A worker with the layer cached boots quickly; a
   new worker may spend roughly a minute pulling it before `on_start` begins.
3. **Host CUDA driver.** The image installs `torch==2.9.1` from PyPI, which
   bundles the CUDA 12.8 runtime. Beam's docs warn that the host driver must
   match or exceed the container's CUDA version. Almost certainly fine on their
   current fleet, but if `torch.cuda.is_available()` comes back False in the
   logs, that is the reason — pin an older torch or a CUDA base image.
4. **Checkpointing remains disabled.** It is advertised for these GPU classes,
   but repeated RTX4090 restores kept Python alive while CUDA was unusable. Any
   future experiment must prove health *and generation* after scale-to-zero.

## Unpunctuated input

The model answers a well-formed question well and a typed-in-a-hurry one badly
("whats the tide table for tuesday", "texas"). SFT user turns are almost all
well-formed — `end_punct_rate` is 0.05 in the C3Rv3 configs — so an unpunctuated
turn is off-distribution. Two container env knobs, both off by default and
independent, both implemented in `nanochat/prompt_shaping.py`:

| env | effect | cost |
| --- | --- | --- |
| `NANOCHAT_FIX_PUNCTUATION=1` | appends a period to each visitor turn that ends without punctuation, before tokenizing it | free |
| `NANOCHAT_PRIMING_TURNS=default` or a path | splices an invisible opening exchange whose *user* turn is unpunctuated, so the model sees the shape answered well | ~40–80 prompt tokens per request |

A system prompt cannot do the second one's job: this tokenizer has no system
special token, so a system prompt is prose merged into the first user turn, and
prose does not describe a token distribution. The priming turns demonstrate it
instead. To use a file, upload it to the volume beside the persona file (start
from `configs/priming_turns/pre1930-companion.json`) and point the env at the
mounted path.

Compare the options on a checkpoint before flipping either on:
`python -m scripts.punctuation_probe --model-tag ... --system-prompt-file ...`

## Two loose ends in the repo, unrelated to Beam

**`conversation.py` duplicates `scripts/chat_web.py`.** Both must agree on the
chat template or the hosted model sees a prompt format it was never trained on.
I did not refactor `chat_web.py` because it is on the training path and you may
be running it right now. The clean fix is to lift `conversation.py` into
`nanochat/` and have both import it — worth doing before the two drift. The
unpunctuated-input shaping added later took that route: it lives in
`nanochat/prompt_shaping.py` and both copies import it, so only the template
itself is still duplicated.

**`nanochat/engine.py:217` picks the KV cache dtype from the device, not from
`COMPUTE_DTYPE`** (`bfloat16 if device.type == "cuda" else float32`). On a
serving GPU those agree, so this does not affect the deployment. It does mean
`Engine` cannot run on CPU with `NANOCHAT_DTYPE=bfloat16` — the cache would be
fp32 against bf16 activations and SDPA rejects it. `test_export.py` shims around
it; the real fix is one line, if you want CPU parity for testing. It is also the
reason a T4 would fail: fp32 compute dtype, bf16 KV cache.
