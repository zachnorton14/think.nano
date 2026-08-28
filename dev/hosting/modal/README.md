# Modal deployment

`modal_app.py` deploys the same Bartholomew III runtime used by Beam as a Modal
ASGI Web Function. Beam remains the rollback target until it is deliberately
retired.

## Local setup

Use the `modal` executable directly after installing it. On this Mac,
`pip install modal` installed under Python 3.9 while Homebrew's `python3` points
at Python 3.14, so `python3 -m modal` is the wrong interpreter even though the
CLI is installed correctly.

```bash
modal setup
modal profile current
```

## Deploy and verify

```bash
modal deploy modal_app.py
python dev/hosting/beam/smoke_test.py \
  https://johnny0595--bartholomew-iii-modal-bart-web.modal.run
```

The deployment bakes the public bf16 export into a cached Modal Image layer,
then copies frequently changing source layers afterward. It requests GPUs in
the documented fallback order `A10`, `L4`, `L40S`; all support bf16 and have
enough VRAM. Do not use Modal's `any` alias because it can select a T4.

Production GPU scaling is `min_containers=0`, `max_containers=1`, and a
120-second `scaledown_window`. The GPU scales to zero, at most one full model
replica runs, and a successful container remains reusable for a two-minute
conversation window.

The established `Bart.web` URL is a CPU-only gateway. It forwards only
`GET /health`, `GET /stream-probe`, and `POST /chat/completions` to the
unadvertised `Engine.web` GPU endpoint. CORS preflights, favicon and robots requests, root
probes, unsupported methods, and malformed bodies stop at the inexpensive
gateway and cannot wake the GPU.

The gateway reserves only 0.125 CPU cores and 128 MiB, with
`min_containers=1`, so its own cold boot is not added to the model's cold start.
At Modal's current CPU and memory rates this always-ready front door is about
$1.15 per week; it does not keep an A10 allocated.

## Current cold-start evidence

On 2026-08-24, five independent A10 containers were forced after stopping the
prior idle container. End-to-end `/health` readiness was 26.15s, 13.47s,
13.02s, 12.12s, and 11.99s (median 13.02s, max 26.15s). The finalized fallback
deployment then cold-started in 18.51s. Every completed cold request returned
HTTP 200 and reported model step 42, bf16 compute, and 5.27 GiB VRAM. A request
deliberately raced immediately after `modal container stop` returned one
transient HTTP 500; waiting five seconds for the manual stop to finish removed
the test artifact.

## Official documentation

- https://modal.com/docs/guide
- https://modal.com/docs/guide/gpu
- https://modal.com/docs/examples/gpu_fallbacks
- https://modal.com/docs/guide/cold-start
- https://modal.com/docs/guide/model-weights
- https://modal.com/docs/guide/lifecycle-functions
- https://modal.com/docs/guide/webhooks
- https://modal.com/docs/guide/scale
- https://modal.com/docs/guide/timeouts
- https://modal.com/docs/guide/retries
