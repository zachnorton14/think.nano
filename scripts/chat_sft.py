"""
Supervised fine-tuning (SFT) the model.
Run as:

python -m scripts.chat_sft

Or torchrun for training:

torchrun --standalone --nproc_per_node=8 -m scripts.chat_sft -- --device-batch-size=16
"""

import gc
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from importlib import import_module
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
import time
import wandb
import torch
from nanochat.common import compute_init, compute_cleanup, print0, DummyWandb, get_base_dir, autodetect_device_type, get_peak_flops, COMPUTE_DTYPE, COMPUTE_DTYPE_REASON, is_ddp_initialized
from nanochat.tokenizer import get_token_bytes
from nanochat.checkpoint_manager import (
    checkpoint_architecture,
    save_checkpoint,
    load_model,
    load_optimizer_state,
    load_model_from_checkpoint_dir,
    load_optimizer_from_checkpoint_dir,
)
from nanochat.loss_eval import evaluate_bpb
from nanochat.experiment_metrics import (
    compute_log_fields,
    configure_wandb_metrics,
    fixed_batch_stage_flops,
    update_wandb_compute_summary,
    update_wandb_lineage_summary,
)
import torch.distributed as dist
from nanochat.flash_attention import HAS_FA3
from nanochat.engine import Engine
from scripts.chat_eval import FINAL_NUMERIC_ANSWER_INSTRUCTION, run_chat_eval

from tasks.common import TaskMixture
from tasks.gsm8k import GSM8K
from tasks.mmlu import MMLU
from tasks.arc import ARC
from tasks.smoltalk import SmolTalk
from tasks.customjson import CustomJSON
_synth_pre1930 = import_module("tasks.synth-pre1930")
Pre1930Route = _synth_pre1930.Pre1930Route
PRE1930_ROUTES = _synth_pre1930.ROUTES
build_curriculum = _synth_pre1930.build_curriculum
from tasks.spellingbee import SimpleSpelling, SpellingBee

# -----------------------------------------------------------------------------
# CLI arguments
parser = argparse.ArgumentParser(description="Supervised fine-tuning (SFT) the model")
# Logging
parser.add_argument("--run", type=str, default="dummy", help="wandb run name ('dummy' disables wandb logging)")
parser.add_argument("--wandb-run-id", type=str, default="")
parser.add_argument("--wandb-group", type=str, default="")
parser.add_argument("--wandb-tags", type=str, default="")
# Runtime
parser.add_argument("--device-type", type=str, default="", help="cuda|cpu|mps (empty = autodetect)")
# Model loading
parser.add_argument("--model-tag", type=str, default=None, help="model tag to load from")
parser.add_argument("--model-step", type=int, default=None, help="model step to load from")
parser.add_argument("--base-checkpoint-dir", type=str, default=None)
parser.add_argument("--base-step", type=int, default=None)
parser.add_argument("--checkpoint-dir", type=str, default=None)
parser.add_argument("--tokenizer-dir", type=str, default=None)
parser.add_argument("--resume-from-step", type=int, default=None)
parser.add_argument("--experiment-id", type=str, default="")
parser.add_argument("--experiment-config", type=str, default="")
parser.add_argument("--parent-cumulative-flops", type=float, default=0.0)
parser.add_argument("--tokenizer-fingerprint", type=str, default="")
parser.add_argument("--git-commit-sha", type=str, default="")
parser.add_argument("--load-optimizer", type=int, default=1, help="warm-start optimizer from pretrained checkpoint (0=no, 1=yes)")
# Training horizon
parser.add_argument("--num-iterations", type=int, default=-1, help="number of optimization steps (-1 = full epoch)")
parser.add_argument("--num-epochs", type=int, default=1, help="number of passes for example-batched historical recipes")
parser.add_argument("--target-examples-per-step", type=int, default=0, help="effective conversations per optimizer step; required by karpathy-discussion8")
# Batch sizes (default: inherit from pretrained checkpoint)
parser.add_argument("--max-seq-len", type=int, default=None, help="max context length (default: inherit from pretrain)")
parser.add_argument("--device-batch-size", type=int, default=None, help="per-device batch size (default: inherit from pretrain)")
parser.add_argument("--total-batch-size", type=int, default=None, help="total batch size in tokens (default: inherit from pretrain)")
# Optimization (default: inherit from pretrained checkpoint)
parser.add_argument("--embedding-lr", type=float, default=None, help="learning rate for embedding parameters (Adam) (default: inherit from pretrain)")
parser.add_argument("--unembedding-lr", type=float, default=None, help="learning rate for unembedding parameters (Adam) (default: inherit from pretrain)")
parser.add_argument("--matrix-lr", type=float, default=None, help="learning rate for matrix parameters (Muon) (default: inherit from pretrain)")
parser.add_argument("--init-lr-frac", type=float, default=0.8, help="initial LR as fraction of base LR")
parser.add_argument("--warmup-ratio", type=float, default=0.0, help="ratio of iterations for LR warmup")
parser.add_argument("--warmdown-ratio", type=float, default=0.5, help="ratio of iterations for LR warmdown")
parser.add_argument("--final-lr-frac", type=float, default=0.0, help="final LR as fraction of initial LR")
# Evaluation
parser.add_argument("--eval-every", type=int, default=200, help="evaluate val bpb every N steps (-1 = disable)")
parser.add_argument("--eval-tokens", type=int, default=40*524288, help="number of tokens to evaluate val loss on")
parser.add_argument("--chatcore-every", type=int, default=200, help="evaluate ChatCORE metric every N steps (-1 = disable)")
parser.add_argument("--chatcore-max-cat", type=int, default=-1, help="max problems per categorical task for ChatCORE")
parser.add_argument("--chatcore-max-sample", type=int, default=32, help="max problems per generative task for ChatCORE")
parser.add_argument("--save-every", type=int, default=200)
# Data mixture
parser.add_argument("--recipe", type=str, default="nanochat-default", help="data recipe to use: nanochat-default | karpathy-discussion8 | pre1930 | pre1930-routes | curriculum")
parser.add_argument("--curriculum-config", type=str, default="", help="path to a curriculum spec JSON (recipe=curriculum); overridden by the experiment config's data.curriculum")
parser.add_argument("--pre1930-epochs", type=int, default=5, help="number of epochs of pre1930 data in training mixture")
parser.add_argument("--mmlu-epochs", type=int, default=3, help="number of epochs of MMLU in training mixture (teaches Multiple Choice)")
parser.add_argument("--gsm8k-epochs", type=int, default=4, help="number of epochs of GSM8K in training mixture (teaches Math and Tool Use)")
parser.add_argument(
    "--max-train-presentations",
    type=int,
    default=-1,
    help=(
        "deterministic cap on row presentations after constructing and shuffling "
        "the nanochat-default mixture (-1 = use the complete mixture)"
    ),
)
parser.add_argument("--authentic-epochs", type=int, default=0, help="epochs of the authentic pre1930 conversational set folded into the pre1930-routes mixture (0 = exclude)")
# per-route epochs for the "pre1930-routes" recipe (0 = route excluded from the mixture)
for _route in PRE1930_ROUTES:
    parser.add_argument(f"--{_route.replace('_', '-')}-epochs", type=int, default=0,
                        help=f"epochs of the {_route} route (pre1930-routes recipe)")
