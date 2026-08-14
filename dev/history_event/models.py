"""Revision-pinned model registry and raw-completion scoring adapters."""

from __future__ import annotations

import base64
import gc
import json
import os
import subprocess
import sys
from pathlib import Path

from .bpb import (
    hf_target_tokens,
    metrics_from_logits,
    native_target_tokens,
    tiktoken_target_tokens,
)
from .config import REPO_ROOT


MODEL_SPECS = {
    "think-unbounded-d32-step9600": {
        "display_name": "Think.Unbounded-d32-v2mix-cont step 9600",
        "kind": "native",
        "repo_id": "jbduran/think.nano",
        "revision": "a7ff746d664c256eed78eb4cd2fde5d519443bcd",
        "checkpoint": "experiments/Think.Unbounded-d32-v2mix-cont/base_checkpoints/model_009600.pt",
        "metadata": "experiments/Think.Unbounded-d32-v2mix-cont/base_checkpoints/meta_009600.json",
        "tokenizer_dir": "experiments/Think.Unbounded-d32-v2mix-cont/tokenizer",
        "runtime": {
            "kind": "git",
            "url": "https://github.com/zachnorton14/think.nano.git",
            "revision": "40dd55cc291e41cf70bdb8b3df90f4bc32665d8d",
            "cache_name": "think-nano",
        },
        "cutoff_year": 1930,
    },
    "think-unbounded-d32-sft-c3-robust-v2": {
        "display_name": "Think.Unbounded d32 SFT C3 robust v2",
        "kind": "native",
        "repo_id": "jbduran/think.nano",
        "revision": "c5352cc09d914ae31c8301f6939970072accd014",
        "checkpoint": (
            "experiments/Think.Unbounded-d32-v2mix-cont/sft/"
            "Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2/"
            "checkpoints/model_000042.pt"
        ),
        "metadata": (
            "experiments/Think.Unbounded-d32-v2mix-cont/sft/"
            "Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2/"
            "checkpoints/meta_000042.json"
        ),
        "tokenizer_dir": "experiments/Think.Unbounded-d32-v2mix-cont/tokenizer",
        "runtime": {
            "kind": "git",
            "url": "https://github.com/zachnorton14/think.nano.git",
            "revision": "04bb043ad61d4db3e9022c422302df7b8f2dc0c9",
            "cache_name": "think-nano",
        },
        "cutoff_year": 1930,
    },
    "gpt1900-d34": {
        "display_name": "GPT-1900 base",
        "kind": "native",
        "repo_id": "mhla/gpt1900-d34-22btok",
        "revision": "d6330f9f0a17ce13da36fb951d7987bb03e6fbd0",
        "checkpoint": "model_010507.pt",
        "metadata": "meta_010507.json",
        "tokenizer_dir": "tokenizer",
        "runtime": {"kind": "bundled", "path": "."},
        "cutoff_year": 1900,
    },
    "gpt1900-sft": {
        "display_name": "GPT-1900 SFT",
        "kind": "native",
        "repo_id": "mhla/gpt1900-instruct-v3-sft",
        "revision": "346dddfe4aa82501fb17a5b4fd7d9bf678ebdca2",
        "checkpoint": "model_000075.pt",
        "metadata": "meta_000075.json",
        "tokenizer_dir": "tokenizer",
        "runtime": {
            "kind": "huggingface",
            "repo_id": "mhla/gpt1900-d34-22btok",
            "revision": "d6330f9f0a17ce13da36fb951d7987bb03e6fbd0",
            "path": ".",
        },
        "cutoff_year": 1900,
    },
    "llama-3.1-8b-instruct": {
        "display_name": "Llama-3.1-8B-Instruct",
        "kind": "huggingface",
        "repo_id": "meta-llama/Llama-3.1-8B-Instruct",
        "revision": "0e9e39f249a16976918f6564b8830bc894c89659",
        "cutoff_year": 2023,
    },
    "talkie-1930-13b-base": {
        "display_name": "Talkie 1930 base",
        "kind": "talkie",
        "repo_id": "talkie-lm/talkie-1930-13b-base",
        "revision": "b7c97680791f7fca4262c3c80b36ff7d666faab0",
        "checkpoint": "final.ckpt",
        "vocab": "vocab.txt",
        "style": "base",
        "runtime": {
            "kind": "git",
            "url": "https://github.com/talkie-lm/talkie.git",
            "revision": "35317ba3a84861a84c84065bd73faf88ad19329c",
            "cache_name": "talkie",
            "required_file": "src/talkie/model.py",
        },
        "cutoff_year": 1930,
    },
    "talkie-1930-13b-it": {
        "display_name": "Talkie 1930 IT",
        "kind": "talkie",
        "repo_id": "talkie-lm/talkie-1930-13b-it",
        "revision": "8033675be6360ae0127fa75f941c12d52064f1dc",
        "checkpoint": "rl-refined.pt",
        "vocab": "vocab.txt",
        "style": "it",
        "runtime": {
            "kind": "git",
            "url": "https://github.com/talkie-lm/talkie.git",
            "revision": "35317ba3a84861a84c84065bd73faf88ad19329c",
            "cache_name": "talkie",
            "required_file": "src/talkie/model.py",
        },
        "cutoff_year": 1930,
    },
}


