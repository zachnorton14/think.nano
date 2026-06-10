"""
Configuration-driven nanochat experiments for Colab and local research.

Examples:
    python -m scripts.experiment all --config experiments/think-d12-r20.json
    python -m scripts.experiment report
    python -m scripts.experiment wandb-workspace
"""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

DEFAULT_ENTITY = "jbduran-thinkingmachinesncsu"
DEFAULT_PROJECT = "think.nano"
DEFAULT_MODEL_REPO = "jbduran/think-nanochat-d12"
STEP_RE = re.compile(r"(?:model|meta|optim)_(\d{6})(?:_rank\d+)?\.(?:pt|json)$")


def get_base_dir():
    path = os.environ.get(
        "NANOCHAT_BASE_DIR",
        os.path.join(os.path.expanduser("~"), ".cache", "nanochat"),
    )
    os.makedirs(path, exist_ok=True)
    return path


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_streaming(cmd, env=None):
    print("Running:", " ".join(str(part) for part in cmd), flush=True)
    proc = subprocess.Popen(
        [str(part) for part in cmd],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        print(line, end="", flush=True)
    code = proc.wait()
    if code:
        raise subprocess.CalledProcessError(code, cmd)


class Experiment:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = read_json(self.config_path)
        self.experiment_id = self.config["experiment_id"]
        root = Path(os.environ.get("NANOCHAT_EXPERIMENT_ROOT", Path(get_base_dir()) / "experiments"))
        self.root = root / self.experiment_id
        self.data_dir = self.root / "data"
        self.tokenizer_dir = self.root / "tokenizer"
        self.pretok_dir = self.root / "pretok"
        self.checkpoint_dir = self.root / "base_checkpoints"
        self.eval_dir = self.root / "evals"
        self.log_dir = self.root / "logs"
        self.run_path = self.root / "run.json"
        self.summary_path = self.root / "summary.json"
        storage = self.config.get("storage", {})
        self.hf_repo = storage.get("hf_model_repo", DEFAULT_MODEL_REPO)
        self.hf_prefix = storage.get("path", f"experiments/{self.experiment_id}").strip("/")
        self._api = None

    @property
    def api(self):
        if self._api is None:
            from huggingface_hub import HfApi
            self._api = HfApi(token=os.environ.get("HF_TOKEN"))
        return self._api

    def initialize(self, recover_remote=True, upload_new=True):
        for path in (
            self.root, self.data_dir, self.tokenizer_dir, self.pretok_dir,
            self.checkpoint_dir, self.eval_dir, self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        atomic_json(self.root / "config.json", self.config)
        created_run = False
        if recover_remote and not self.run_path.exists():
            try:
                remote_run = self.remote_path("run.json")
                if remote_run in self.remote_files():
                    from huggingface_hub import hf_hub_download
                    cached = hf_hub_download(
                        self.hf_repo, remote_run, repo_type="model",
                        token=os.environ.get("HF_TOKEN"),
                    )
                    shutil.copy2(cached, self.run_path)
                    print("Recovered W&B run id from Hugging Face")
            except Exception as exc:
                print(f"Could not check remote run metadata: {type(exc).__name__}: {exc}")
        if not self.run_path.exists():
            atomic_json(self.run_path, {
                "experiment_id": self.experiment_id,
                "wandb_run_id": secrets.token_hex(4),
                "created_at": int(time.time()),
            })
            created_run = True
        if created_run and upload_new:
            self.upload_file(self.root / "config.json", "config.json", f"Create {self.experiment_id}")
            self.upload_file(self.run_path, "run.json", f"Store W&B run id for {self.experiment_id}")

    @property
    def run_info(self):
        self.initialize()
        return read_json(self.run_path)

    @property
    def wandb(self):
        value = self.config.get("wandb", {})
        return {
            "entity": value.get("entity", DEFAULT_ENTITY),
            "project": value.get("project", DEFAULT_PROJECT),
            "name": value.get("name", self.experiment_id),
            "group": value.get("group", self.config.get("dataset", {}).get("repo")),
            "tags": value.get("tags", []),
        }

    def environment(self):
        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "1",
            "NANOCHAT_DATA_DIR": str(self.data_dir),
            "NANOCHAT_TOKENIZER_DIR": str(self.tokenizer_dir),
            "NANOCHAT_PRETOKENIZED_DIR": str(self.pretok_dir),
            "WANDB_ENTITY": self.wandb["entity"],
            "WANDB_PROJECT": self.wandb["project"],
        })
        return env

    def remote_files(self):
        try:
            entries = self.api.list_repo_tree(
                self.hf_repo,
                path_in_repo=self.hf_prefix,
                recursive=True,
                repo_type="model",
            )
            return {
                entry.path
                for entry in entries
                if hasattr(entry, "path") and not entry.path.endswith("/")
            }
        except Exception:
            return set()

    def remote_path(self, relative):
        return f"{self.hf_prefix}/{relative}".strip("/")

    def upload_file(self, local_path, relative_path, message):
        self.api.create_repo(
            self.hf_repo, repo_type="model", private=False, exist_ok=True,
        )
        self.api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=self.remote_path(relative_path),
            repo_id=self.hf_repo,
            repo_type="model",
            commit_message=message,
        )

    def upload_folder(self, local_dir, relative_dir, message):
        self.api.create_repo(
            self.hf_repo, repo_type="model", private=False, exist_ok=True,
        )
        self.api.upload_folder(
            folder_path=str(local_dir),
            path_in_repo=self.remote_path(relative_dir),
            repo_id=self.hf_repo,
            repo_type="model",
            commit_message=message,
        )

    def download_folder(self, relative_dir, local_dir):
        from huggingface_hub import hf_hub_download
        prefix = self.remote_path(relative_dir).rstrip("/") + "/"
        selected = [path for path in self.remote_files() if path.startswith(prefix)]
        for repo_path in selected:
            cached = hf_hub_download(
                self.hf_repo, repo_path, repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            relative = repo_path[len(prefix):]
            destination = Path(local_dir) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, destination)
        return len(selected)

    def prepare_dataset(self):
        dataset = self.config["dataset"]
        adapter = dataset.get("adapter", "parquet_shards")
        if adapter == "parquet_shards":
            base_url = dataset.get("base_url")
            if not base_url:
                repo = dataset["repo"]
                revision = dataset.get("revision", "main")
                base_url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}"
            cmd = [
                sys.executable, "-u", "-m", "nanochat.dataset",
                "-n", str(dataset["num_train_shards"]),
                "-w", str(dataset.get("download_workers", 4)),
                "--base-url", base_url,
                "--data-dir", str(self.data_dir),
                "--max-shard", str(dataset["validation_shard"]),
            ]
            run_streaming(cmd, self.environment())
        elif adapter == "hf_stream":
            self._prepare_streamed_dataset(dataset)
        else:
            raise ValueError(f"Unknown dataset adapter: {adapter}")
        files = sorted(self.data_dir.glob("shard_*.parquet"))
        if len(files) < 2:
            raise RuntimeError("Dataset preparation did not produce train and validation shards")
        print(f"Prepared {len(files) - 1} train shards and validation {files[-1].name}")

    def _prepare_streamed_dataset(self, dataset):
        from datasets import load_dataset
        import pyarrow as pa
        import pyarrow.parquet as pq

        if list(self.data_dir.glob("shard_*.parquet")):
            print("Streaming dataset already prepared; skipping")
            return

        repo = dataset["repo"]
        revision = dataset.get("revision")
        config_name = dataset.get("config")
        text_column = dataset.get("text_column", "text")
        train_split = dataset.get("train_split", "train")
        val_split = dataset.get("validation_split")
        validation_rows = int(dataset.get("validation_rows", 1000))
        shard_chars = int(dataset.get("shard_chars", 250_000_000))
        max_train_rows = int(dataset.get("max_train_rows", -1))

        def stream(split):
            return load_dataset(
                repo, config_name, split=split, streaming=True,
                revision=revision, token=os.environ.get("HF_TOKEN"),
            )

        train_stream = iter(stream(train_split))
        if val_split:
            val_rows = list(_take_text_rows(stream(val_split), text_column, validation_rows))
        else:
            val_rows = list(_take_text_rows(train_stream, text_column, validation_rows))

        shard_index = 0
        rows = []
        chars = 0
        seen = 0
        for text in _iter_text(train_stream, text_column):
            rows.append(text)
            chars += len(text)
            seen += 1
            if chars >= shard_chars:
                _write_text_parquet(self.data_dir / f"shard_{shard_index:05d}.parquet", rows, pa, pq)
                shard_index += 1
                rows, chars = [], 0
            if max_train_rows > 0 and seen >= max_train_rows:
                break
        if rows:
            _write_text_parquet(self.data_dir / f"shard_{shard_index:05d}.parquet", rows, pa, pq)
            shard_index += 1
        if not val_rows:
            raise RuntimeError("Validation split produced no text rows")
        _write_text_parquet(self.data_dir / "shard_99999.parquet", val_rows, pa, pq)

    def prepare_tokenizer(self):
        tokenizer = self.config.get("tokenizer", {"mode": "train"})
        downloaded = self.download_folder("tokenizer", self.tokenizer_dir)
        if downloaded and (self.tokenizer_dir / "tokenizer.pkl").exists():
            print("Downloaded experiment tokenizer from Hugging Face")
            return
        if tokenizer.get("mode", "train") != "train":
            raise RuntimeError("Configured tokenizer was not found in the model repository")
        cmd = [
            sys.executable, "-u", "-m", "scripts.tok_train",
            "--data-dir", str(self.data_dir),
            "--tokenizer-dir", str(self.tokenizer_dir),
            "--max-chars", str(tokenizer.get("max_chars", 2_000_000_000)),
            "--doc-cap", str(tokenizer.get("doc_cap", 10_000)),
            "--vocab-size", str(tokenizer.get("vocab_size", 32768)),
        ]
        run_streaming(cmd, self.environment())
        marker = {
            "experiment_id": self.experiment_id,
            "dataset": self.config["dataset"],
            "tokenizer": tokenizer,
            "created_at": int(time.time()),
        }
        atomic_json(self.tokenizer_dir / "experiment_tokenizer.json", marker)
        self.upload_folder(self.tokenizer_dir, "tokenizer", f"Upload tokenizer for {self.experiment_id}")

    def prepare_pretokenized(self):
        pretok = self.config.get("pretokenize", {})
        if not pretok.get("enabled", True):
            return
        target_tokens = pretok.get("target_tokens")
        if target_tokens is None:
            training = self.config["training"]
            if training.get("target_tokens") is not None:
                target_tokens = math.ceil(
                    int(training["target_tokens"]) * float(pretok.get("slack", 1.03))
                )
            elif training.get("target_param_data_ratio") is not None:
                ratio = float(training["target_param_data_ratio"])
                scaling_params = int(training["scaling_params"])
                batch = int(training.get("total_batch_size", 524_288))
                horizon = math.floor(ratio * scaling_params / batch) * batch
                target_tokens = math.ceil(horizon * float(pretok.get("slack", 1.03)))
            else:
                target_tokens = -1
        cmd = [
            sys.executable, "-u", "-m", "scripts.pretok_think",
            "--data-dir", str(self.data_dir),
            "--tokenizer-dir", str(self.tokenizer_dir),
            "--output-dir", str(self.pretok_dir),
            "--source-dataset-repo", self.config["dataset"]["repo"],
            "--source-revision", self.config["dataset"].get("revision", "main"),
            "--target-tokens", str(int(target_tokens)),
            "--val-tokens", str(int(pretok.get("val_tokens", 20_971_520))),
            "--shard-tokens", str(int(pretok.get("shard_tokens", 100_000_000))),
            "--tokenizer-threads", str(int(pretok.get("tokenizer_threads", 8))),
        ]
        run_streaming(cmd, self.environment())

    def complete_local_steps(self):
        models, metas, optims = set(), set(), set()
        for path in self.checkpoint_dir.glob("*"):
            match = STEP_RE.match(path.name)
            if not match:
                continue
            step = int(match.group(1))
            if path.name.startswith("model_"):
                models.add(step)
            elif path.name.startswith("meta_"):
                metas.add(step)
            elif path.name.startswith("optim_"):
                optims.add(step)
        return sorted(models & metas & optims)

    def complete_remote_steps(self):
        prefix = self.remote_path("base_checkpoints") + "/"
        models, metas, optims = set(), set(), set()
        for path in self.remote_files():
            if not path.startswith(prefix):
                continue
            name = os.path.basename(path)
            match = STEP_RE.match(name)
            if not match:
                continue
            step = int(match.group(1))
            if name.startswith("model_"):
                models.add(step)
            elif name.startswith("meta_"):
                metas.add(step)
            elif name.startswith("optim_"):
                optims.add(step)
        return sorted(models & metas & optims)

    def checkpoint_files(self, step):
        suffix = f"{step:06d}"
        files = [
            self.checkpoint_dir / f"model_{suffix}.pt",
            self.checkpoint_dir / f"meta_{suffix}.json",
        ]
        files.extend(sorted(self.checkpoint_dir.glob(f"optim_{suffix}_rank*.pt")))
        return files

    def download_step(self, step):
        from huggingface_hub import hf_hub_download
        prefix = self.remote_path("base_checkpoints") + "/"
        suffix = f"{step:06d}"
        for repo_path in self.remote_files():
            name = os.path.basename(repo_path)
            if not repo_path.startswith(prefix):
                continue
            if not (
                name == f"model_{suffix}.pt"
                or name == f"meta_{suffix}.json"
                or name.startswith(f"optim_{suffix}_rank")
            ):
                continue
            cached = hf_hub_download(
                self.hf_repo, repo_path, repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            shutil.copy2(cached, self.checkpoint_dir / name)

    def upload_step(self, step, uploaded):
        if step in uploaded:
            return
        files = self.checkpoint_files(step)
        if len(files) < 3 or not all(path.exists() for path in files):
            return
        first = {path: path.stat().st_size for path in files}
        time.sleep(5)
        if first != {path: path.stat().st_size for path in files}:
            return
        if not all(_valid_checkpoint_file(path) for path in files):
            return
        for path in files:
            self.upload_file(
                path, f"base_checkpoints/{path.name}",
                f"Upload {self.experiment_id} step {step}",
            )
        uploaded.add(step)
        print(f"Uploaded checkpoint step {step}", flush=True)

    def start_watcher(self, stop_event, check_remote=True, upload_run_metadata=False):
        uploaded = set(self.complete_remote_steps()) if check_remote else set()

        def watch():
            if upload_run_metadata:
                try:
                    self.upload_file(
                        self.root / "config.json",
                        "config.json",
                        f"Create {self.experiment_id}",
                    )
                    self.upload_file(
                        self.run_path,
                        "run.json",
                        f"Store W&B run id for {self.experiment_id}",
                    )
                except Exception as exc:
                    print(
                        f"Background metadata upload failed; training continues: "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
            while not stop_event.is_set():
                for step in self.complete_local_steps():
                    self.upload_step(step, uploaded)
                stop_event.wait(60)
            for step in self.complete_local_steps():
                self.upload_step(step, uploaded)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        return thread, uploaded

    def reset_training_state(self):
        print(
            "Fresh training requested: preserving data/tokenizer/pretok and "
            "resetting checkpoints, evaluations, logs, and W&B run metadata.",
            flush=True,
        )
        for path in (self.checkpoint_dir, self.eval_dir, self.log_dir):
            if path.exists():
                shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
        for path in (self.run_path, self.summary_path):
            path.unlink(missing_ok=True)

    def train(self, fresh=False):
        training = self.config["training"]
        if fresh:
            self.reset_training_state()
            self.initialize(recover_remote=False, upload_new=False)
        else:
            self.initialize()

        remote_steps = []
        if not fresh:
            print(
                f"Checking Hugging Face for existing {self.experiment_id} checkpoints...",
                flush=True,
            )
            remote_steps = self.complete_remote_steps()
        resume = []
        if remote_steps:
            step = remote_steps[-1]
            print(f"Downloading checkpoint step {step}...", flush=True)
            self.download_step(step)
            resume = [f"--resume-from-step={step}"]
            print(f"Resuming from Hugging Face checkpoint step {step}")
        elif not fresh:
            print("No complete remote checkpoint found; starting at step 0.", flush=True)
        else:
            print("Starting a new model at step 0.", flush=True)

        run_info = self.run_info
        cmd = [
            sys.executable, "-u", "-m", "scripts.base_train",
            f"--depth={training.get('depth', 12)}",
            f"--model-tag={self.experiment_id}",
            f"--experiment-id={self.experiment_id}",
            f"--experiment-config={self.root / 'config.json'}",
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--data-dir={self.data_dir}",
            f"--window-pattern={training.get('window_pattern', 'L')}",
            f"--device-batch-size={training.get('device_batch_size', 16)}",
            f"--total-batch-size={training.get('total_batch_size', 524288)}",
            f"--eval-every={training.get('eval_every', 250)}",
            f"--eval-tokens={training.get('eval_tokens', 2097152)}",
            f"--core-metric-every={training.get('core_metric_every', -1)}",
            f"--sample-every={training.get('sample_every', -1)}",
            f"--save-every={training.get('save_every', 500)}",
            f"--run={self.wandb['name']}",
            f"--wandb-run-id={run_info['wandb_run_id']}",
            f"--wandb-group={self.wandb['group'] or ''}",
            f"--wandb-tags={','.join(self.wandb['tags'])}",
            *resume,
        ]
        num_iterations = self._explicit_iterations()
        if num_iterations is not None:
            cmd.extend([
                f"--num-iterations={num_iterations}",
                "--target-param-data-ratio=-1",
            ])
        else:
            cmd.append(f"--target-param-data-ratio={training.get('target_param_data_ratio', -1)}")
        if self.config.get("pretokenize", {}).get("enabled", True):
            cmd.extend(["--pretokenized", f"--pretokenized-dir={self.pretok_dir}"])

        stop = threading.Event()
        print(
            f"Starting training with W&B entity={self.wandb['entity']} "
            f"project={self.wandb['project']} run_id={run_info['wandb_run_id']}",
            flush=True,
        )
        watcher, uploaded = self.start_watcher(
            stop,
            check_remote=not fresh,
            upload_run_metadata=fresh,
        )
        try:
            run_streaming(cmd, self.environment())
        finally:
            stop.set()
            watcher.join()
            for step in self.complete_local_steps():
                self.upload_step(step, uploaded)

    def _explicit_iterations(self):
        training = self.config["training"]
        if training.get("num_iterations") is not None:
            return int(training["num_iterations"])
        batch = int(training.get("total_batch_size", 524_288))
        if training.get("target_tokens") is not None:
            return max(1, int(training["target_tokens"]) // batch)
        if training.get("epochs") is not None:
            meta_path = self.pretok_dir / "meta.json"
            if not meta_path.exists():
                raise RuntimeError("Epoch-based training requires a prepared pretokenized cache")
            unique_tokens = int(read_json(meta_path)["train_tokens"])
            return max(1, math.ceil(float(training["epochs"]) * unique_tokens / batch))
        return None

    def evaluate(self):
        local_steps = self.complete_local_steps()
        if not local_steps:
            remote_steps = self.complete_remote_steps()
            if not remote_steps:
                raise RuntimeError("No complete checkpoint available")
            self.download_step(remote_steps[-1])
            local_steps = self.complete_local_steps()
        step = local_steps[-1]
        run_info = self.run_info
        common = [
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--step={step}",
            f"--device-batch-size={self.config['training'].get('device_batch_size', 16)}",
            f"--wandb-run-id={run_info['wandb_run_id']}",
            f"--wandb-run-name={self.wandb['name']}",
        ]
        if self.config.get("pretokenize", {}).get("enabled", True):
            common.extend(["--pretokenized", f"--pretokenized-dir={self.pretok_dir}"])
        else:
            common.append(f"--data-dir={self.data_dir}")

        run_streaming([
            sys.executable, "-u", "-m", "scripts.base_eval",
            "--eval=core", "--max-per-task=-1",
            f"--output-json={self.eval_dir / 'core.json'}",
            *common,
        ], self.environment())
        run_streaming([
            sys.executable, "-u", "-m", "scripts.base_eval",
            "--eval=bpb", "--split=val", "--split-tokens=20971520",
            f"--output-json={self.eval_dir / 'val_bpb.json'}",
            *common,
        ], self.environment())
        self.build_summary()
        self.sync_metadata()

    def build_summary(self):
        steps = self.complete_local_steps()
        if not steps:
            return None
        step = steps[-1]
        meta = read_json(self.checkpoint_dir / f"meta_{step:06d}.json")
        core = read_json(self.eval_dir / "core.json") if (self.eval_dir / "core.json").exists() else {}
        bpb = read_json(self.eval_dir / "val_bpb.json") if (self.eval_dir / "val_bpb.json").exists() else {}
        loop = meta.get("loop_state", {})
        training = self.config["training"]
        summary = {
            "experiment_id": self.experiment_id,
            "dataset": self.config["dataset"].get("repo"),
            "dataset_revision": self.config["dataset"].get("revision", "main"),
            "step": step,
            "depth": training.get("depth", 12),
            "target_param_data_ratio": training.get("target_param_data_ratio"),
            "training_tokens": meta.get("total_batch_size", training.get("total_batch_size", 524288)) * step,
            "final_sampled_val_bpb": meta.get("val_bpb"),
            "minimum_sampled_val_bpb": loop.get("min_val_bpb"),
            "full_val_bpb": bpb.get("bpb", {}).get("val"),
            "core_metric": core.get("core_metric"),
            "centered_results": core.get("centered_results"),
            "training_time_seconds": loop.get("total_training_time"),
            "wandb_url": (
                f"https://wandb.ai/{self.wandb['entity']}/{self.wandb['project']}"
                f"/runs/{self.run_info['wandb_run_id']}"
            ),
            "huggingface_url": f"https://huggingface.co/{self.hf_repo}/tree/main/{self.hf_prefix}",
            "dataset_fingerprint": _json_fingerprint(self.config["dataset"]),
            "tokenizer_fingerprint": _directory_fingerprint(self.tokenizer_dir),
        }
        pretok_meta_path = self.pretok_dir / "meta.json"
        if pretok_meta_path.exists():
            unique_tokens = read_json(pretok_meta_path).get("train_tokens")
            summary["unique_train_tokens"] = unique_tokens
            if unique_tokens:
                summary["effective_epochs"] = summary["training_tokens"] / unique_tokens
        atomic_json(self.summary_path, summary)
        return summary

    def sync_metadata(self):
        for path in (self.root / "config.json", self.run_path, self.summary_path):
            if path.exists():
                self.upload_file(path, path.name, f"Update metadata for {self.experiment_id}")
        if self.eval_dir.exists():
            self.upload_folder(self.eval_dir, "evals", f"Upload evals for {self.experiment_id}")

    def all(self):
        self.initialize()
        self.prepare_dataset()
        self.prepare_tokenizer()
        self.prepare_pretokenized()
        self.train()
        self.evaluate()


def _iter_text(rows, text_column):
    for row in rows:
        text = row.get(text_column)
        if isinstance(text, str) and text.strip():
            yield text


def _take_text_rows(rows, text_column, count):
    for index, text in enumerate(_iter_text(rows, text_column)):
        yield text
        if index + 1 >= count:
            return


def _write_text_parquet(path, rows, pa, pq):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"text": rows}), path, compression="zstd", row_group_size=64)
    print(f"Wrote {path} ({len(rows):,} documents)", flush=True)


