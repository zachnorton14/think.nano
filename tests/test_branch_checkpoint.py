"""
Branching from another run's checkpoint: what actually carries over.

These exercise the handoff scripts/base_train.py performs when it is given
--init-from-checkpoint-dir/--init-from-step, on a tiny CPU model:

  - the parent's weights load into a freshly built model of the same shape
  - the parent's optimizer moments carry over
  - the *new* run's optimizer hyperparameters survive that load (torch's
    load_state_dict would otherwise restore the parent's learning rates)
  - a shape mismatch is refused instead of silently reshaping

Run: python -m pytest tests/test_branch_checkpoint.py -v
"""
import json

import pytest
import torch

from nanochat.checkpoint_manager import load_checkpoint, save_checkpoint
from nanochat.gpt import GPT, GPTConfig


DEVICE = torch.device("cpu")


@pytest.fixture(autouse=True)
def eager_optimizer():
    """The optimizer's fused steps are torch.compiled. Compilation is not what these
    tests are about, and Inductor needs a C toolchain, so run them eagerly."""
    import torch._dynamo as dynamo

    previous = dynamo.config.disable
    dynamo.config.disable = True
    try:
        yield
    finally:
        dynamo.config.disable = previous


def build(n_layer=2, n_embd=64, n_head=2, vocab_size=128, seed=0):
    torch.manual_seed(seed)
    config = GPTConfig(
        sequence_len=32, vocab_size=vocab_size, n_layer=n_layer,
        n_head=n_head, n_kv_head=n_head, n_embd=n_embd, window_pattern="L",
    )
    with torch.device("meta"):
        model = GPT(config)
    model.to_empty(device=DEVICE)
    model.init_weights()
    return model


def take_a_step(model, optimizer, seed=0):
    """One real optimizer step so the checkpoint carries non-trivial state."""
    torch.manual_seed(seed)
    x = torch.randint(0, model.config.vocab_size, (2, model.config.sequence_len))
    y = torch.randint(0, model.config.vocab_size, (2, model.config.sequence_len))
    model(x, y).backward()
    optimizer.step()
    model.zero_grad(set_to_none=True)


def write_parent_checkpoint(checkpoint_dir, step=1500, matrix_lr=0.02, **kwargs):
    model = build(**kwargs)
    optimizer = model.setup_optimizer(matrix_lr=matrix_lr, embedding_lr=0.3)
    take_a_step(model, optimizer)
    save_checkpoint(
        str(checkpoint_dir),
        step,
        model.state_dict(),
        optimizer.state_dict(),
        {
            "step": step,
            "model_config": {
                "sequence_len": model.config.sequence_len,
                "vocab_size": model.config.vocab_size,
                "n_layer": model.config.n_layer,
                "n_head": model.config.n_head,
                "n_kv_head": model.config.n_kv_head,
                "n_embd": model.config.n_embd,
                "window_pattern": model.config.window_pattern,
            },
            "loop_state": {
                "stage_start_step": 0,
                "stage_training_flops": 150.0,
                "inherited_parent_flops": 0.0,
                "cumulative_pipeline_training_flops": 150.0,
            },
        },
        rank=0,
    )
    return model, optimizer


def branch_from(checkpoint_dir, step, matrix_lr, embedding_lr, load_optimizer=True):
    """The sequence scripts/base_train.py runs for a branch."""
    model_data, optimizer_data, meta = load_checkpoint(
        str(checkpoint_dir), step, DEVICE, load_optimizer=load_optimizer, rank=0
    )
    child = build(
        n_layer=meta["model_config"]["n_layer"],
        n_embd=meta["model_config"]["n_embd"],
        n_head=meta["model_config"]["n_head"],
        vocab_size=meta["model_config"]["vocab_size"],
        seed=99,  # a different init, so a silent no-op load would be visible
    )
    model_data = {k.removeprefix("_orig_mod."): v for k, v in model_data.items()}
    child.load_state_dict(model_data, strict=True, assign=True)
    optimizer = child.setup_optimizer(matrix_lr=matrix_lr, embedding_lr=embedding_lr)
    if optimizer_data is not None:
        hyperparameters = [
            {key: value for key, value in group.items() if key != "params"}
            for group in optimizer.param_groups
        ]
        assert len(optimizer_data["param_groups"]) == len(hyperparameters)
        optimizer.load_state_dict(optimizer_data)
        for group, saved in zip(optimizer.param_groups, hyperparameters):
            group.update(saved)
    return child, optimizer, meta


