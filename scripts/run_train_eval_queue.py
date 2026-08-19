"""Keep two 80 GB GPUs busy with concurrent SFT and queued one-GPU IFEval jobs."""

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


@dataclass(frozen=True)
class Job:
    name: str
    command: tuple[str, ...]


def eval_job(model_id):
    return Job(
        name=f"eval:{model_id}",
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
    return Job(name=name, command=("bash", launcher))


def gpu_preflight():
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        raise RuntimeError("The queue requires two visible CUDA GPUs")
    specs = []
    for index in range(2):
        props = torch.cuda.get_device_properties(index)
        gib = props.total_memory / 1024**3
        if gib < 70:
            raise RuntimeError(
                f"GPU {index} has {gib:.1f} GiB; the queue requires 80 GB-class GPUs"
            )
        specs.append(f"GPU {index}: {torch.cuda.get_device_name(index)} {gib:.1f}GiB")
    print("Queue runtime PASS: " + "; ".join(specs), flush=True)


def start_job(gpu_index, job):
    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": str(gpu_index),
        "NPROC_PER_NODE": "1",
        "NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY": "0",
    })
    if job.name == "train:c3rv3":
        env["DEFER_CHATCORE"] = "1"
    print(
        f"\n=== GPU {gpu_index} START {job.name}: {' '.join(job.command)} ===",
        flush=True,
    )
    process = subprocess.Popen(
        job.command,
        cwd=REPO_ROOT,
        env=env,
        start_new_session=True,
    )
    return process


def terminate_running(running):
    for _, process in running.values():
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for _, process in running.values():
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main():
    gpu_preflight()
    initial = {
        0: training_job(
            "train:c3rv3",
            "runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh",
        ),
        1: training_job(
            "train:d34-modern",
            "runs/karpathy-nanochat-d34-complete-modern-sft.sh",
        ),
    }
    # These hosted models are ready immediately, but both GPUs begin with training.
    # They become the first jobs claimed by whichever training process exits first.
    ready = deque([
        eval_job("hla-gpt1900"),
        eval_job("d32-modern-sft"),
    ])
    training_dependents = {
        "train:c3rv3": "d32-c3rv3",
        "train:d34-modern": "karpathy-d34-modern-sft",
    }
    running = {
        gpu: (job, start_job(gpu, job)) for gpu, job in initial.items()
    }
    completed = []
    try:
        while running or ready:
            finished_gpus = []
            for gpu, (job, process) in list(running.items()):
                code = process.poll()
                if code is None:
                    continue
                finished_gpus.append(gpu)
                del running[gpu]
                if code:
                    raise RuntimeError(
                        f"GPU {gpu} job {job.name} failed with exit status {code}"
                    )
                completed.append(job.name)
                print(f"=== GPU {gpu} DONE {job.name} ===", flush=True)
                dependent = training_dependents.get(job.name)
                if dependent is not None:
                    ready.append(eval_job(dependent))

            for gpu in sorted(finished_gpus):
                if ready:
                    job = ready.popleft()
                    running[gpu] = (job, start_job(gpu, job))

            # Once initial jobs are gone, a GPU can also become free in an
            # iteration where another GPU is still working.
            for gpu in range(2):
                if gpu not in running and ready:
                    job = ready.popleft()
                    running[gpu] = (job, start_job(gpu, job))

            if running:
                time.sleep(2)
    except (KeyboardInterrupt, Exception):
        terminate_running(running)
        raise

    expected = 6  # two training jobs plus four model evaluations
    if len(completed) != expected:
        raise RuntimeError(f"Queue completed {len(completed)}/{expected} jobs: {completed}")
    print("\n=== Two-GPU training/evaluation queue completed successfully ===", flush=True)


if __name__ == "__main__":
    main()
