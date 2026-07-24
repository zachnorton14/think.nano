"""
Test the FP8 hardware capability guard.

Run: python -m pytest tests/test_fp8_guard.py -v

FP8 tensor cores only exist on SM 89+ (Ada/Hopper). Requesting FP8 on older
hardware (A100 = SM 80) used to blow up on the first training step inside
Inductor with ValueError("type fp8e4nv not supported in this architecture"),
so base_train downgrades to BF16 up front based on fp8_supported().
"""
import pytest
import torch

from nanochat.fp8 import fp8_supported


@pytest.fixture
def fake_cuda(monkeypatch):
    """Pretend CUDA is available with a given (capability, name)."""
    def _fake(capability, name):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.cuda, "get_device_capability", lambda idx=None: capability)
        monkeypatch.setattr(torch.cuda, "get_device_name", lambda idx=None: name)
    return _fake


@pytest.mark.parametrize("capability,name", [
    ((8, 0), "NVIDIA A100-SXM4-40GB"),  # Ampere: no FP8
    ((8, 6), "NVIDIA A10G"),            # Ampere: no FP8
    ((7, 5), "Tesla T4"),               # Turing: no FP8
])
def test_pre_ada_gpus_are_unsupported(fake_cuda, capability, name):
    fake_cuda(capability, name)
    supported, reason = fp8_supported("cuda")
    assert not supported
    assert name in reason and "SM 89+" in reason


@pytest.mark.parametrize("capability,name", [
    ((8, 9), "NVIDIA L40S"),        # Ada
    ((9, 0), "NVIDIA H100 80GB HBM3"),  # Hopper
])
def test_ada_and_hopper_are_supported(fake_cuda, capability, name):
    fake_cuda(capability, name)
    supported, _ = fp8_supported("cuda")
    assert supported


def test_non_cuda_device_is_unsupported(fake_cuda):
    fake_cuda((9, 0), "NVIDIA H100 80GB HBM3")  # CUDA present but not selected
    supported, reason = fp8_supported("cpu")
    assert not supported
    assert "cpu" in reason


def test_no_cuda_runtime_is_unsupported(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    supported, _ = fp8_supported("cuda")
    assert not supported