args = parser.parse_args()
user_config = vars(args).copy()
if args.experiment_config and os.path.exists(args.experiment_config):
    with open(args.experiment_config, "r", encoding="utf-8") as f:
        user_config["resolved_experiment_config"] = json.load(f)
    experiment = user_config["resolved_experiment_config"]
    user_config.update({
        "stage": "sft",
        "base_experiment_id": experiment.get("parent", {}).get("base_experiment_id"),
        "parent_experiment_id": experiment.get("parent", {}).get("base_experiment_id"),
        "parent_checkpoint_step": experiment.get("parent", {}).get("checkpoint_step"),
        "config_fingerprint": experiment.get("config_fingerprint"),
    })
    # let the experiment config's `data` section drive the run: recipe + per-task epochs
    # (e.g. {"recipe": "pre1930-routes", "stem_reasoning_epochs": 5}) map onto the args
    for _k, _v in experiment.get("data", {}).items():
        if hasattr(args, _k):
            setattr(args, _k, _v)
# -----------------------------------------------------------------------------

# Compute init
device_type = autodetect_device_type() if args.device_type == "" else args.device_type
ddp, ddp_rank, ddp_local_rank, ddp_world_size, device = compute_init(device_type)
master_process = ddp_rank == 0
print0(f"COMPUTE_DTYPE: {COMPUTE_DTYPE} ({COMPUTE_DTYPE_REASON})")
synchronize = torch.cuda.synchronize if device_type == "cuda" else lambda: None
get_max_memory = torch.cuda.max_memory_allocated if device_type == "cuda" else lambda: 0
if device_type == "cuda":
    gpu_device_name = torch.cuda.get_device_name(0)
    gpu_peak_flops = get_peak_flops(gpu_device_name)
    print0(f"GPU: {gpu_device_name} | Peak FLOPS (BF16): {gpu_peak_flops:.2e}")
else:
    gpu_peak_flops = float('inf')  # MFU not meaningful for CPU/MPS

# wandb logging init
use_dummy_wandb = args.run == "dummy" or not master_process
wandb_run = DummyWandb() if use_dummy_wandb else wandb.init(
    entity=os.environ.get("WANDB_ENTITY"),
    project=os.environ.get("WANDB_PROJECT", "think.nano"),
    name=args.run,
    id=args.wandb_run_id or None,
    resume="allow",
    group=args.wandb_group or None,
    tags=[tag for tag in args.wandb_tags.split(",") if tag],
    config=user_config,
)
if not use_dummy_wandb:
    configure_wandb_metrics(wandb_run)
    update_wandb_lineage_summary(
        wandb_run, user_config, args.experiment_id or args.run
    )

# Flash Attention status
if not HAS_FA3:
    print0("WARNING: Flash Attention 3 not available, using PyTorch SDPA fallback. Training will be less efficient.")

# Load either an SFT resume checkpoint or the exact base parent.
if args.resume_from_step is not None:
    if not args.checkpoint_dir:
        raise ValueError("--resume-from-step requires --checkpoint-dir")
    model, tokenizer, meta = load_model_from_checkpoint_dir(
        args.checkpoint_dir,
        device,
        phase="train",
        step=args.resume_from_step,
        tokenizer_dir=args.tokenizer_dir,
    )
elif args.base_checkpoint_dir:
    model, tokenizer, meta = load_model_from_checkpoint_dir(
        args.base_checkpoint_dir,
        device,
        phase="train",
        step=args.base_step,
        tokenizer_dir=args.tokenizer_dir,
    )
else:
    model, tokenizer, meta = load_model(
        "base", device, phase="train", model_tag=args.model_tag, step=args.model_step
    )

# Inherit training hyperparameters from pretrained checkpoint (None = inherit, explicit value = override)
pretrain_user_config = meta.get("user_config", {})
for name, fallback, source in [
    ("max_seq_len",       2048,  meta),
    ("device_batch_size", 32,    meta),
    ("total_batch_size",  524288, meta),
    ("embedding_lr",      0.3,   pretrain_user_config),
    ("unembedding_lr",    0.004, pretrain_user_config),
    ("matrix_lr",         0.02,  pretrain_user_config),
]:
    arg_val = getattr(args, name)
    pretrain_val = source.get(name)
    if arg_val is None:
        resolved = pretrain_val if pretrain_val is not None else fallback
        setattr(args, name, resolved)
        print0(f"Inherited {name}={resolved} from pretrained checkpoint")
    elif pretrain_val is not None and arg_val != pretrain_val:
        print0(f"NOTE: --{name.replace('_', '-')}={arg_val} overrides pretrained value of {pretrain_val}")
    else:
        print0(f"Using {name}={arg_val}")

orig_model = model
example_batched_recipe = args.recipe == "karpathy-discussion8"
# Karpathy's discussion #8 loader batches variable-length conversations. Keep
# that path eager, as the fixed-shape compile used by packed curricula would
# recompile for nearly every micro-batch shape.
model = orig_model if example_batched_recipe else torch.compile(model, dynamic=False)
depth = model.config.n_layer
num_flops_per_token = model.estimate_flops()
tokens_per_fwdbwd = args.device_batch_size * args.max_seq_len # tokens per iteration for a single rank
world_tokens_per_fwdbwd = tokens_per_fwdbwd * ddp_world_size # total tokens per iteration for all ranks
if example_batched_recipe:
    examples_per_micro = args.device_batch_size * ddp_world_size
    if args.target_examples_per_step <= 0:
        raise ValueError("karpathy-discussion8 requires --target-examples-per-step")
    if args.target_examples_per_step % examples_per_micro:
        raise ValueError(
            "target_examples_per_step must be divisible by device_batch_size * world_size"
        )
    grad_accum_steps = args.target_examples_per_step // examples_per_micro
    print0(
        f"Examples / micro-batch: {examples_per_micro}; target examples / step: "
        f"{args.target_examples_per_step} => gradient accumulation steps: {grad_accum_steps}"
    )
