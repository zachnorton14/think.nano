"""
Configuration-driven nanochat experiments for Colab and local research.

Examples:
    python -m scripts.experiment all --config configs/base/think-d12-r20.json
    python -m scripts.experiment train --config configs/sft/smoltalk-mmlu3-gsm8k4-v1.json
    python -m scripts.experiment wandb-workspace
"""

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import zipfile
from pathlib import Path

DEFAULT_ENTITY = "jbduran-thinkingmachinesncsu"
DEFAULT_PROJECT = "think.nano"
DEFAULT_MODEL_REPO = "jbduran/think.nano"
STEP_RE = re.compile(r"(?:model|meta|optim)_(\d{6})(?:_rank\d+)?\.(?:pt|json)$")
OPTIM_RANK_RE = re.compile(r"optim_(\d{6})_rank(\d+)\.pt$")
STAGES = {"base", "sft", "posttrain"}
# How a branched run positions its learning-rate schedule relative to the parent:
#   branch   - a fresh warmup/warmdown across this run's own span (default)
#   continue - keep the parent's global schedule position, so this run picks the
#              schedule up exactly where the parent stopped
BRANCH_LR_SCHEDULES = ("branch", "continue")


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


def _copy_cached_file(source, destination):
    """Atomically copy a hosted artifact without shutil's sendfile fast path.

    Some overlayfs-backed cloud containers report a spurious ENOSPC from
    sendfile even when the destination filesystem has ample free space. Hosted
    artifacts are setup-time copies, so use the portable buffered path and
    replace the destination only after the copy completes.
    """
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".copying")
    try:
        with source.open("rb") as source_file, temporary.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file, length=16 * 1024 * 1024)
        shutil.copystat(source, temporary)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _complete_steps(paths, prefix, required_ranks=None):
    """Steps under `prefix` that have model, meta, and optimizer files.

    `required_ranks` demands that exact set of optimizer shards; without it any
    optimizer shard counts, which is what auto-detecting a parent checkpoint needs.
    """
    models, metas, optimizer_ranks = set(), set(), {}
    for path in paths:
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
            rank_match = OPTIM_RANK_RE.match(name)
            if rank_match:
                optimizer_ranks.setdefault(step, set()).add(int(rank_match.group(2)))
    if required_ranks is None:
        return sorted(step for step in models & metas if optimizer_ranks.get(step))
    return sorted(
        step for step in models & metas
        if required_ranks.issubset(optimizer_ranks.get(step, set()))
    )