def test_branch_loads_parent_weights(tmp_path):
    parent, _ = write_parent_checkpoint(tmp_path)
    child, _, meta = branch_from(tmp_path, 1500, matrix_lr=0.01, embedding_lr=0.1)
    assert meta["step"] == 1500
    parent_state = parent.state_dict()
    for name, tensor in child.state_dict().items():
        assert torch.equal(tensor, parent_state[name]), name


def test_branch_keeps_parent_optimizer_state_but_new_hyperparameters(tmp_path):
    _, parent_optimizer = write_parent_checkpoint(tmp_path, matrix_lr=0.02)
    _, optimizer, _ = branch_from(
        tmp_path, 1500, matrix_lr=0.005, embedding_lr=0.1,
    )

    # This run's learning rates, not the parent's.
    for group in optimizer.param_groups:
        if group["kind"] == "muon":
            assert group["lr"] == 0.005
            assert group["initial_lr"] == 0.005
    parent_muon = next(
        group for group in parent_optimizer.param_groups if group["kind"] == "muon"
    )
    assert parent_muon["lr"] == 0.02

    # The parent's momentum and second-moment buffers carried over.
    parent_state = parent_optimizer.state_dict()["state"]
    child_state = optimizer.state_dict()["state"]
    assert child_state and set(child_state) == set(parent_state)
    carried = 0
    for key, state in child_state.items():
        for name, value in state.items():
            if torch.is_tensor(value):
                assert torch.equal(value, parent_state[key][name]), (key, name)
                carried += 1
            else:
                assert value == parent_state[key][name], (key, name)
    assert carried, "expected optimizer moment tensors to carry over"


def test_branch_without_optimizer_state_starts_fresh(tmp_path):
    write_parent_checkpoint(tmp_path)
    _, optimizer, _ = branch_from(
        tmp_path, 1500, matrix_lr=0.005, embedding_lr=0.1, load_optimizer=False,
    )
    assert optimizer.state_dict()["state"] == {}


def test_branch_refuses_a_parent_of_a_different_shape(tmp_path):
    write_parent_checkpoint(tmp_path, n_embd=64)
    model_data, _, meta = load_checkpoint(str(tmp_path), 1500, DEVICE, rank=0)
    wider = build(n_embd=128, n_head=2)
    # base_train compares model_config first; a mismatch that slipped past it still
    # cannot load silently.
    assert meta["model_config"]["n_embd"] != wider.config.n_embd
    with pytest.raises(RuntimeError):
        wider.load_state_dict(model_data, strict=True, assign=True)


def test_parent_checkpoint_carries_the_flops_a_branch_inherits(tmp_path):
    write_parent_checkpoint(tmp_path)
    meta = json.loads((tmp_path / "meta_001500.json").read_text())
    assert meta["loop_state"]["cumulative_pipeline_training_flops"] == 150.0


# --------------------------------------------------------------------------------
# Which data position a branch starts from. base_train is a script, so this runs the
# decision straight out of its source rather than restating it here.


def dataloader_state_for(resuming, branching, lr_schedule):
    import types
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "scripts/base_train.py"
    ).read_text(encoding="utf-8")
    start = source.index("# Initialize the DataLoaders for train/val")
    end = source.index("# A mixture_schedule in the experiment config")
    namespace = {
        "print0": lambda *args, **kwargs: None,
        "resuming": resuming,
        "branching": branching,
        "args": types.SimpleNamespace(branch_lr_schedule=lr_schedule),
        "meta_data": {"dataloader_state_dict": "own-checkpoint-position"},
        "branch_meta": {"dataloader_state_dict": "parent-position"},
    }
    exec(source[start:end], namespace)
    return namespace["dataloader_resume_state_dict"]


def test_continue_branch_picks_up_the_parents_data_position():
    """A mixture branch that restarted its data would silently re-run stage 0 instead
    of the stage the parent had reached."""
    assert dataloader_state_for(False, True, "continue") == "parent-position"


def test_fresh_branch_starts_its_data_from_the_beginning():
    assert dataloader_state_for(False, True, "branch") is None


def test_a_run_resuming_itself_uses_its_own_position():
    for lr_schedule in ("branch", "continue"):
        assert dataloader_state_for(True, True, lr_schedule) == "own-checkpoint-position"
    assert dataloader_state_for(True, False, "branch") == "own-checkpoint-position"


def test_a_plain_run_is_unaffected():
    assert dataloader_state_for(False, False, "branch") is None
