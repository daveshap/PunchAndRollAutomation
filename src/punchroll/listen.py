"""A trained listener: an estimate of how clean a finished file sounds, ten seconds at a time. Optional.

Uses torchaudio's SQUIM objective model, which estimates PESQ (1 to 4.5, higher is cleaner) from the
audio alone. It needs PyTorch and torchaudio, which punchroll does not otherwise use:

    pip install -e ".[listen]"

The first use downloads the model (about 28 MB) from PyTorch's server. Its weights are under the
Creative Commons Attribution 4.0 licence.

Scores and the lowest-scoring window locations support passage inspection alongside the signal
measurements in docs/checking.md.
"""
from __future__ import annotations

import os

import numpy as np

_model = None


def available() -> bool:
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        return True
    except ImportError:
        return False


def pesq_estimate(x: np.ndarray, sr: int, window_s: float = 10.0, skip_s: float = 2.0) -> dict:
    """The model's PESQ estimate for each `window_s` of the file, leaving `skip_s` off each end.

    Returns the mean, the tenth-percentile window ("low"), and the three lowest windows as
    (start in seconds, estimate), which are places to look, not verdicts.
    """
    global _model
    try:
        import torch
        import torchaudio
    except ImportError as e:
        raise RuntimeError('the listener needs PyTorch and torchaudio: pip install -e ".[listen]"') from e
    if _model is None:
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
        _model = torchaudio.pipelines.SQUIM_OBJECTIVE.get_model().eval()
    y = torchaudio.functional.resample(torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32)), sr, 16000)
    n, skip, rows = int(window_s * 16000), int(skip_s * 16000), []
    with torch.no_grad():
        for s in range(skip, len(y) - skip - n + 1, n):
            rows.append((s / 16000, float(_model(y[s:s + n].unsqueeze(0))[1])))
    if not rows:
        return {"mean": None, "low": None, "lowest": []}
    p = np.array([r[1] for r in rows])
    return {"mean": float(p.mean()), "low": float(np.percentile(p, 10)), "lowest": sorted(rows, key=lambda r: r[1])[:3]}
