"""
End-to-end: a mixture run branches off a single-source parent and picks up its schedule.

This drives the real scripts/base_train.py as a subprocess, on a tiny CPU model, through
the exact chain a d24 mix-og run performs against clean1930s-...-sssl-fulltok-v1:

  1. a single-source parent trains and checkpoints (the "v1" run)
  2. a mixture run branches off the parent's step-N checkpoint into its OWN checkpoint
     directory -- the parent's files are never written to
  3. the branch inherits the parent's weights and step numbering
  4. its mixture ledger starts at the parent's token count, so a schedule whose boundaries
     are absolute over the lineage puts the branch straight into the injection stage
     instead of replaying stage 0
  5. it crosses the next stage boundary on the step the schedule says
  6. resuming the branch mid-flight lands back in the right stage with the ledger intact

Scaled-down mirror of the real numbers: the branch step sits past the injection boundary
and before the decay boundary, exactly as step 6000 does at 8352 total.

Run: python -m pytest tests/test_branch_mixture_e2e.py -v
"""
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("tiktoken")

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tiny model / batch geometry. TOTAL_BATCH is 2 micro-batches of B*T at world_size 1.
DEPTH, HEAD_DIM, SEQ_LEN, DEVICE_BATCH = 4, 64, 64, 2
TOKENS_PER_MICROBATCH = DEVICE_BATCH * SEQ_LEN          # 128
TOTAL_BATCH = 2 * TOKENS_PER_MICROBATCH                 # 256, so grad_accum == 2

BRANCH_STEP = 6          # the "6000"
TOTAL_STEPS = 10         # the "8352"
INJECTION_AT = 5 * TOTAL_BATCH   # step 5: before the branch, so the branch starts inside it
DECAY_AT = 9 * TOTAL_BATCH       # step 9: crossed during the branch's own span

# Disjoint id ranges so a batch's tokens identify the source they came from.
SOURCE_RANGES = {"original": (0, 100), "midtrain_r30": (100, 200), "midtrain_r60": (200, 256)}


def _source_of_token(tok):
    for name, (low, high) in SOURCE_RANGES.items():
        if low <= tok < high:
            return name
    raise AssertionError(f"token {tok} belongs to no source")


# -----------------------------------------------------------------------------
# Fixtures on disk: a minimal byte-level tokenizer and uint16 token caches.


def _write_tokenizer(tokenizer_dir):
    """A byte-level tiktoken encoding, in the layout RustBPETokenizer.from_directory wants.

    256 single-byte ranks + the project's special tokens. Small enough to build instantly
    and wide enough to hold every id in the caches below.
    """
    import tiktoken
    from nanochat.tokenizer import SPECIAL_TOKENS

    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    mergeable_ranks = {bytes([i]): i for i in range(256)}
    special_tokens = {name: 256 + i for i, name in enumerate(SPECIAL_TOKENS)}
    enc = tiktoken.Encoding(
        name="e2e-bytes",
        pat_str=r".",
        mergeable_ranks=mergeable_ranks,
        special_tokens=special_tokens,
    )
    with open(tokenizer_dir / "tokenizer.pkl", "wb") as f:
        pickle.dump(enc, f)
    # token_bytes drives bits-per-byte; specials count as 0 (see scripts/tok_train.py).
    token_bytes = [1] * 256 + [0] * len(SPECIAL_TOKENS)
    with open(tokenizer_dir / "token_bytes.pt", "wb") as f:
        torch.save(torch.tensor(token_bytes, dtype=torch.int32), f)
    return 256 + len(SPECIAL_TOKENS)


def _write_cache(directory, source, num_tokens=20000):
    """A uint16 token cache whose ids all fall in `source`'s range."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    low, high = SOURCE_RANGES[source]
    span = high - low
    train = np.array([low + (i % span) for i in range(num_tokens)], dtype=np.uint16)
    val = np.array([low + (i % span) for i in range(512)], dtype=np.uint16)
    train.tofile(directory / "train_00000.bin")
    val.tofile(directory / "val_00000.bin")
    meta = {
        "dtype": "uint16",
        "train_tokens": int(len(train)),
        "val_tokens": int(len(val)),
        "train_files": [{"filename": "train_00000.bin", "num_tokens": int(len(train))}],
        "val_files": [{"filename": "val_00000.bin", "num_tokens": int(len(val))}],
    }
    (directory / "meta.json").write_text(json.dumps(meta))
    return str(directory)


def _mixture_config(path):
    """The branch's experiment config: boundaries are absolute over the whole lineage."""
    config = {
        "schema_version": 1,
        "stage": "base",
        "experiment_id": "e2e-mix-branch",
        "mixture_schedule": {
            "total_tokens": TOTAL_STEPS * TOTAL_BATCH,
            "seed_data": 1234,
            "max_epochs": 4,
            "stages": [
                {"name": "base", "start_tokens": 0, "source": "original"},
                {"name": "injection", "start_tokens": INJECTION_AT, "source": "midtrain_r30"},
                {"name": "decay_mix", "start_tokens": DECAY_AT, "source": "midtrain_r60"},
            ],
        },
        "training": {"total_batch_size": TOTAL_BATCH},
    }
    Path(path).write_text(json.dumps(config))
    return str(path)


