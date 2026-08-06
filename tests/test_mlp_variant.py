"""Tests for the MLP variant switch (relu2 vs parameter-matched SwiGLU)."""

import pytest
import torch

from nanochat.gpt import GPT, GPTConfig, MLP, SwiGLUMLP, swiglu_hidden_dim


def make_config(**overrides):
    kwargs = dict(
        sequence_len=128, vocab_size=256, n_layer=2,
        n_head=2, n_kv_head=2, n_embd=768, window_pattern="L",
    )
    kwargs.update(overrides)
    return GPTConfig(**kwargs)


def mlp_params(model):
    return sum(p.numel() for block in model.transformer.h for p in block.mlp.parameters())


def test_relu2_is_the_default():
    model = GPT(make_config())
    assert all(isinstance(block.mlp, MLP) for block in model.transformer.h)


def test_swiglu_is_parameter_matched_at_d768():
    # 8 * 768 / 3 = 2048 exactly, so the match should be exact at the d12 width
    assert swiglu_hidden_dim(768) == 2048
    relu2 = GPT(make_config(mlp_variant="relu2"))
    swiglu = GPT(make_config(mlp_variant="swiglu"))
    assert all(isinstance(block.mlp, SwiGLUMLP) for block in swiglu.transformer.h)
    assert mlp_params(swiglu) == mlp_params(relu2)
    # and the whole model matches too, since only the MLP changed
    assert sum(p.numel() for p in swiglu.parameters()) == sum(p.numel() for p in relu2.parameters())


@pytest.mark.parametrize("n_embd", [512, 768, 1024, 1536, 2048])
def test_swiglu_parameter_count_stays_close(n_embd):
    """Rounding to a multiple of 128 keeps the match within a few percent at other widths."""
    hidden = swiglu_hidden_dim(n_embd)
    assert hidden % 128 == 0
    relative_error = abs(3 * hidden * n_embd - 8 * n_embd**2) / (8 * n_embd**2)
    assert relative_error < 0.05


def test_swiglu_forward_runs_and_starts_as_identity():
    config = make_config(mlp_variant="swiglu")
    model = GPT(config)
    model.init_weights()
    # c_proj is zero-initialised, so the block's MLP contributes nothing at step 0
    x = torch.randn(2, 16, config.n_embd)
    assert torch.equal(model.transformer.h[0].mlp(x), torch.zeros_like(x))


def test_unknown_mlp_variant_is_rejected():
    with pytest.raises(ValueError, match="mlp_variant"):
        GPT(make_config(mlp_variant="gelu"))
