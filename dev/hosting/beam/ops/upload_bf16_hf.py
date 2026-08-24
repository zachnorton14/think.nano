#!/usr/bin/env python3
"""
Copy the bf16 export from the Beam volume to the HuggingFace artifacts repo.

The 5.25 GiB export lives only on `think-nano-weights` (export_bf16.py wrote it
there; the raw checkpoint on HF is the 8.37 GiB pre-export one). Baking weights
into the container image needs them fetchable at image-build time, so this
uploads them once, datacenter-to-datacenter -- no multi-GiB round trip through
a laptop:

    beam run dev/hosting/beam/ops/upload_bf16_hf.py:upload      # from repo root

Needs the `HF_TOKEN` Beam secret (`beam secret create HF_TOKEN <token>`), with
write access to the repo. Re-running overwrites the same paths; it is
idempotent, just not free.

Destination layout, which app.py's image bake mirrors:

    experiments/<BASE_ID>/sft/<MODEL_TAG>/bf16/
        model_000042.pt            5.25 GiB, bf16
        meta_000042.json
        tokenizer/tokenizer.pkl
        pre1930-companion.txt      the persona file, from the volume root
"""

from beam import Image, Volume, function

MOUNT_PATH = "/vol/model"
HF_REPO = "jbduran/bart-experiments"
BASE_EXPERIMENT_ID = "Think.Unbounded-d32-v2mix-cont"
MODEL_TAG = "Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2"
STEP = 42

HF_PREFIX = f"experiments/{BASE_EXPERIMENT_ID}/sft/{MODEL_TAG}/bf16"

# (path on the volume, path in the repo)
FILES = [
    (f"{MOUNT_PATH}/{MODEL_TAG}/model_{STEP:06d}.pt", f"{HF_PREFIX}/model_{STEP:06d}.pt"),
    (f"{MOUNT_PATH}/{MODEL_TAG}/meta_{STEP:06d}.json", f"{HF_PREFIX}/meta_{STEP:06d}.json"),
    (f"{MOUNT_PATH}/{MODEL_TAG}/tokenizer/tokenizer.pkl", f"{HF_PREFIX}/tokenizer/tokenizer.pkl"),
    (f"{MOUNT_PATH}/pre1930-companion.txt", f"{HF_PREFIX}/pre1930-companion.txt"),
]


@function(
    image=Image(python_version="python3.11").add_python_packages(["huggingface_hub"]),
    cpu=4,
    memory="4Gi",
    volumes=[Volume(name="think-nano-weights", mount_path=MOUNT_PATH)],
    secrets=["HF_TOKEN"],
    timeout=3600,
)
def upload():
    import os
    import time

    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN"])
    for src, dest in FILES:
        size = os.path.getsize(src)
        print(f"uploading {src} ({size / 1024**3:.2f} GiB) -> {dest}", flush=True)
        t0 = time.time()
        api.upload_file(
            repo_id=HF_REPO, repo_type="model",
            path_or_fileobj=src, path_in_repo=dest,
            commit_message=f"hosting: bf16 export for image bake ({os.path.basename(dest)})",
        )
        elapsed = time.time() - t0
        print(f"  done in {elapsed:.1f}s ({size / 1024**2 / max(elapsed, 0.01):.0f} MiB/s)", flush=True)
    print("all files uploaded under " + HF_PREFIX)
    return {"prefix": HF_PREFIX, "files": [dest for _, dest in FILES]}


if __name__ == "__main__":
    upload()