else:
    assert args.total_batch_size % world_tokens_per_fwdbwd == 0
    grad_accum_steps = args.total_batch_size // world_tokens_per_fwdbwd
    print0(f"Tokens / micro-batch / rank: {args.device_batch_size} x {args.max_seq_len} = {tokens_per_fwdbwd:,}")
    print0(f"Tokens / micro-batch: {world_tokens_per_fwdbwd:,}")
    print0(f"Total batch size {args.total_batch_size:,} => gradient accumulation steps: {grad_accum_steps}")
token_bytes = get_token_bytes(device=device)

# Initialize the Optimizer (combined MuonAdamW: Muon for matrix params, AdamW for rest)
# Note that pretraining ramps weight_decay to zero by end of pretraining, so SFT continues with zero
optimizer = model.setup_optimizer(unembedding_lr=args.unembedding_lr, embedding_lr=args.embedding_lr, matrix_lr=args.matrix_lr, weight_decay=0.0)

# Optionally warm-start optimizer from pretrained checkpoint (momentum buffers etc.)
# Note: load_state_dict overwrites param_group metadata (LRs, betas, etc.) with the
# pretrained values. Since pretraining warmdown brings LRs to ~0, we must save and
# restore our fresh SFT LRs after loading.
base_dir = get_base_dir()
if args.load_optimizer:
    if args.resume_from_step is not None:
        optimizer_data = load_optimizer_from_checkpoint_dir(
            args.checkpoint_dir, device, ddp_rank, args.resume_from_step
        )
    elif args.base_checkpoint_dir:
        optimizer_data = load_optimizer_from_checkpoint_dir(
            args.base_checkpoint_dir, device, ddp_rank, args.base_step
        )
    else:
        optimizer_data = load_optimizer_state(
            "base", device, rank=ddp_rank,
            model_tag=args.model_tag, step=args.model_step,
        )
    if optimizer_data is not None:
        base_lrs = [group["lr"] for group in optimizer.param_groups]
        optimizer.load_state_dict(optimizer_data)
        del optimizer_data
        for group, base_lr in zip(optimizer.param_groups, base_lrs):
            group["lr"] = base_lr
        print0("Loaded optimizer state from pretrained checkpoint (momentum buffers only, LRs reset)")
    else:
        print0("WARNING: optimizer checkpoint not found, starting with fresh optimizer (slightly worse)")

# GradScaler for fp16 training (bf16/fp32 don't need it)
scaler = torch.amp.GradScaler() if COMPUTE_DTYPE == torch.float16 else None
if scaler is not None:
    print0("GradScaler enabled for fp16 training")

# Override the initial learning rate as a fraction of the base learning rate
for group in optimizer.param_groups:
    group["lr"] = group["lr"] * args.init_lr_frac
    group["initial_lr"] = group["lr"]

# SFT data mixture and DataLoader
curriculum_bundle = None
karpathy_num_iterations = None
sft_mixture_summary = None
if args.recipe == "karpathy-discussion8":
    # Historical mixture from Karpathy's October 2025 d32 report (discussion #8):
    # ARC-Easy train + ARC-Challenge train + GSM8K train + 10,000 SmolTalk rows.
    train_dataset = TaskMixture([
        ARC(subset="ARC-Easy", split="train"),
        ARC(subset="ARC-Challenge", split="train"),
        GSM8K(subset="main", split="train"),
        SmolTalk(split="train", stop=10_000),
    ])
    val_dataset = SmolTalk(split="test")
    karpathy_num_iterations = (
        len(train_dataset) // args.target_examples_per_step
    ) * args.num_epochs
    if args.num_iterations > 0:
        karpathy_num_iterations = min(karpathy_num_iterations, args.num_iterations)
    print0(
        f"Karpathy discussion #8 mixture: {len(train_dataset):,} rows, "
        f"{args.num_epochs} epoch(s), {karpathy_num_iterations:,} reported iterations "
        f"({karpathy_num_iterations - 1:,} optimizer updates, matching the historical final-eval step)"
    )
elif args.recipe == "pre1930":
    AuthenticPre1930 = import_module("tasks.authentic-pre1930").AuthenticPre1930
    train_tasks = [AuthenticPre1930(split="train") for _ in range(args.pre1930_epochs)]
    train_dataset = TaskMixture(train_tasks)
    print0(f"Training mixture: {len(train_dataset):,} rows (pre1930 x{args.pre1930_epochs})")
    val_dataset = TaskMixture([AuthenticPre1930(split="test")])
elif args.recipe == "pre1930-routes":
    # per-route epochs from --<route>-epochs (or the config's data.<route>_epochs)
    route_epochs = {r: getattr(args, f"{r}_epochs") for r in PRE1930_ROUTES}
    active = {r: n for r, n in route_epochs.items() if n > 0}
    assert active, "pre1930-routes: set at least one <route>_epochs > 0 (e.g. stem_reasoning_epochs)"
    train_tasks = []
    for r, n in active.items():
        train_tasks += [Pre1930Route(route=r, split="train") for _ in range(n)]
    if args.authentic_epochs > 0:
        AuthenticPre1930 = import_module("tasks.authentic-pre1930").AuthenticPre1930
        train_tasks += [AuthenticPre1930(split="train") for _ in range(args.authentic_epochs)]
    train_dataset = TaskMixture(train_tasks)
    authentic_label = f", authentic x{args.authentic_epochs}" if args.authentic_epochs > 0 else ""
    print0(f"Training mixture: {len(train_dataset):,} rows (pre1930-routes {active}{authentic_label})")
    val_tasks = [Pre1930Route(route=r, split="test") for r in active]
    if args.authentic_epochs > 0:
        val_tasks.append(AuthenticPre1930(split="test"))
    val_dataset = TaskMixture(val_tasks)
