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
SCALEDOWN_WINDOW_SECONDS = 600
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
class Bart:
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
            cors=True,
            provider="modal",
            keep_warm_seconds=SCALEDOWN_WINDOW_SECONDS,
            checkpoint_enabled=False,
        )
