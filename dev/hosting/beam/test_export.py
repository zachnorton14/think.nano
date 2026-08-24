#!/usr/bin/env python3
"""
Proves the bf16 export is lossless, on CPU, in a few seconds, with no checkpoint.

The claim export_bf16.py makes is that casting rank >= 2 weights to bf16 changes
nothing, because `Linear.forward` already rounds them to the activation dtype on
every forward pass. This builds a tiny d4 model, saves it the way training does,
runs the export, and checks that the fp32 and bf16 checkpoints produce
*bit-identical* logits and *identical* greedy token streams.

It forces NANOCHAT_DTYPE=bfloat16 so CPU reproduces the CUDA compute dtype. That
matters: the equality only holds when COMPUTE_DTYPE is bf16, which is what a
post-Ampere serving GPU gives you.

    pytest dev/hosting/test_export.py -v
    python dev/hosting/test_export.py        # same checks, no pytest needed
"""

import os

# Must precede any nanochat import: COMPUTE_DTYPE is resolved at import time.
os.environ["NANOCHAT_DTYPE"] = "bfloat16"

import contextlib
import sys

import torch

# Walk up to the directory holding nanochat/ rather than counting ".." levels,
# so moving this folder does not break the import.
_path = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(_path, "nanochat")):
    _parent = os.path.dirname(_path)
    if _parent == _path:
        raise SystemExit("Could not find the nanochat package above this script")
    _path = _parent
sys.path.insert(0, _path)

import nanochat.engine as engine_module  # noqa: E402
from nanochat.common import COMPUTE_DTYPE  # noqa: E402
from nanochat.engine import Engine  # noqa: E402
from nanochat.gpt import GPT, GPTConfig  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_bf16 import cast_state_dict  # noqa: E402

# sequence_len 512 makes the short window (128) differ from the long one, so the
# sliding-window branch of the SDPA fallback is actually exercised.
CONFIG = GPTConfig(
    sequence_len=512, vocab_size=192, n_layer=4,
    n_head=2, n_kv_head=2, n_embd=128, window_pattern="SSSL",
)


@contextlib.contextmanager
def kv_cache_in_compute_dtype():
    """Work around engine.py picking the KV cache dtype from the device.

    `Engine.generate` hardcodes `bfloat16 if device.type == "cuda" else float32`
    (engine.py:217) rather than reading COMPUTE_DTYPE. In production that is the
    same thing. Here it is not: we are on CPU with COMPUTE_DTYPE forced to bf16,
    so the cache would be fp32 while the activations are bf16, and SDPA would
    reject the mismatch. Serving on CUDA never hits this.
    """
    original = engine_module.KVCache

    class ComputeDtypeKVCache(original):
        def __init__(self, *args, dtype=None, **kwargs):
            super().__init__(*args, dtype=COMPUTE_DTYPE, **kwargs)

    engine_module.KVCache = ComputeDtypeKVCache
    try:
        yield
    finally:
        engine_module.KVCache = original


class StubTokenizer:
    """Just enough of the tokenizer interface for Engine.generate.

    Engine looks up the tool-use specials through a try/except and disables the
    calculator path when they are missing, which is also what the real vintage
    tokenizer does -- so this stub exercises the same branch as production.
    """

    def get_bos_token_id(self):
        return 0

    def encode_special(self, text):
        raise KeyError(text)

    def decode(self, ids):
        return "".join(chr(97 + (i % 26)) for i in ids)

    def encode(self, text):
        return [ord(c) % 128 for c in text]


def build(state_dict):
    """Mirror checkpoint_manager.build_model: meta init, then assign the weights."""
    with torch.device("meta"):
        model = GPT(CONFIG)
    model.to_empty(device=torch.device("cpu"))
    model.init_weights()
    model.load_state_dict(state_dict, strict=True, assign=True)
    model.eval()
    return model


def reference_state_dict(seed=0):
    """A checkpoint shaped like a real one: fp32 matrices, bf16 embeddings.

    init_weights() casts wte and value_embeds to COMPUTE_DTYPE, so a real
    nanochat checkpoint already stores those two in bf16 and everything else in
    fp32. Reproducing that here keeps the test honest about what is left to cast.
    """
    torch.manual_seed(seed)
    with torch.device("meta"):
        model = GPT(CONFIG)
    model.to_empty(device=torch.device("cpu"))
    model.init_weights()
    return {k: v.detach().clone() for k, v in model.state_dict().items()}