elif args.recipe == "curriculum":
    # Grade-and-count aware mixture. The spec is embedded in the experiment config under
    # data.curriculum (preferred, so it rides in config.json and the fingerprint), or
    # passed via --curriculum-config as a standalone JSON file.
    spec = None
    resolved = user_config.get("resolved_experiment_config", {})
    if isinstance(resolved, dict):
        spec = resolved.get("data", {}).get("curriculum")
    if spec is None and args.curriculum_config:
        with open(args.curriculum_config, "r", encoding="utf-8") as f:
            spec = json.load(f)
    assert spec is not None, "recipe=curriculum needs data.curriculum in the experiment config or --curriculum-config"
    curriculum_bundle = build_curriculum(spec)
    train_dataset = curriculum_bundle.train
    val_dataset = curriculum_bundle.val
    print0(f"Curriculum {spec.get('name','?')} ({curriculum_bundle.summary['mode']}): "
           f"{len(train_dataset):,} train rows, {len(val_dataset):,} val rows")
    print0(f"Curriculum summary: {json.dumps(curriculum_bundle.summary)}")
else:
    identity_conversations_filepath = os.path.join(base_dir, "identity_conversations.jsonl")
    smoltalk_task = SmolTalk(split="train")
    identity_tasks = [
        CustomJSON(filepath=identity_conversations_filepath),
        CustomJSON(filepath=identity_conversations_filepath),
    ]
    mmlu_tasks = [
        MMLU(subset="all", split="auxiliary_train") for _ in range(args.mmlu_epochs)
    ]
    gsm8k_tasks = [
        GSM8K(subset="main", split="train") for _ in range(args.gsm8k_epochs)
    ]
    simple_spelling_task = SimpleSpelling(size=200000, split="train")
    spelling_bee_task = SpellingBee(size=80000, split="train")
    train_tasks = [
        smoltalk_task,                         # ~460K rows of general conversations
        *identity_tasks,                       # 1K rows x2
        *mmlu_tasks,                           # ~100K rows per configured epoch
        *gsm8k_tasks,                          # ~8K rows per configured epoch
        simple_spelling_task,                  # 200K generated spelling rows
        spelling_bee_task,                     # 80K generated character-count rows
    ]
    task_sources = (
        ["smoltalk"]
        + ["identity"] * len(identity_tasks)
        + ["mmlu"] * len(mmlu_tasks)
        + ["gsm8k"] * len(gsm8k_tasks)
        + ["simple_spelling", "spelling_bee"]
    )
    train_dataset = TaskMixture(train_tasks)
    full_mixture_rows = len(train_dataset)
    if args.max_train_presentations > 0:
        if args.max_train_presentations > full_mixture_rows:
            raise ValueError(
                f"max_train_presentations={args.max_train_presentations:,} exceeds "
                f"the nanochat-default mixture's {full_mixture_rows:,} rows"
            )
        # TaskMixture shuffles its complete index map deterministically before this
        # logical slice is applied, so the cap remains representative of every source
        # instead of taking a prefix from SmolTalk.
        train_dataset.stop = args.max_train_presentations

    selected_index_map = train_dataset.index_map[:len(train_dataset)]
    full_counts = Counter(task_sources[task_idx] for task_idx, _ in train_dataset.index_map)
    selected_counts = Counter(task_sources[task_idx] for task_idx, _ in selected_index_map)
    selected_task_counts = Counter(task_idx for task_idx, _ in selected_index_map)
    selected_unique_indices = defaultdict(set)
    selection_hash = hashlib.sha256()
    for task_idx, local_idx in selected_index_map:
        source = task_sources[task_idx]
        selected_unique_indices[source].add(local_idx)
        selection_hash.update(f"{task_idx}:{source}:{local_idx}\n".encode())

    def sha256_file(path):
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    word_list_hash = hashlib.sha256(
        ("\n".join(spelling_bee_task.words) + "\n").encode()
    ).hexdigest()
    source_specs = {
        "smoltalk": {
            "kind": "huggingface",
            "repo": "HuggingFaceTB/smol-smoltalk",
            "split": "train",
            "dataset_fingerprint": getattr(smoltalk_task.ds, "_fingerprint", None),
            "configured_repetitions": 1,
            "available_rows": len(smoltalk_task),
        },
        "identity": {
            "kind": "jsonl",
            "url": "https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl",
            "sha256": sha256_file(identity_conversations_filepath),
            "configured_repetitions": len(identity_tasks),
            "available_rows": len(identity_tasks[0]),
        },
        "mmlu": {
            "kind": "huggingface",
            "repo": "cais/mmlu",
            "subset": "all",
            "split": "auxiliary_train",
            "dataset_fingerprint": getattr(mmlu_tasks[0].ds, "_fingerprint", None),
            "configured_repetitions": len(mmlu_tasks),
            "available_rows": len(mmlu_tasks[0]),
        },
        "gsm8k": {
            "kind": "huggingface",
            "repo": "openai/gsm8k",
            "subset": "main",
            "split": "train",
            "dataset_fingerprint": getattr(gsm8k_tasks[0].ds, "_fingerprint", None),
            "configured_repetitions": len(gsm8k_tasks),
            "available_rows": len(gsm8k_tasks[0]),
        },
        "simple_spelling": {
            "kind": "deterministic_generated",
            "generator": "tasks.spellingbee.SimpleSpelling",
            "word_list_url": simple_spelling_task.WORD_LIST_URL if hasattr(simple_spelling_task, "WORD_LIST_URL") else None,
            "word_list_sha256": word_list_hash,
            "configured_repetitions": 1,
            "available_rows": len(simple_spelling_task),
        },
        "spelling_bee": {
            "kind": "deterministic_generated",
            "generator": "tasks.spellingbee.SpellingBee",
            "word_list_url": spelling_bee_task.WORD_LIST_URL if hasattr(spelling_bee_task, "WORD_LIST_URL") else None,
            "word_list_sha256": word_list_hash,
            "configured_repetitions": 1,
            "available_rows": len(spelling_bee_task),
        },
    }
    from huggingface_hub import HfApi
    hf_api = HfApi(token=os.environ.get("HF_TOKEN"))
    for spec in source_specs.values():
        if spec["kind"] == "huggingface":
            spec["resolved_revision"] = hf_api.repo_info(
                spec["repo"], repo_type="dataset"
            ).sha
    # WORD_LIST_URL is a module constant rather than a Task attribute in the upstream
    # implementation; retain the canonical URL in the manifest in either case.
    for source in ("simple_spelling", "spelling_bee"):
        source_specs[source]["word_list_url"] = (
            source_specs[source]["word_list_url"]
            or "https://raw.githubusercontent.com/dwyl/english-words/refs/heads/master/words_alpha.txt"
        )
    for source, spec in source_specs.items():
        selected = selected_counts[source]
        task_indices = [i for i, name in enumerate(task_sources) if name == source]
        spec.update({
            "full_mixture_presentations": full_counts[source],
            "selected_presentations": selected,
            "selected_presentations_by_replica": [
                selected_task_counts[i] for i in task_indices
            ],
            "selected_distinct_rows": len(selected_unique_indices[source]),
            "selected_fraction": selected / len(train_dataset),
        })
    sft_mixture_summary = {
        "schema_version": 1,
        "recipe": "nanochat-default",
        "selection": {
            "algorithm": "TaskMixture(seed=42) deterministic global shuffle then prefix",
            "selected_presentations": len(train_dataset),
            "full_mixture_presentations": full_mixture_rows,
            "selection_sha256": selection_hash.hexdigest(),
        },
        "sources": source_specs,
    }
    print0(
        f"Training mixture: {len(train_dataset):,} row presentations selected from "
        f"{full_mixture_rows:,} total (MMLU x{args.mmlu_epochs}, "
        f"GSM8K x{args.gsm8k_epochs})"
    )
    print0(f"SFT mixture manifest: {json.dumps(sft_mixture_summary, sort_keys=True)}")
    if not use_dummy_wandb:
        wandb_run.config.update(
            {"sft_mixture_summary": sft_mixture_summary}, allow_val_change=True
        )
    val_dataset = TaskMixture([
        SmolTalk(split="test"), # 24K rows in test set
        MMLU(subset="all", split="test", stop=5200), # 14K rows in test set, use only 5.2K to match the train ratios
        GSM8K(subset="main", split="test", stop=420), # 1.32K rows in test set, use only 420 to match the train ratios
    ]) # total: 24K + 5.2K + 0.42K ~= 29.6K rows
