"""The graphics card gives the same numbers as the CPU: the 4x oversampling behind true peak, and the pitch tracker."""
import numpy as np
import pytest
from scipy.signal import resample_poly

from punchroll import gpu, measure

SR = 44100
needs_card = pytest.mark.skipif(gpu.torch_cuda() is None, reason="no CUDA build of PyTorch, or no card")


def voice(seconds=30.0, pitch=128.0, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    turn = 2 * np.pi * pitch * (t + 0.04 / (2 * np.pi * 5) * np.sin(2 * np.pi * 5 * t))
    on = (t % 1.6) < 0.8
    return (0.2 * on * sum(np.sin(k * turn) / k for k in range(1, 15)) + rng.normal(0, 1e-3, len(t))).astype(np.float32)


@needs_card
def test_true_peak_on_the_card_matches_the_cpu():
    x = voice()
    x[SR * 5] = 0.95                                          # a spike, where the oversampling matters most
    cpu = np.abs(resample_poly(x.astype(np.float64), 4, 1)).reshape(-1, 4).max(axis=1)
    card = np.concatenate([m for _, m in gpu.true_abs_blocks(x, block=1 << 18)])
    assert len(card) == len(x)
    assert np.max(np.abs(card - cpu)) < 1e-5
    assert abs(20 * np.log10(card.max()) - 20 * np.log10(cpu.max())) < 1e-3


@needs_card
def test_pitch_on_the_card_matches_the_cpu(monkeypatch):
    x = voice(pitch=131.0)
    card = measure.pitch(x, SR)
    monkeypatch.setattr(gpu, "torch_cuda", lambda: None)
    cpu = measure.pitch(x, SR)
    assert card == pytest.approx(cpu, abs=1e-6) and abs(cpu - 131.0) < 2
