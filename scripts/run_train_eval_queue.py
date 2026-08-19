"""Run SFT and IFEval jobs on any compatible visible GPU inventory."""

import os
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import torch


REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_CONFIG = "configs/ifeval/four-models-mini120-v1.json"
SINGLE_TRAIN_MIN_GIB = 70
PAIRED_TRAIN_MIN_GIB = 35
EVAL_MIN_GIB = 20


@dataclass(frozen=True)
class GPUInfo:
    index: int
    name: str
    memory_gib: float


@dataclass(frozen=True)
class Job:
    name: str
    command: tuple[str, ...]
    kind: str


@dataclass
class RunningJob:
    job: Job
    gpu_indices: tuple[int, ...]
    process: subprocess.Popen


def eval_job(model_id):
    return Job(
        name=f"eval:{model_id}",
        kind="eval",
        command=(
            sys.executable,
            "-u",
            "-m",
            "scripts.run_ifeval_suite",
            "--config",
            SUITE_CONFIG,
            "--model-id",
            model_id,
            "--gpu-shards",
            "1",
        ),
    )


def training_job(name, launcher):
    return Job(name=name, kind="train", command=("bash", launcher))


def discover_gpus():
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError("The queue requires at least one visible CUDA GPU")
    gpus = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        gpus.append(GPUInfo(
            index=index,
            name=torch.cuda.get_device_name(index),
            memory_gib=props.total_memory / 1024**3,
        ))
    details = "; ".join(
        f"GPU {gpu.index}: {gpu.name} {gpu.memory_gib:.1f}GiB" for gpu in gpus
    )
    print(f"Queue runtime PASS: {len(gpus)} visible GPU(s); {details}", flush=True)
    return gpus


def choose_training_gpus(available, gpus):
    """Prefer one 80 GB-class GPU, otherwise use a pair of 40 GB-class GPUs."""
    by_index = {gpu.index: gpu for gpu in gpus}
    large = sorted(
        index
        for index in available
        if by_index[index].memory_gib >= SINGLE_TRAIN_MIN_GIB
    )
    if large:
        return (large[0],)
    medium = sorted(
        index
        for index in available
        if by_index[index].memory_gib >= PAIRED_TRAIN_MIN_GIB
    )
    if len(medium) >= 2:
        return tuple(medium[:2])
    return None


def choose_eval_gpu(available, gpus):
    """Use the smallest adequate free GPU so larger devices remain available."""
    candidates = [
        gpu for gpu in gpus
        if gpu.index in available and gpu.memory_gib >= EVAL_MIN_GIB
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda gpu: (gpu.memory_gib, gpu.index)).index


def validate_inventory(gpus):
    available = {gpu.index for gpu in gpus}
    if choose_training_gpus(available, gpus) is None:
        raise RuntimeError(
            "Training requires either one 80 GB-class GPU or two 40 GB-class GPUs"
        )
    if choose_eval_gpu(available, gpus) is None:
        raise RuntimeError("IFEval requires at least one GPU with 20 GiB of VRAM")


def start_job(gpu_indices, job):
    env = os.environ.copy()
    low_memory_optimizer = job.kind == "train" and len(gpu_indices) > 1
    env.update({
        "CUDA_VISIBLE_DEVICES": ",".join(str(index) for index in gpu_indices),
        "NPROC_PER_NODE": str(len(gpu_indices)),
        # The paired 40 GB topology trades optimizer overlap for a lower peak.
        "NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY": "1" if low_memory_optimizer else "0",
    })
    if job.name == "train:c3rv3":
        env["DEFER_CHATCORE"] = "1"
    label = ",".join(str(index) for index in gpu_indices)
    print(
        f"\n=== GPU(S) {label} START {job.name}: {' '.join(job.command)} ===",
        flush=True,
    )
    process = subprocess.Popen(
        job.command,
        cwd=REPO_ROOT,
        env=env,
        start_new_session=True,
    )
    return RunningJob(job=job, gpu_indices=gpu_indices, process=process)


def terminate_running(running):
    for item in running.values():
        if item.process.poll() is None:
            try:
                os.killpg(item.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for item in running.values():
        try:
            item.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(item.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def schedule_jobs(pending_training, ready_eval, running, available, gpus):
    """Fill all compatible free GPUs, always giving ready training priority."""
    started = 0
    while available:
        if pending_training:
            allocation = choose_training_gpus(available, gpus)
            if allocation is not None:
                job = pending_training.popleft()
                for index in allocation:
                    available.remove(index)
                running[job.name] = start_job(allocation, job)
                started += 1
                continue
        if ready_eval:
            gpu_index = choose_eval_gpu(available, gpus)
            if gpu_index is not None:
                job = ready_eval.popleft()
                available.remove(gpu_index)
                running[job.name] = start_job((gpu_index,), job)
                started += 1
                continue
        break
    return started


def main():
    gpus = discover_gpus()
    validate_inventory(gpus)
    available = {gpu.index for gpu in gpus}
    pending_training = deque([
        training_job(
            "train:c3rv3",
            "runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh",
        ),
        training_job(
            "train:d34-modern",
            "runs/karpathy-nanochat-d34-complete-modern-sft.sh",
        ),
    ])
    ready_eval = deque([
        eval_job("hla-gpt1900"),
        eval_job("d32-modern-sft"),
    ])
    training_dependents = {
        "train:c3rv3": "d32-c3rv3",
        "train:d34-modern": "karpathy-d34-modern-sft",
    }
    running = {}
    completed = []
    try:
        while pending_training or ready_eval or running:
            schedule_jobs(
                pending_training, ready_eval, running, available, gpus
            )
            if not running:
                raise RuntimeError(
                    "Pending queue jobs cannot fit the currently available GPUs"
                )

            finished = []
            while not finished:
                for name, item in list(running.items()):
                    code = item.process.poll()
                    if code is not None:
                        finished.append((name, item, code))
                if not finished:
                    time.sleep(2)

            for name, item, code in finished:
                del running[name]
                available.update(item.gpu_indices)
                label = ",".join(str(index) for index in item.gpu_indices)
                if code:
                    raise RuntimeError(
                        f"GPU(s) {label} job {name} failed with exit status {code}"
                    )
                completed.append(name)
                print(f"=== GPU(S) {label} DONE {name} ===", flush=True)
                dependent = training_dependents.get(name)
                if dependent is not None:
                    ready_eval.append(eval_job(dependent))
    except BaseException:
        terminate_running(running)
        raise

    expected = 6  # two training jobs plus four model evaluations
    if len(completed) != expected:
        raise RuntimeError(f"Queue completed {len(completed)}/{expected} jobs: {completed}")
    print("\n=== Training/evaluation queue completed successfully ===", flush=True)


if __name__ == "__main__":
    main()