# -----------------------------------------------------------------------------
# Driving the real training script.


def _run_base_train(base_dir, tokenizer_dir, checkpoint_dir, extra):
    env = os.environ.copy()
    env.update({
        "NANOCHAT_BASE_DIR": str(base_dir),
        # Inductor needs a C toolchain and is not what this test is about.
        "TORCHDYNAMO_DISABLE": "1",
        "PYTHONPATH": str(REPO_ROOT),
        "WANDB_MODE": "disabled",
        # The startup banner is not representable in the Windows console codepage.
        "PYTHONIOENCODING": "utf-8",
    })
    command = [
        sys.executable, "-u", "-m", "scripts.base_train",
        "--run=dummy",
        "--device-type=cpu",
        f"--depth={DEPTH}",
        f"--head-dim={HEAD_DIM}",
        "--window-pattern=L",
        f"--max-seq-len={SEQ_LEN}",
        f"--device-batch-size={DEVICE_BATCH}",
        f"--total-batch-size={TOTAL_BATCH}",
        "--eval-every=-1",
        "--core-metric-every=-1",
        "--sample-every=-1",
        "--pretokenized",
        f"--tokenizer-dir={tokenizer_dir}",
        f"--checkpoint-dir={checkpoint_dir}",
        *extra,
    ]
    result = subprocess.run(
        command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"base_train failed ({result.returncode})\n"
            f"--- args ---\n{' '.join(extra)}\n"
            f"--- stdout ---\n{result.stdout[-6000:]}\n"
            f"--- stderr ---\n{result.stderr[-6000:]}"
        )
    return result.stdout


STEP_LINE = re.compile(r"^step (\d+)/\d+ .*?\| mix_stage: (\w+)", re.MULTILINE)


def _stages_by_step(stdout):
    """{step: active mixture stage} as the training loop actually logged it."""
    return {int(step): stage for step, stage in STEP_LINE.findall(stdout)}


def _snapshot(directory):
    return {p.name: p.read_bytes() for p in sorted(Path(directory).iterdir()) if p.is_file()}


# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    """Train the parent, then branch a mixture run off it. Shared by the assertions."""
    root = tmp_path_factory.mktemp("branch_mixture_e2e")
    base_dir = root / "base"
    tokenizer_dir = root / "tokenizer"
    vocab_size = _write_tokenizer(tokenizer_dir)
    assert vocab_size >= max(high for _, high in SOURCE_RANGES.values())

    caches = {name: _write_cache(root / f"pretok_{name}", name) for name in SOURCE_RANGES}
    parent_dir = root / "parent_experiment" / "base_checkpoints"
    branch_dir = root / "branch_experiment" / "base_checkpoints"
    mixture_config = _mixture_config(root / "mix.json")

    # 1) The parent: a plain single-source run, exactly like the v1 d24.
    parent_stdout = _run_base_train(
        base_dir, tokenizer_dir, parent_dir,
        [
            f"--pretokenized-dir={caches['original']}",
            f"--num-iterations={BRANCH_STEP}",
            "--save-every=3",
            "--experiment-id=e2e-parent",
        ],
    )
    parent_before = _snapshot(parent_dir)

    # 2) The branch: its own checkpoint directory, the parent's weights and optimizer
    #    state, its own mixture data, and the parent's global LR schedule continued.
    branch_stdout = _run_base_train(
        base_dir, tokenizer_dir, branch_dir,
        [
            f"--init-from-checkpoint-dir={parent_dir}",
            f"--init-from-step={BRANCH_STEP}",
            "--branch-lr-schedule=continue",
            "--branch-parent-experiment-id=e2e-parent",
            f"--num-iterations={TOTAL_STEPS}",
            "--save-every=1",
            "--experiment-id=e2e-mix-branch",
            f"--experiment-config={mixture_config}",
            f"--mixture-source-dirs={json.dumps(caches)}",
        ],
    )

    # Snapshot the branch's final metadata now: the resume below re-runs the last steps
    # and overwrites their checkpoints, as a real restart would.
    branch_final_meta = json.loads(
        (branch_dir / f"meta_{TOTAL_STEPS:06d}.json").read_text()
    )

    # 3) Resume the branch from a mid-flight checkpoint, as a restarted box would.
    resume_stdout = _run_base_train(
        base_dir, tokenizer_dir, branch_dir,
        [
            f"--init-from-checkpoint-dir={parent_dir}",
            f"--init-from-step={BRANCH_STEP}",
            "--branch-lr-schedule=continue",
            "--branch-parent-experiment-id=e2e-parent",
            f"--num-iterations={TOTAL_STEPS}",
            "--save-every=1",
            "--experiment-id=e2e-mix-branch",
            f"--experiment-config={mixture_config}",
            f"--mixture-source-dirs={json.dumps(caches)}",
            f"--resume-from-step={TOTAL_STEPS - 2}",
        ],
    )

    return {
        "parent_dir": parent_dir,
        "branch_dir": branch_dir,
        "parent_before": parent_before,
        "parent_after": _snapshot(parent_dir),
        "branch_final_meta": branch_final_meta,
        "parent_stdout": parent_stdout,
        "branch_stdout": branch_stdout,
        "resume_stdout": resume_stdout,
        "caches": caches,
    }


