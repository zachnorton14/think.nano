#!/usr/bin/env python3
"""Run original, filtered, and restyled CORE with a pinned nanochat model.

The parent process downloads artifacts and starts a worker with exactly one
model runtime on PYTHONPATH. The worker contains the prompt rendering and
scoring behavior from nanochat/core_eval.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE = Path(os.environ.get("VINTAGE_CORE_CACHE", "~/.cache/vintage-core")).expanduser()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def parse_bundle_names(value: str, registry: dict[str, Any]) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in registry]
    if not names or unknown:
        raise ValueError(f"Invalid bundles {unknown or value!r}; choose from {sorted(registry)}")
    return names


# Kept public so the prompt behavior can be parity-tested without loading a model.
def render_prompts_mc(item: dict[str, Any], continuation_delimiter: str,
                      fewshot_examples: list[dict[str, Any]] | None = None) -> list[str]:
    from jinja2 import Template

    template = Template("""
{%- for example in fewshot_examples -%}
{{ example.query }}{{ continuation_delimiter }}{{ example.choices[example.gold] }}

{% endfor -%}
{{ item.query }}{{ continuation_delimiter }}{{ choice }}""".strip())
    context = {
        "fewshot_examples": fewshot_examples or [],
        "continuation_delimiter": continuation_delimiter,
        "item": item,
    }
    return [template.render(choice=choice, **context) for choice in item["choices"]]


def render_prompts_schema(item: dict[str, Any], continuation_delimiter: str,
                          fewshot_examples: list[dict[str, Any]] | None = None) -> list[str]:
    from jinja2 import Template

    template = Template("""
{%- for example in fewshot_examples -%}
{{ example.context_options[example.gold] }}{{ continuation_delimiter }}{{ example.continuation }}

{% endfor -%}
{{ context }}{{ continuation_delimiter }}{{ item.continuation }}""".strip())
    context = {
        "fewshot_examples": fewshot_examples or [],
        "continuation_delimiter": continuation_delimiter,
        "item": item,
    }
    return [template.render(context=option, **context) for option in item["context_options"]]


def render_prompts_lm(item: dict[str, Any], continuation_delimiter: str,
                      fewshot_examples: list[dict[str, Any]] | None = None) -> list[str]:
    from jinja2 import Template

    template = Template("""
{%- for example in fewshot_examples -%}
{{ example.context | trim }}{{ continuation_delimiter }}{{ example.continuation }}

{% endfor -%}
{{ item.context | trim }}{{ continuation_delimiter }}{% if include_continuation %}{{ item.continuation }}{% endif %}""".strip())
    context = {
        "fewshot_examples": fewshot_examples or [],
        "continuation_delimiter": continuation_delimiter,
        "item": item,
    }
    without = template.render(include_continuation=False, **context).strip()
    return [without, template.render(include_continuation=True, **context)]


def score_core_logits(task_type: str, logits, input_ids, start_indices: list[int],
                      end_indices: list[int], gold: int | None = None) -> bool:
    """Apply nanochat CORE's exact-token or lowest-mean-loss decision rule."""
    import torch

    targets = torch.roll(input_ids, shifts=-1, dims=1)
    losses = torch.nn.functional.cross_entropy(
        logits.reshape(-1, logits.size(-1)), targets.reshape(-1), reduction="none"
    ).view(input_ids.size())
    predictions = logits.argmax(dim=-1)
    if task_type == "language_modeling":
        start, end = start_indices[0], end_indices[0]
        return torch.all(
            predictions[0, start - 1:end - 1] == input_ids[0, start:end]
        ).item()
    if task_type in {"multiple_choice", "schema"}:
        mean_losses = [
            losses[row, start - 1:end - 1].mean().item()
            for row, (start, end) in enumerate(zip(start_indices, end_indices))
        ]
        return mean_losses.index(min(mean_losses)) == gold
    raise ValueError(f"Unsupported task type: {task_type}")


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle_zip:
        for member in bundle_zip.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe ZIP member: {member.filename}")
        bundle_zip.extractall(destination)


