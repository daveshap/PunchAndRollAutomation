"""Spectrogram pictures of a passage, for looking at what a number can't show. Optional.

A picture shows the noise between words, a hum as a level line, mouth clicks as thin bright vertical
lines, breaths as a soft haze, echo as smear after a word ends, and what noise reduction took away
when the recording is set above the finished file. It needs matplotlib:

    pip install -e ".[pictures]"
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft


def spectrogram_png(panels, out, top_hz: float = 10000.0, floor_db: float = -120.0, ceiling_db: float = -30.0) -> None:
    """Write one PNG with a panel for each (title, samples, sample rate), all on one colour scale.

    Levels are dB relative to full scale for a sine in one frequency bin, so the same colour means the
    same level in every panel. Bring the panels to one loudness first if they are to be compared.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise RuntimeError('pictures need matplotlib: pip install -e ".[pictures]"') from e
    fig, axes = plt.subplots(len(panels), 1, figsize=(18, 4.8 * len(panels)), dpi=100, squeeze=False)
    im = None
    for ax, (title, x, sr) in zip(axes[:, 0], panels):
        n = 2048 if len(x) > 4 * sr else 512                  # a close-up gets finer time steps
        f, t, s = stft(np.asarray(x, dtype=np.float64), fs=sr, window="hann", nperseg=n, noverlap=n - n // 8)
        keep = f <= top_hz
        im = ax.pcolormesh(t, f[keep], 20 * np.log10(np.abs(s[keep]) * 2 + 1e-9), vmin=floor_db, vmax=ceiling_db,
                           cmap="magma", shading="auto")
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_ylabel("Hz")
    axes[-1, 0].set_xlabel("seconds")
    fig.colorbar(im, ax=axes, label="dB re full scale", fraction=0.02, pad=0.01)
    fig.savefig(str(out), bbox_inches="tight")
    plt.close(fig)


def passage(x: np.ndarray, sr: int, start_s: float, seconds: float) -> np.ndarray:
    return x[max(0, int(start_s * sr)):int((start_s + seconds) * sr)]


def match_loudness(x: np.ndarray, like: np.ndarray) -> np.ndarray:
    """x scaled to the RMS level of `like`, so two passages compare colour for colour."""
    a, b = float(np.mean(np.square(x, dtype=np.float64))), float(np.mean(np.square(like, dtype=np.float64)))
    return x * np.sqrt(b / a) if a > 0 and b > 0 else x