def model_allow_patterns(spec: dict) -> list[str]:
    if spec["kind"] == "talkie":
        return [spec["checkpoint"], spec["vocab"]]
    if spec["kind"] != "native":
        return []
    patterns = [spec["checkpoint"], spec["metadata"], f"{spec['tokenizer_dir']}/**"]
    if spec["runtime"]["kind"] == "bundled":
        patterns.append("nanochat/**")
    return patterns


def resolve_snapshot(spec: dict, cache_dir: Path, token: str | None = None) -> Path:
    from huggingface_hub import snapshot_download

    kwargs = {
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "cache_dir": str(cache_dir / "huggingface"),
        "token": token,
    }
    patterns = model_allow_patterns(spec)
    if patterns:
        kwargs["allow_patterns"] = patterns
        kwargs["ignore_patterns"] = ["**/optim*.pt", "**/optimizer/**"]
    return Path(snapshot_download(**kwargs)).resolve()


def resolve_runtime(spec: dict, snapshot: Path, cache_dir: Path) -> Path:
    runtime = spec.get("runtime")
    if not runtime:
        return REPO_ROOT
    if runtime["kind"] == "bundled":
        path = (snapshot / runtime["path"]).resolve()
    elif runtime["kind"] == "git":
        cache_name = runtime.get("cache_name", "runtime")
        path = cache_dir / "runtimes" / f"{cache_name}-{runtime['revision']}"
        if not (path / ".git").exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--filter=blob:none", runtime["url"], str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "fetch", "origin", runtime["revision"], "--depth", "1"], check=True)
        subprocess.run(["git", "-C", str(path), "checkout", "--detach", runtime["revision"]], check=True)
        path = path.resolve()
    elif runtime["kind"] == "huggingface":
        from huggingface_hub import snapshot_download

        path = Path(snapshot_download(
            repo_id=runtime["repo_id"],
            revision=runtime["revision"],
            cache_dir=str(cache_dir / "huggingface"),
            allow_patterns=["nanochat/**"],
        ))
        path = (path / runtime["path"]).resolve()
    else:
        raise ValueError(f"unsupported runtime: {runtime}")
    required_file = runtime.get("required_file", "nanochat/gpt.py")
    if not (path / required_file).is_file():
        raise FileNotFoundError(f"runtime file {required_file} missing from {path}")
    return path