def test_cast_targets_only_rank2_weights():
    fp32 = reference_state_dict()
    _, cast_keys, kept_keys = cast_state_dict(fp32)

    # Everything cast must be rank >= 2, everything kept must be rank < 2 or
    # already the target dtype. That split is the whole safety argument.
    assert cast_keys, "Nothing was cast -- the reference checkpoint is not fp32"
    for key in cast_keys:
        assert fp32[key].dim() >= 2, f"{key} is rank {fp32[key].dim()}, should not be cast"
    for key in kept_keys:
        assert fp32[key].dim() < 2 or fp32[key].dtype == torch.bfloat16, f"{key} should have been cast"

    # The per-layer scalars multiply the residual stream with no cast in
    # forward(), so they must survive at full precision.
    for name in ("resid_lambdas", "x0_lambdas", "smear_lambda", "backout_lambda"):
        assert name in kept_keys, f"{name} must stay fp32"
        assert fp32[name].dtype == torch.float32


def test_logits_are_bit_identical():
    fp32 = reference_state_dict()
    bf16, _, _ = cast_state_dict(fp32)

    idx = torch.randint(0, CONFIG.vocab_size, (2, 16))
    with torch.inference_mode():
        a = build(fp32).forward(idx)
        b = build(bf16).forward(idx)

    assert a.dtype == b.dtype
    assert torch.equal(a, b), (
        "bf16 export changed the logits; max abs diff "
        f"{(a - b).abs().max().item():.3e}"
    )


def test_kv_cache_generation_is_identical():
    """The serving path is Engine.generate, not model.forward -- check it too."""
    fp32 = reference_state_dict()
    bf16, _, _ = cast_state_dict(fp32)

    tokenizer = StubTokenizer()
    prompt = [0, 5, 9, 12, 30, 41]
    kwargs = dict(num_samples=1, max_tokens=24, temperature=0.0)

    def run(state_dict):
        engine = Engine(build(state_dict), tokenizer)
        return [column[0] for column, _ in engine.generate(prompt, **kwargs)]

    with kv_cache_in_compute_dtype():
        assert run(fp32) == run(bf16), "bf16 export changed the greedy token stream"


def test_fast_load_matches_build_model():
    """fast_load.load_model_fast must equal the build_model path, tensor for tensor.

    It skips to_empty() and init_weights(), so the risk is a parameter or buffer
    left on meta, or rotary tables that differ from the ones init_weights would
    have produced. Check every one.
    """
    import json
    import tempfile

    from fast_load import load_model_fast

    state = reference_state_dict()
    with tempfile.TemporaryDirectory() as tmpdir:
        torch.save(state, os.path.join(tmpdir, "model_000001.pt"))
        meta = {"step": 1, "model_config": {
            "sequence_len": CONFIG.sequence_len, "vocab_size": CONFIG.vocab_size,
            "n_layer": CONFIG.n_layer, "n_head": CONFIG.n_head,
            "n_kv_head": CONFIG.n_kv_head, "n_embd": CONFIG.n_embd,
            "window_pattern": CONFIG.window_pattern,
        }}
        with open(os.path.join(tmpdir, "meta_000001.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # get_tokenizer() would need a real tokenizer dir; the vocab-size check
        # is the only thing it feeds, and reference() covers the model itself.
        import fast_load as fast_load_module
        original = fast_load_module.get_tokenizer
        fast_load_module.get_tokenizer = lambda tokenizer_dir=None: _VocabStub(CONFIG.vocab_size)
        try:
            fast, _, _ = load_model_fast(tmpdir, torch.device("cpu"), step=1, verbose=False)
        finally:
            fast_load_module.get_tokenizer = original

    reference = build(state)

    ref_params = dict(reference.named_parameters())
    for name, param in fast.named_parameters():
        assert not param.is_meta, f"{name} left on meta"
        assert param.dtype == ref_params[name].dtype, f"{name} dtype differs"
        assert torch.equal(param, ref_params[name]), f"{name} differs"
    for name in ("cos", "sin"):
        a, b = getattr(fast, name), getattr(reference, name)
        assert not a.is_meta, f"{name} left on meta"
        assert a.dtype == b.dtype and torch.equal(a, b), f"{name} differs"

    idx = torch.randint(0, CONFIG.vocab_size, (1, 12))
    with torch.inference_mode():
        assert torch.equal(fast.forward(idx), reference.forward(idx))


class _VocabStub:
    def __init__(self, vocab_size):
        self._vocab_size = vocab_size

    def get_vocab_size(self):
        return self._vocab_size


def test_size_actually_shrinks():
    fp32 = reference_state_dict()
    bf16, _, _ = cast_state_dict(fp32)

    def nbytes(sd):
        return sum(t.numel() * t.element_size() for t in sd.values())

    assert nbytes(bf16) < nbytes(fp32)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")
    raise SystemExit(1 if failures else 0)
