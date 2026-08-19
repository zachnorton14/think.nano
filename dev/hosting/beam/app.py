"""
Beam deployment for the think.nano chat model.

    beam deploy dev/hosting/app.py:handler --name think-nano

Shape of the thing:
  * the Engine is built once in `on_start`, so the load cost is paid per
    container, not per request;
  * weights are read from a Beam Volume mounted at MOUNT_PATH, so a cold start
    is a local disk read rather than a HuggingFace download;
  * generation runs on a worker thread and is bridged back to asyncio, so a
    20-second completion does not block /health -- which is what the UI polls to
    decide whether the model is awake;
  * one generation at a time (single model, single CUDA stream), enforced by a
    semaphore rather than by hoping.

Deploy-time settings live in config.py, so probe_app.py rehearses this exact
configuration. Everything in CONTAINER_ENV is read inside the container.
"""

import os
import sys

from beam import Image, QueueDepthAutoscaler, Volume, asgi

# Beam syncs the working directory into the container, so `nanochat` resolves
# from the repo root and `conversation` from this folder -- but only if both are
# on sys.path. Deploying from the repo root gives us the first for free; make
# the second explicit rather than depending on how Beam loads the entrypoint.
# The root is found by walking up to the directory that holds nanochat/, so
# moving this folder around the tree does not break the import.
_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo_root(start):
    path = start
    while not os.path.isdir(os.path.join(path, "nanochat")):
        parent = os.path.dirname(path)
        if parent == path:
            raise RuntimeError(f"No nanochat/ package found above {start}")
        path = parent
    return path


