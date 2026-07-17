"""Fast Hopper training preflight used before downloading hosted artifacts."""

import argparse
import os

import torch
import torch.distributed as dist


def _cuda_version_tuple(value: str | None) -> tuple[int, int]:
    if not value:
        return (0, 0)
    parts = value.split(".")
    return (int(parts[0]), int(parts[1]))


def _exercise_bf16_and_fp8(device: torch.device) -> None:
    from nanochat.fp8 import Float8Linear

    # Exercise ordinary Hopper tensor cores on every visible training device.
    left = torch.randn(512, 512, device=device, dtype=torch.bfloat16)
    right = torch.randn(512, 512, device=device, dtype=torch.bfloat16)
    (left @ right).sum().item()

    # Exercise all three scaled FP8 GEMMs: forward, grad-input, and grad-weight.
    layer = Float8Linear(
        1024,
        1024,
        bias=False,
        device=device,
        dtype=torch.bfloat16,
    )
    inputs = torch.randn(
        64,
        1024,
        device=device,
        dtype=torch.bfloat16,
        requires_grad=True,
    )
    output = layer(inputs)
    output.float().square().mean().backward()
    torch.cuda.synchronize(device)


def _exercise_compile_and_fa3(device: torch.device) -> None:
    from nanochat.fp8 import Float8Linear

    # Compile the same custom FP8 autograd path used by base_train.
    layer = Float8Linear(
        1024,
        1024,
        bias=False,
        device=device,
        dtype=torch.bfloat16,
    )
    compiled_layer = torch.compile(layer, dynamic=False)
    inputs = torch.randn(
        64,
        1024,
        device=device,
        dtype=torch.bfloat16,
        requires_grad=True,
    )
    output = compiled_layer(inputs)
    output.float().square().mean().backward()
    torch.cuda.synchronize(device)

    # Require and execute FA3 instead of silently accepting the slower SDPA
    # fallback on the expensive training node.
    from nanochat.flash_attention import HAS_FA3, flash_attn

    if not HAS_FA3:
        raise RuntimeError("Flash Attention 3 did not load on the H100")
    q = torch.randn(
        1, 128, 8, 128, device=device, dtype=torch.bfloat16, requires_grad=True
    )
    k = torch.randn_like(q, requires_grad=True)
    v = torch.randn_like(q, requires_grad=True)
    attention = flash_attn.flash_attn_func(q, k, v, causal=True)
    attention.float().square().mean().backward()
    torch.cuda.synchronize(device)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-gpus", type=int, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if torch.cuda.device_count() != args.expected_gpus:
        raise RuntimeError(
            f"Expected {args.expected_gpus} GPUs, found {torch.cuda.device_count()}"
        )
    if torch.__version__.split("+")[0] != "2.9.1":
        raise RuntimeError(f"Expected PyTorch 2.9.1, found {torch.__version__}")
    if _cuda_version_tuple(torch.version.cuda) < (12, 8):
        raise RuntimeError(
            f"Expected a PyTorch CUDA runtime >=12.8, found {torch.version.cuda}"
        )

    rank = int(os.environ["RANK"])
    local_rank = int(os.environ["LOCAL_RANK"])
    world_size = int(os.environ["WORLD_SIZE"])
    if world_size != args.expected_gpus:
        raise RuntimeError(
            f"Expected world size {args.expected_gpus}, found {world_size}"
        )

    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    gpu_name = torch.cuda.get_device_name(local_rank)
    capability = torch.cuda.get_device_capability(local_rank)
    if "H100" not in gpu_name or capability != (9, 0):
        raise RuntimeError(
            f"Rank {rank} expected an H100 (SM90), found {gpu_name} SM{capability}"
        )

    dist.init_process_group(backend="nccl")
    try:
        _exercise_bf16_and_fp8(device)

        # Verify that all ranks can participate in a real NCCL collective.
        collective = torch.tensor(float(rank + 1), device=device)
        dist.all_reduce(collective)
        expected = world_size * (world_size + 1) / 2
        if collective.item() != expected:
            raise RuntimeError(
                f"NCCL all-reduce returned {collective.item()}, expected {expected}"
            )

        # The compile and hosted FA3 checks only need to run once. Other ranks
        # remain in the process group so torchrun still validates all 8 workers.
        if rank == 0:
            _exercise_compile_and_fa3(device)
        dist.barrier()

        if rank == 0:
            names = [torch.cuda.get_device_name(i) for i in range(world_size)]
            print(f"GPU preflight passed: {world_size} GPUs, {names}")
            print(
                f"Runtime preflight passed: torch={torch.__version__}, "
                f"CUDA={torch.version.cuda}, FP8=ok, FA3=ok, NCCL=ok"
            )
    finally:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