def _config_iterations(config):
    """Planned optimizer steps for a config, or None when the horizon can only be
    known from a prepared token cache (epoch-based runs)."""
    training = config.get("training", {})
    batch = int(training.get("total_batch_size", 524_288))
    mixture = config.get("mixture_schedule")
    if mixture and mixture.get("total_tokens") is not None:
        return max(1, int(mixture["total_tokens"]) // batch)
    if training.get("num_iterations") is not None:
        return int(training["num_iterations"])
    if training.get("target_tokens") is not None:
        return max(1, int(training["target_tokens"]) // batch)
    ratio = training.get("target_param_data_ratio")
    scaling_params = training.get("scaling_params")
    if ratio is not None and scaling_params and float(ratio) > 0:
        return int(math.floor(float(ratio) * int(scaling_params) / batch))
    return None


def _model_dimensions(config):
    """(n_layer, model_dim, n_head) implied by a base config's training block.

    Mirrors build_model_meta in scripts.base_train; base_train re-checks these
    against the parent checkpoint before any weights are loaded.
    """
    training = config.get("training", {})
    depth = int(training.get("depth", 12))
    aspect_ratio = int(training.get("aspect_ratio", 64))
    head_dim = int(training.get("head_dim", 128))
    model_dim = ((depth * aspect_ratio + head_dim - 1) // head_dim) * head_dim
    return depth, model_dim, model_dim // head_dim


def _dataset_label(config):
    """One-line description of the data a base config trains on."""
    if config.get("mixture_schedule"):
        stages = config["mixture_schedule"].get("stages", [])
        datasets = config.get("datasets", {})
        parts = []
        for stage in stages:
            source = stage.get("source")
            repo = datasets.get(source, {}).get("repo", "?")
            subfolder = datasets.get(source, {}).get("subfolder")
            parts.append(f"{source}={repo}{'/' + subfolder.strip('/') if subfolder else ''}")
        return ("mixture: " + " -> ".join(parts)) if parts else "mixture"
    dataset = config.get("dataset", {})
    label = dataset.get("repo", "(none)")
    if dataset.get("subfolder"):
        label += "/" + dataset["subfolder"].strip("/")
    return label


def _tokenizer_source(spec, experiment_id):
    """The experiment whose tokenizer bytes a run trains with: its own when it
    trains one, otherwise the run it reuses."""
    if spec.get("mode", "train") == "reuse" and spec.get("source_experiment_id"):
        return spec["source_experiment_id"]
    return experiment_id


def _tokenizer_label(spec, source):
    label = str(source)
    if spec.get("vocab_size"):
        label += f" (vocab {int(spec['vocab_size']):,})"
    return label


def _complete_ratio_scout_output(output, step):
    return bool(
        isinstance(output, dict)
        and output.get("step") == step
        and output.get("core_metric") is not None
        and output.get("bpb", {}).get("val") is not None
    )


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
    def __init__(
        self,
        config_path,
        parent_experiment_id=None,
        parent_step=None,
        nproc_per_node=1,
        branch_step=None,
    ):
        self.config_path = Path(config_path).resolve()
        self.config = read_json(self.config_path)
        self.stage = self.config.get("stage", "base")
        if self.stage not in STAGES:
            raise ValueError(f"Unsupported experiment stage: {self.stage}")
        self.nproc_per_node = int(nproc_per_node)
        if self.nproc_per_node < 1:
            raise ValueError("nproc_per_node must be at least 1")
        if self.stage != "base" and self.nproc_per_node != 1:
            raise ValueError("--nproc-per-node currently supports base training only")
        self.parent = dict(self.config.get("parent", {}))
        # A base run may branch off another base run: it starts from that run's
        # weights (and optimizer state) and then trains with its own data and
        # hyperparameters. Absent a "branch" block this dict is empty and every
        # path below is the pre-existing from-scratch base run.
        self.branch = dict(self.config.get("branch", {}))
        if "branch" in self.config and self.stage != "base":
            raise ValueError(
                "branch is only supported for base configs; sft and posttrain "
                "configs identify their checkpoint through 'parent'"
            )
        if branch_step is not None and "branch" in self.config:
            self.branch["parent_step"] = int(branch_step)
        # The presence of the key is the intent, so an incomplete block fails loudly
        # instead of silently training from scratch.
        self.is_branch = "branch" in self.config
        self.branch_parent_id = self.branch.get("parent_experiment_id")
        self.branch_lr_schedule = self.branch.get("lr_schedule", "branch")
        self.branch_load_optimizer = bool(self.branch.get("load_optimizer", True))
        self._branch_parent_config = None
        if parent_experiment_id is not None:
            self.parent["base_experiment_id"] = parent_experiment_id
        if parent_step is not None:
            self.parent["checkpoint_step"] = parent_step
        self.base_experiment_id = (
            None if self.stage == "base"
            else self.parent.get("base_experiment_id")
        )
        if self.stage != "base" and not self.base_experiment_id:
            raise ValueError(f"{self.stage} config requires parent.base_experiment_id")
        # experiment_id: explicit in config, or auto-generated from parent + suffix
        if "experiment_id" in self.config:
            self.experiment_id = self.config["experiment_id"]
        elif self.stage != "base" and "experiment_suffix" in self.config:
            self.experiment_id = f"{self.base_experiment_id}-{self.config['experiment_suffix']}"
        else:
            raise ValueError("Config requires either experiment_id or experiment_suffix")
        if self.stage == "base":
            self.base_experiment_id = self.experiment_id
        self.sft_experiment_id = (
            self.experiment_id if self.stage == "sft"
            else self.parent.get("sft_experiment_id")
        )
        if self.stage == "posttrain" and not self.sft_experiment_id:
            raise ValueError("posttrain config requires parent.sft_experiment_id")

        experiment_root = Path(os.environ.get(
            "NANOCHAT_EXPERIMENT_ROOT",
            Path(get_base_dir()) / "experiments",
        ))
        self.experiment_root = experiment_root
        # A branch keeps its own top-level experiment tree; only the parent's
        # checkpoint is read, from the parent's own directory.
        self.branch_parent_root = (
            experiment_root / self.branch_parent_id if self.branch_parent_id else None
        )
        self.branch_parent_checkpoint_dir = (
            self.branch_parent_root / "base_checkpoints"
            if self.branch_parent_root else None
        )
        self.branch_parent_hf_prefix = (
            f"experiments/{self.branch_parent_id}" if self.branch_parent_id else None
        )
        self.base_root = experiment_root / self.base_experiment_id
        if self.stage == "base":
            self.root = self.base_root
            self.hf_prefix = f"experiments/{self.base_experiment_id}"
        elif self.stage == "sft":
            self.root = self.base_root / "sft" / self.experiment_id
            self.hf_prefix = (
                f"experiments/{self.base_experiment_id}/sft/{self.experiment_id}"
            )
        else:
            self.root = (
                self.base_root / "sft" / self.sft_experiment_id
                / "posttrain" / self.experiment_id
            )
            self.hf_prefix = (
                f"experiments/{self.base_experiment_id}/sft/{self.sft_experiment_id}"
                f"/posttrain/{self.experiment_id}"
            )

        self.data_dir = self.base_root / "data"
        self.tokenizer_dir = self.base_root / "tokenizer"
        self.pretok_dir = self.base_root / "pretok"
        # Multi-stage data mixtures build one pretokenized cache per named source under
        # pretok_<source>/. Absent a mixture_schedule this dict is empty and nothing here
        # changes the single-source path above.
        self.mixture_config = self.config.get("mixture_schedule")
        self.mixture_source_dirs = {}
        self.mixture_data_dirs = {}
        self.mixture_datasets = self.config.get("datasets", {})
        if self.stage == "base" and self.mixture_config:
            mixture_sources = []
            for _stage in self.mixture_config.get("stages", []):
                _name = _stage.get("source")
                if _name and _name not in mixture_sources:
                    mixture_sources.append(_name)
            self.mixture_source_dirs = {
                name: self.base_root / f"pretok_{name}" for name in mixture_sources
            }
            self.mixture_data_dirs = {
                name: self.base_root / f"data_{name}" for name in mixture_sources
            }
        self.checkpoint_relative = "base_checkpoints" if self.stage == "base" else "checkpoints"
        self.checkpoint_dir = self.root / self.checkpoint_relative
        self.eval_dir = self.root / "evals"
        self.log_dir = self.root / "logs"
        self.run_path = self.root / "run.json"
        self.summary_path = self.root / "summary.json"
        artifacts = self.config.get("artifacts", {})
        storage = self.config.get("storage", {})
        self.hf_repo = artifacts.get(
            "repo", storage.get("hf_model_repo", DEFAULT_MODEL_REPO)
        )
        self.config_fingerprint = _json_fingerprint(self.config)
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
        self.validate_config()
        runtime_config = dict(self.config)
        runtime_config["config_fingerprint"] = self.config_fingerprint
        runtime_config["artifact_path"] = self.hf_prefix
        local_config = self.root / "config.json"
        if local_config.exists():
            existing = read_json(local_config)
            existing.pop("config_fingerprint", None)
            existing.pop("artifact_path", None)
            if _json_fingerprint(existing) != self.config_fingerprint:
                raise RuntimeError(
                    f"Experiment ID {self.experiment_id!r} already has a different "
                    "local config. Use a new experiment ID."
                )
        if recover_remote:
            self._validate_remote_config()
        atomic_json(local_config, runtime_config)
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
                    _copy_cached_file(cached, self.run_path)
                    print("Recovered W&B run id from Hugging Face")
            except Exception as exc:
                print(f"Could not check remote run metadata: {type(exc).__name__}: {exc}")
        if not self.run_path.exists():
            atomic_json(self.run_path, {
                "experiment_id": self.experiment_id,
                "stage": self.stage,
                "base_experiment_id": self.base_experiment_id,
                "parent_experiment_id": self.parent_experiment_id,
                "parent_checkpoint_step": self.parent_checkpoint_step,
                "branch_parent_step": self.branch.get("parent_step"),
                "config_fingerprint": self.config_fingerprint,
                "wandb_run_id": (
                    secrets.token_hex(4)
                    if self.config.get("wandb", {}).get("enabled", True)
                    else None
                ),
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
            "enabled": value.get("enabled", True),
        }

    @property
    def parent_experiment_id(self):
        if self.stage == "base":
            # Only a branched base run has a parent; from-scratch runs have none.
            return self.branch_parent_id
        if self.stage == "sft":
            return self.base_experiment_id
        return self.sft_experiment_id

    @property
    def parent_checkpoint_step(self):
        if self.stage == "base":
            return self.branch.get("parent_step")
        return self.parent.get("checkpoint_step")

    @property
    def tokenizer_spec(self):
        """The tokenizer block this run trains with. A branch that does not name one
        inherits its parent's: branched weights are tied to the parent vocabulary."""
        tokenizer = self.config.get("tokenizer")
        if tokenizer is not None:
            return tokenizer
        if self.is_branch:
            spec = {"mode": "reuse", "source_experiment_id": self.branch_parent_id}
            parent_vocab = self.branch_parent_config().get("tokenizer", {}).get(
                "vocab_size"
            )
            if parent_vocab:
                spec["vocab_size"] = parent_vocab
            return spec
        return {"mode": "train"}

    def branch_parent_config(self):
        """The parent's immutable specification from Git."""
        if self._branch_parent_config is not None:
            return self._branch_parent_config
        path = self._config_registry_path("base", self.branch_parent_id)
        if not path.exists():
            raise RuntimeError(
                f"Branch parent config not found: {path}. Branching requires the "
                "parent's immutable specification in Git."
            )
        parent = read_json(path)
        if parent.get("experiment_id") != self.branch_parent_id:
            raise RuntimeError(f"Parent config ID does not match filename: {path}")
        self._branch_parent_config = parent
        return parent

    def validate_config(self):
        if self.config.get("schema_version", 1) != 1:
            raise ValueError("Unsupported config schema_version")
        if self.stage == "base":
            required = ("training",) if self.is_branch else ("tokenizer", "training")
            for key in required:
                if key not in self.config:
                    raise ValueError(f"base config requires {key}")
            if self.is_branch:
                self._validate_branch_config()
            # A run declares its data either as a single 'dataset' (single-source, the
            # historical shape) or, for a multi-stage mixture, as a 'datasets' map with
            # one block per mixture source. Exactly one form is required.
            if self.mixture_config:
                self._validate_mixture_config()
            elif "dataset" not in self.config:
                raise ValueError("base config requires dataset (or datasets + mixture_schedule)")
            tokenizer = self.tokenizer_spec
            tokenizer_mode = tokenizer.get("mode", "train")
            if tokenizer_mode not in {"train", "reuse"}:
                raise ValueError(
                    f"Unsupported tokenizer.mode {tokenizer_mode!r}; use 'train' or 'reuse'"
                )
            if tokenizer_mode == "reuse":
                source_id = tokenizer.get("source_experiment_id")
                if not source_id or source_id == self.experiment_id:
                    raise ValueError(
                        "tokenizer.mode='reuse' requires a different "
                        "tokenizer.source_experiment_id"
                    )
            muon_momentum = self.config["training"].get("muon_momentum")
            if muon_momentum is not None and (
                isinstance(muon_momentum, bool)
                or not isinstance(muon_momentum, (int, float))
                or not math.isfinite(muon_momentum)
                or not 0 <= muon_momentum < 1
            ):
                raise ValueError("training.muon_momentum must be a number in [0, 1)")
        else:
            step = self.parent.get("checkpoint_step")
            if step is not None and (not isinstance(step, int) or step < 0):
                raise ValueError(
                    f"{self.stage} config requires an exact non-negative "
                    "parent.checkpoint_step"
                )
            if "training" not in self.config:
                raise ValueError(f"{self.stage} config requires training")

    def _primary_dataset(self):
        """A representative dataset block for lineage/summary fields. For a mixture run
        this is the first source's dataset; otherwise the single 'dataset' block."""
        if self.mixture_config and self.mixture_datasets:
            first = self.eval_source or next(iter(self.mixture_source_dirs))
            return self.mixture_datasets.get(first, {})
        return self.config.get("dataset", {})

    def _validate_branch_config(self):
        """Validate a base config's 'branch' block at config-load time.

        A branch inherits the parent's weights, so it also inherits the parent's
        vocabulary and layer shapes. Everything else -- data, horizon, learning
        rates, context length, attention pattern, precision -- is free to change.
        """
        if not self.branch_parent_id:
            raise ValueError("branch requires branch.parent_experiment_id")
        if self.branch_parent_id == self.experiment_id:
            raise ValueError(
                "branch.parent_experiment_id must differ from experiment_id"
            )
        step = self.branch.get("parent_step")
        if step is not None and (
            isinstance(step, bool) or not isinstance(step, int) or step < 0
        ):
            raise ValueError("branch.parent_step must be a non-negative integer")
        if self.branch_lr_schedule not in BRANCH_LR_SCHEDULES:
            raise ValueError(
                f"branch.lr_schedule must be one of {list(BRANCH_LR_SCHEDULES)}, "
                f"got {self.branch_lr_schedule!r}"
            )
        if not isinstance(self.branch.get("load_optimizer", True), bool):
            raise ValueError("branch.load_optimizer must be true or false")
        unknown = set(self.branch) - {
            "parent_experiment_id", "parent_step", "lr_schedule", "load_optimizer",
        }
        if unknown:
            raise ValueError(f"Unknown keys in branch block: {sorted(unknown)}")

        parent_config = self.branch_parent_config()
        if parent_config.get("stage", "base") != "base":
            raise ValueError(
                f"branch parent {self.branch_parent_id!r} is not a base experiment"
            )
        parent_tokenizer = parent_config.get("tokenizer", {})
        tokenizer = self.config.get("tokenizer")
        if tokenizer is not None:
            # Training a new tokenizer would renumber the vocabulary the parent's
            # embedding and lm_head rows were learned against.
            if tokenizer.get("mode", "train") != "reuse":
                raise ValueError(
                    "a branch must reuse its parent's tokenizer: set "
                    "tokenizer.mode='reuse', or omit the tokenizer block to inherit "
                    "the parent's automatically"
                )
            allowed = {self.branch_parent_id}
            if (
                parent_tokenizer.get("mode") == "reuse"
                and parent_tokenizer.get("source_experiment_id")
            ):
                allowed.add(parent_tokenizer["source_experiment_id"])
            source = tokenizer.get("source_experiment_id")
            if source not in allowed:
                raise ValueError(
                    f"branch tokenizer.source_experiment_id {source!r} is not the "
                    f"parent's tokenizer (allowed: {sorted(allowed)}); branched "
                    "weights are tied to the parent vocabulary"
                )
            vocab = tokenizer.get("vocab_size")
            parent_vocab = parent_tokenizer.get("vocab_size")
            if vocab is not None and parent_vocab is not None and vocab != parent_vocab:
                raise ValueError(
                    f"branch vocab_size {vocab} does not match parent vocab_size "
                    f"{parent_vocab}"
                )
        parent_dimensions = _model_dimensions(parent_config)
        dimensions = _model_dimensions(self.config)
        if parent_dimensions != dimensions:
            raise ValueError(
                "branch model shape must match the parent: parent "
                f"(n_layer, model_dim, n_head)={parent_dimensions}, this config "
                f"{dimensions}"
            )

    def _validate_mixture_config(self):
        """Validate the mixture_schedule at config-load time (Step 2 requirement).

        MixtureSchedule.from_config enforces: weights sum to 1.0 per stage, start_tokens
        strictly increasing, first stage starts at 0, no gaps/overlaps. Here we also
        require a per-source dataset block for every source the schedule references.
        """
        from nanochat.mixture import MixtureSchedule

        batch = int(self.config["training"].get("total_batch_size", 524_288))
        # Raises ValueError with a precise message on any schedule violation.
        schedule = MixtureSchedule.from_config(self.mixture_config, total_batch_size=batch)
        datasets = self.config.get("datasets")
        if not isinstance(datasets, dict) or not datasets:
            raise ValueError(
                "mixture_schedule requires a 'datasets' map with one block per source"
            )
        missing = [s for s in schedule.sources if s not in datasets]
        if missing:
            raise ValueError(
                f"mixture sources missing from config 'datasets': {missing}"
            )

    def _validate_remote_config(self):
        remote_config = self.remote_path("config.json")
        if remote_config not in self.remote_files():
            return
        from huggingface_hub import hf_hub_download
        cached = hf_hub_download(
            self.hf_repo,
            remote_config,
            repo_type="model",
            token=os.environ.get("HF_TOKEN"),
        )
        existing = read_json(cached)
        recorded = existing.pop("config_fingerprint", None)
        existing.pop("artifact_path", None)
        fingerprint = recorded or _json_fingerprint(existing)
        if fingerprint != self.config_fingerprint:
            raise RuntimeError(
                f"Experiment ID {self.experiment_id!r} already exists on Hugging "
                "Face with a different config. Use a new experiment ID."
            )

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
            "NANOCHAT_EXPERIMENT_STAGE": self.stage,
            "NANOCHAT_EXPERIMENT_ID": self.experiment_id,
        })
        # Don't let a stale wandb-core service from the parent process bleed into subprocesses
        env.pop("WANDB_SERVICE", None)
        return env

    def remote_files(self, strict=False, path_in_repo=None):
        try:
            entries = self.api.list_repo_tree(
                self.hf_repo,
                path_in_repo=self.hf_prefix if path_in_repo is None else path_in_repo,
                recursive=True,
                repo_type="model",
            )
            return {
                entry.path
                for entry in entries
                if hasattr(entry, "path") and not entry.path.endswith("/")
            }
        except Exception as exc:
            from huggingface_hub.errors import EntryNotFoundError
            if isinstance(exc, EntryNotFoundError):
                return set()
            if strict:
                raise
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

    def download_folder(self, relative_dir, local_dir, strict=False):
        return self.download_folder_from_remote_path(
            self.remote_path(relative_dir), local_dir, strict=strict
        )

    def download_folder_from_remote_path(self, remote_dir, local_dir, strict=False):
        from huggingface_hub import hf_hub_download
        prefix = remote_dir.rstrip("/") + "/"
        selected = [
            path for path in self.remote_files(
                strict=strict, path_in_repo=remote_dir
            )
            if path.startswith(prefix)
        ]
        for repo_path in selected:
            cached = hf_hub_download(
                self.hf_repo, repo_path, repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            relative = repo_path[len(prefix):]
            destination = Path(local_dir) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_cached_file(cached, destination)
        return len(selected)

    def _config_registry_path(self, stage, experiment_id):
        repo_root = Path(__file__).resolve().parents[1]
        folder = {"base": "base", "sft": "sft", "posttrain": "posttrain"}[stage]
        return repo_root / "configs" / folder / f"{experiment_id}.json"

    def load_parent_config(self):
        if self.stage == "base":
            return None
        parent_stage = "base" if self.stage == "sft" else "sft"
        parent_id = self.parent_experiment_id
        path = self._config_registry_path(parent_stage, parent_id)
        if not path.exists():
            raise RuntimeError(
                f"Parent config not found: {path}. Downstream training requires "
                "the immutable parent specification in Git."
            )
        parent = read_json(path)
        if parent.get("experiment_id") != parent_id:
            raise RuntimeError(f"Parent config ID does not match filename: {path}")
        if self.stage == "posttrain":
            parent_base = parent.get("parent", {}).get("base_experiment_id")
            if parent_base != self.base_experiment_id:
                raise RuntimeError(
                    f"SFT parent {parent_id} belongs to base {parent_base}, not "
                    f"{self.base_experiment_id}"
                )
        return parent

    def parent_hf_prefix(self):
        if self.stage == "sft":
            return f"experiments/{self.base_experiment_id}"
        if self.stage == "posttrain":
            return (
                f"experiments/{self.base_experiment_id}/sft/"
                f"{self.sft_experiment_id}"
            )
        raise RuntimeError("Base experiments do not have a parent checkpoint")

    def parent_checkpoint_dir(self):
        if self.stage == "sft":
            return self.base_root / "base_checkpoints"
        if self.stage == "posttrain":
            return self.base_root / "sft" / self.sft_experiment_id / "checkpoints"
        raise RuntimeError("Base experiments do not have a parent checkpoint")

    def resolve_parent_step(self):
        """Return checkpoint_step from parent config, or auto-detect latest from HF."""
        if self.parent.get("checkpoint_step") is not None:
            return int(self.parent["checkpoint_step"])
        parent_prefix = self.parent_hf_prefix()
        checkpoint_folder = "base_checkpoints" if self.stage == "sft" else "checkpoints"
        prefix = f"{parent_prefix}/{checkpoint_folder}/"
        files = self.remote_files(strict=True, path_in_repo=parent_prefix)
        complete = _complete_steps(files, prefix)
        if not complete:
            raise RuntimeError(f"No complete checkpoints found for parent {parent_prefix} on HF")
        latest = complete[-1]
        print(f"Auto-detected latest parent checkpoint: step {latest}", flush=True)
        return latest

    def resolve_branch_step(self):
        """The exact parent step this run branches from.

        Config value first, then the step already recorded in run.json, then the
        latest complete parent checkpoint on Hugging Face. Auto-detected steps are
        persisted so a resumed run keeps branching from the same weights even if
        the parent trains further.
        """
        if self.branch.get("parent_step") is not None:
            return int(self.branch["parent_step"])
        if self.run_path.exists():
            recorded = read_json(self.run_path).get("branch_parent_step")
            if recorded is not None:
                self.branch["parent_step"] = int(recorded)
                return int(recorded)
        prefix = f"{self.branch_parent_hf_prefix}/base_checkpoints/"
        files = self.remote_files(strict=True, path_in_repo=self.branch_parent_hf_prefix)
        complete = _complete_steps(files, prefix, self.expected_optimizer_ranks)
        if not complete:
            raise RuntimeError(
                f"No complete checkpoint found for branch parent "
                f"{self.branch_parent_id!r} on Hugging Face "
                f"(need model, meta, and optimizer ranks "
                f"{sorted(self.expected_optimizer_ranks)})"
            )
        latest = complete[-1]
        print(
            f"Auto-detected latest branch parent checkpoint: step {latest}",
            flush=True,
        )
        self.branch["parent_step"] = latest
        self._record_branch_step(latest)
        return latest

    def _record_branch_step(self, step):
        """Pin the resolved branch point in run.json so it survives a fresh runtime."""
        if not self.run_path.exists():
            return
        run_info = read_json(self.run_path)
        if run_info.get("branch_parent_step") == step:
            return
        run_info["branch_parent_step"] = step
        run_info["parent_experiment_id"] = self.branch_parent_id
        run_info["parent_checkpoint_step"] = step
        atomic_json(self.run_path, run_info)
        try:
            self.upload_file(
                self.run_path,
                "run.json",
                f"Pin branch point for {self.experiment_id}",
            )
        except Exception as exc:
            print(
                f"Could not upload the pinned branch point; training continues: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    def prepare_branch_parent(self):
        """Download the parent checkpoint this run branches from. Idempotent."""
        self.branch_parent_config()
        step = self.resolve_branch_step()
        checkpoint_dir = self.branch_parent_checkpoint_dir
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"{step:06d}"
        required = {f"model_{suffix}.pt", f"meta_{suffix}.json"}
        if self.branch_load_optimizer:
            required |= {
                f"optim_{suffix}_rank{rank}.pt"
                for rank in sorted(self.expected_optimizer_ranks)
            }
        if all((checkpoint_dir / name).exists() for name in required):
            print(
                f"Branch parent {self.branch_parent_id} step {step} already local; "
                "skipping download.",
                flush=True,
            )
            self._validate_branch_parent_checkpoint(step)
            return step
        prefix = f"{self.branch_parent_hf_prefix}/base_checkpoints/"
        available = {
            os.path.basename(path)
            for path in self.remote_files(
                strict=True, path_in_repo=self.branch_parent_hf_prefix
            )
            if path.startswith(prefix)
        }
        missing = sorted(required - available)
        if missing:
            raise RuntimeError(
                f"Branch parent {self.branch_parent_id!r} step {step} is missing "
                f"{missing} on Hugging Face. Optimizer state is sharded per rank, so "
                f"branching with --nproc-per-node={self.nproc_per_node} needs ranks "
                f"{sorted(self.expected_optimizer_ranks)}; set "
                '"load_optimizer": false to branch from weights alone.'
            )
        from huggingface_hub import hf_hub_download
        for name in sorted(required):
            cached = hf_hub_download(
                self.hf_repo,
                prefix + name,
                repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            _copy_cached_file(cached, checkpoint_dir / name)
        print(
            f"Prepared branch parent {self.branch_parent_id} checkpoint step {step}",
            flush=True,
        )
        self._validate_branch_parent_checkpoint(step)
        return step

    def _validate_branch_parent_checkpoint(self, step):
        """Check the parent checkpoint's architecture before any GPU work starts."""
        meta_path = self.branch_parent_checkpoint_dir / f"meta_{step:06d}.json"
        parent_model = read_json(meta_path).get("model_config", {})
        depth, model_dim, num_heads = _model_dimensions(self.config)
        expected = {"n_layer": depth, "n_embd": model_dim, "n_head": num_heads}
        mismatched = {
            key: (parent_model.get(key), value)
            for key, value in expected.items()
            if parent_model.get(key) is not None and parent_model[key] != value
        }
        if mismatched:
            raise RuntimeError(
                f"Branch parent {self.branch_parent_id!r} step {step} has a different "
                f"architecture than this config: "
                + ", ".join(
                    f"{key}: parent {parent}, this run {mine}"
                    for key, (parent, mine) in sorted(mismatched.items())
                )
            )
        parent_vocab = parent_model.get("vocab_size")
        vocab = self.tokenizer_spec.get("vocab_size")
        if parent_vocab is not None and vocab is not None and parent_vocab != vocab:
            raise RuntimeError(
                f"Branch parent vocab_size {parent_vocab:,} does not match this "
                f"config's tokenizer vocab_size {int(vocab):,}"
            )

    def _parent_checkpoint_complete_locally(self, step):
        checkpoint_dir = self.parent_checkpoint_dir()
        model_file = checkpoint_dir / f"model_{step:06d}.pt"
        meta_file = checkpoint_dir / f"meta_{step:06d}.json"
        tokenizer_file = self.tokenizer_dir / "tokenizer.pkl"
        token_bytes_file = self.tokenizer_dir / "token_bytes.pt"
        return (
            model_file.exists()
            and meta_file.exists()
            and tokenizer_file.exists()
            and token_bytes_file.exists()
        )

    def prepare_parent(self):
        self.load_parent_config()
        step = self.resolve_parent_step()
        if self._parent_checkpoint_complete_locally(step):
            print(
                f"Parent {self.parent_experiment_id} step {step} already local; skipping download.",
                flush=True,
            )
            return
        checkpoint_dir = self.parent_checkpoint_dir()
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        remote_checkpoint_folder = (
            "base_checkpoints" if self.stage == "sft" else "checkpoints"
        )
        prefix = (
            f"{self.parent_hf_prefix()}/{remote_checkpoint_folder}/"
        )
        suffix = f"{step:06d}"
        selected = [
            path for path in self.remote_files(strict=True, path_in_repo=self.parent_hf_prefix())
            if path.startswith(prefix)
            and (
                path.endswith(f"model_{suffix}.pt")
                or path.endswith(f"meta_{suffix}.json")
                or f"optim_{suffix}_rank" in path
            )
        ]
        names = {Path(path).name for path in selected}
        if (
            f"model_{suffix}.pt" not in names
            or f"meta_{suffix}.json" not in names
            or not any(name.startswith(f"optim_{suffix}_rank") for name in names)
        ):
            raise RuntimeError(
                f"Parent checkpoint {self.parent_experiment_id} step {step} is "
                "not complete on Hugging Face"
            )
        from huggingface_hub import hf_hub_download
        for repo_path in selected:
            cached = hf_hub_download(
                self.hf_repo,
                repo_path,
                repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            _copy_cached_file(cached, checkpoint_dir / Path(repo_path).name)

        tokenizer_prefix = f"experiments/{self.base_experiment_id}/tokenizer/"
        tokenizer_files = [
            path for path in self.remote_files(
                strict=True,
                path_in_repo=f"experiments/{self.base_experiment_id}",
            )
            if path.startswith(tokenizer_prefix)
        ]
        if not tokenizer_files:
            raise RuntimeError(
                f"Tokenizer missing for base experiment {self.base_experiment_id}"
            )
        for repo_path in tokenizer_files:
            cached = hf_hub_download(
                self.hf_repo,
                repo_path,
                repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            destination = self.tokenizer_dir / repo_path[len(tokenizer_prefix):]
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_cached_file(cached, destination)
        print(
            f"Prepared parent {self.parent_experiment_id} checkpoint step {step}",
            flush=True,
        )

    @property
    def mixture_start_tokens(self):
        """Token offset where this run begins consuming its lineage schedule."""
        if not self.mixture_config:
            return 0
        if not (self.is_branch and self.branch_lr_schedule == "continue"):
            return 0
        step = self.branch.get("parent_step")
        if step is None:
            # Auto-selected branch points are resolved during preparation. Until then,
            # retain the historical full-schedule behavior rather than guessing.
            return 0
        batch = int(self.config["training"].get("total_batch_size", 524_288))
        return int(step) * batch

    @property
    def active_mixture_sources(self):
        """Ordered sources this run can still draw after its continuation offset."""
        if not self.mixture_config:
            return []
        from nanochat.mixture import MixtureSchedule
        batch = int(self.config["training"].get("total_batch_size", 524_288))
        schedule = MixtureSchedule.from_config(
            self.mixture_config, total_batch_size=batch
        )
        return schedule.active_sources(self.mixture_start_tokens)

    @property
    def active_mixture_source_dirs(self):
        return {
            name: self.mixture_source_dirs[name]
            for name in self.active_mixture_sources
        }

    @property
    def eval_source(self):
        """Name of the mixture source that backs the headline val BPB, or None for a
        single-source run. A continuation validates against the source active at its
        branch point, so sources wholly in the inherited past need no local cache."""
        if not self.mixture_source_dirs:
            return None
        active = self.active_mixture_sources
        return active[0] if active else None

    @property
    def eval_pretok_dir(self):
        """Token cache whose val split the final BPB eval reads."""
        source = self.eval_source
        return self.pretok_dir if source is None else self.mixture_source_dirs[source]

    @property
    def eval_data_dir(self):
        """Parquet directory feeding eval_pretok_dir."""
        source = self.eval_source
        return self.data_dir if source is None else self.mixture_data_dirs[source]

    @property
    def eval_dataset_config(self):
        """Dataset block feeding eval_pretok_dir. Mixture configs carry one block per
        source under 'datasets' and have no top-level 'dataset'."""
        source = self.eval_source
        if source is None:
            return self.config.get("dataset", {})
        return self.mixture_datasets.get(source, {})

    def _has_pretok_val(self):
        meta_path = self.eval_pretok_dir / "meta.json"
        if not meta_path.exists():
            return False
        meta = read_json(meta_path)
        return bool(meta.get("val_files"))

    def prepare_eval(self):
        """Download only what's needed to run eval: tokenizer + val parquet shard."""
        if self.stage != "base":
            return
        # Tokenizer
        if not (self.tokenizer_dir / "tokenizer.pkl").exists():
            self.download_folder("tokenizer", self.tokenizer_dir, strict=True)
            print("Downloaded tokenizer.", flush=True)
        # Val parquet shard (only if pretok val isn't already present)
        if self._has_pretok_val():
            return
        data_dir = self.eval_data_dir
        val_parquet = sorted(data_dir.glob("shard_*.parquet"))
        if not val_parquet:
            dataset = self.eval_dataset_config
            repo = dataset.get("repo")
            revision = dataset.get("revision", "main")
            val_shard = dataset.get("validation_shard")
            if not repo or val_shard is None:
                print("No dataset config; cannot download val shard.", flush=True)
                return
            base_url = dataset.get("base_url") or f"https://huggingface.co/datasets/{repo}/resolve/{revision}"
            # Mixture sources can live in a subfolder of their repo (e.g. mixed/ratio_30/data)
            subfolder = dataset.get("subfolder")
            if subfolder:
                base_url = f"{base_url.rstrip('/')}/{subfolder.strip('/')}"
            cmd = [
                sys.executable, "-u", "-m", "nanochat.dataset",
                "-n", "0",
                "--base-url", base_url,
                "--data-dir", str(data_dir),
                "--max-shard", str(val_shard),
            ]
            data_dir.mkdir(parents=True, exist_ok=True)
            run_streaming(cmd, self.environment())
            print("Downloaded val shard.", flush=True)
        # Rebuild the pretokenized val cache so cold-runtime evals measure BPB on
        # the exact same token stream as evals run right after training. Without
        # this, eval silently falls back to the on-the-fly bestfit-packing loader,
        # which packs the val text differently and shifts the bpb scale.
        pretok = self.config.get("pretokenize", {})
        if pretok.get("enabled", True):
            cmd = [
                sys.executable, "-u", "-m", "scripts.pretok_think",
                "--data-dir", str(data_dir),
                "--tokenizer-dir", str(self.tokenizer_dir),
                "--output-dir", str(self.eval_pretok_dir),
                "--val-only",
                "--val-tokens", str(int(pretok.get("val_tokens", 20_971_520))),
                "--shard-tokens", str(int(pretok.get("shard_tokens", 100_000_000))),
                "--tokenizer-threads", str(int(pretok.get("tokenizer_threads", 8))),
            ]
            run_streaming(cmd, self.environment())
            print("Rebuilt pretokenized val cache.", flush=True)

    def prepare_dataset(self):
        if self.stage != "base":
            self.prepare_parent()
            return
        if self.mixture_config:
            # Multi-source mixture: build each source's parquet shards independently.
            satisfied = self._satisfied_mixture_sources()
            for name in self.active_mixture_sources:
                if name not in self.mixture_datasets:
                    raise ValueError(
                        f"mixture source {name!r} has no entry in config 'datasets'; "
                        f"each mixture source needs its own dataset block"
                    )
                if name in satisfied:
                    # Parquet shards are only ever an input to pretokenization, and
                    # pretok_think will reuse this cache untouched. Downloading tens of
                    # GB to feed a step that will not run is pure waste -- this is the
                    # common case for a hosted cache shared with an earlier run.
                    print(
                        f"Mixture source {name!r}: pretokenized cache already satisfies "
                        f"its planned draw; skipping the parquet download."
                    )
                    continue
                print(f"Preparing dataset for mixture source {name!r}...")
                self._prepare_dataset_into(
                    self.mixture_datasets[name], self.mixture_data_dirs[name]
                )
            return
        self._prepare_dataset_into(self.config["dataset"], self.data_dir)

    def _satisfied_mixture_sources(self):
        """Mixture sources whose pretokenized cache already covers their planned draw.

        Uses exactly the predicate pretok_think uses to decide it can reuse a cache, so
        this never skips a download the pretokenization step would then need.
        """
        pretok = self.config.get("pretokenize", {})
        if not self.mixture_config or not pretok.get("enabled", True):
            return set()
        from nanochat.mixture import MixtureSchedule
        try:
            from scripts.pretok_think import (
                _existing_cache_satisfies,
                _tokenizer_fingerprint,
            )
        except ImportError as exc:
            # Only an optimization. Without the tokenizer stack we cannot validate a
            # cache, so fall back to downloading everything exactly as before.
            print(f"Cannot check for reusable pretokenized caches ({exc}); "
                  f"preparing every mixture source's dataset.")
            return set()

        fingerprint = _tokenizer_fingerprint(str(self.tokenizer_dir))
        if not fingerprint:
            return set()  # no tokenizer yet, so no cache can be validated against it
        batch = int(self.config["training"].get("total_batch_size", 524_288))
        planned = MixtureSchedule.from_config(
            self.mixture_config, total_batch_size=batch
        ).planned_tokens_per_source(start_tokens=self.mixture_start_tokens)
        slack = float(pretok.get("slack", 1.03))
        # Mixture caches feed the periodic in-training evaluations. The canonical
        # full validation is prepared separately by prepare_eval(), and some
        # midtrain validation shards contain fewer than 20.97M tokens.
        val_tokens = int(self.config["training"].get("eval_tokens", 2_097_152))
        return {
            name
            for name, output_dir in self.active_mixture_source_dirs.items()
            if _existing_cache_satisfies(
                str(output_dir),
                math.ceil(planned.get(name, 0) * slack),
                val_tokens,
                fingerprint,
            )
        }

    def _prepare_dataset_into(self, dataset, data_dir):
        adapter = dataset.get("adapter", "parquet_shards")
        if adapter == "parquet_shards":
            base_url = dataset.get("base_url")
            if not base_url:
                repo = dataset["repo"]
                revision = dataset.get("revision", "main")
                base_url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}"
            # Optional subfolder within the repo, e.g. "mixed/ratio_30/data" for the
            # pre-mixed midtrain datasets that live under mixed/ratio_N/data/.
            subfolder = dataset.get("subfolder")
            if subfolder:
                base_url = f"{base_url.rstrip('/')}/{subfolder.strip('/')}"
            cmd = [
                sys.executable, "-u", "-m", "nanochat.dataset",
                "-n", str(dataset["num_train_shards"]),
                "-w", str(dataset.get("download_workers", 4)),
                "--base-url", base_url,
                "--data-dir", str(data_dir),
                "--max-shard", str(dataset["validation_shard"]),
                "--min-shard", str(dataset.get("min_train_shard", 0)),
            ]
            run_streaming(cmd, self.environment())
        elif adapter == "hf_stream":
            self._prepare_streamed_dataset(dataset, data_dir)
        else:
            raise ValueError(f"Unknown dataset adapter: {adapter}")
        files = sorted(Path(data_dir).glob("shard_*.parquet"))
        if len(files) < 2:
            raise RuntimeError("Dataset preparation did not produce train and validation shards")
        print(f"Prepared {len(files) - 1} train shards and validation {files[-1].name}")

    def _prepare_streamed_dataset(self, dataset, data_dir=None):
        if data_dir is None:
            data_dir = self.data_dir
        from datasets import load_dataset
        import pyarrow as pa
        import pyarrow.parquet as pq

        if list(Path(data_dir).glob("shard_*.parquet")):
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
                _write_text_parquet(Path(data_dir) / f"shard_{shard_index:05d}.parquet", rows, pa, pq)
                shard_index += 1
                rows, chars = [], 0
            if max_train_rows > 0 and seen >= max_train_rows:
                break
        if rows:
            _write_text_parquet(Path(data_dir) / f"shard_{shard_index:05d}.parquet", rows, pa, pq)
            shard_index += 1
        if not val_rows:
            raise RuntimeError("Validation split produced no text rows")
        _write_text_parquet(Path(data_dir) / "shard_99999.parquet", val_rows, pa, pq)

    def prepare_tokenizer(self):
        if self.stage != "base":
            return
        tokenizer = self.tokenizer_spec
        marker = {
            "experiment_id": self.experiment_id,
            "dataset": self.config.get("dataset", self.config.get("datasets", {})),
            "tokenizer": tokenizer,
            "created_at": int(time.time()),
        }

        def finalize_tokenizer():
            atomic_json(self.tokenizer_dir / "experiment_tokenizer.json", marker)
            self.upload_folder(
                self.tokenizer_dir,
                "tokenizer",
                f"Upload tokenizer for {self.experiment_id}",
            )

        downloaded = self.download_folder(
            "tokenizer", self.tokenizer_dir, strict=True
        )
        if downloaded and (self.tokenizer_dir / "tokenizer.pkl").exists():
            print("Downloaded experiment tokenizer from Hugging Face")
            return
        local_files = (
            self.tokenizer_dir / "tokenizer.pkl",
            self.tokenizer_dir / "token_bytes.pt",
        )
        if all(path.exists() and path.stat().st_size > 0 for path in local_files):
            print("Recovering completed local tokenizer from interrupted preparation")
            finalize_tokenizer()
            return
        if tokenizer.get("mode", "train") == "reuse":
            source_id = tokenizer["source_experiment_id"]
            source_dir = f"experiments/{source_id}/tokenizer"
            downloaded = self.download_folder_from_remote_path(
                source_dir, self.tokenizer_dir, strict=True
            )
            if not downloaded or not all(
                path.exists() and path.stat().st_size > 0 for path in local_files
            ):
                raise RuntimeError(
                    f"Configured tokenizer source {source_id!r} was not found in "
                    f"{self.hf_repo}"
                )
            # Do not rewrite experiment_tokenizer.json: it participates in the
            # tokenizer fingerprint recorded by the hosted pretok cache.
            self.upload_folder(
                self.tokenizer_dir,
                "tokenizer",
                f"Reuse tokenizer from {source_id} for {self.experiment_id}",
            )
            print(f"Reused tokenizer from experiment {source_id}")
            return
        cmd = [
            sys.executable, "-u", "-m", "scripts.tok_train",
            "--data-dir", str(self.data_dir),
            "--tokenizer-dir", str(self.tokenizer_dir),
            "--max-chars", str(tokenizer.get("max_chars", 2_000_000_000)),
            "--doc-cap", str(tokenizer.get("doc_cap", 10_000)),
            "--vocab-size", str(tokenizer.get("vocab_size", 32768)),
            "--sampling", str(tokenizer.get("sampling", "head")),
            "--sampling-seed", str(tokenizer.get("sampling_seed", 42)),
        ]
        run_streaming(cmd, self.environment())
        finalize_tokenizer()

    def prepare_pretokenized(self):
        if self.stage != "base":
            return
        pretok = self.config.get("pretokenize", {})
        if not pretok.get("enabled", True):
            return
        if self.mixture_config:
            self._prepare_pretokenized_mixture(pretok)
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
        meta = read_json(self.pretok_dir / "meta.json")
        unique_tokens = int(meta["train_tokens"])
        training = self.config["training"]
        batch = int(training.get("total_batch_size", 524_288))
        if training.get("target_tokens") is not None:
            horizon = (int(training["target_tokens"]) // batch) * batch
        elif training.get("target_param_data_ratio") is not None:
            horizon = math.floor(
                float(training["target_param_data_ratio"])
                * int(training["scaling_params"])
                / batch
            ) * batch
        else:
            horizon = None
        print(f"Unique pretokenized train tokens: {unique_tokens:,}")
        if horizon is not None:
            print(f"Planned training horizon:         {horizon:,}")
            print(f"Effective passes over cache:      {horizon / unique_tokens:.2f}")
        if pretok.get("require_no_wrap", False):
            if meta.get("train_source_exhausted", False):
                raise RuntimeError(
                    "Pretokenized source shards were exhausted before the requested "
                    "cache target. Increase dataset.num_train_shards."
                )
            if horizon is None:
                raise RuntimeError(
                    "pretokenize.require_no_wrap requires a token- or ratio-based "
                    "training horizon"
                )
            if unique_tokens < horizon:
                raise RuntimeError(
                    f"Training would wrap the token cache: horizon={horizon:,}, "
                    f"cache={unique_tokens:,}. Increase the pretokenization target."
                )
            print("No-wrap validation passed.")

        self.validate_pretokenized_cache(meta)

    def _prepare_pretokenized_mixture(self, pretok):
        """Build one pretokenized cache per mixture source, each sized to that source's
        planned token draw (times slack), then hard-enforce the epoch cap."""
        from nanochat.mixture import MixtureSchedule

        training = self.config["training"]
        batch = int(training.get("total_batch_size", 524_288))
        schedule = MixtureSchedule.from_config(self.mixture_config, total_batch_size=batch)
        start_tokens = self.mixture_start_tokens
        planned = schedule.planned_tokens_per_source(start_tokens=start_tokens)
        slack = float(pretok.get("slack", 1.03))
        val_tokens = int(training.get("eval_tokens", 2_097_152))
        source_unique = {}
        for name in self.active_mixture_sources:
            dataset = self.mixture_datasets[name]
            data_dir = self.mixture_data_dirs[name]
            output_dir = self.mixture_source_dirs[name]
            # Size each cache to the tokens this source will draw, plus slack.
            target_tokens = math.ceil(planned[name] * slack)
            cmd = [
                sys.executable, "-u", "-m", "scripts.pretok_think",
                "--data-dir", str(data_dir),
                "--tokenizer-dir", str(self.tokenizer_dir),
                "--output-dir", str(output_dir),
                "--source-dataset-repo", (
                    f"{dataset['repo']}/{dataset['subfolder'].strip('/')}"
                    if dataset.get("subfolder") else dataset["repo"]
                ),
                "--source-revision", dataset.get("revision", "main"),
                "--target-tokens", str(int(target_tokens)),
                "--val-tokens", str(val_tokens),
                "--shard-tokens", str(int(pretok.get("shard_tokens", 100_000_000))),
                "--tokenizer-threads", str(int(pretok.get("tokenizer_threads", 8))),
            ]
            print(f"Pretokenizing mixture source {name!r}: target {target_tokens:,} tokens")
            run_streaming(cmd, self.environment())
            meta = read_json(output_dir / "meta.json")
            unique = int(meta["train_tokens"])
            source_unique[name] = unique
            print(f"  {name}: {unique:,} unique tokens ({planned[name]:,} planned draw)")
            if pretok.get("require_no_wrap", False) and meta.get("train_source_exhausted", False):
                raise RuntimeError(
                    f"Mixture source {name!r} exhausted its shards before the target "
                    f"({unique:,} < {target_tokens:,}). Increase that source's "
                    f"num_train_shards or shorten the stage(s) that use it."
                )
        # Hard epoch-cap enforcement against the real per-source cache sizes.
        schedule.check_epoch_cap(source_unique, start_tokens=start_tokens)
        realized = schedule.realized_epochs(planned, source_unique)
        print("Mixture pretokenization complete. Realized epochs per source:")
        for name in self.active_mixture_sources:
            print(f"  {name}: {realized[name]:.3f} epochs "
                  f"({planned[name]:,} / {source_unique[name]:,})")
        print(f"Epoch cap ({schedule.max_epochs}) satisfied for all sources.")

    def validate_pretokenized_cache(self, meta=None):
        """Validate hosted/local uint16 cache metadata without rereading token data."""
        if meta is None:
            meta_path = self.pretok_dir / "meta.json"
            if not meta_path.exists():
                raise RuntimeError(f"Pretokenized cache metadata missing: {meta_path}")
            meta = read_json(meta_path)

        dataset = self.config["dataset"]
        expected_source = dataset.get("repo")
        expected_revision = dataset.get("revision", "main")
        if meta.get("source_dataset_repo") != expected_source:
            raise RuntimeError(
                "Pretokenized cache source mismatch: "
                f"expected {expected_source!r}, got {meta.get('source_dataset_repo')!r}"
            )
        if meta.get("source_revision") != expected_revision:
            raise RuntimeError(
                "Pretokenized cache revision mismatch: "
                f"expected {expected_revision!r}, got {meta.get('source_revision')!r}"
            )
        if meta.get("dtype") != "uint16":
            raise RuntimeError(
                f"Pretokenized cache dtype must be uint16, got {meta.get('dtype')!r}"
            )

        expected_vocab = int(self.tokenizer_spec.get("vocab_size", 32768))
        actual_vocab = meta.get("vocab_size")
        if not isinstance(actual_vocab, int) or actual_vocab != expected_vocab:
            raise RuntimeError(
                "Pretokenized cache vocab mismatch: "
                f"expected {expected_vocab:,}, got {meta.get('vocab_size')!r}"
            )

        from scripts.pretok_think import _tokenizer_fingerprint

        tokenizer_fingerprint = _tokenizer_fingerprint(self.tokenizer_dir)
        if meta.get("tokenizer_fingerprint") != tokenizer_fingerprint:
            raise RuntimeError(
                "Pretokenized cache tokenizer fingerprint does not match the "
                "downloaded experiment tokenizer"
            )

        seen = set()
        for split in ("train", "val"):
            entries = meta.get(f"{split}_files")
            if not isinstance(entries, list) or not entries:
                raise RuntimeError(f"Pretokenized cache has no {split} files")
            total = 0
            for entry in entries:
                filename = entry.get("filename") if isinstance(entry, dict) else None
                num_tokens = entry.get("num_tokens") if isinstance(entry, dict) else None
                if not filename or Path(filename).name != filename or filename in seen:
                    raise RuntimeError(
                        f"Invalid or duplicate pretokenized filename: {filename!r}"
                    )
                if not isinstance(num_tokens, int) or num_tokens <= 0:
                    raise RuntimeError(
                        f"Invalid token count for pretokenized file {filename!r}: "
                        f"{num_tokens!r}"
                    )
                seen.add(filename)
                path = self.pretok_dir / filename
                expected_bytes = num_tokens * 2
                if not path.exists() or path.stat().st_size != expected_bytes:
                    actual = path.stat().st_size if path.exists() else None
                    raise RuntimeError(
                        f"Pretokenized file {filename!r} has {actual!r} bytes; "
                        f"expected {expected_bytes:,}"
                    )
                total += num_tokens
            recorded_total = meta.get(f"{split}_tokens")
            if not isinstance(recorded_total, int) or total != recorded_total:
                raise RuntimeError(
                    f"Pretokenized {split} token total mismatch: files contain "
                    f"{total:,}, metadata records {meta.get(f'{split}_tokens')!r}"
                )

        print(
            "Validated pretokenized cache: "
            f"{len(meta['train_files'])} train files, "
            f"{len(meta['val_files'])} val files.",
            flush=True,
        )
        return meta

    @property
    def expected_optimizer_ranks(self):
        return set(range(self.nproc_per_node))

    def complete_local_steps(self):
        return _complete_steps(
            [path.name for path in self.checkpoint_dir.glob("*")],
            "",
            self.expected_optimizer_ranks,
        )

    def complete_remote_steps(self, strict=False):
        return _complete_steps(
            self.remote_files(strict=strict),
            self.remote_path(self.checkpoint_relative) + "/",
            self.expected_optimizer_ranks,
        )

    def checkpoint_files(self, step):
        suffix = f"{step:06d}"
        files = [
            self.checkpoint_dir / f"model_{suffix}.pt",
            self.checkpoint_dir / f"meta_{suffix}.json",
        ]
        files.extend(
            self.checkpoint_dir / f"optim_{suffix}_rank{rank}.pt"
            for rank in sorted(self.expected_optimizer_ranks)
        )
        return files

    def validate_resume_checkpoint(self, step):
        suffix = f"{step:06d}"
        required = {
            self.checkpoint_dir / f"model_{suffix}.pt",
            self.checkpoint_dir / f"meta_{suffix}.json",
        }
        missing = sorted(str(path.name) for path in required if not path.exists())
        actual_ranks = {
            int(match.group(2))
            for path in self.checkpoint_dir.glob(f"optim_{suffix}_rank*.pt")
            if (match := OPTIM_RANK_RE.match(path.name))
        }
        if missing or actual_ranks != self.expected_optimizer_ranks:
            details = []
            if missing:
                details.append(f"missing files={missing}")
            if actual_ranks != self.expected_optimizer_ranks:
                details.append(
                    f"optimizer ranks expected={sorted(self.expected_optimizer_ranks)} "
                    f"found={sorted(actual_ranks)}"
                )
            raise RuntimeError(
                f"Checkpoint step {step} is incompatible with "
                f"nproc_per_node={self.nproc_per_node}: " + "; ".join(details)
            )

    def download_step(self, step, include_optimizer=True):
        from huggingface_hub import hf_hub_download
        prefix = self.remote_path(self.checkpoint_relative) + "/"
        suffix = f"{step:06d}"
        for repo_path in self.remote_files():
            name = os.path.basename(repo_path)
            if not repo_path.startswith(prefix):
                continue
            if not (
                name == f"model_{suffix}.pt"
                or name == f"meta_{suffix}.json"
                or (
                    include_optimizer
                    and name.startswith(f"optim_{suffix}_rank")
                )
            ):
                continue
            cached = hf_hub_download(
                self.hf_repo, repo_path, repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            _copy_cached_file(cached, self.checkpoint_dir / name)

    def restore_run_info_from_checkpoint(self, step):
        meta_path = self.checkpoint_dir / f"meta_{step:06d}.json"
        if not meta_path.exists():
            return
        meta = read_json(meta_path)
        checkpoint_run_id = meta.get("user_config", {}).get("wandb_run_id")
        if not checkpoint_run_id:
            return
        current = read_json(self.run_path) if self.run_path.exists() else {}
        if current.get("wandb_run_id") == checkpoint_run_id:
            return
        restored = {
            "experiment_id": self.experiment_id,
            "wandb_run_id": checkpoint_run_id,
            "created_at": current.get("created_at", int(time.time())),
            "recovered_from_checkpoint_step": step,
        }
        # The branch point is part of this run's identity; never drop it here.
        for key in ("branch_parent_step", "parent_experiment_id", "parent_checkpoint_step"):
            if current.get(key) is not None:
                restored[key] = current[key]
        atomic_json(self.run_path, restored)
        self.upload_file(
            self.run_path,
            "run.json",
            f"Restore W&B run id from checkpoint step {step}",
        )
        print(
            f"Restored W&B run id {checkpoint_run_id} from checkpoint step {step}",
            flush=True,
        )

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
                path, f"{self.checkpoint_relative}/{path.name}",
                f"Upload {self.experiment_id} step {step}",
            )
        uploaded.add(step)
        print(f"Uploaded checkpoint step {step}", flush=True)
        self.prune_uploaded_checkpoints(uploaded)

    def prune_uploaded_checkpoints(self, uploaded):
        """Bound local checkpoint storage after complete remote uploads."""
        keep = int(self.config.get("artifacts", {}).get("keep_local_checkpoints", -1))
        if keep < 0:
            return
        keep_steps = set(sorted(uploaded)[-keep:]) if keep else set()
        for local_step in self.complete_local_steps():
            if local_step not in uploaded or local_step in keep_steps:
                continue
            for path in self.checkpoint_files(local_step):
                path.unlink(missing_ok=True)
            print(
                f"Removed uploaded local checkpoint step {local_step}",
                flush=True,
            )

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

    def train(self, fresh=False, confirm_fresh=False):
        if self.stage == "base":
            return self._train_base(fresh=fresh, confirm_fresh=confirm_fresh)
        return self._train_downstream(fresh=fresh, confirm_fresh=confirm_fresh)

    def _base_train_command(self, run_info, resume=None):
        training = self.config["training"]
        cmd = [
            sys.executable, "-u", "-m", "scripts.base_train",
            f"--depth={training.get('depth', 12)}",
            f"--seed={training.get('seed', 42)}",
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
            f"--tokenizer-fingerprint={_directory_fingerprint(self.tokenizer_dir)}",
            f"--git-commit-sha={_git_commit_sha() or ''}",
            *(resume or []),
        ]
        optional_args = {
            "device_type": "device-type",
            "aspect_ratio": "aspect-ratio",
            "head_dim": "head-dim",
            "max_seq_len": "max-seq-len",
            "embedding_lr": "embedding-lr",
            "unembedding_lr": "unembedding-lr",
            "weight_decay": "weight-decay",
            "matrix_lr": "matrix-lr",
            "muon_momentum": "muon-momentum",
            "scalar_lr": "scalar-lr",
            "warmup_steps": "warmup-steps",
            "warmdown_ratio": "warmdown-ratio",
            "final_lr_frac": "final-lr-frac",
            "core_metric_max_per_task": "core-metric-max-per-task",
        }
        for config_key, cli_name in optional_args.items():
            if config_key in training:
                cmd.append(f"--{cli_name}={training[config_key]}")

        if training.get("fp8", False):
            cmd.append("--fp8")
            cmd.append(f"--fp8-recipe={training.get('fp8_recipe', 'tensorwise')}")

        num_iterations = self._explicit_iterations()
        if num_iterations is not None:
            cmd.extend([
                f"--num-iterations={num_iterations}",
                "--target-param-data-ratio=-1",
            ])
        elif training.get("target_flops") is not None:
            cmd.extend([
                f"--target-flops={training['target_flops']}",
                "--target-param-data-ratio=-1",
            ])
        else:
            cmd.append(
                f"--target-param-data-ratio="
                f"{training.get('target_param_data_ratio', -1)}"
            )
        if self.is_branch:
            # Passed on every launch, including a resume of this run's own
            # checkpoints: base_train needs the branch point to keep the step
            # numbering, learning-rate schedule, and FLOPs accounting consistent.
            step = self.branch.get("parent_step")
            if step is None:
                raise RuntimeError(
                    "Branch point is unresolved; run prepare before train"
                )
            cmd.extend([
                f"--init-from-checkpoint-dir={self.branch_parent_checkpoint_dir}",
                f"--init-from-step={int(step)}",
                f"--branch-lr-schedule={self.branch_lr_schedule}",
                f"--branch-parent-experiment-id={self.branch_parent_id}",
            ])
            if not self.branch_load_optimizer:
                cmd.append("--no-init-optimizer")
        if self.config.get("pretokenize", {}).get("enabled", True):
            cmd.extend(["--pretokenized", f"--pretokenized-dir={self.pretok_dir}"])
        if self.active_mixture_source_dirs:
            source_dirs_json = json.dumps(
                {name: str(path) for name, path in self.active_mixture_source_dirs.items()}
            )
            cmd.append(f"--mixture-source-dirs={source_dirs_json}")
        if self.nproc_per_node > 1:
            cmd = [
                sys.executable, "-u", "-m", "torch.distributed.run",
                "--standalone",
                f"--nproc-per-node={self.nproc_per_node}",
                "-m", "scripts.base_train", "--",
                *cmd[4:],
            ]
        return cmd

    def _checkpoint_meta(self, step):
        meta_path = self.checkpoint_dir / f"meta_{step:06d}.json"
        if meta_path.exists():
            return read_json(meta_path)
        return {}

    def _is_training_complete(self):
        """Return (complete, step) if the latest local checkpoint is marked training_complete."""
        local_steps = self.complete_local_steps()
        if not local_steps:
            return False, None
        step = local_steps[-1]
        meta = self._checkpoint_meta(step)
        return bool(meta.get("training_complete", False)), step

    def _train_base(self, fresh=False, confirm_fresh=False):
        if fresh:
            remote_steps = self.complete_remote_steps(strict=True)
            if remote_steps and not confirm_fresh:
                raise RuntimeError(
                    f"Refusing --fresh because Hugging Face already contains complete "
                    f"checkpoint steps for {self.experiment_id}: {remote_steps}. "
                    "Resume without --fresh, or pass --confirm-fresh to intentionally "
                    "start over and replace this experiment's training state."
                )
            self.reset_training_state()
            self.initialize(recover_remote=False, upload_new=False)
        else:
            self.initialize()
            complete, step = self._is_training_complete()
            if complete:
                print(
                    f"Training already complete at step {step}. "
                    "Use --fresh to start over.",
                    flush=True,
                )
                return

        remote_steps = []
        if not fresh:
            print(
                f"Checking Hugging Face for existing {self.experiment_id} checkpoints...",
                flush=True,
            )
            remote_steps = self.complete_remote_steps(strict=True)
        resume = []
        if remote_steps:
            step = remote_steps[-1]
            print(f"Downloading checkpoint step {step}...", flush=True)
            self.download_step(step)
            self.validate_resume_checkpoint(step)
            self.restore_run_info_from_checkpoint(step)
            resume = [f"--resume-from-step={step}"]
            print(f"Resuming from Hugging Face checkpoint step {step}")
            if self.is_branch:
                # Resuming this run's own checkpoints: the parent's weights are
                # already baked in, but the branch point still drives the schedule.
                self.resolve_branch_step()
        elif self.is_branch:
            branch_step = self.prepare_branch_parent()
            self.print_branch_table()
            print(
                f"Branching from {self.branch_parent_id} checkpoint step "
                f"{branch_step}",
                flush=True,
            )
        elif not fresh:
            print("No complete remote checkpoint found; starting at step 0.", flush=True)
        else:
            print("Starting a new model at step 0.", flush=True)

        run_info = self.run_info
        cmd = self._base_train_command(run_info, resume)

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

    def _parent_cumulative_flops(self):
        parent_prefix = self.parent_hf_prefix()
        remote_summary = f"{parent_prefix}/summary.json"
        files = self.remote_files(strict=True, path_in_repo=parent_prefix)
        if remote_summary not in files:
            return 0.0
        from huggingface_hub import hf_hub_download
        cached = hf_hub_download(
            self.hf_repo,
            remote_summary,
            repo_type="model",
            token=os.environ.get("HF_TOKEN"),
        )
        summary = read_json(cached)
        return float(
            summary.get(
                "cumulative_pipeline_training_flops",
                summary.get("stage_training_flops", 0.0),
            )
        )

    def remote_summary(self):
        remote_path = self.remote_path("summary.json")
        if remote_path not in self.remote_files():
            return {}
        try:
            from huggingface_hub import hf_hub_download
            cached = hf_hub_download(
                self.hf_repo,
                remote_path,
                repo_type="model",
                token=os.environ.get("HF_TOKEN"),
            )
            return read_json(cached)
        except Exception:
            return {}

    def _train_downstream(self, fresh=False, confirm_fresh=False):
        if fresh:
            remote_steps = self.complete_remote_steps(strict=True)
            if remote_steps and not confirm_fresh:
                raise RuntimeError(
                    f"Refusing --fresh because {self.experiment_id} already has "
                    f"remote checkpoints: {remote_steps}"
                )
            self.reset_training_state()
            self.initialize(recover_remote=False, upload_new=False)
        else:
            self.initialize()
            complete, step = self._is_training_complete()
            if complete:
                print(
                    f"Training already complete at step {step}. "
                    "Use --fresh to start over.",
                    flush=True,
                )
                return
        self.parent["checkpoint_step"] = self.resolve_parent_step()
        if not self._parent_checkpoint_complete_locally(self.parent["checkpoint_step"]):
            raise RuntimeError(
                f"Parent checkpoint not found locally. "
                f"Run: python -m scripts.experiment prepare --config <config>"
            )

        remote_steps = [] if fresh else self.complete_remote_steps(strict=True)
        resume_step = remote_steps[-1] if remote_steps else None
        if resume_step is not None:
            self.download_step(resume_step)
            self.restore_run_info_from_checkpoint(resume_step)

        run_info = self.run_info
        training = self.config["training"]
        parent_flops = self._parent_cumulative_flops()
        common = [
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--experiment-id={self.experiment_id}",
            f"--experiment-config={self.root / 'config.json'}",
            f"--run={self.wandb['name'] if self.wandb['enabled'] else 'dummy'}",
            f"--wandb-run-id={run_info.get('wandb_run_id') or ''}",
            f"--wandb-group={self.wandb['group'] or self.base_experiment_id}",
            f"--wandb-tags={','.join(self.wandb['tags'])}",
            f"--parent-cumulative-flops={parent_flops}",
            f"--tokenizer-fingerprint={_directory_fingerprint(self.tokenizer_dir)}",
            f"--git-commit-sha={_git_commit_sha() or ''}",
        ]
        if resume_step is not None:
            common.append(f"--resume-from-step={resume_step}")

        if self.stage == "sft":
            data = self.config.get("data", {})
            cmd = [
                sys.executable, "-u", "-m", "scripts.chat_sft",
                f"--base-checkpoint-dir={self.parent_checkpoint_dir()}",
                f"--base-step={self.parent['checkpoint_step']}",
                f"--recipe={data.get('recipe', 'nanochat-default')}",
                f"--pre1930-epochs={data.get('pre1930_epochs', 5)}",
                f"--mmlu-epochs={data.get('mmlu_epochs', 3)}",
                f"--gsm8k-epochs={data.get('gsm8k_epochs', 4)}",
                f"--num-iterations={training.get('num_iterations', -1)}",
                f"--device-batch-size={training.get('device_batch_size', 8)}",
                f"--eval-every={training.get('eval_every', -1)}",
                f"--chatcore-every={training.get('chatcore_every', -1)}",
                f"--save-every={training.get('save_every', 200)}",
                *common,
            ]
            # The curriculum spec rides inside config.json (passed via --experiment-config),
            # so chat_sft reads data.curriculum directly. Optional LR/schedule/batch knobs
            # are forwarded only when present, so existing configs keep inheriting from pretrain.
            _sft_optional = {
                "warmup_ratio": "--warmup-ratio", "warmdown_ratio": "--warmdown-ratio",
                "init_lr_frac": "--init-lr-frac", "final_lr_frac": "--final-lr-frac",
                "matrix_lr": "--matrix-lr", "embedding_lr": "--embedding-lr",
                "unembedding_lr": "--unembedding-lr", "max_seq_len": "--max-seq-len",
                "total_batch_size": "--total-batch-size", "eval_tokens": "--eval-tokens",
                "load_optimizer": "--load-optimizer",
            }
            for _key, _flag in _sft_optional.items():
                if training.get(_key) is not None:
                    cmd.append(f"{_flag}={training[_key]}")
        else:
            cmd = [
                sys.executable, "-u", "-m", "scripts.chat_rl",
                f"--sft-checkpoint-dir={self.parent_checkpoint_dir()}",
                f"--sft-step={self.parent['checkpoint_step']}",
                f"--num-epochs={training.get('num_epochs', 1)}",
                f"--device-batch-size={training.get('device_batch_size', 8)}",
                f"--examples-per-step={training.get('examples_per_step', 16)}",
                f"--num-samples={training.get('num_samples', 16)}",
                f"--eval-every={training.get('eval_every', 60)}",
                f"--save-every={training.get('save_every', 60)}",
                *common,
            ]

        stop = threading.Event()
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
        batch = int(training.get("total_batch_size", 524_288))
        # A mixture schedule's total_tokens is authoritative for the training horizon;
        # num_iterations == total_tokens // batch == MixtureSchedule.total_steps.
        if self.mixture_config:
            return max(1, int(self.mixture_config["total_tokens"]) // batch)
        if training.get("num_iterations") is not None:
            return int(training["num_iterations"])
        if training.get("target_tokens") is not None:
            return max(1, int(training["target_tokens"]) // batch)
        if training.get("epochs") is not None:
            meta_path = self.pretok_dir / "meta.json"
            if not meta_path.exists():
                raise RuntimeError("Epoch-based training requires a prepared pretokenized cache")
            unique_tokens = int(read_json(meta_path)["train_tokens"])
            return max(1, math.ceil(float(training["epochs"]) * unique_tokens / batch))
        return None

    def branch_table_rows(self):
        """(field, parent value, this run's value) rows comparing a branch to its
        parent. The parent side is read from the immutable config in Git, so this
        works offline; the branch step falls back to '(latest on HF)' when it has
        not been pinned or resolved yet."""
        parent = self.branch_parent_config()
        child = self.config
        step = self.branch.get("parent_step")
        branch_point = f"{step:,}" if step is not None else "(latest on HF)"
        parent_steps = _config_iterations(parent)
        child_steps = _config_iterations(child)
        parent_batch = int(parent.get("training", {}).get("total_batch_size", 524_288))
        child_batch = int(child.get("training", {}).get("total_batch_size", 524_288))
        if child_steps is None:
            span, end = None, None
        elif self.branch_lr_schedule == "continue":
            # The horizon is the whole schedule, of which the parent already ran part.
            end = child_steps
            span = end - step if step is not None else None
        else:
            span = child_steps
            end = child_steps + step if step is not None else None
        child_range = (
            f"{branch_point} -> {end:,}" if end is not None
            else f"{branch_point} -> +{child_steps:,}" if child_steps is not None
            else "(from token cache)"
        )
        child_span = f"{span:,}" if span is not None else "(from token cache)"
        child_tokens = f"{span * child_batch:,}" if span is not None else "?"
        parent_dimensions = _model_dimensions(parent)
        child_dimensions = _model_dimensions(child)

        def training(config, key, default=None):
            value = config.get("training", {}).get(key, default)
            return "(default)" if value is None else str(value)

        parent_tokenizer = parent.get("tokenizer", {"mode": "train"})
        parent_tokenizer_source = _tokenizer_source(parent_tokenizer, self.branch_parent_id)
        tokenizer_source = _tokenizer_source(self.tokenizer_spec, self.experiment_id)
        if tokenizer_source == self.branch_parent_id:
            # Naming the parent and naming what the parent reused are the same bytes.
            tokenizer_source = parent_tokenizer_source
        rows = [
            ("experiment_id", self.branch_parent_id, self.experiment_id),
            (
                "checkpoint steps",
                f"branch point {branch_point}"
                + (f" of {parent_steps:,}" if parent_steps else ""),
                child_range,
            ),
            (
                "steps trained here",
                f"{parent_steps:,}" if parent_steps else "?",
                child_span,
            ),
            (
                "tokens trained here",
                f"{parent_steps * parent_batch:,}" if parent_steps else "?",
                child_tokens,
            ),
            ("data", _dataset_label(parent), _dataset_label(child)),
            (
                "tokenizer",
                _tokenizer_label(parent_tokenizer, parent_tokenizer_source),
                _tokenizer_label(self.tokenizer_spec, tokenizer_source),
            ),
            (
                "model (n_layer, dim, heads)",
                str(parent_dimensions),
                str(child_dimensions),
            ),
            ("max_seq_len", training(parent, "max_seq_len", 2048), training(child, "max_seq_len", 2048)),
            ("window_pattern", training(parent, "window_pattern", "SSSL"), training(child, "window_pattern", "SSSL")),
            ("total_batch_size", f"{parent_batch:,}", f"{child_batch:,}"),
            ("device_batch_size", training(parent, "device_batch_size", 32), training(child, "device_batch_size", 32)),
            ("matrix_lr", training(parent, "matrix_lr", 0.02), training(child, "matrix_lr", 0.02)),
            ("embedding_lr", training(parent, "embedding_lr", 0.3), training(child, "embedding_lr", 0.3)),
            ("unembedding_lr", training(parent, "unembedding_lr", 0.008), training(child, "unembedding_lr", 0.008)),
            ("weight_decay", training(parent, "weight_decay", 0.28), training(child, "weight_decay", 0.28)),
            ("warmup_steps", training(parent, "warmup_steps", 40), training(child, "warmup_steps", 40)),
            ("warmdown_ratio", training(parent, "warmdown_ratio", 0.65), training(child, "warmdown_ratio", 0.65)),
            ("seed", training(parent, "seed", 42), training(child, "seed", 42)),
            ("fp8", training(parent, "fp8", False), training(child, "fp8", False)),
            ("artifacts", self.branch_parent_hf_prefix, self.hf_prefix),
        ]
        return [(field, str(left), str(right)) for field, left, right in rows]

    def print_branch_table(self):
        """Print the parent model next to the model that resumes from its weights."""
        if not self.is_branch:
            return
        try:
            rows = self.branch_table_rows()
        except Exception as exc:
            print(f"Could not build the branch table: {type(exc).__name__}: {exc}")
            return
        inherits = "weights + optimizer state" if self.branch_load_optimizer else (
            "weights only (fresh optimizer state)"
        )
        header = ("field", "parent", "this run (branch)")
        # Long values (a mixture's source list) wrap instead of pushing the table
        # off the side of a notebook cell.
        limit = 46
        wrapped = [
            (field, textwrap.wrap(left, limit) or [""], textwrap.wrap(right, limit) or [""])
            for field, left, right in rows
        ]
        widths = [
            max([len(header[0])] + [len(field) for field, _, _ in wrapped]),
            max([len(header[1])] + [len(line) for _, left, _ in wrapped for line in left]),
            max([len(header[2])] + [len(line) for _, _, right in wrapped for line in right]),
        ]
        rule = "-" * (sum(widths) + 3 * 3 + 2)
        print("=" * len(rule))
        print(f"Branch: {self.experiment_id} resumes from {self.branch_parent_id}")
        print(f"Inherits:      {inherits}")
        print(f"Artifact repo: {self.hf_repo}")
        print(f"LR schedule:   {self.branch_lr_schedule}", end="")
        if self.branch_lr_schedule == "branch":
            print("  (fresh warmup/warmdown across this run's own span)")
        else:
            print("  (keeps the parent's global schedule position)")
        print(rule)
        print(
            f"  {header[0]:<{widths[0]}}   {header[1]:<{widths[1]}}   {header[2]}"
        )
        print(rule)
        for (field, left, right), (_, raw_left, raw_right) in zip(wrapped, rows):
            marker = " " if raw_left == raw_right else "*"
            for index in range(max(len(left), len(right))):
                label = field if index == 0 else ""
                print(
                    f"{marker if index == 0 else ' '} {label:<{widths[0]}}   "
                    f"{(left[index] if index < len(left) else ''):<{widths[1]}}   "
                    f"{right[index] if index < len(right) else ''}".rstrip()
                )
        print(rule)
        print("* marks a value this run changes. The tokenizer and model shape rows")
        print("  must match the parent for its weights to load; every other row is")
        print("  free to differ -- that is the point of a branch.")
        print("=" * len(rule))

    def _print_branch_mixture_position(self, schedule, batch):
        """Where a branch picks the mixture up, which depends on its lr_schedule."""
        if not self.is_branch:
            return
        step = self.branch.get("parent_step")
        if self.branch_lr_schedule != "continue":
            print("  Branch (lr_schedule='branch'): this run restarts the mixture at")
            print("  stage 0; the boundaries above are relative to its own first step.")
            return
        if step is None:
            print("  Branch (lr_schedule='continue'): resumes the parent's stage "
                  "position; branch step not pinned yet.")
            return
        active = schedule.stage_for_step(step)
        index = schedule.stage_index(active)
        _, end = schedule.stage_bounds_steps(index)
        print(f"  Branch (lr_schedule='continue'): starts at step {step:,} inside "
              f"stage [{index}] {active.name!r}")
        print(f"  reading {active.source!r} for {end - step:,} more steps, then "
              f"{schedule.total_steps - step:,} steps in total to the horizon.")

    def plan(self):
        """Dry-run planner: load config and print the branch table and mixture
        schedule without training.

        Prints stage boundaries (tokens and steps), total tokens drawn per source,
        realized epochs per source, and realized token ratio per stage. Reads per-source
        cache meta.json best-effort for epoch estimates; runs offline in well under a
        second (no model, no CUDA, no network).
        """
        from nanochat.mixture import MixtureSchedule

        # Offline, so config mistakes surface here rather than after a download.
        self.validate_config()
        self.print_branch_table()

        if not self.mixture_config:
            print("No mixture_schedule in config; this is a single-source run.")
            training = self.config["training"]
            batch = int(training.get("total_batch_size", 524_288))
            iters = self._explicit_iterations()
            if iters is not None:
                print(f"total_batch_size: {batch:,}")
                print(f"num_iterations:   {iters:,}")
                print(f"total_tokens:     {iters * batch:,}")
            return

        training = self.config["training"]
        batch = int(training.get("total_batch_size", 524_288))
        schedule = MixtureSchedule.from_config(self.mixture_config, total_batch_size=batch)

        # Best-effort per-source unique token counts from prepared caches (if present).
        source_unique = {}
        for name, directory in self.active_mixture_source_dirs.items():
            meta_path = Path(directory) / "meta.json"
            if meta_path.exists():
                source_unique[name] = int(read_json(meta_path).get("train_tokens", 0))

        start_tokens = self.mixture_start_tokens
        planned = schedule.planned_tokens_per_source(start_tokens=start_tokens)

        print("=" * 68)
        print(f"Mixture plan for experiment: {self.experiment_id}")
        print(f"total_tokens: {schedule.total_tokens:,}  |  total_batch_size: {batch:,}  "
              f"|  total_steps: {schedule.total_steps:,}")
        print(f"seed_data: {schedule.seed_data}  |  max_epochs: {schedule.max_epochs}")
        print("-" * 68)
        print("Stages (each reads one pre-mixed source; boundaries in tokens and steps):")
        for i, st in enumerate(schedule.stages):
            s0, s1 = schedule.stage_bounds_steps(i)
            stage_tokens = (s1 - s0) * batch
            ds = self.mixture_datasets.get(st.source, {})
            loc = ds.get("repo", "?")
            if ds.get("subfolder"):
                loc += f"/{ds['subfolder']}"
            print(f"  [{i}] {st.name}  <- source {st.source!r}  ({loc})")
            print(f"      start: {st.start_tokens:,} tok  =>  step {st.start_step:,}")
            print(f"      span:  steps [{s0:,}, {s1:,})  =  {stage_tokens:,} tok")
        self._print_branch_mixture_position(schedule, batch)
        print("-" * 68)
        print("Total tokens drawn per source:")
        for s in schedule.sources:
            line = f"  {s:12s}: {planned[s]:,} tok"
            if s in source_unique and source_unique[s] > 0:
                line += f"  ({planned[s] / source_unique[s]:.3f} epochs over {source_unique[s]:,} unique)"
            elif planned[s] > 0:
                line += "  (cache not prepared; epochs unknown)"
            else:
                line += "  (inherited; no cache required)"
            print(line)
        if source_unique:
            try:
                schedule.check_epoch_cap(source_unique, start_tokens=start_tokens)
                print(f"Epoch cap check: PASS (<= {schedule.max_epochs} epochs per source)")
            except ValueError as exc:
                print(f"Epoch cap check: FAIL\n{exc}")
        else:
            print("Epoch cap check: skipped (no prepared caches; enforced at train time)")
        print("=" * 68)

    def serve(self, port=8000):
        local_steps = self.complete_local_steps()
        if not local_steps:
            remote_steps = self.complete_remote_steps()
            if not remote_steps:
                raise RuntimeError("No complete checkpoint available to serve")
            self.download_step(remote_steps[-1])
            local_steps = self.complete_local_steps()
        step = local_steps[-1]
        source = "sft" if self.stage == "sft" else ("rl" if self.stage == "posttrain" else "base")
        cmd = [
            sys.executable, "-m", "scripts.chat_web",
            f"--source={source}",
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--step={step}",
            f"--port={port}",
        ]
        print(f"Serving {self.experiment_id} checkpoint step {step} on port {port}", flush=True)
        run_streaming(cmd, self.environment())

    def _ensure_tokenizer(self):
        """Download the tokenizer if it's not already on disk. Tokenizer lives
        under the base experiment on HF regardless of stage."""
        if (self.tokenizer_dir / "tokenizer.pkl").exists():
            return
        print("Downloading tokenizer...", flush=True)
        if self.stage == "base":
            self.download_folder("tokenizer", self.tokenizer_dir, strict=True)
        else:
            from huggingface_hub import hf_hub_download
            prefix = f"experiments/{self.base_experiment_id}/tokenizer/"
            files = [
                p for p in self.remote_files(strict=True, path_in_repo=f"experiments/{self.base_experiment_id}")
                if p.startswith(prefix)
            ]
            if not files:
                raise RuntimeError(f"Tokenizer not found on HF for base experiment {self.base_experiment_id}")
            for repo_path in files:
                cached = hf_hub_download(self.hf_repo, repo_path, repo_type="model", token=os.environ.get("HF_TOKEN"))
                dest = self.tokenizer_dir / repo_path[len(prefix):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                _copy_cached_file(cached, dest)
        print("Downloaded tokenizer.", flush=True)

    def chat(self, port=8000):
        """Serve this experiment's checkpoint and open a public cloudflared
        tunnel to it, for chatting from a notebook. Blocks until interrupted."""
        import urllib.request

        self._ensure_tokenizer()

        if not self.complete_local_steps() and not self.complete_remote_steps():
            hint = ""
            if self.stage != "base":
                hint = (
                    f"\n\nThis is the SFT config for base '{self.base_experiment_id}'. "
                    "If you only meant to chat with the base model, point --config at "
                    "the base config instead. If you want the finetuned version, run "
                    "'prepare' and 'train' for this SFT config first."
                )
            raise RuntimeError(
                f"No checkpoint found (local or on HF) for experiment '{self.experiment_id}'.{hint}"
            )

        subprocess.run(["pkill", "-f", "scripts.chat_web"], capture_output=True)
        time.sleep(1)

        source = "sft" if self.stage == "sft" else ("rl" if self.stage == "posttrain" else "base")
        server_proc = subprocess.Popen(
            [
                sys.executable, "-u", "-m", "scripts.chat_web",
                f"--source={source}",
                f"--checkpoint-dir={self.checkpoint_dir}",
                f"--tokenizer-dir={self.tokenizer_dir}",
                f"--port={port}",
            ],
            env=self.environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        server_log = []
        threading.Thread(target=lambda: [server_log.append(l) for l in server_proc.stdout], daemon=True).start()

        # Colab's kernel.proxyPort() doesn't register a working route on some
        # GPU runtime types, so open a public URL via a cloudflare quick
        # tunnel instead -- no account/signup needed.
        cloudflared_bin = "/usr/local/bin/cloudflared"
        if not os.path.exists(cloudflared_bin):
            subprocess.check_call([
                "wget", "-q",
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                "-O", cloudflared_bin,
            ])
            os.chmod(cloudflared_bin, 0o755)
        tunnel_proc = subprocess.Popen(
            [cloudflared_bin, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        tunnel_log = []
        threading.Thread(target=lambda: [tunnel_log.append(l) for l in tunnel_proc.stdout], daemon=True).start()

        try:
            print("Loading model...", flush=True)
            for _ in range(120):
                time.sleep(2)
                if server_proc.poll() is not None:
                    print("".join(server_log))
                    raise RuntimeError(f"chat_web server exited early with code {server_proc.returncode}")
                try:
                    urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1)
                    print("Ready!")
                    break
                except Exception:
                    pass
            else:
                raise RuntimeError("Server did not become healthy in time")

            tunnel_url = None
            for _ in range(30):
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", "".join(tunnel_log))
                if match:
                    tunnel_url = match.group(0)
                    break
                time.sleep(1)
            if not tunnel_url:
                raise RuntimeError("Could not find cloudflared tunnel URL. Tunnel log:\n" + "".join(tunnel_log))
            print(f"Chat with your model here: {tunnel_url}", flush=True)

            server_proc.wait()
        finally:
            tunnel_proc.terminate()
            if server_proc.poll() is None:
                server_proc.terminate()

    def _ensure_checkpoint(self):
        local_steps = self.complete_local_steps()
        if not local_steps:
            remote_steps = self.complete_remote_steps()
            if not remote_steps:
                raise RuntimeError("No complete checkpoint available")
            self.download_step(remote_steps[-1])
            local_steps = self.complete_local_steps()
        return local_steps[-1]

    def evaluate(self, eval_parts=("core", "bpb"), per_position_bpb=False):
        step = self._ensure_checkpoint()
        if self.stage != "base":
            print(
                f"No {self.stage} eval configured yet; skipping.",
                flush=True,
            )
            self.build_summary()
            self.sync_metadata()
            return
        self.prepare_eval()
        run_info = self.run_info
        common = [
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--step={step}",
            f"--device-batch-size={self.config['training'].get('device_batch_size', 16)}",
        ]
        wandb_common = []
        if run_info.get("wandb_run_id"):
            wandb_common = [
                f"--wandb-run-id={run_info['wandb_run_id']}",
                f"--wandb-run-name={self.wandb['name']}",
            ]
        if self._has_pretok_val():
            common.extend(["--pretokenized", f"--pretokenized-dir={self.eval_pretok_dir}"])
        else:
            common.append(f"--data-dir={self.eval_data_dir}")
        if self.eval_source:
            print(f"Final BPB eval reads mixture source {self.eval_source!r}", flush=True)

        if "core" in eval_parts:
            run_streaming([
                sys.executable, "-u", "-m", "scripts.base_eval",
                "--eval=core", "--max-per-task=-1",
                f"--output-json={self.eval_dir / 'core.json'}",
                *common,
                *wandb_common,
            ], self.environment())
        if "bpb" in eval_parts:
            run_streaming([
                sys.executable, "-u", "-m", "scripts.base_eval",
                "--eval=bpb", "--split=val", "--split-tokens=20971520",
                f"--output-json={self.eval_dir / 'val_bpb.json'}",
                *(["--per-position-bpb"] if per_position_bpb else []),
                *common,
                *wandb_common,
            ], self.environment())
        # samples are cheap and always worth having; run them unconditionally
        run_streaming([
            sys.executable, "-u", "-m", "scripts.base_eval",
            "--eval=sample",
            f"--output-json={self.eval_dir / 'samples.json'}",
            *common,
        ], self.environment())
        self.build_summary()
        self.sync_metadata()

    def evaluate_cross_dataset(self, other_config_path, per_position_bpb=False):
        """Evaluate this experiment's model on another config's validation shard,
        tokenized with this experiment's own tokenizer. BPB normalizes the loss
        by target bytes, so results are comparable across models that use
        different tokenizers -- fixing the eval text gives a fair head-to-head
        between models trained on different datasets."""
        if self.stage != "base":
            raise RuntimeError("Cross-dataset eval is only available for base runs")
        step = self._ensure_checkpoint()
        self._ensure_tokenizer()
        other = read_json(other_config_path)
        dataset = other.get("dataset", {})
        repo = dataset.get("repo")
        val_shard = dataset.get("validation_shard")
        if not repo or val_shard is None:
            raise RuntimeError(
                f"{other_config_path} does not define dataset.repo and "
                "dataset.validation_shard"
            )
        slug = repo.split("/")[-1]
        cross_root = self.root / "cross" / slug
        data_dir = cross_root / "data"
        pretok_dir = cross_root / "pretok"
        data_dir.mkdir(parents=True, exist_ok=True)
        if not sorted(data_dir.glob("shard_*.parquet")):
            base_url = dataset.get("base_url") or (
                f"https://huggingface.co/datasets/{repo}/resolve/"
                f"{dataset.get('revision', 'main')}"
            )
            run_streaming([
                sys.executable, "-u", "-m", "nanochat.dataset",
                "-n", "0",
                "--base-url", base_url,
                "--data-dir", str(data_dir),
                "--max-shard", str(val_shard),
            ], self.environment())
            print(f"Downloaded {repo} val shard.", flush=True)
        pretok = self.config.get("pretokenize", {})
        run_streaming([
            sys.executable, "-u", "-m", "scripts.pretok_think",
            "--data-dir", str(data_dir),
            "--tokenizer-dir", str(self.tokenizer_dir),
            "--output-dir", str(pretok_dir),
            "--val-only",
            "--val-tokens", str(int(pretok.get("val_tokens", 20_971_520))),
            "--shard-tokens", str(int(pretok.get("shard_tokens", 100_000_000))),
            "--tokenizer-threads", str(int(pretok.get("tokenizer_threads", 8))),
        ], self.environment())
        output_json = self.eval_dir / f"val_bpb_on_{slug}.json"
        run_streaming([
            sys.executable, "-u", "-m", "scripts.base_eval",
            "--eval=bpb", "--split=val", "--split-tokens=20971520",
            f"--output-json={output_json}",
            *(["--per-position-bpb"] if per_position_bpb else []),
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--step={step}",
            f"--device-batch-size={self.config['training'].get('device_batch_size', 16)}",
            "--pretokenized", f"--pretokenized-dir={pretok_dir}",
        ], self.environment())
        result = read_json(output_json)
        print(
            f"{self.experiment_id} on {repo} val: bpb {result['bpb']['val']:.6f}",
            flush=True,
        )
        self.sync_metadata()
        return result

    def evaluate_ratio_scout(self, steps):
        if self.stage != "base":
            raise RuntimeError("Ratio-scout evaluation is only available for base runs")
        steps = sorted(set(int(step) for step in steps))
        if not steps or any(step <= 0 for step in steps):
            raise ValueError("Ratio-scout steps must be positive integers")

        self.initialize()
        scout_dir = self.eval_dir / "ratio_scout"
        scout_dir.mkdir(parents=True, exist_ok=True)
        # Recover prior scout outputs and the standard final eval so a fresh
        # Colab runtime can reuse completed benchmark work.
        self.download_folder("evals", self.eval_dir)

        def has_eval_checkpoint(step):
            suffix = f"{step:06d}"
            return (
                (self.checkpoint_dir / f"model_{suffix}.pt").exists()
                and (self.checkpoint_dir / f"meta_{suffix}.json").exists()
            )

        missing_steps = [step for step in steps if not has_eval_checkpoint(step)]
        if missing_steps:
            remote_steps = set(self.complete_remote_steps(strict=True))
            unavailable = [step for step in missing_steps if step not in remote_steps]
            if unavailable:
                raise RuntimeError(
                    f"Complete checkpoints are unavailable for steps: {unavailable}"
                )
            for step in missing_steps:
                print(f"Downloading checkpoint step {step:,} from Hugging Face", flush=True)
                self.download_step(step, include_optimizer=False)

        training = self.config["training"]
        scaling_params = int(training["scaling_params"])
        common = [
            f"--checkpoint-dir={self.checkpoint_dir}",
            f"--tokenizer-dir={self.tokenizer_dir}",
            f"--device-batch-size={training.get('device_batch_size', 16)}",
        ]
        if self.config.get("pretokenize", {}).get("enabled", True):
            common.extend(["--pretokenized", f"--pretokenized-dir={self.eval_pretok_dir}"])
        else:
            common.append(f"--data-dir={self.eval_data_dir}")

        records = []
        for step in steps:
            output_path = scout_dir / f"step_{step:06d}.json"
            output = read_json(output_path) if output_path.exists() else None
            created_output = False
            if not _complete_ratio_scout_output(output, step):
                output = self._reuse_final_base_eval(step)
                if output is not None:
                    atomic_json(output_path, output)
                    created_output = True
                    print(f"Reused existing full evaluation for step {step:,}", flush=True)
                else:
                    run_streaming([
                        sys.executable, "-u", "-m", "scripts.base_eval",
                        "--eval=core,bpb", "--max-per-task=-1",
                        "--split=val", "--split-tokens=20971520",
                        f"--step={step}", f"--output-json={output_path}",
                        *common,
                    ], self.environment())
                    output = read_json(output_path)
                    created_output = True
            if not _complete_ratio_scout_output(output, step):
                raise RuntimeError(f"Incomplete ratio-scout output for step {step}")
            if created_output:
                self.upload_file(
                    output_path,
                    f"evals/ratio_scout/{output_path.name}",
                    f"Upload ratio-scout step {step} for {self.experiment_id}",
                )

            meta = read_json(self.checkpoint_dir / f"meta_{step:06d}.json")
            from nanochat.experiment_metrics import checkpoint_compute_fields
            compute = checkpoint_compute_fields(meta, fallback_step=step)
            batch = int(meta.get("total_batch_size", training["total_batch_size"]))
            records.append({
                "step": step,
                "realized_ratio": step * batch / scaling_params,
                "training_tokens": step * batch,
                "stage_training_flops": compute["stage_training_flops"],
                "inherited_parent_flops": compute["inherited_parent_flops"],
                "cumulative_pipeline_training_flops": compute[
                    "cumulative_pipeline_training_flops"
                ],
                "core_metric": output["core_metric"],
                "full_val_bpb": output["bpb"]["val"],
                "centered_results": output.get("centered_results"),
                "output_json": output_path.name,
            })

        results_path = scout_dir / "results.json"
        previous = read_json(results_path) if results_path.exists() else {}
        logged_steps = set(previous.get("wandb_logged_steps", []))
        run_info = self.run_info
        run_id = run_info.get("wandb_run_id")
        pending = [record for record in records if record["step"] not in logged_steps]
        if run_id and pending:
            import wandb
            from nanochat.experiment_metrics import (
                configure_wandb_metrics,
                update_wandb_compute_summary,
            )
            run = wandb.init(
                project=self.wandb["project"],
                entity=self.wandb["entity"],
                id=run_id,
                resume="allow",
                name=self.wandb["name"],
            )
            configure_wandb_metrics(run)
            for record in pending:
                log_data = {
                    "step": record["step"],
                    "total_training_flops": record[
                        "cumulative_pipeline_training_flops"
                    ],
                    "stage_training_flops": record["stage_training_flops"],
                    "inherited_parent_flops": record["inherited_parent_flops"],
                    "cumulative_pipeline_training_flops": record[
                        "cumulative_pipeline_training_flops"
                    ],
                    "eval/realized_ratio": record["realized_ratio"],
                    "core_metric": record["core_metric"],
                    "eval/full_val_bpb": record["full_val_bpb"],
                    "centered_results": record["centered_results"],
                }
                run.log(log_data)
                logged_steps.add(record["step"])
            final = max(records, key=lambda record: record["step"])
            final_compute = {
                "total_training_flops": final[
                    "cumulative_pipeline_training_flops"
                ],
                "stage_training_flops": final["stage_training_flops"],
                "inherited_parent_flops": final["inherited_parent_flops"],
                "cumulative_pipeline_training_flops": final[
                    "cumulative_pipeline_training_flops"
                ],
            }
            update_wandb_compute_summary(run, final_compute)
            run.summary["core_metric"] = final["core_metric"]
            run.summary["full_val_bpb"] = final["full_val_bpb"]
            run.summary["ratio_scout_steps"] = steps
            run.finish()

        atomic_json(results_path, {
            "experiment_id": self.experiment_id,
            "note": (
                "Checkpoint results share one ratio-30 learning-rate schedule; "
                "they scout candidate regions and are not independent ratio runs."
            ),
            "records": records,
            "wandb_logged_steps": sorted(logged_steps),
        })
        self.upload_folder(
            scout_dir,
            "evals/ratio_scout",
            f"Upload ratio scout for {self.experiment_id}",
        )
        print(f"Ratio-scout results written to {results_path}", flush=True)
        return records

    def _reuse_final_base_eval(self, step):
        core_path = self.eval_dir / "core.json"
        bpb_path = self.eval_dir / "val_bpb.json"
        if not core_path.exists() or not bpb_path.exists():
            return None
        core = read_json(core_path)
        bpb = read_json(bpb_path)
        if core.get("step") != step or bpb.get("step") != step:
            return None
        return {
            "model": core.get("model") or bpb.get("model"),
            "step": step,
            "bpb": bpb.get("bpb", {}),
            "core_metric": core.get("core_metric"),
            "core_results": core.get("core_results"),
            "centered_results": core.get("centered_results"),
            "conditioned_samples": [],
            "unconditioned_samples": [],
        }

    def build_summary(self):
        steps = self.complete_local_steps()
        if not steps:
            return None
        step = steps[-1]
        meta = read_json(self.checkpoint_dir / f"meta_{step:06d}.json")
        loop = meta.get("loop_state", {})
        prior_summary = self.remote_summary()
        if self.stage != "base":
            chat = (
                read_json(self.eval_dir / "chatcore.json")
                if (self.eval_dir / "chatcore.json").exists()
                else {}
            )
            stage_flops = float(loop.get(
                "stage_training_flops",
                prior_summary.get("stage_training_flops", 0.0),
            ))
            inherited = float(loop.get(
                "inherited_parent_flops",
                prior_summary.get("inherited_parent_flops", 0.0),
            ))
            summary = {
                "experiment_id": self.experiment_id,
                "stage": self.stage,
                "base_experiment_id": self.base_experiment_id,
                "parent_experiment_id": self.parent_experiment_id,
                "parent_checkpoint_step": self.parent.get("checkpoint_step"),
                "step": step,
                "stage_training_flops": stage_flops,
                "inherited_parent_flops": inherited,
                "cumulative_pipeline_training_flops": float(
                    loop.get(
                        "cumulative_pipeline_training_flops",
                        prior_summary.get(
                            "cumulative_pipeline_training_flops",
                            inherited + stage_flops,
                        ),
                    )
                ),
                "chatcore_metric": chat.get("chatcore_metric"),
                "chat_results": chat.get("results"),
                "training_time_seconds": loop.get("total_training_time"),
                "config_fingerprint": self.config_fingerprint,
                "tokenizer_fingerprint": _directory_fingerprint(self.tokenizer_dir),
                "git_commit_sha": _git_commit_sha(),
                "wandb_url": (
                    f"https://wandb.ai/{self.wandb['entity']}/{self.wandb['project']}"
                    f"/runs/{self.run_info.get('wandb_run_id')}"
                    if self.run_info.get("wandb_run_id")
                    else None
                ),
                "huggingface_url": (
                    f"https://huggingface.co/{self.hf_repo}/tree/main/{self.hf_prefix}"
                ),
            }
            atomic_json(self.summary_path, summary)
            return summary
        core = read_json(self.eval_dir / "core.json") if (self.eval_dir / "core.json").exists() else {}
        bpb = read_json(self.eval_dir / "val_bpb.json") if (self.eval_dir / "val_bpb.json").exists() else {}
        samples = (
            read_json(self.eval_dir / "samples.json")
            if (self.eval_dir / "samples.json").exists()
            else {}
        )
        training = self.config["training"]
        stage_flops = float(loop.get(
            "stage_training_flops",
            prior_summary.get("stage_training_flops", 0.0),
        ))
        # 0.0 for a from-scratch run; a branch inherits the parent's pipeline FLOPs.
        inherited = float(loop.get(
            "inherited_parent_flops",
            prior_summary.get("inherited_parent_flops", 0.0),
        ))
        branch_step = int(loop.get("stage_start_step", 0) or 0)
        summary = {
            "experiment_id": self.experiment_id,
            "stage": self.stage,
            "base_experiment_id": self.base_experiment_id,
            "parent_experiment_id": self.parent_experiment_id,
            "parent_checkpoint_step": self.branch.get("parent_step"),
            "dataset": self._primary_dataset().get("repo"),
            "dataset_revision": self._primary_dataset().get("revision", "main"),
            "step": step,
            "depth": training.get("depth", 12),
            "target_param_data_ratio": training.get("target_param_data_ratio"),
            "training_tokens": meta.get("total_batch_size", training.get("total_batch_size", 524288)) * step,
            "final_sampled_val_bpb": meta.get("val_bpb"),
            "minimum_sampled_val_bpb": loop.get("min_val_bpb"),
            "full_val_bpb": bpb.get("bpb", {}).get("val"),
            "core_metric": core.get("core_metric"),
            "centered_results": core.get("centered_results"),
            "conditioned_samples": samples.get("conditioned_samples", []),
            "unconditioned_samples": samples.get("unconditioned_samples", []),
            "training_time_seconds": loop.get("total_training_time"),
            "stage_training_flops": stage_flops,
            "inherited_parent_flops": inherited,
            "cumulative_pipeline_training_flops": float(loop.get(
                "cumulative_pipeline_training_flops",
                prior_summary.get(
                    "cumulative_pipeline_training_flops", inherited + stage_flops
                ),
            )),
            "config_fingerprint": self.config_fingerprint,
            "git_commit_sha": _git_commit_sha(),
            "wandb_url": (
                f"https://wandb.ai/{self.wandb['entity']}/{self.wandb['project']}"
                f"/runs/{self.run_info['wandb_run_id']}"
            ),
            "huggingface_url": f"https://huggingface.co/{self.hf_repo}/tree/main/{self.hf_prefix}",
            "dataset_fingerprint": _json_fingerprint(
                self.config.get("dataset", self.config.get("datasets", {}))
            ),
            "tokenizer_fingerprint": _directory_fingerprint(self.tokenizer_dir),
        }
        # A mixture run has no single pretok/ cache: unique tokens are the sum over the
        # per-source caches, and per-source realized epochs are reported by the planner.
        if self.mixture_source_dirs:
            per_source = {}
            for name, directory in self.active_mixture_source_dirs.items():
                meta_path = directory / "meta.json"
                if meta_path.exists():
                    per_source[name] = read_json(meta_path).get("train_tokens")
            if per_source and all(per_source.values()):
                summary["unique_train_tokens_per_source"] = per_source
                unique_tokens = sum(per_source.values())
            else:
                unique_tokens = None
        else:
            pretok_meta_path = self.pretok_dir / "meta.json"
            unique_tokens = (
                read_json(pretok_meta_path).get("train_tokens")
                if pretok_meta_path.exists() else None
            )
        # A branch keeps the parent's step numbering, so training_tokens above spans
        # the whole lineage; its own data is only what it drew after the branch point.
        stage_tokens = summary["training_tokens"] - (
            meta.get("total_batch_size", training.get("total_batch_size", 524288))
            * branch_step
        )
        if self.is_branch:
            summary["branch_parent_experiment_id"] = self.branch_parent_id
            summary["branch_parent_step"] = branch_step or self.branch.get("parent_step")
            summary["branch_lr_schedule"] = self.branch_lr_schedule
            summary["stage_training_tokens"] = stage_tokens
        if unique_tokens:
            summary["unique_train_tokens"] = unique_tokens
            summary["effective_epochs"] = stage_tokens / unique_tokens
        atomic_json(self.summary_path, summary)
        return summary

    def sync_metadata(self):
        for path in (self.root / "config.json", self.run_path, self.summary_path):
            if path.exists():
                self.upload_file(path, path.name, f"Update metadata for {self.experiment_id}")
        if self.eval_dir.exists():
            self.upload_folder(self.eval_dir, "evals", f"Upload evals for {self.experiment_id}")

    def all(self, fresh=False, confirm_fresh=False):
        self.initialize()
        if self.is_branch:
            # Fail before hours of data preparation if the parent is unusable.
            self.prepare_branch_parent()
            self.print_branch_table()
        self.prepare_dataset()
        self.prepare_tokenizer()
        self.prepare_pretokenized()
        self.train(fresh=fresh, confirm_fresh=confirm_fresh)
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


def _git_commit_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def create_wandb_workspace(entity, project):
    try:
        import wandb_workspaces.reports.v2 as wr
        import wandb_workspaces.workspaces as ws
    except ImportError as exc:
        raise RuntimeError("Install wandb-workspaces before creating the workspace") from exc

    classify_wandb_runs(entity, project)
    sections = [
        ws.Section(name="Benchmarks versus compute", is_open=True, panels=[
            wr.LinePlot(
                title="CORE versus cumulative training FLOPs",
                x="cumulative_pipeline_training_flops",
                y=["core_metric"],
            ),
            wr.LinePlot(
                title="ChatCORE versus cumulative training FLOPs",
                x="cumulative_pipeline_training_flops",
                y=["chatcore_metric"],
            ),
            wr.LinePlot(
                title="Post-training reward versus cumulative training FLOPs",
                x="cumulative_pipeline_training_flops",
                y=["reward", "pass@1", "pass@8"],
            ),
            wr.LinePlot(
                title="Periodic validation BPB versus cumulative training FLOPs",
                x="cumulative_pipeline_training_flops",
                y=["val/bpb"],
            ),
            wr.LinePlot(
                title="Full validation BPB versus cumulative training FLOPs",
                x="cumulative_pipeline_training_flops",
                y=["eval/full_val_bpb"],
            ),
        ]),
        ws.Section(name="Training", is_open=True, panels=[
            wr.LinePlot(x="step", y=["train/loss"]),
            wr.LinePlot(
                x="step",
                y=["train/lrm", "train/lrm_matrix", "train/lrm_adam", "lrm"],
            ),
            wr.LinePlot(x="step", y=["train/epoch"]),
            wr.LinePlot(x="step", y=["train/dt"]),
            wr.LinePlot(x="step", y=["total_training_time"]),
        ]),
        ws.Section(name="Efficiency", is_open=True, panels=[
            wr.LinePlot(x="step", y=["train/mfu"]),
            wr.LinePlot(x="step", y=["train/tok_per_sec"]),
        ]),
        ws.Section(name="Lineage", is_open=True, panels=[
            wr.RunComparer(diff_only="split", layout={"w": 24, "h": 12}),
        ]),
    ]
    workspace = ws.Workspace(
        name="Nanochat Dataset Experiments",
        entity=entity,
        project=project,
        sections=sections,
        runset_settings=ws.RunsetSettings(
            filters="State != 'crashed' and State != 'killed'",
            pinned_columns=[
                "summary:dataset",
                "config:stage",
                "config:base_experiment_id",
                "config:parent_experiment_id",
                "config:parent_checkpoint_step",
                "summary:stage_training_flops",
                "summary:cumulative_pipeline_training_flops",
                "summary:target_param_data_ratio",
                "summary:training_tokens",
                "summary:min_val_bpb",
                "summary:full_val_bpb",
                "summary:core_metric",
                "summary:training_time_seconds",
                "summary:final_mfu",
                "summary:final_tok_per_sec",
            ],
        ),
        auto_generate_panels=False,
    )
    workspace.save()
    print(workspace.url)


def classify_wandb_runs(entity, project):
    import wandb

    api = wandb.Api()
    for run in api.runs(f"{entity}/{project}"):
        tags = set(run.tags or [])
        if run.state in {"crashed", "killed"}:
            tags.add("interrupted")
        if (
            run.state == "finished"
            and run.summary.get("cumulative_pipeline_training_flops") is None
        ):
            tags.add("legacy")
        updated_tags = sorted(tags)
        if updated_tags != sorted(run.tags or []):
            run.tags = updated_tags
            run.update()


def main():
    parser = argparse.ArgumentParser(description="Run reproducible nanochat experiments")
    parser.add_argument(
        "command",
        choices=[
            "prepare", "train", "eval", "serve", "chat", "ratio-scout", "sync", "all",
            "wandb-workspace", "plan",
        ],
    )
    parser.add_argument("--config", type=str, help="experiment JSON config")
    parser.add_argument("--experiment-root", type=str, default=None)
    parser.add_argument(
        "--nproc-per-node",
        type=int,
        default=1,
        help="number of local processes for distributed base training (default: 1)",
    )
    parser.add_argument("--port", type=int, default=8000, help="(serve/chat commands) port to listen on")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="reset model checkpoints/evals/W&B state but preserve prepared data and tokenizer",
    )
    parser.add_argument(
        "--confirm-fresh",
        action="store_true",
        help="allow --fresh even when complete remote checkpoints already exist",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default="",
        help="comma-separated checkpoint steps for ratio-scout",
    )
    parser.add_argument(
        "--parent-experiment-id",
        type=str,
        default=None,
        help="base experiment ID to finetune from (required for sft/posttrain if not in config)",
    )
    parser.add_argument(
        "--parent-step",
        type=int,
        default=None,
        help="checkpoint step of the parent experiment to finetune from (required for sft/posttrain if not in config)",
    )
    parser.add_argument(
        "--branch-step",
        type=int,
        default=None,
        help=(
            "checkpoint step of the parent base run to branch from, overriding "
            "branch.parent_step (default: the latest complete parent checkpoint)"
        ),
    )
    parser.add_argument(
        "--val-bpb-only",
        action="store_true",
        help="(eval command) only compute val BPB",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="(eval command) only run the CORE benchmark",
    )
    parser.add_argument(
        "--per-position-bpb-only",
        action="store_true",
        help="(eval command) only compute val BPB, bucketed by token position",
    )
    parser.add_argument(
        "--per-position-bpb",
        action="store_true",
        help="(eval command) also report val BPB bucketed by token position",
    )
    parser.add_argument(
        "--cross-dataset-config",
        type=str,
        default=None,
        help=(
            "(eval command) evaluate this model's val BPB on another config's "
            "validation shard (tokenized with this model's tokenizer)"
        ),
    )
    args = parser.parse_args()

    if args.experiment_root:
        os.environ["NANOCHAT_EXPERIMENT_ROOT"] = args.experiment_root
    root = os.environ.get("NANOCHAT_EXPERIMENT_ROOT", str(Path(get_base_dir()) / "experiments"))

    if args.command == "wandb-workspace":
        create_wandb_workspace(
            os.environ.get("WANDB_ENTITY", DEFAULT_ENTITY),
            os.environ.get("WANDB_PROJECT", DEFAULT_PROJECT),
        )
        return
    if not args.config:
        parser.error("--config is required for this command")

    parent_experiment_id = args.parent_experiment_id or os.environ.get("NANOCHAT_PARENT_EXPERIMENT_ID") or None
    parent_step_env = os.environ.get("NANOCHAT_PARENT_STEP")
    parent_step = args.parent_step if args.parent_step is not None else (int(parent_step_env) if parent_step_env else None)
    branch_step_env = os.environ.get("NANOCHAT_BRANCH_STEP")
    branch_step = args.branch_step if args.branch_step is not None else (int(branch_step_env) if branch_step_env else None)
    experiment = Experiment(
        args.config,
        parent_experiment_id=parent_experiment_id,
        parent_step=parent_step,
        nproc_per_node=args.nproc_per_node,
        branch_step=branch_step,
    )
    if args.command == "plan":
        experiment.plan()
    elif args.command == "prepare":
        experiment.initialize()
        if experiment.stage == "base":
            if experiment.is_branch:
                # Resolve and fetch the parent weights first: a bad branch point
                # should fail here, not after the dataset download.
                experiment.prepare_branch_parent()
                experiment.print_branch_table()
            experiment.prepare_dataset()
            experiment.prepare_tokenizer()
            experiment.prepare_pretokenized()
        else:
            experiment.prepare_parent()
    elif args.command == "train":
        experiment.train(fresh=args.fresh, confirm_fresh=args.confirm_fresh)
    elif args.command == "eval":
        experiment.initialize()
        only_flags = [args.val_bpb_only, args.core_only, args.per_position_bpb_only]
        if sum(only_flags) > 1:
            parser.error("--val-bpb-only, --core-only and --per-position-bpb-only are mutually exclusive")
        if args.cross_dataset_config:
            if any(only_flags):
                parser.error("--cross-dataset-config cannot be combined with the *-only flags")
            experiment.evaluate_cross_dataset(
                args.cross_dataset_config,
                per_position_bpb=args.per_position_bpb,
            )
            return
        if args.core_only:
            eval_parts = {"core"}
        elif args.val_bpb_only or args.per_position_bpb_only:
            eval_parts = {"bpb"}
        else:
            eval_parts = {"core", "bpb"}
        experiment.evaluate(
            eval_parts=eval_parts,
            per_position_bpb=args.per_position_bpb or args.per_position_bpb_only,
        )
    elif args.command == "serve":
        experiment.initialize()
        experiment.serve(port=args.port)
    elif args.command == "chat":
        experiment.initialize()
        experiment.chat(port=args.port)
    elif args.command == "ratio-scout":
        try:
            steps = [int(value.strip()) for value in args.steps.split(",") if value.strip()]
        except ValueError as exc:
            parser.error(f"--steps must be comma-separated integers: {exc}")
        if not steps:
            parser.error("ratio-scout requires --steps")
        experiment.evaluate_ratio_scout(steps)
    elif args.command == "sync":
        experiment.initialize()
        experiment.build_summary()
        experiment.sync_metadata()
    elif args.command == "all":
        experiment.all(
            fresh=args.fresh,
            confirm_fresh=args.confirm_fresh,
        )


if __name__ == "__main__":
    main()