for _path in (_HERE, _find_repo_root(_HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from config import (  # noqa: E402
    APP_NAME, AUTHORIZED, CHECKPOINT_ENABLED, CONCURRENT_REQUESTS, CONTAINER_ENV,
    CPU, GPU, KEEP_WARM_SECONDS, MAX_CONTAINERS, MEMORY, MIN_CONTAINERS,
    MOUNT_PATH, TASKS_PER_CONTAINER, UI_FILE, VOLUME_NAME,
)

# `kernels` is intentionally absent: nanochat only reaches for Flash Attention 3
# on Hopper (sm90) and falls back to SDPA everywhere else, so on A10G/RTX4090 it
# would be dead weight that also pulls a kernel from the Hub at import time.
image = (
    Image(python_version="python3.11")
    .add_python_packages([
        "torch==2.9.1",
        "fastapi>=0.117.1",
        "uvicorn>=0.36.0",
        "tiktoken>=0.11.0",
        "tokenizers>=0.22.0",
        "rustbpe>=0.1.0",
        "filelock",  # nanochat.common; psutil is not on the serving import path
    ])
)

volume = Volume(name=VOLUME_NAME, mount_path=MOUNT_PATH)


# --- Container startup -------------------------------------------------------

def _build_engine():
    """Build the Engine once per container. Runs before the first request.

    Beam bills for on_start, but with CHECKPOINT_ENABLED everything done here is
    captured in the snapshot and replayed for free on later cold boots. So this
    deliberately front-loads work: read the checkpoint off the mounted volume,
    move it to the GPU, and run a realistic-length prefill so CUDA kernel
    selection happens here rather than inside the first visitor's request.
    """
    import time

    t0 = time.time()

    import torch

    from nanochat.checkpoint_manager import find_last_step
    from nanochat.common import COMPUTE_DTYPE, COMPUTE_DTYPE_REASON, compute_init
    from nanochat.engine import Engine
    from nanochat.prompt_shaping import load_priming_turns

    from fast_load import load_model_fast

    checkpoint_dir = os.environ["NANOCHAT_CHECKPOINT_DIR"]
    step_env = os.environ.get("NANOCHAT_STEP", "").strip()
    step = int(step_env) if step_env else find_last_step(checkpoint_dir)

    _, _, _, _, device = compute_init("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[boot] device={device} compute_dtype={COMPUTE_DTYPE} ({COMPUTE_DTYPE_REASON})")
    print(f"[boot] loading step {step} from {checkpoint_dir}")

    # load_model_fast, not load_model_from_checkpoint_dir: the latter allocates
    # and randomly initialises all 2.8B parameters before overwriting them. See
    # fast_load.py.
    model, tokenizer, meta = load_model_fast(
        checkpoint_dir, device, step=step,
        tokenizer_dir=os.environ.get("NANOCHAT_TOKENIZER_DIR") or None,
    )
    engine = Engine(model, tokenizer)
    load_seconds = time.time() - t0

    # Read the system prompt before warming up, so the warmup prompt can be the
    # length a real one will be.
    system_prompt = ""
    prompt_file = os.environ.get("NANOCHAT_SYSTEM_PROMPT_FILE", "").strip()
    if prompt_file:
        with open(prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()
        print(f"[boot] system prompt: {len(system_prompt)} chars from {prompt_file}")

    # User-turn shaping for unpunctuated input (nanochat/prompt_shaping.py).
    # Resolved here so a malformed priming file fails the boot -- loudly, in the
    # boot log -- rather than every request.
    fix_punctuation = os.environ.get("NANOCHAT_FIX_PUNCTUATION", "").strip().lower() \
        in ("1", "true", "yes", "on")
    priming_turns = load_priming_turns(os.environ.get("NANOCHAT_PRIMING_TURNS", "").strip())
    print(f"[boot] user-turn repair: {'on' if fix_punctuation else 'off'}, "
          f"priming turns: {len(priming_turns) or 'off'}")

    # Warm the kernels on a prompt shaped like a real one. This matters more
    # than it looks: attention picks different kernels for a 2-token prefill
    # than for a 400-token one, so a token-sized warmup leaves the first real
    # request paying for kernel selection anyway. The persona alone is ~400
    # tokens, so warm at that scale.
    #
    # With CHECKPOINT_ENABLED this is close to free: everything on_start does is
    # captured in the snapshot, so a restored container starts already warm.
    # That inverts the usual advice -- here it is worth doing MORE work in
    # on_start, not less.
    warm_t0 = time.time()
    warm_text = (system_prompt + "\n\n" if system_prompt else "") + \
        "Tell me about the wireless telegraph, and what it has meant for ships at sea."
    warm_prompt = [
        tokenizer.get_bos_token_id(),
        tokenizer.encode_special("<|user_start|>"),
        *tokenizer.encode(warm_text),
        tokenizer.encode_special("<|user_end|>"),
        tokenizer.encode_special("<|assistant_start|>"),
    ]
    for _ in engine.generate(warm_prompt, num_samples=1, max_tokens=16, temperature=0.0):
        pass
    warm_seconds = time.time() - warm_t0
    print(f"[boot] warmed on a {len(warm_prompt)}-token prefill")

    vram = torch.cuda.memory_allocated() / 1024 ** 3 if torch.cuda.is_available() else 0.0
    print(f"[boot] ready in {load_seconds + warm_seconds:.1f}s "
          f"(load {load_seconds:.1f}s, warmup {warm_seconds:.1f}s, {vram:.2f} GiB allocated)")

    return {
        "engine": engine,
        "tokenizer": tokenizer,
        "meta": meta,
        "step": step,
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "compute_dtype": str(COMPUTE_DTYPE),
        "vram_gib": round(vram, 2),
        "boot_seconds": round(load_seconds + warm_seconds, 1),
        "system_prompt": system_prompt,
        "priming_turns": priming_turns,
        "fix_punctuation": fix_punctuation,
        # Wall clock at the moment on_start finished. A process restored from a
        # Beam memory snapshot replays this value rather than re-recording it,
        # so an age far greater than KEEP_WARM_SECONDS is positive evidence the
        # container was restored: a merely-warm container cannot have idled
        # longer than its own keep-warm window without being shut down.
        "booted_at": time.time(),
    }


def load_engine():
    """Run the real loader, but never let a failure vanish into the boot log.

    Beam brings the ASGI app up whether or not on_start succeeded, so an
    exception here would otherwise turn every later request into an opaque 500
    -- "'NoneType' object is not subscriptable", raised from deep inside a route
    -- while the traceback that explains it sits only in `beam logs`. That is
    the most expensive failure mode this deployment has, because the symptom
    points nowhere near the cause.

    Returning the traceback instead lets /health serve it directly, so
    `curl <url>/health` answers "why is it broken?" without the dashboard.
    """
    try:
        return _build_engine()
    except Exception:
        import traceback

        tb = traceback.format_exc()
        print("[boot] FAILED -- this container will serve 503 until it is fixed:", flush=True)
        print(tb, flush=True)
        return {"boot_error": tb}


# --- The web app -------------------------------------------------------------

@asgi(
    name=APP_NAME,
    image=image,
    on_start=load_engine,
    gpu=GPU,
    cpu=CPU,
    memory=MEMORY,
    volumes=[volume],
    env=CONTAINER_ENV,
    keep_warm_seconds=KEEP_WARM_SECONDS,
    concurrent_requests=CONCURRENT_REQUESTS,
    authorized=AUTHORIZED,
    timeout=600,
    checkpoint_enabled=CHECKPOINT_ENABLED,
    autoscaler=QueueDepthAutoscaler(
        min_containers=MIN_CONTAINERS,
        max_containers=MAX_CONTAINERS,
        tasks_per_container=TASKS_PER_CONTAINER,
    ),
)
def handler(context):
    import asyncio
    import json
    import logging
    import pathlib
    import threading
    import time

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel
    from typing import List, Optional

    from conversation import (
        ValidationError,
        render_conversation_tokens,
        validate_messages,
        validate_sampling,
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
    logger = logging.getLogger(APP_NAME)

    UI_HTML = (pathlib.Path(__file__).parent / UI_FILE).read_text(encoding="utf-8")

    def env(name, cast, fallback):
        """Read a tuning knob, tolerating a blank value in CONTAINER_ENV."""
        raw = os.environ.get(name, "").strip()
        return cast(raw) if raw else fallback

    DEFAULTS = {
        "temperature": env("NANOCHAT_TEMPERATURE", float, 0.8),
        "top_k": env("NANOCHAT_TOP_K", int, 50),
        "max_tokens": env("NANOCHAT_MAX_TOKENS", int, 512),
        "repetition_penalty": env("NANOCHAT_REPETITION_PENALTY", float, 1.0),
    }
    # 0 means "penalise over the whole response", which Engine spells as None.
    REPETITION_WINDOW = env("NANOCHAT_REPETITION_WINDOW", int, 64) or None

    # One generation at a time. The model is a single replica on a single
    # stream; overlapping requests would interleave, not parallelise.
    gpu_lock = asyncio.Semaphore(1)

    def fresh_seed():
        """A per-request sampling seed drawn from the OS, not from `random`.

        CHECKPOINT_ENABLED snapshots the process after on_start, and the Python
        `random` module's state is part of that snapshot. Every container
        restored from it therefore starts with an identical RNG stream, so
        `random.randint` would hand the same seed sequence to every replica --
        two readers on two fresh containers asking the same question would get
        byte-identical answers. os.urandom is not restored from the snapshot.
        """
        return int.from_bytes(os.urandom(4), "big") >> 1  # fits in 2**31 - 1

    SSE_HEADERS = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # Standard opt-out for nginx-family proxies that would otherwise buffer.
        "X-Accel-Buffering": "no",
    }

    BOOT_MISSING = (
        "on_start produced no value: the container came up without ever running "
        "the loader. Check `beam logs --deployment-id <id>` for the boot lines."
    )

    async def gpu_alive(timeout=8.0):
        """Touch CUDA, briefly and with a deadline. Returns (ok, detail).

        Without this /health can report a perfectly healthy container whose GPU
        is dead, which is the single most misleading thing this service has done:
        it reads `on_start_value` out of memory and never goes near the device,
        so a container restored from a Beam memory snapshot with a broken CUDA
        context answers 200 in a millisecond while every generation hangs on its
        first kernel launch. The check that says "fine" and the thing that is
        broken were on different sides of the GPU boundary.

        Bounded and on a thread, so a wedged device costs one 503 rather than an
        event loop that never comes back. The op is a single-element add: tens of
        microseconds when the device is healthy.
        """
        import torch

        if not torch.cuda.is_available():
            return True, "cpu"

        def touch():
            torch.zeros(1, device="cuda").add_(1).item()

        try:
            await asyncio.wait_for(asyncio.to_thread(touch), timeout)
            return True, ""
        except asyncio.TimeoutError:
            return False, (f"CUDA did not answer a one-element add within {timeout}s. "
                           "The container is up but the device is not usable -- "
                           "generation would hang rather than fail.")
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def boot():
        """The on_start payload. Read lazily so import order cannot bite us.

        A container whose on_start failed still serves HTTP -- it just has no
        model. load_engine() hands the traceback through instead of dying, and
        this is where it becomes a 503 whose body says what happened, rather
        than a 500 from whichever route touched the missing state first.
        """
        state = context.on_start_value
        if state is None:
            raise HTTPException(status_code=503, detail=BOOT_MISSING)
        if "boot_error" in state:
            raise HTTPException(status_code=503, detail=state["boot_error"])
        return state

    app = FastAPI(title="Bartholomew III")

    # No CORSMiddleware here on purpose. Beam's proxy already answers preflights
    # itself and stamps `Access-Control-Allow-Origin: *` on every response, so a
    # second set from FastAPI made the header read `*, *` -- which browsers
    # reject outright ("contains multiple values ... but only one is allowed"),
    # breaking exactly the cross-origin case the middleware was meant to enable.
    # Verified with an OPTIONS probe: the proxy replies 204 with
    # Allow-Origin/Methods/Headers all `*` without ever waking a container.
    # preview_ui.py sends its own CORS headers, so local file:// previews of
    # ui_updated.html are unaffected.

    class ChatMessage(BaseModel):
        role: str
        content: str

    class ChatRequest(BaseModel):
        messages: List[ChatMessage]
        temperature: Optional[float] = None
        max_tokens: Optional[int] = None
        top_k: Optional[int] = None
        repetition_penalty: Optional[float] = None
        stream: bool = True

    # -- routes ---------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTMLResponse(UI_HTML)

    @app.get("/health")
    async def health():
        """Cheap and non-blocking: this returning 200 *is* the wake signal.

        Beam queues requests while a container boots, so the UI's first call
        here returns exactly when the model is ready to answer.
        """
        state = context.on_start_value
        if state is None or "boot_error" in state:
            # The one endpoint that must answer even when nothing else can: this
            # is what the UI polls and what smoke_test.py hits first, so it is
            # the cheapest place to read a boot failure off.
            return JSONResponse(status_code=503, content={
                "status": "error",
                "ready": False,
                "error": BOOT_MISSING if state is None else state["boot_error"],
            })

        gpu_ok, gpu_detail = await gpu_alive()
        if not gpu_ok:
            return JSONResponse(status_code=503, content={
                "status": "error",
                "ready": False,
                "error": "The model is loaded but the GPU is not responding.\n\n"
                         + gpu_detail
                         + "\n\nThis is what a container restored from a broken memory "
                           "snapshot looks like. Set CHECKPOINT_ENABLED = False in "
                           "config.py and redeploy; MIN_CONTAINERS = 1 avoids the cold "
                           "boot that triggers it at all.",
            })

        meta = state["meta"]
        return {
            "status": "ok",
            "ready": True,
            "busy": gpu_lock.locked(),
            # How long ago on_start finished, in this process's own memory.
            # Read it against KEEP_WARM_SECONDS: a container cannot idle longer
            # than its keep-warm window and survive, so an age much greater than
            # that means this process did not boot -- it was restored from a
            # snapshot. That is the one externally visible way to tell the two
            # boot paths apart, and they fail differently.
            "process_age_seconds": (round(time.time() - state["booted_at"], 1)
                                    if state.get("booted_at") else None),
            "keep_warm_seconds": KEEP_WARM_SECONDS,
            "checkpoint_enabled": CHECKPOINT_ENABLED,
            "model": {
                "step": state["step"],
                "config": meta.get("model_config", {}),
                "val_bpb": meta.get("val_bpb"),
                "storage_dtype": meta.get("export", {}).get("storage_dtype", "float32"),
            },
            "runtime": {
                "gpu": state["gpu_name"],
                "device": state["device"],
                "compute_dtype": state["compute_dtype"],
                "vram_gib": state["vram_gib"],
                "boot_seconds": state["boot_seconds"],
            },
            "defaults": DEFAULTS,
        }

    @app.get("/stream-probe")
    async def stream_probe():
        """Emit 6 frames 500ms apart, to prove SSE is not being buffered.

        Beam's docs do not state whether an ASGI StreamingResponse passes
        through unbuffered. Hit this before wiring up the GPU: if the frames
        arrive together at the end rather than one every half second, set
        `stream: false` on chat requests and the UI falls back cleanly.
        """
        import time

        async def gen():
            for i in range(6):
                yield f"data: {json.dumps({'i': i, 't': round(time.time(), 3)})}\n\n"
                await asyncio.sleep(0.5)
            yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    def build_tokens(request: ChatRequest, max_new_tokens: int):
        state = boot()
        messages = [m.model_dump() for m in request.messages]
        try:
            validate_messages(messages)
            validate_sampling(
                temperature=request.temperature, top_k=request.top_k,
                max_tokens=request.max_tokens, repetition_penalty=request.repetition_penalty,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return render_conversation_tokens(
            state["tokenizer"],
            state["engine"].model.config.sequence_len,
            messages,
            max_new_tokens,
            default_system_prompt=state["system_prompt"],
            priming_turns=state["priming_turns"],
            fix_punctuation=state["fix_punctuation"],
            log=logger.info,
        )

    async def token_stream(tokens, params):
        """Run Engine.generate on a thread; yield decoded text on the loop.

        Engine.generate is a synchronous CUDA loop. Iterating it directly inside
        an async generator would pin the event loop for the whole completion and
        make /health time out mid-answer.
        """
        state = boot()
        engine, tokenizer = state["engine"], state["tokenizer"]
        assistant_end = tokenizer.encode_special("<|assistant_end|>")
        bos = tokenizer.get_bos_token_id()

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()

        def produce():
            try:
                for column, _ in engine.generate(tokens, num_samples=1, **params):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", column[0]))
            except Exception as exc:  # surfaced to the client below
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

        thread = threading.Thread(target=produce, daemon=True, name="nanochat-generate")
        thread.start()

        # Accumulate tokens so multi-byte UTF-8 (emoji, accents) is never split
        # across two SSE frames.
        accumulated, last_clean = [], ""
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "end":
                    return
                if kind == "error":
                    raise payload
                if payload == assistant_end or payload == bos:
                    stop.set()
                    continue
                accumulated.append(payload)
                current = tokenizer.decode(accumulated)
                if current.endswith("�"):
                    continue  # incomplete UTF-8 sequence, wait for the next token
                new_text = current[len(last_clean):]
                if new_text:
                    last_clean = current
                    yield new_text
        finally:
            # Covers the client hanging up mid-answer: stop paying for tokens
            # nobody is reading.
            stop.set()

    @app.post("/chat/completions")
    async def chat_completions(request: ChatRequest, http_request: Request):
        max_new_tokens = request.max_tokens if request.max_tokens is not None else DEFAULTS["max_tokens"]
        tokens = build_tokens(request, max_new_tokens)
        params = dict(
            max_tokens=max_new_tokens,
            temperature=request.temperature if request.temperature is not None else DEFAULTS["temperature"],
            top_k=request.top_k if request.top_k is not None else DEFAULTS["top_k"],
            repetition_penalty=(request.repetition_penalty if request.repetition_penalty is not None
                                else DEFAULTS["repetition_penalty"]),
            repetition_window=REPETITION_WINDOW,
            seed=fresh_seed(),
        )
        logger.info(f"prompt={len(tokens)} tokens, max_new={max_new_tokens}, stream={request.stream}")

        if not request.stream:
            # Fallback for environments where SSE turns out to be buffered.
            async with gpu_lock:
                parts = [chunk async for chunk in token_stream(tokens, params)]
            return JSONResponse({"content": "".join(parts)})

        async def sse():
            async with gpu_lock:
                try:
                    async for text in token_stream(tokens, params):
                        if await http_request.is_disconnected():
                            break
                        yield f"data: {json.dumps({'token': text}, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.exception("generation failed")
                    yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)

    return app