class NativeAdapter:
    def __init__(self, spec: dict, snapshot: Path, runtime: Path, device: str = "cuda"):
        import torch

        if not torch.cuda.is_available() and device == "cuda":
            raise RuntimeError("CUDA is required for native HISTORY-EVENT scoring")
        sys.path.insert(0, str(runtime))
        from nanochat.gpt import GPT, GPTConfig
        from nanochat.tokenizer import RustBPETokenizer

        metadata = json.loads((snapshot / spec["metadata"]).read_text(encoding="utf-8"))
        config = GPTConfig(**metadata["model_config"])
        active_device = torch.device(device)
        with torch.device("meta"):
            model = GPT(config)
        model.to_empty(device=active_device)
        model.init_weights()
        state = torch.load(snapshot / spec["checkpoint"], map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
            state = state["model"]
        elif isinstance(state, dict) and "model_state_dict" in state:
            state = state["model_state_dict"]
        state = {key.removeprefix("_orig_mod."): value for key, value in state.items()}
        model.load_state_dict(state, strict=True)
        model.to(dtype=torch.bfloat16)
        model.eval()
        self.model = model
        self.tokenizer = RustBPETokenizer.from_directory(snapshot / spec["tokenizer_dir"])
        self.device = active_device

    def score(self, prefix: str, target: str) -> dict:
        import torch

        tokens = native_target_tokens(self.tokenizer, prefix, target)
        ids = torch.tensor(tokens.input_ids, dtype=torch.long, device=self.device)
        with torch.inference_mode(), torch.autocast(device_type=self.device.type, dtype=torch.bfloat16):
            logits = self.model(ids[:-1].unsqueeze(0))
        result = metrics_from_logits(
            logits, ids[1:], tokens.target_mask, tokens.target_bytes
        )
        return {**result, "boundary_crossing": tokens.boundary_crossing}


def _talkie_full_logits(model, input_ids):
    """Evaluate every position; Talkie's public forward returns only the last."""
    import torch.nn.functional as functional

    _, sequence_length = input_ids.shape
    cos_sin = model.cos[:, :sequence_length], model.sin[:, :sequence_length]
    hidden = model.embed(input_ids)
    hidden = functional.rms_norm(hidden, (hidden.shape[-1],))
    embedded = hidden
    for block in model.blocks:
        hidden = block(embedded, hidden, cos_sin)
    hidden = functional.rms_norm(hidden, (hidden.shape[-1],))
    return functional.linear(hidden, model.lm_head_gain(model.lm_head)).float()


def _load_local_tiktoken_bpe(path: str | Path) -> dict[bytes, int]:
    """Read Talkie's local base64/rank vocabulary without blobfile."""
    ranks = {}
    for line_number, line in enumerate(Path(path).read_bytes().splitlines(), start=1):
        try:
            encoded_token, rank = line.split()
            ranks[base64.b64decode(encoded_token)] = int(rank)
        except Exception as exc:
            raise ValueError(f"invalid Talkie vocabulary line {line_number}") from exc
    return ranks


class TalkieAdapter:
    def __init__(self, spec: dict, snapshot: Path, runtime: Path, device: str = "cuda"):
        import torch

        if not torch.cuda.is_available() and device == "cuda":
            raise RuntimeError("CUDA is required for Talkie HISTORY-EVENT scoring")
        sys.path.insert(0, str(runtime / "src"))
        from talkie.model import GPTConfig, TalkieModel, resize_model_embeddings
        from talkie import tokenizer as talkie_tokenizer

        self.device = torch.device(device)
        talkie_tokenizer.load_tiktoken_bpe = _load_local_tiktoken_bpe
        self.tokenizer = talkie_tokenizer.build_tokenizer(
            snapshot / spec["vocab"], style=spec["style"]
        )
        self.bos_token_id = self.tokenizer.encode_single_token("<|endoftext|>")
        checkpoint_path = snapshot / spec["checkpoint"]
        try:
            checkpoint = torch.load(
                checkpoint_path, map_location="cpu", mmap=True, weights_only=True
            )
        except (RuntimeError, TypeError, ValueError):
            checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        if "model_state_dict" in checkpoint:
            state = checkpoint["model_state_dict"]
        elif "model" in checkpoint:
            state = checkpoint["model"]
        else:
            state = checkpoint
        state = {key.replace("_orig_mod.", ""): value for key, value in state.items()}
        config = GPTConfig(vocab_size=state["embed.weight"].shape[0])
        with torch.device("meta"):
            model = TalkieModel(config, torch.device("meta"))
        model.load_state_dict(state, strict=True, assign=True)
        if spec["style"] == "it" and config.vocab_size < talkie_tokenizer.IT_VOCAB_SIZE:
            model = resize_model_embeddings(model, talkie_tokenizer.IT_VOCAB_SIZE, "cpu")
        model._buffers["cos"] = None
        model._buffers["sin"] = None
        model = model.to(dtype=torch.bfloat16, device=self.device)
        model.device = self.device
        cos, sin = model._precompute_rotary_embeddings(4096, config.head_dim)
        model._buffers["cos"] = cos
        model._buffers["sin"] = sin
        model.eval()
        self.model = model
        del checkpoint, state
        gc.collect()

    def score(self, prefix: str, target: str) -> dict:
        import torch

        tokens = tiktoken_target_tokens(
            self.tokenizer, prefix, target, self.bos_token_id
        )
        ids = torch.tensor(tokens.input_ids, dtype=torch.long, device=self.device)
        with torch.inference_mode(), torch.autocast(
            device_type=self.device.type, dtype=torch.bfloat16
        ):
            logits = _talkie_full_logits(self.model, ids[:-1].unsqueeze(0))
        result = metrics_from_logits(
            logits, ids[1:], tokens.target_mask, tokens.target_bytes
        )
        return {**result, "boundary_crossing": tokens.boundary_crossing}


class HuggingFaceAdapter:
    def __init__(self, spec: dict, snapshot: Path, device: str = "cuda"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available() and device == "cuda":
            raise RuntimeError("CUDA is required for Llama HISTORY-EVENT scoring")
        self.device = torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot, use_fast=True)
        if not self.tokenizer.is_fast:
            raise RuntimeError("a fast tokenizer is required for exact target offsets")
        self.model = AutoModelForCausalLM.from_pretrained(
            snapshot, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
        ).to(self.device)
        self.model.eval()

    def score(self, prefix: str, target: str) -> dict:
        import torch

        tokens = hf_target_tokens(self.tokenizer, prefix, target)
        ids = torch.tensor(tokens.input_ids, dtype=torch.long, device=self.device)
        with torch.inference_mode(), torch.autocast(device_type=self.device.type, dtype=torch.bfloat16):
            logits = self.model(input_ids=ids[:-1].unsqueeze(0)).logits
        result = metrics_from_logits(
            logits, ids[1:], tokens.target_mask, tokens.target_bytes
        )
        return {**result, "boundary_crossing": tokens.boundary_crossing}


def load_adapter(model_id: str, cache_dir: Path, device: str = "cuda"):
    if model_id not in MODEL_SPECS:
        raise ValueError(f"unknown model {model_id!r}; choose from {sorted(MODEL_SPECS)}")
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        load_dotenv = lambda: None
    load_dotenv()
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    spec = MODEL_SPECS[model_id]
    snapshot = resolve_snapshot(spec, cache_dir, token)
    if spec["kind"] == "native":
        runtime = resolve_runtime(spec, snapshot, cache_dir)
        adapter = NativeAdapter(spec, snapshot, runtime, device=device)
    elif spec["kind"] == "talkie":
        runtime = resolve_runtime(spec, snapshot, cache_dir)
        adapter = TalkieAdapter(spec, snapshot, runtime, device=device)
    else:
        runtime = None
        adapter = HuggingFaceAdapter(spec, snapshot, device=device)
    provenance = {
        "model_id": model_id,
        "display_name": spec["display_name"],
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "checkpoint": spec.get("checkpoint"),
        "runtime_revision": (spec.get("runtime") or {}).get("revision"),
        "runtime_source": (
            (spec.get("runtime") or {}).get("repo_id")
            or (spec.get("runtime") or {}).get("url")
        ),
        "model_kind": spec["kind"],
        "style": spec.get("style"),
        "snapshot": str(snapshot),
        "runtime": str(runtime) if runtime else None,
        "cutoff_year": spec["cutoff_year"],
        "dtype": "bfloat16",
        "quantization": None,
        "chat_template": False,
    }
    return adapter, provenance