def validate_bundle(bundle_dir: Path, expected_tasks: int | None = None,
                    expected_rows: int | None = None) -> dict[str, Any]:
    import yaml

    required = [bundle_dir / "core.yaml", bundle_dir / "eval_meta_data.csv"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Bundle {bundle_dir} is missing: {missing}")
    with (bundle_dir / "core.yaml").open(encoding="utf-8") as handle:
        tasks = yaml.safe_load(handle).get("icl_tasks", [])
    if expected_tasks is not None and len(tasks) != expected_tasks:
        raise ValueError(f"{bundle_dir}: expected {expected_tasks} tasks, found {len(tasks)}")
    labels: set[str] = set()
    seen_data_paths: set[Path] = set()
    rows = 0
    task_rows: dict[str, int] = {}
    for task in tasks:
        label = task["label"]
        if label in labels:
            raise ValueError(f"{bundle_dir}: duplicate task label {label}")
        labels.add(label)
        data_path = bundle_dir / "eval_data" / task["dataset_uri"]
        if not data_path.is_file():
            raise FileNotFoundError(f"{bundle_dir}: missing {data_path.relative_to(bundle_dir)}")
        with data_path.open(encoding="utf-8") as handle:
            count = sum(1 for line in handle if line.strip())
        task_rows[label] = count
        if data_path not in seen_data_paths:
            rows += count
            seen_data_paths.add(data_path)
    if expected_rows is not None and rows != expected_rows:
        raise ValueError(f"{bundle_dir}: expected {expected_rows} rows, found {rows}")
    return {"tasks": len(tasks), "rows": rows, "task_rows": task_rows}


def download_original(entry: dict[str, Any], cache_dir: Path) -> Path:
    archive = cache_dir / "bundles" / "original" / "eval_bundle.zip"
    destination = archive.parent / "extracted"
    bundle_dir = destination / entry["directory"]
    if not bundle_dir.is_dir():
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.is_file():
            print(f"Downloading {entry['url']}", flush=True)
            urllib.request.urlretrieve(entry["url"], archive)
        if destination.exists():
            shutil.rmtree(destination)
        safe_extract(archive, destination)
    return bundle_dir


def download_hf_bundle(entry: dict[str, Any], cache_dir: Path, token: str | None) -> Path:
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(
        repo_id=entry["repo_id"],
        repo_type="dataset",
        revision=entry["revision"],
        allow_patterns=[f"{entry['subdirectory']}/**"],
        cache_dir=str(cache_dir / "huggingface"),
        token=token,
    ))
    return snapshot / entry["subdirectory"]


def resolve_bundles(names: list[str], registry: dict[str, Any], cache_dir: Path,
                    token: str | None) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for name in names:
        entry = registry[name]
        if entry["type"] == "zip":
            path = download_original(entry, cache_dir)
        elif entry["type"] == "huggingface_dataset":
            path = download_hf_bundle(entry, cache_dir, token)
        else:
            raise ValueError(f"Unsupported bundle type: {entry['type']}")
        info = validate_bundle(path, entry.get("expected_tasks"), entry.get("expected_rows"))
        print(f"Validated {name}: {info['tasks']} tasks, {info['rows']:,} rows", flush=True)
        resolved[name] = path.resolve()
    return resolved


def download_model(entry: dict[str, Any], cache_dir: Path, token: str | None) -> Path:
    from huggingface_hub import snapshot_download

    patterns = entry["allow_patterns"]
    lowered = [pattern.lower() for pattern in patterns]
    if any("optim" in pattern or "optimizer" in pattern for pattern in lowered):
        raise ValueError("Model allow_patterns must never include optimizer files")
    snapshot = Path(snapshot_download(
        repo_id=entry["artifact_repo"],
        revision=entry["artifact_revision"],
        allow_patterns=patterns,
        ignore_patterns=["*optimizer*", "*optim*", "optimizer/**"],
        cache_dir=str(cache_dir / "huggingface"),
        token=token,
    ))
    for key in ("checkpoint", "metadata"):
        if not (snapshot / entry[key]).is_file():
            raise FileNotFoundError(snapshot / entry[key])
    if not (snapshot / entry["tokenizer_dir"] / "tokenizer.pkl").is_file():
        raise FileNotFoundError(snapshot / entry["tokenizer_dir"] / "tokenizer.pkl")
    return snapshot.resolve()