# DataLoader is defined here, it emits inputs, targets : 2D tensors of shape (device_batch_size, max_seq_len)
# A big problem is that we don't know the final num_iterations in advance. So we create
# these two global variables and update them from within the data generator.
last_step = False # we will toggle this to True when we reach the end of the training dataset
approx_progress = 0.0 # will go from 0 to 1 over the course of the epoch
current_epoch = 1 # track epoch for logging
def sft_data_generator_bos_bestfit(split, buffer_size=100, dataset=None):
    """
    BOS-aligned dataloader for SFT with bestfit-pad packing.

    Each row in the batch starts with BOS (beginning of a conversation).
    Conversations are packed using best-fit algorithm. When no conversation fits,
    the row is padded (instead of cropping) to ensure no tokens are ever discarded.
    Padding positions have targets masked with -1 (ignore_index for cross-entropy).

    `dataset` overrides the split's default dataset (used for per-route val eval);
    progress/last_step side effects only apply to the train split.
    """
    global last_step, approx_progress, current_epoch
    assert split in {"train", "val"}, "split must be 'train' or 'val'"
    if dataset is None:
        dataset = train_dataset if split == "train" else val_dataset
    dataset_size = len(dataset)
    assert dataset_size > 0
    row_capacity = args.max_seq_len + 1  # +1 for target at last position
    bos_token = tokenizer.get_bos_token_id()

    # Conversation buffer: list of (token_ids, loss_mask) tuples
    conv_buffer = []
    cursor = ddp_rank  # Each rank processes different conversations (for fetching)
    consumed = ddp_rank  # Track actual consumption separately from buffering
    epoch = 1
    it = 0  # iteration counter

    def refill_buffer():
        nonlocal cursor, epoch
        while len(conv_buffer) < buffer_size:
            conversation = dataset[cursor]
            ids, mask = tokenizer.render_conversation(conversation)
            conv_buffer.append((ids, mask))
            cursor += ddp_world_size
            if cursor >= dataset_size:
                cursor = cursor % dataset_size
                epoch += 1
                # Note: last_step is now triggered based on consumption, not fetching

    while True:
        rows = []
        mask_rows = []
        row_lengths = []  # Track actual content length (excluding padding) for each row
        for _ in range(args.device_batch_size):
            row = []
            mask_row = []
            padded = False
            while len(row) < row_capacity:
                # Ensure buffer has conversations
                while len(conv_buffer) < buffer_size:
                    refill_buffer()

                remaining = row_capacity - len(row)

                # Find largest conversation that fits entirely
                best_idx = -1
                best_len = 0
                for i, (conv, _) in enumerate(conv_buffer):
                    conv_len = len(conv)
                    if conv_len <= remaining and conv_len > best_len:
                        best_idx = i
                        best_len = conv_len

                if best_idx >= 0:
                    # Found a conversation that fits - use it entirely
                    conv, conv_mask = conv_buffer.pop(best_idx)
                    row.extend(conv)
                    mask_row.extend(conv_mask)
                    consumed += ddp_world_size  # Track actual consumption
                else:
                    # No conversation fits - pad the remainder instead of cropping
                    # This ensures we never discard any tokens
                    content_len = len(row)
                    row.extend([bos_token] * remaining)  # Pad with BOS tokens
                    mask_row.extend([0] * remaining)
                    padded = True
                    break  # Row is now full (with padding)

            # Track content length: full row if no padding, otherwise the length before padding
            if padded:
                row_lengths.append(content_len)
            else:
                row_lengths.append(row_capacity)
            rows.append(row[:row_capacity])
            mask_rows.append(mask_row[:row_capacity])

        # Stopping condition to respect num_iterations, if given
        it += 1
        if 0 < args.num_iterations <= it and split == "train":
            last_step = True

        # Update progress tracking (based on consumed, not cursor, to account for buffering)
        if split == "train":
            current_epoch = epoch
            if args.num_iterations > 0:
                approx_progress = it / args.num_iterations
            else:
                approx_progress = consumed / dataset_size
            # Trigger last_step when we've consumed enough (instead of when cursor wraps)
            if consumed >= dataset_size:
                last_step = True

        # Build tensors
        use_cuda = device_type == "cuda"
        batch_tensor = torch.tensor(rows, dtype=torch.long, pin_memory=use_cuda)
        inputs = batch_tensor[:, :-1].to(device=device, dtype=torch.int32, non_blocking=use_cuda).contiguous()
        targets = batch_tensor[:, 1:].to(device=device, dtype=torch.int64, non_blocking=use_cuda).contiguous()

        # Apply the loss mask from render_conversation (mask=1 for assistant completions,
        # mask=0 for user prompts, BOS, special tokens, tool outputs). mask[1:] aligns
        # with targets (shifted by 1). Unmasked positions get -1 (ignore_index).
        mask_tensor = torch.tensor(mask_rows, dtype=torch.int8)
        mask_targets = mask_tensor[:, 1:].to(device=device)
        targets[mask_targets == 0] = -1

        # Mask out padding positions in targets (set to -1 = ignore_index)
        # For each row, positions >= (content_length - 1) in targets should be masked
        for i, content_len in enumerate(row_lengths):
            if content_len < row_capacity:
                targets[i, content_len-1:] = -1

        yield inputs, targets