def test_parent_run_checkpoints_normally(e2e):
    """The parent is an ordinary single-source run: no mixture state in its checkpoints."""
    assert (e2e["parent_dir"] / f"model_{BRANCH_STEP:06d}.pt").exists()
    assert (e2e["parent_dir"] / f"optim_{BRANCH_STEP:06d}_rank0.pt").exists()
    meta = json.loads((e2e["parent_dir"] / f"meta_{BRANCH_STEP:06d}.json").read_text())
    assert meta["step"] == BRANCH_STEP
    assert "mixture" not in meta["dataloader_state_dict"]
    assert "mix_stage" not in e2e["parent_stdout"]


def test_branch_never_writes_to_the_parent(e2e):
    """'Copy, don't modify': every parent file is byte-identical after the branch ran."""
    assert e2e["parent_before"], "parent produced no checkpoint files"
    assert e2e["parent_after"] == e2e["parent_before"]
    # And the branch's own checkpoints landed in its own tree.
    branch_files = {p.name for p in e2e["branch_dir"].iterdir()}
    assert f"model_{TOTAL_STEPS:06d}.pt" in branch_files


def test_branch_inherits_parent_weights_and_step_numbering(e2e):
    """Step numbering continues from the parent, and the weights are the parent's --
    a fresh init would be uncorrelated with them."""
    from nanochat.checkpoint_manager import load_checkpoint

    # It never restarts at step 1; its first own checkpoint is one step past the branch.
    steps = sorted(
        int(p.name.split("_")[1].split(".")[0]) for p in e2e["branch_dir"].glob("model_*.pt")
    )
    assert min(steps) == BRANCH_STEP + 1
    assert max(steps) == TOTAL_STEPS
    assert f"checkpoint step {BRANCH_STEP}" in e2e["branch_stdout"]

    device = torch.device("cpu")
    parent, _, _ = load_checkpoint(e2e["parent_dir"], BRANCH_STEP, device)
    child, _, meta = load_checkpoint(e2e["branch_dir"], BRANCH_STEP + 1, device)
    assert meta["parent_experiment_id"] == "e2e-parent"
    assert meta["parent_checkpoint_step"] == BRANCH_STEP
    assert meta["loop_state"]["stage_start_step"] == BRANCH_STEP

    key = "transformer.wte.weight"
    a = parent[key].float().flatten()
    b = child[key.removeprefix("_orig_mod.")].float().flatten()
    similarity = torch.nn.functional.cosine_similarity(a, b, dim=0).item()
    assert similarity > 0.9, (
        f"branch weights are only {similarity:.3f} similar to the parent's; they look "
        f"freshly initialized rather than inherited"
    )


def test_branch_enters_the_injection_stage_immediately(e2e):
    """THE regression this whole change exists for: the branch's ledger starts at the
    parent's token count, so a boundary already crossed by the parent is not replayed."""
    stages = _stages_by_step(e2e["branch_stdout"])
    assert stages, f"no mixture step lines logged:\n{e2e['branch_stdout'][-3000:]}"
    assert stages[BRANCH_STEP] == "injection", (
        f"branch started in stage {stages[BRANCH_STEP]!r}; it replayed the schedule from "
        f"the beginning instead of entering where the parent left off"
    )
    assert "original" not in stages.values()
    inherited = BRANCH_STEP * TOTAL_BATCH
    assert f"entering the schedule at {inherited:,} inherited tokens" in e2e["branch_stdout"]