def _valid_checkpoint_file(path):
    if path.suffix == ".json":
        try:
            read_json(path)
            return True
        except Exception:
            return False
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _json_fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _directory_fingerprint(path):
    digest = hashlib.sha256()
    for file_path in sorted(Path(path).glob("*")):
        if not file_path.is_file() or file_path.name.endswith(".tmp"):
            continue
        digest.update(file_path.name.encode())
        digest.update(str(file_path.stat().st_size).encode())
        with open(file_path, "rb") as f:
            digest.update(f.read(1024 * 1024))
    return digest.hexdigest()[:16]


def collect_summaries(root):
    root = Path(root)
    summaries = []
    historical = Path("experiments/historical_runs.json")
    if historical.exists():
        summaries.extend(read_json(historical))
    for path in root.glob("*/summary.json"):
        summaries.append(read_json(path))
    summaries.sort(key=lambda row: row["experiment_id"])
    return summaries


def write_report(root):
    root = Path(root)
    summaries = collect_summaries(root)
    output_root = Path("experiments")
    output_root.mkdir(exist_ok=True)
    atomic_json(output_root / "results.json", summaries)

    fields = [
        "experiment_id", "dataset", "step", "depth", "target_param_data_ratio",
        "training_tokens", "unique_train_tokens", "effective_epochs",
        "minimum_sampled_val_bpb", "full_val_bpb",
        "core_metric", "training_time_seconds", "wandb_url", "huggingface_url",
    ]
    with open(output_root / "results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)

    lines = [
        "# Nanochat Experiment Results", "",
        "Native validation BPB is comparable only within the same dataset and validation policy.",
        "CORE is the primary cross-dataset comparison.", "",
        "| Experiment | Dataset | Tokens | Ratio | Min BPB | Full BPB | CORE | Time |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        time_seconds = row.get("training_time_seconds")
        time_text = f"{time_seconds / 60:.1f}m" if isinstance(time_seconds, (int, float)) else "-"
        lines.append(
            f"| {row['experiment_id']} | {row.get('dataset', '-')} | "
            f"{_fmt(row.get('training_tokens'))} | {_fmt(row.get('target_param_data_ratio'))} | "
            f"{_fmt(row.get('minimum_sampled_val_bpb'))} | {_fmt(row.get('full_val_bpb'))} | "
            f"{_fmt(row.get('core_metric'))} | {time_text} |"
        )
    (output_root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote report for {len(summaries)} experiments")


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def create_wandb_workspace(entity, project):
    try:
        import wandb_workspaces.reports.v2 as wr
        import wandb_workspaces.workspaces as ws
    except ImportError as exc:
        raise RuntimeError("Install wandb-workspaces before creating the workspace") from exc

    sections = [
        ws.Section(name="Validation", is_open=True, panels=[
            wr.LinePlot(title="Validation BPB by step", x="step", y=["val/bpb"]),
            wr.LinePlot(title="Validation BPB by training time", x="total_training_time", y=["val/bpb"]),
            wr.LinePlot(title="Validation BPB by FLOPs", x="total_training_flops", y=["val/bpb"]),
        ]),
        ws.Section(name="CORE", is_open=True, panels=[
            wr.LinePlot(title="CORE metric", x="step", y=["core_metric"]),
            wr.BarPlot(title="Latest CORE", metrics=["core_metric"]),
        ]),
        ws.Section(name="Training", is_open=True, panels=[
            wr.LinePlot(x="step", y=["train/loss"]),
            wr.LinePlot(x="step", y=["train/lrm_matrix", "train/lrm_adam"]),
            wr.LinePlot(x="step", y=["train/epoch"]),
            wr.LinePlot(x="step", y=["train/dt"]),
        ]),
        ws.Section(name="Efficiency", is_open=True, panels=[
            wr.LinePlot(x="step", y=["train/mfu"]),
            wr.LinePlot(x="step", y=["train/tok_per_sec"]),
        ]),
    ]
    workspace = ws.Workspace(
        name="Nanochat Dataset Experiments",
        entity=entity,
        project=project,
        sections=sections,
        runset_settings=ws.RunsetSettings(pinned_columns=[
            "summary:dataset",
            "summary:target_param_data_ratio",
            "summary:training_tokens",
            "summary:min_val_bpb",
            "summary:full_val_bpb",
            "summary:core_metric",
            "summary:training_time_seconds",
            "summary:final_mfu",
            "summary:final_tok_per_sec",
        ]),
        auto_generate_panels=True,
    )
    workspace.save()
    print(workspace.url)


def main():
    parser = argparse.ArgumentParser(description="Run reproducible nanochat experiments")
    parser.add_argument(
        "command",
        choices=["prepare", "train", "eval", "sync", "all", "report", "wandb-workspace"],
    )
    parser.add_argument("--config", type=str, help="experiment JSON config")
    parser.add_argument("--experiment-root", type=str, default=None)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="reset model checkpoints/evals/W&B state but preserve prepared data and tokenizer",
    )
    args = parser.parse_args()

    if args.experiment_root:
        os.environ["NANOCHAT_EXPERIMENT_ROOT"] = args.experiment_root
    root = os.environ.get("NANOCHAT_EXPERIMENT_ROOT", str(Path(get_base_dir()) / "experiments"))

    if args.command == "report":
        write_report(root)
        return
    if args.command == "wandb-workspace":
        create_wandb_workspace(
            os.environ.get("WANDB_ENTITY", DEFAULT_ENTITY),
            os.environ.get("WANDB_PROJECT", DEFAULT_PROJECT),
        )
        return
    if not args.config:
        parser.error("--config is required for this command")

    experiment = Experiment(args.config)
    if args.command == "prepare":
        experiment.initialize()
        experiment.prepare_dataset()
        experiment.prepare_tokenizer()
        experiment.prepare_pretokenized()
    elif args.command == "train":
        experiment.train(fresh=args.fresh)
    elif args.command == "eval":
        experiment.initialize()
        experiment.evaluate()
    elif args.command == "sync":
        experiment.initialize()
        experiment.build_summary()
        experiment.sync_metadata()
    elif args.command == "all":
        if args.fresh:
            experiment.reset_training_state()
        experiment.all()


if __name__ == "__main__":
    main()