def resolve_runtime(entry: dict[str, Any], snapshot: Path, cache_dir: Path) -> Path:
    runtime = entry["runtime"]
    if runtime["type"] == "bundled":
        path = snapshot / runtime["path"]
        if not (path / "nanochat" / "gpt.py").is_file():
            raise FileNotFoundError(f"Bundled nanochat runtime missing from {path}")
        return path.resolve()
    if runtime["type"] != "git":
        raise ValueError(f"Unsupported runtime type: {runtime['type']}")
    slug = entry["artifact_repo"].replace("/", "--")
    path = cache_dir / "runtimes" / f"{slug}-{runtime['revision']}"
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", runtime["url"], str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "fetch", "origin", runtime["revision"], "--depth", "1"], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "--detach", runtime["revision"]], check=True)
    return path.resolve()


def run_worker(model_id: str, entry: dict[str, Any], snapshot: Path, runtime: Path,
               bundles: dict[str, Path], output_dir: Path, max_per_task: int) -> None:
    payload = {
        "model_id": model_id,
        "model": entry,
        "snapshot": str(snapshot),
        "runtime": str(runtime),
        "bundles": {name: str(path) for name, path in bundles.items()},
        "output_dir": str(output_dir.resolve()),
        "max_per_task": max_per_task,
    }
    payload_path = output_dir / "worker_input.json"
    atomic_json(payload_path, payload)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(runtime)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(payload_path)]
    subprocess.run(command, check=True, env=environment, cwd=str(runtime))