def _expected_draw_sources():
    """Source of every micro-batch this branch draws, from the schedule alone.

    The loop prefetches one batch before the first step and one more per micro-step, so a
    span of N steps at grad_accum G issues 1 + N*G draws. Draw k reads at cumulative
    offset + k*B, and the stage is a pure function of that.
    """
    grad_accum = TOTAL_BATCH // TOKENS_PER_MICROBATCH
    offset = BRANCH_STEP * TOTAL_BATCH
    draws = 1 + (TOTAL_STEPS - BRANCH_STEP) * grad_accum
    sources = []
    for k in range(draws):
        cumulative = offset + k * TOKENS_PER_MICROBATCH
        sources.append(
            "midtrain_r60" if cumulative >= DECAY_AT else
            "midtrain_r30" if cumulative >= INJECTION_AT else "original"
        )
    return sources


def test_branch_crosses_the_next_boundary_on_schedule(e2e):
    """decay_mix data begins on exactly the step the absolute schedule names.

    NB: the logged mix_stage label leads the data by one draw. state_dict() reports the
    position of the *next* draw -- which is what resume needs -- and the loop prefetches
    that batch before printing. epoch/tok_file/pos in the single-source path lead the same
    way. So assert against the tokens actually drawn, not the label.
    """
    grad_accum = TOTAL_BATCH // TOKENS_PER_MICROBATCH
    sources = _expected_draw_sources()
    decay_step = DECAY_AT // TOTAL_BATCH
    # Draw index of the first micro-batch of the step where decay_mix should begin.
    first_decay_draw = (decay_step - BRANCH_STEP) * grad_accum
    assert sources[first_decay_draw - 1] == "midtrain_r30"
    assert sources[first_decay_draw] == "midtrain_r60"

    mixture = e2e["branch_final_meta"]["dataloader_state_dict"]["mixture"]
    for source in ("midtrain_r30", "midtrain_r60"):
        expected = sources.count(source) * TOKENS_PER_MICROBATCH
        assert mixture["source_tokens"][source] == expected, (
            f"{source} drew {mixture['source_tokens'][source]:,} tokens, schedule says "
            f"{expected:,}; the boundary landed on the wrong step"
        )

    # The label leads the data by exactly one draw, and never by more.
    stages = _stages_by_step(e2e["branch_stdout"])
    assert stages[decay_step] == "decay_mix"
    assert stages[decay_step - 1] == "decay_mix", "label should lead by one prefetch"
    assert stages[decay_step - 2] == "injection", "label leads by more than one prefetch"


def test_branch_trains_on_the_active_stages_data(e2e):
    """The ledger is not just a label: the tokens really come from the staged sources,
    and the source that stage 0 names is never drawn."""
    mixture = e2e["branch_final_meta"]["dataloader_state_dict"]["mixture"]
    assert mixture["source_tokens"]["original"] == 0
    assert mixture["source_tokens"]["midtrain_r30"] > 0
    assert mixture["source_tokens"]["midtrain_r60"] > 0
    # Every token the run drew is accounted for, on top of the parent's inherited count.
    drawn = sum(mixture["source_tokens"].values())
    assert drawn == len(_expected_draw_sources()) * TOKENS_PER_MICROBATCH
    assert mixture["cumulative_tokens"] == BRANCH_STEP * TOTAL_BATCH + drawn


def test_resuming_the_branch_keeps_its_place_in_the_schedule(e2e):
    """A restart mid-branch reloads the ledger rather than re-seeding it, so it neither
    replays stage 0 nor double-counts the parent's tokens."""
    resume_from = TOTAL_STEPS - 2
    assert f"Resuming optimization from step {resume_from}" in e2e["resume_stdout"]
    stages = _stages_by_step(e2e["resume_stdout"])
    decay_step = DECAY_AT // TOTAL_BATCH
    assert stages[decay_step] == "decay_mix"
    assert "original" not in stages.values()

    meta = json.loads((e2e["branch_dir"] / f"meta_{TOTAL_STEPS:06d}.json").read_text())
    mixture = meta["dataloader_state_dict"]["mixture"]
    drawn = sum(mixture["source_tokens"].values())
    assert mixture["cumulative_tokens"] == BRANCH_STEP * TOTAL_BATCH + drawn
    assert mixture["source_tokens"]["original"] == 0