def sft_data_generator_examples(split, dataset=None):
    """Historical discussion #8 batching: one conversation per row, no packing."""
    global current_epoch
    assert split in {"train", "val"}
    if dataset is None:
        dataset = train_dataset if split == "train" else val_dataset
    pad_token = tokenizer.encode_special("<|assistant_end|>")
    cursor = ddp_rank
    epoch = 1
    while True:
        batch = []
        for _ in range(args.device_batch_size):
            conversation = dataset[cursor]
            ids, mask = tokenizer.render_conversation(conversation)
            if len(ids) > args.max_seq_len + 1:
                raise RuntimeError(
                    f"Karpathy SFT conversation has {len(ids)} tokens, exceeding "
                    f"the model limit of {args.max_seq_len + 1}"
                )
            batch.append((ids, mask))
            cursor += ddp_world_size
            if cursor >= len(dataset):
                cursor %= len(dataset)
                epoch += 1
        if split == "train":
            current_epoch = epoch
        ncols = max(len(ids) for ids, _ in batch) - 1
        inputs = torch.full(
            (len(batch), ncols), pad_token, dtype=torch.int32, device=device
        )
        targets = torch.full(
            (len(batch), ncols), -1, dtype=torch.int64, device=device
        )
        for row, (ids, mask) in enumerate(batch):
            ids_tensor = torch.tensor(ids, dtype=torch.int32, device=device)
            inputs[row, : len(ids) - 1] = ids_tensor[:-1]
            row_targets = ids_tensor[1:].to(torch.int64)
            mask_tensor = torch.tensor(mask[1:], dtype=torch.bool, device=device)
            row_targets[~mask_tensor] = -1
            targets[row, : len(ids) - 1] = row_targets
        yield inputs, targets


if example_batched_recipe:
    train_loader = sft_data_generator_examples("train")
    build_val_loader = lambda: sft_data_generator_examples("val")
else:
    train_loader = sft_data_generator_bos_bestfit("train")
    build_val_loader = lambda: sft_data_generator_bos_bestfit("val")
progress = 0 # will go from 0 to 1 over the course of the epoch

# Stratified per-route / per-domain val bpb, evaluated once at the final step for the
# curriculum recipe (feeds the cross-run ranking report).
per_route_bpb = {}
per_domain_bpb = {}
latest_chatcore = {}

def _eval_subset_bpb(task):
    """Val bpb over a single held-out Task (a route or domain slice), ~one pass."""
    import math as _math
    loader = sft_data_generator_bos_bestfit("val", dataset=task)
    tokens_per_step = args.device_batch_size * args.max_seq_len * ddp_world_size
    # enough steps to cover the (small) holdout roughly once
    subset_steps = max(1, _math.ceil(len(task) / (args.device_batch_size * ddp_world_size)))
    return float(evaluate_bpb(model, loader, subset_steps, token_bytes))

# Learning rate schedule (linear warmup, constant, linear warmdown)
# Same shape as base_train but uses progress (0→1) instead of absolute step counts,
# because SFT doesn't always know num_iterations in advance (dataset-driven stopping).
def get_lr_multiplier(progress):
    if progress < args.warmup_ratio:
        return (progress + 1e-8) / args.warmup_ratio
    elif progress <= 1.0 - args.warmdown_ratio:
        return 1.0
    else:
        decay = (progress - (1.0 - args.warmdown_ratio)) / args.warmdown_ratio
        return (1 - decay) * 1.0 + decay * args.final_lr_frac

# Momentum scheduler for Muon optimizer
def get_muon_momentum(it):
    frac = min(it / 300, 1)
    momentum = (1 - frac) * 0.85 + frac * 0.95
    return momentum

# -----------------------------------------------------------------------------
# Training loop
x, y = next(train_loader) # prefetch the very first batch of data
resume_loop = meta.get("loop_state", {}) if args.resume_from_step is not None else {}
min_val_bpb = float(resume_loop.get("min_val_bpb", float("inf")))
smooth_train_loss = float(resume_loop.get("smooth_train_loss", 0))
ema_beta = 0.9 # EMA decay factor
total_training_time = float(resume_loop.get("total_training_time", 0))
val_bpb = meta.get("val_bpb")
mfu = float(resume_loop.get("mfu", 0.0))
tok_per_sec = int(resume_loop.get("tok_per_sec", 0))
step = args.resume_from_step or 0
stage_training_tokens = int(resume_loop.get("stage_training_tokens", 0))
if not example_batched_recipe:
    stage_training_tokens = step * args.total_batch_size
if step:
    for _ in range(step * grad_accum_steps):
        x, y = next(train_loader)
    print0(f"Resumed SFT loop at optimizer step {step}")