def write_tables(model_id: str, bundle_names: list[str], output_dir: Path) -> None:
    results = {name: read_json(output_dir / f"{name}.json") for name in bundle_names}
    common = set.intersection(*(set(result["centered_results"]) for result in results.values()))
    common_20 = sorted(common)
    if len(common_20) != 20:
        raise ValueError(f"Expected a 20-task intersection, found {len(common_20)}")
    summary_fields = ["model", "bundle", "native_core", "common_20_core", "runtime_seconds"]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        for name in bundle_names:
            result = results[name]
            writer.writerow({
                "model": model_id,
                "bundle": name,
                "native_core": result["core_metric"],
                "common_20_core": sum(result["centered_results"][task] for task in common_20) / 20,
                "runtime_seconds": result["runtime_seconds"],
            })
    with (output_dir / "task_accuracy.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["task", *bundle_names]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        all_tasks = sorted(set().union(*(set(result["results"]) for result in results.values())))
        for task in all_tasks:
            writer.writerow({"task": task, **{
                name: results[name]["results"].get(task, "") for name in bundle_names
            }})
    if {"original", "filtered", "restyled"}.issubset(results):
        with (output_dir / "task_deltas.csv").open("w", newline="", encoding="utf-8") as handle:
            fields = ["task", "filtered_minus_original", "restyled_minus_filtered"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for task in common_20:
                writer.writerow({
                    "task": task,
                    "filtered_minus_original": results["filtered"]["results"][task] - results["original"]["results"][task],
                    "restyled_minus_filtered": results["restyled"]["results"][task] - results["filtered"]["results"][task],
                })


# ---------------------------------------------------------------------------
# Worker: exact nanochat CORE prompt construction and scoring behavior.

def worker_main(payload_path: Path) -> None:
    import torch
    import yaml

    payload = read_json(payload_path)
    runtime = Path(payload["runtime"])
    sys.path.insert(0, str(runtime))
    from nanochat.gpt import GPT, GPTConfig
    from nanochat.tokenizer import RustBPETokenizer

    model_entry = payload["model"]
    snapshot = Path(payload["snapshot"])
    metadata = read_json(snapshot / model_entry["metadata"])
    config = GPTConfig(**metadata["model_config"])
    device = torch.device("cuda")
    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required for these checkpoints")
    torch.set_float32_matmul_precision("high")
    with torch.device("meta"):
        model = GPT(config)
    model.to_empty(device=device)
    model.init_weights()
    state = torch.load(snapshot / model_entry["checkpoint"], map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
        state = state["model"]
    elif isinstance(state, dict) and "model_state_dict" in state:
        state = state["model_state_dict"]
    state = {key.removeprefix("_orig_mod."): value for key, value in state.items()}
    model.load_state_dict(state, strict=True)
    model.eval()
    if not hasattr(model, "max_seq_len"):
        model.max_seq_len = metadata["model_config"]["sequence_len"]
    tokenizer = RustBPETokenizer.from_directory(snapshot / model_entry["tokenizer_dir"])

    def common_length(sequences, direction="left"):
        minimum = min(len(sequence) for sequence in sequences)
        indices = range(minimum) if direction == "left" else range(-1, -minimum - 1, -1)
        for index, position in enumerate(indices):
            token = sequences[0][position]
            if not all(sequence[position] == token for sequence in sequences):
                return index
        return minimum

    def make_batch(item, task_meta, examples):
        task_type = task_meta["task_type"]
        delimiter = task_meta["continuation_delimiter"]
        if task_type == "multiple_choice":
            prompts = render_prompts_mc(item, delimiter, examples)
            tokens = tokenizer(prompts, prepend=tokenizer.get_bos_token_id())
            start = common_length(tokens, "left")
            return tokens, [start] * len(tokens), [len(value) for value in tokens]
        if task_type == "schema":
            prompts = render_prompts_schema(item, delimiter, examples)
            tokens = tokenizer(prompts, prepend=tokenizer.get_bos_token_id())
            suffix = common_length(tokens, "right")
            ends = [len(value) for value in tokens]
            return tokens, [end - suffix for end in ends], ends
        if task_type == "language_modeling":
            prompts = render_prompts_lm(item, delimiter, examples)
            without, with_continuation = tokenizer(prompts, prepend=tokenizer.get_bos_token_id())
            start, end = len(without), len(with_continuation)
            assert start < end and without == with_continuation[:start]
            return [with_continuation], [start], [end]
        raise ValueError(f"Unsupported task type: {task_type}")

    @torch.inference_mode()
    def evaluate_example(index, data, task_meta):
        item = data[index]
        examples = []
        if task_meta["num_fewshot"] > 0:
            rng = random.Random(1234 + index)
            available = [candidate for candidate in range(len(data)) if candidate != index]
            examples = [data[candidate] for candidate in rng.sample(available, task_meta["num_fewshot"])]
        tokens, starts, ends = make_batch(item, task_meta, examples)
        maximum = model.max_seq_len
        cropped = []
        new_starts, new_ends = [], []
        for sequence, start, end in zip(tokens, starts, ends):
            remove = max(0, len(sequence) - maximum)
            cropped.append(sequence[remove:])
            new_starts.append(start - remove)
            new_ends.append(end - remove)
            assert start - remove >= 0
        tokens, starts, ends = cropped, new_starts, new_ends
        width = max(len(sequence) for sequence in tokens)
        input_ids = torch.full((len(tokens), width), tokenizer.get_bos_token_id(), dtype=torch.long, device=device)
        for row, sequence in enumerate(tokens):
            input_ids[row, :len(sequence)] = torch.tensor(sequence, dtype=torch.long, device=device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            outputs = model(input_ids)
        logits = outputs[0] if isinstance(outputs, tuple) else outputs
        return score_core_logits(
            task_meta["task_type"], logits, input_ids, starts, ends, item.get("gold")
        )

    # One forward pass verifies the loader without sampling benchmark rows.
    # Two tokens also satisfy runtimes whose training-path forward asserts T > 1.
    bos_id = tokenizer.get_bos_token_id()
    bos = torch.tensor([[bos_id, bos_id]], dtype=torch.long, device=device)
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        check = model(bos)
    check_logits = check[0] if isinstance(check, tuple) else check
    if check_logits.shape[:2] != (1, 2):
        raise RuntimeError(f"Unexpected loader-check output shape: {tuple(check_logits.shape)}")
    print("Model loader check passed", flush=True)

    output_dir = Path(payload["output_dir"])
    for bundle_name, bundle_value in payload["bundles"].items():
        output_path = output_dir / f"{bundle_name}.json"
        if output_path.is_file():
            completed = read_json(output_path)
            if (completed.get("model") == payload["model_id"] and
                    completed.get("bundle") == bundle_name and
                    completed.get("max_per_task") == payload["max_per_task"]):
                print(f"Keeping completed result: {output_path}", flush=True)
                continue
            print(f"Replacing result from a different run: {output_path}", flush=True)
        bundle_dir = Path(bundle_value)
        with (bundle_dir / "core.yaml").open(encoding="utf-8") as handle:
            tasks = yaml.safe_load(handle)["icl_tasks"]
        with (bundle_dir / "eval_meta_data.csv").open(encoding="utf-8") as handle:
            baselines = {row["Eval Task"]: float(row["Random baseline"]) for row in csv.DictReader(handle)}
        raw: dict[str, float] = {}
        centered: dict[str, float] = {}
        bundle_start = time.time()
        for task in tasks:
            task_start = time.time()
            label = task["label"]
            path = bundle_dir / "eval_data" / task["dataset_uri"]
            with path.open(encoding="utf-8") as handle:
                data = [json.loads(line) for line in handle if line.strip()]
            random.Random(1337).shuffle(data)
            if payload["max_per_task"] > 0:
                data = data[:payload["max_per_task"]]
            task_meta = {
                "task_type": task["icl_task_type"],
                "num_fewshot": task["num_fewshot"][0],
                "continuation_delimiter": task.get("continuation_delimiter", " "),
            }
            correct = sum(evaluate_example(index, data, task_meta) for index in range(len(data)))
            accuracy = correct / len(data)
            raw[label] = accuracy
            baseline = 0.01 * baselines[label]
            centered[label] = (accuracy - baseline) / (1.0 - baseline)
            print(f"{bundle_name}/{label}: raw={accuracy:.6f} centered={centered[label]:.6f} "
                  f"time={time.time() - task_start:.1f}s", flush=True)
        result = {
            "model": payload["model_id"],
            "bundle": bundle_name,
            "max_per_task": payload["max_per_task"],
            "core_metric": sum(centered.values()) / len(centered),
            "results": raw,
            "centered_results": centered,
            "runtime_seconds": time.time() - bundle_start,
        }
        atomic_json(output_path, result)
        print(f"Saved {output_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=sorted(read_json(ROOT / "models.json")["models"]))
    parser.add_argument("--bundles", default="original,filtered,restyled")
    parser.add_argument("--output-dir", type=Path, default=Path("/content/vintage-core-results"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--max-per-task", type=int, default=-1, help="-1 evaluates every row")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker_main(args.worker)
        return
    if not args.model:
        parser.error("--model is required")
    models = read_json(ROOT / "models.json")["models"]
    bundles_registry = read_json(ROOT / "bundles.json")["bundles"]
    bundle_names = parse_bundle_names(args.bundles, bundles_registry)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("HF_TOKEN")
    selected = models[args.model]
    bundle_paths = resolve_bundles(bundle_names, bundles_registry, args.cache_dir, token)
    snapshot = download_model(selected, args.cache_dir, token)
    runtime = resolve_runtime(selected, snapshot, args.cache_dir)
    run_worker(args.model, selected, snapshot, runtime, bundle_paths, args.output_dir, args.max_per_task)
    write_tables(args.model, bundle_names, args.output_dir)
    print(f"Results written to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()

