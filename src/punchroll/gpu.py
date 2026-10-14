"""The graphics card, for the heaviest number-crunching, when PyTorch with CUDA is installed. Optional.

Nothing needs it: every step has the same computation on the CPU, which is what runs when there is no
card, no CUDA build of PyTorch, or PUNCHROLL_DEVICE=cpu in the environment. A CUDA build of PyTorch:

    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126

What runs on the card: the 4x oversampling behind every true-peak reading and the limiter, the pitch
tracker in the scorecard, and the trained listener (listen.py).
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def torch_cuda():
    """The torch module when a CUDA card can be used, otherwise None."""
    if os.environ.get("PUNCHROLL_DEVICE", "").lower() == "cpu":
        return None
    try:
        import torch
    except ImportError:
        return None
    return torch if torch.cuda.is_available() else None


@lru_cache(maxsize=1)
def _oversampler():
    """The filter scipy's resample_poly(x, 4, 1) uses, as a tensor on the card."""
    from scipy.signal import firwin
    torch = torch_cuda()
    h = firwin(81, 1 / 4, window=("kaiser", 5.0)) * 4
    return torch.tensor(h[::-1].copy(), dtype=torch.float32, device="cuda").view(1, 1, -1)


def true_abs_blocks(y: np.ndarray, block: int = 1 << 23, pad: int = 64):
    """As audio._true_abs_blocks, on the card: |y| 4x oversampled, the loudest of each sample's four, block by block.

    The filter reaches 10 samples either side, so each block computed with 64 samples of its neighbours gives
    exactly what the whole signal would, as on the CPU.
    """
    torch = torch_cuda()
    w = _oversampler()
    for a in range(0, len(y), block):
        lo, n = max(0, a - pad), min(block, len(y) - a)
        seg = torch.from_numpy(np.ascontiguousarray(y[lo:min(len(y), a + block + pad)], dtype=np.float32)).cuda()
        full = torch.nn.functional.conv_transpose1d(seg.view(1, 1, -1), w, stride=4).view(-1)
        up = full[40:40 + 4 * len(seg)].abs().view(-1, 4).amax(dim=1)
        yield a, up[a - lo:a - lo + n].cpu().numpy()


def yin_differences(frames: np.ndarray, n: int, tmax: int) -> np.ndarray:
    """As in measure.pitch: for each frame, the squared difference from itself shifted by each lag 1 to tmax."""
    torch = torch_cuda()
    f = torch.from_numpy(np.ascontiguousarray(frames, dtype=np.float64)).cuda()
    d = torch.empty((len(f), tmax + 1), dtype=torch.float64, device="cuda")
    d[:, 0] = 1.0
    head = f[:, :n]
    for tau in range(1, tmax + 1):
        d[:, tau] = ((head - f[:, tau:tau + n]) ** 2).sum(dim=1)
    return d.cpu().numpy()
