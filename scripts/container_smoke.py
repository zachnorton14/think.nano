"""Cheap GPU smoke test for the prebuilt Vast training image."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _validate_prebuilt_lock(repo_root: Path) -> None:
    venv = os.environ.get("NANOCHAT_PREBUILT_VENV")
    lock = os.environ.get("NANOCHAT_PREBUILT_LOCK")
    if not venv or not lock:
        raise RuntimeError(
            "This checkout is not running inside the prebuilt think.nano image"
        )
    image_lock = Path(lock)
    if not image_lock.is_file() or image_lock.read_bytes() != (repo_root / "uv.lock").read_bytes():
        raise RuntimeError(
            "The image dependency lock does not match this checkout; use the "
            "image tag built for the current uv.lock"
        )
    image_python = Path(venv) / "bin/python"
    if not image_python.is_file():
        raise RuntimeError(f"Prebuilt Python is missing: {image_python}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-compile",
        action="store_true",
        help="skip the tiny torch.compile check",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    _validate_prebuilt_lock(repo_root)
    expected_prefix = Path(os.environ["NANOCHAT_PREBUILT_VENV"]).resolve()
    if Path(sys.prefix).resolve() != expected_prefix:
        raise RuntimeError(
            f"Smoke test is using {sys.prefix}, not {expected_prefix}. Run "
            f"{expected_prefix}/bin/python -m scripts.container_smoke"
        )

    import datasets
    import rustbpe
    import tiktoken
    import tokenizers
    import torch
    import wandb
    from nanochat.fp8 import Float8Linear

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available inside the container")
    device = torch.device("cuda", 0)
    properties = torch.cuda.get_device_properties(device)
    dtype = torch.bfloat16 if properties.major >= 8 else torch.float16
    left = torch.randn((1024, 1024), device=device, dtype=dtype)
    right = torch.randn((1024, 1024), device=device, dtype=dtype)
    result = left @ right
    if not torch.isfinite(result).all().item():
        raise RuntimeError("CUDA matrix multiplication produced non-finite values")

    if not args.skip_compile:
        compiled = torch.compile(lambda value: torch.sin(value) + 1)
        compiled_result = compiled(result[:32, :32])
        if not torch.isfinite(compiled_result).all().item():
            raise RuntimeError("torch.compile produced non-finite values")
    torch.cuda.synchronize(device)

    print("Container smoke test passed")
    print(f"GPU: {properties.name} (SM{properties.major}{properties.minor})")
    print(f"torch={torch.__version__} CUDA={torch.version.cuda} dtype={dtype}")
    print(
        "Imports: "
        f"datasets={datasets.__version__}, wandb={wandb.__version__}, "
        f"tiktoken={tiktoken.__version__}, tokenizers={tokenizers.__version__}, "
        f"rustbpe={rustbpe.__name__}, fp8={Float8Linear.__name__}"
    )


if __name__ == "__main__":
    main()