while True:
    if example_batched_recipe:
        # The historical loop calls its final eval at iteration N-1 and exits before
        # another optimizer update. Preserve that behavior for a fair reproduction.
        last_step = step >= karpathy_num_iterations - 1
        progress = min(step / max(karpathy_num_iterations, 1), 1.0)
        stage_flops = stage_training_tokens * num_flops_per_token
    else:
        stage_training_tokens = step * args.total_batch_size
        stage_flops = fixed_batch_stage_flops(
            step, args.total_batch_size, num_flops_per_token
        )
    cumulative_flops = args.parent_cumulative_flops + stage_flops

    # Synchronize last_step across all ranks to avoid hangs in the distributed setting
    if ddp:
        last_step_tensor = torch.tensor(last_step, dtype=torch.int32, device=device)
        dist.all_reduce(last_step_tensor, op=dist.ReduceOp.MAX)
        last_step = bool(last_step_tensor.item())

    # once in a while: evaluate the val bpb (all ranks participate)
    if last_step or (args.eval_every > 0 and step % args.eval_every == 0):
        model.eval()
        val_loader = build_val_loader()
        if example_batched_recipe:
            # Karpathy's report used 100 held-out SmolTalk batches.
            eval_steps = 100
        else:
            eval_steps = args.eval_tokens // (args.device_batch_size * args.max_seq_len * ddp_world_size)
        val_bpb = evaluate_bpb(model, val_loader, eval_steps, token_bytes)
        print0(f"Step {step:05d} | Validation bpb: {val_bpb:.4f}")
        if val_bpb < min_val_bpb:
            min_val_bpb = val_bpb
        wandb_run.log({
            **compute_log_fields(
                step, stage_flops, args.parent_cumulative_flops
            ),
            "total_training_time": total_training_time,
            "val/bpb": val_bpb,
        })
        # Final step: per-route (and per-domain) stratified val bpb for the ranking report.
        if last_step and curriculum_bundle is not None:
            for _name, _task in curriculum_bundle.val_by_route.items():
                if len(_task) == 0:
                    continue
                per_route_bpb[_name] = _eval_subset_bpb(_task)
                print0(f"  val/bpb[{_name}]: {per_route_bpb[_name]:.4f}")
            if curriculum_bundle.summary.get("mode") == "domain_rebalanced":
                for _name, _task in curriculum_bundle.val_by_domain.items():
                    per_domain_bpb[_name] = _eval_subset_bpb(_task)
            wandb_run.log({
                **{f"val/bpb/{k}": v for k, v in per_route_bpb.items()},
                **{f"val/bpb/domain/{k}": v for k, v in per_domain_bpb.items()},
            })
        model.train()

    # once in a while: estimate the ChatCORE metric (all ranks participate)
    # use the original uncompiled model because the inputs keep changing shape
    chatcore_results = {}
    if args.chatcore_every > 0 and (last_step or (step > 0 and step % args.chatcore_every == 0)):
        try:
            model.eval()
            engine = Engine(orig_model, tokenizer)
            # HumanEval is intentionally excluded for the pre-1930 sweep. Keep the
            # categorical benchmarks complete and cap slow generative tasks.
            all_tasks = ['ARC-Easy', 'ARC-Challenge', 'MMLU', 'GSM8K', 'SpellingBee']
            categorical_tasks = {'ARC-Easy', 'ARC-Challenge', 'MMLU'}
            baseline_accuracies = {
                'ARC-Easy': 0.25, 'ARC-Challenge': 0.25, 'MMLU': 0.25,
                'GSM8K': 0.0, 'SpellingBee': 0.0,
            }
            task_results = {}
            for task_name in all_tasks:
                limit = args.chatcore_max_cat if task_name in categorical_tasks else args.chatcore_max_sample
                max_problems = None if limit < 0 else limit  # -1 means no limit
                acc = run_chat_eval(task_name, orig_model, tokenizer, engine,
                                    batch_size=args.device_batch_size, max_problems=max_problems)
                task_results[task_name] = acc
                print0(f"  {task_name}: {100*acc:.2f}%")
            # Compute ChatCORE metrics (mean centered accuracy, ranges from 0=random to 1=perfect)
            def centered_mean(tasks):
                return sum((task_results[t] - baseline_accuracies[t]) / (1.0 - baseline_accuracies[t]) for t in tasks) / len(tasks)
            chatcore = centered_mean(all_tasks)
            chatcore_cat = centered_mean(categorical_tasks)
            latest_chatcore = {"chatcore_metric": chatcore, "chatcore_cat": chatcore_cat,
                               "suite": {"tasks": all_tasks,
                                         "max_generative_problems": args.chatcore_max_sample,
                                         "generative_answer_format": FINAL_NUMERIC_ANSWER_INSTRUCTION},
                               **{task_name: acc for task_name, acc in task_results.items()}}
            print0(f"Step {step:05d} | ChatCORE: {chatcore:.4f} | ChatCORE_cat: {chatcore_cat:.4f}")
            wandb_run.log({
                **compute_log_fields(
                    step, stage_flops, args.parent_cumulative_flops
                ),
                "chatcore_metric": chatcore,
                "chatcore_cat": chatcore_cat,
                **{f"chatcore/{task_name}": acc for task_name, acc in task_results.items()},
            })
        except Exception as e:
            # An unattended curriculum sweep must not lose its checkpoint to a flaky ChatCORE
            # task (dataset fetch, evaluator failure, ...). Other recipes keep the old behavior.
            if curriculum_bundle is None:
                raise
            print0(f"WARNING: ChatCORE eval failed at step {step}, continuing without it: {type(e).__name__}: {e}")
        finally:
            model.train()

    should_save = last_step or (
        args.save_every > 0 and step > 0 and step % args.save_every == 0
    )
    if should_save:
        checkpoint_dir = args.checkpoint_dir
        if checkpoint_dir is None:
            output_dirname = args.model_tag if args.model_tag else f"d{depth}"
            checkpoint_dir = os.path.join(base_dir, "chatsft_checkpoints", output_dirname)
        save_checkpoint(
            checkpoint_dir,
            step,
            orig_model.state_dict(),
            optimizer.state_dict(),
            {
                "step": step,
                "training_complete": last_step,
                "model_architecture": checkpoint_architecture(
                    orig_model.state_dict(), meta
                ),
                "val_bpb": val_bpb, # loss at last step
                "total_batch_size": args.total_batch_size,
                "model_config": {
                    "sequence_len": args.max_seq_len,
                    "vocab_size": tokenizer.get_vocab_size(),
                    "n_layer": depth,
                    "n_head": model.config.n_head,
                    "n_kv_head": model.config.n_kv_head,
                    "n_embd": model.config.n_embd,
                    "window_pattern": model.config.window_pattern,
                },
                "user_config": user_config, # inputs to the training script
                "sft_mixture_summary": sft_mixture_summary,
                "loop_state": {
                    "step": step,
                    "total_training_time": total_training_time,
                    "min_val_bpb": min_val_bpb,
                    "smooth_train_loss": smooth_train_loss,
                    "mfu": mfu,
                    "tok_per_sec": tok_per_sec,
                    "stage_training_flops": stage_flops,
                    "stage_training_tokens": stage_training_tokens,
                    "inherited_parent_flops": args.parent_cumulative_flops,
                    "cumulative_pipeline_training_flops": cumulative_flops,
                },
            },
            rank=ddp_rank,
        )
        # Write a compact metrics file next to every completed SFT checkpoint so sweep
        # tooling can compare runs without depending on W&B. Curriculum runs add their
        # stratified validation breakdown; other recipes leave those fields empty.
        if last_step and master_process:
            metrics = {
                "experiment_id": args.experiment_id or args.run,
                "recipe": args.recipe,
                "step": step,
                "val_bpb": val_bpb,
                "min_val_bpb": min_val_bpb,
                "per_route_bpb": per_route_bpb,
                "per_domain_bpb": per_domain_bpb,
                "chatcore": latest_chatcore,
                "curriculum_summary": (
                    curriculum_bundle.summary if curriculum_bundle is not None else None
                ),
                "sft_mixture_summary": sft_mixture_summary,
            }
            with open(os.path.join(checkpoint_dir, "eval_metrics.json"), "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            print0(f"Wrote eval_metrics.json to {checkpoint_dir}")
            if sft_mixture_summary is not None:
                with open(os.path.join(checkpoint_dir, "mixture_manifest.json"), "w", encoding="utf-8") as f:
                    json.dump(sft_mixture_summary, f, indent=2, sort_keys=True)
                print0(f"Wrote mixture_manifest.json to {checkpoint_dir}")

    if last_step:
        break

    # -------------------------------------------------------------------------
    # single training step
    # evaluate the gradient
    synchronize()
    t0 = time.time()
    step_model_tokens = 0
    for micro_step in range(grad_accum_steps):
        if example_batched_recipe:
            step_model_tokens += x.numel() * ddp_world_size
        loss = model(x, y)
        train_loss = loss.detach() # for logging
        loss = loss / grad_accum_steps # each .backward() is a grad sum => normalize loss here
        if scaler is not None:
            scaler.scale(loss).backward()
        else:
            loss.backward()
        x, y = next(train_loader) # prefetch the next batch while the GPU is busy with forward/backward
        progress = max(progress, approx_progress) # only increase progress monotonically
    # step the optimizer
    lrm = get_lr_multiplier(progress)
    muon_momentum = get_muon_momentum(step)
    for group in optimizer.param_groups:
        group["lr"] = group["initial_lr"] * lrm
        if group['kind'] == 'muon':
            group["momentum"] = muon_momentum
    if scaler is not None:
        scaler.unscale_(optimizer)
        if is_ddp_initialized():
            for v in scaler._found_inf_per_device(optimizer).values():
                dist.all_reduce(v, op=dist.ReduceOp.MAX)
        scaler.step(optimizer)
        scaler.update()
    else:
        optimizer.step()
    model.zero_grad(set_to_none=True)
    synchronize()
    t1 = time.time()
    dt = t1 - t0
    # -------------------------------------------------------------------------

    # State
    step += 1
    if example_batched_recipe:
        stage_training_tokens += step_model_tokens
        stage_flops = stage_training_tokens * num_flops_per_token
    else:
        stage_training_tokens = step * args.total_batch_size
        stage_flops = fixed_batch_stage_flops(
            step, args.total_batch_size, num_flops_per_token
        )
    cumulative_flops = args.parent_cumulative_flops + stage_flops

    # logging
    smooth_train_loss = ema_beta * smooth_train_loss + (1 - ema_beta) * train_loss.item() # EMA the training loss
    debiased_smooth_loss = smooth_train_loss / (1 - ema_beta**(step + 1)) # debias the EMA
    pct_done = 100 * progress
    tokens_this_step = (
        step_model_tokens if example_batched_recipe else args.total_batch_size
    )
    tok_per_sec = int(tokens_this_step / dt)
    flops_per_sec = num_flops_per_token * tokens_this_step / dt
    mfu = 100 * flops_per_sec / (gpu_peak_flops * ddp_world_size)
    if step > 10:
        total_training_time += dt # only count the time after the first 10 steps
    print0(f"step {step:05d} ({pct_done:.2f}%) | loss: {debiased_smooth_loss:.6f} | lrm: {lrm:.2f} | dt: {dt * 1000:.2f}ms | tok/sec: {tok_per_sec:,} | mfu: {mfu:.2f} | epoch: {current_epoch} | total time: {total_training_time/60:.2f}m")
    if step % 10 == 0:
        wandb_run.log({
            **compute_log_fields(
                step, stage_flops, args.parent_cumulative_flops
            ),
            "total_training_time": total_training_time,
            "train/loss": debiased_smooth_loss,
            "train/lrm": lrm,
            "train/dt": dt,
            "train/tok_per_sec": tok_per_sec,
            "train/mfu": mfu,
            "train/epoch": current_epoch,
        })

    # The garbage collector spends ~500ms scanning for cycles quite frequently.
    # We manually manage it to avoid these pauses during training.
    if step == 1:
        gc.collect() # manually collect a lot of garbage from setup
        gc.freeze() # freeze all currently surviving objects and exclude them from GC
        gc.disable() # disable GC entirely except:
    elif step % 5000 == 0: # every 5000 steps...
        gc.collect() # manually collect, just to be safe for very long runs

# print a few more stats
print0(f"Peak memory usage: {get_max_memory() / 1024 / 1024:.2f}MiB")
print0(f"Total training time: {total_training_time/60:.2f}m")
print0(f"Minimum validation bpb: {min_val_bpb:.4f}")
if not use_dummy_wandb:
    final_compute = compute_log_fields(
        step, stage_flops, args.parent_cumulative_flops
    )
    update_wandb_compute_summary(wandb_run, final_compute)
    wandb_run.summary["final_val_bpb"] = val_bpb
    wandb_run.summary["min_val_bpb"] = min_val_bpb
    wandb_run.summary["training_time_seconds"] = total_training_time
    wandb_run.summary["final_mfu"] = mfu
    wandb_run.summary["final_tok_per_sec"] = tok_per_sec
    wandb_run.summary["stage_training_tokens"] = stage_training_tokens
    if sft_mixture_summary is not None:
        selection = sft_mixture_summary["selection"]
        wandb_run.summary["data/selected_presentations"] = selection["selected_presentations"]
        wandb_run.summary["data/full_mixture_presentations"] = selection["full_mixture_presentations"]
        wandb_run.summary["data/selection_sha256"] = selection["selection_sha256"]
        for source, values in sft_mixture_summary["sources"].items():
            wandb_run.summary[f"data/presentations/{source}"] = values["selected_presentations"]
            wandb_run.summary[f"data/distinct_rows/{source}"] = values["selected_distinct_rows"]

# Log to report
from nanochat.report import get_report
get_report().log(section="SFT", data=[
    user_config, # CLI args
    { # stats about the training setup
        "Number of iterations": step,
        "DDP world size": ddp_world_size,
    },
    { # stats about training outcomes
        "Minimum validation bpb": min_val_bpb,
    }
])

# cleanup
wandb_run.finish() # wandb run finish
compute_cleanup()
