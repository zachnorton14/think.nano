"""Modal serverless-GPU deployment for Bartholomew III.

Deploy with:

    modal deploy modal_app.py

Beam remains a separate deployment and rollback target. This adapter reuses the
same model loader and FastAPI routes from dev/hosting/beam/app.py; provider-only
resource setup lives here.
"""

from pathlib import Path

import modal


APP_NAME = "bartholomew-iii-modal"
# Modal tries these in order for every new container. All three support bf16
# and have enough VRAM for Bart; never use "any", because Modal documents that
# it may select a T4, which does not support this model's bf16 compute path.
GPU_FALLBACKS = ["A10", "L4", "L40S"]
SCALEDOWN_WINDOW_SECONDS = 120
MAX_CONTAINERS = 1
MODEL_REPO = "jbduran/bart-experiments"
BASE_EXPERIMENT_ID = "Think.Unbounded-d32-v2mix-cont"
MODEL_TAG = "Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2"
HF_PREFIX = f"experiments/{BASE_EXPERIMENT_ID}/sft/{MODEL_TAG}/bf16"

repo_root = Path(__file__).parent

runtime_env = {
    "NANOCHAT_PROVIDER": "modal",
    "NANOCHAT_CHECKPOINT_DIR": "/img-model",
    "NANOCHAT_TOKENIZER_DIR": "/img-model/tokenizer",
    "NANOCHAT_STEP": "42",
    "NANOCHAT_SYSTEM_PROMPT_FILE": "/img-model/pre1930-companion.txt",
    "NANOCHAT_FIX_PUNCTUATION": "",
    "NANOCHAT_PRIMING_TURNS": "default",
    "NANOCHAT_TEMPERATURE": "0.8",
    "NANOCHAT_TOP_K": "50",
    "NANOCHAT_MAX_TOKENS": "512",
    "NANOCHAT_REPETITION_PENALTY": "1.0",
    "NANOCHAT_REPETITION_WINDOW": "64",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "HF_HUB_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTHONPATH": "/root:/root/beam-runtime",
}

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "torch==2.9.1",
        "fastapi[standard]>=0.117.1",
        "tiktoken>=0.11.0",
        "tokenizers>=0.22.0",
        "rustbpe>=0.1.0",
        "filelock",
        "numpy",
        "huggingface_hub[cli]",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .run_commands(
        f"hf download {MODEL_REPO} --repo-type model "
        f"--include '{HF_PREFIX}/*' --local-dir /tmp/bart-weights",
        f"mkdir -p /img-model && mv /tmp/bart-weights/{HF_PREFIX}/* /img-model/ "
        "&& rm -rf /tmp/bart-weights && ls -lah /img-model",
    )
    # Put changing source layers after the 5+ GiB model layer so ordinary code
    # edits do not download or rebuild the weights again.
    .add_local_dir(repo_root / "nanochat", "/root/nanochat", copy=True)
    .add_local_dir(repo_root / "dev/hosting/beam", "/root/beam-runtime", copy=True)
    .env(runtime_env)
    .workdir("/root")
)

gateway_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "fastapi[standard]>=0.117.1",
    "httpx>=0.28.0",
)

app = modal.App(APP_NAME)


@app.cls(
    image=image,
    gpu=GPU_FALLBACKS,
    cpu=2,
    memory=16384,
    timeout=600,
    # Five successful cold starts were 11.99-26.15s. Treat a five-minute load
    # as a failed container and let Modal's deployed-App crash recovery replace
    # it instead of leaving a visitor attached to a wedged startup indefinitely.
    startup_timeout=300,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    min_containers=0,
    max_containers=MAX_CONTAINERS,
)
@modal.concurrent(max_inputs=10, target_inputs=1)
class Engine:
    @modal.enter()
    def load(self):
        import sys

        sys.path.insert(0, "/root/beam-runtime")
        import app as runtime

        self.runtime = runtime
        self.state = runtime.load_engine()

    @modal.asgi_app()
    def web(self):
        return self.runtime.build_app(
            state=self.state,
            # The public CPU gateway owns CORS. Keeping it off here prevents
            # duplicate headers when the gateway streams this response onward.
            cors=False,
            provider="modal",
            keep_warm_seconds=SCALEDOWN_WINDOW_SECONDS,
            checkpoint_enabled=False,
        )


# Keep the established Bart.web URL as a cheap public gateway. Only the three
# routes the demo actually uses are forwarded to Engine.web, so favicon, robots,
# root-path probes, malformed methods, and CORS preflights never allocate a GPU.
# The Engine URL is captured as a Modal handle rather than embedded in the site.
engine_web = Engine().web


@app.cls(
    image=gateway_image,
    cpu=0.125,
    memory=128,
    scaledown_window=60,
    # This CPU-only front door costs about $1.15/week at current list rates and
    # removes its own cold boot from the user-visible GPU startup path.
    min_containers=1,
    max_containers=2,
)
@modal.concurrent(max_inputs=100)
class Bart:
    @modal.asgi_app()
    def web(self):
        import httpx

        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, StreamingResponse
        from starlette.background import BackgroundTask

        gateway = FastAPI(title="Bartholomew III gateway", docs_url=None, redoc_url=None)
        gateway.add_middleware(
            CORSMiddleware,
            allow_origins=["https://www.unboundedlab.com"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type"],
        )

        upstream_base = engine_web.get_web_url().rstrip("/")
        allowed = {
            ("GET", "/health"),
            ("GET", "/stream-probe"),
            ("POST", "/chat/completions"),
        }
        hop_by_hop = {
            "connection",
            "content-length",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }

        async def proxy(request: Request):
            route = (request.method, request.url.path)
            if route not in allowed:
                return JSONResponse({"detail": "Not found"}, status_code=404)

            body = b""
            if request.method == "POST":
                if not request.headers.get("content-type", "").lower().startswith("application/json"):
                    return JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)
                body = await request.body()
                if len(body) > 1_048_576:
                    return JSONResponse({"detail": "Request body is too large"}, status_code=413)

            client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0))
            try:
                upstream = await client.send(
                    client.build_request(
                        request.method,
                        upstream_base + request.url.path,
                        headers={
                            "accept": request.headers.get("accept", "*/*"),
                            **({"content-type": "application/json"} if body else {}),
                        },
                        content=body,
                    ),
                    stream=True,
                )
            except httpx.HTTPError as exc:
                await client.aclose()
                return JSONResponse(
                    {"detail": f"Inference service unavailable: {type(exc).__name__}"},
                    status_code=502,
                )

            headers = {
                name: value
                for name, value in upstream.headers.items()
                if name.lower() not in hop_by_hop
                # Modal's internal response metadata cannot be replayed through
                # another Modal Web Function; its edge rejects the response as
                # a malformed initial message if these headers are forwarded.
                and not name.lower().startswith("modal-")
            }
            return StreamingResponse(
                upstream.aiter_raw(),
                status_code=upstream.status_code,
                headers=headers,
                background=BackgroundTask(client.aclose),
            )

        gateway.add_api_route("/health", proxy, methods=["GET"])
        gateway.add_api_route("/stream-probe", proxy, methods=["GET"])
        gateway.add_api_route("/chat/completions", proxy, methods=["POST"])
        return gateway
