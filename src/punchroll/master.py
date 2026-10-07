"""Mastering to ACX specs: high-pass, gentle compression, a look-ahead limiter, and loudness.

Pure numpy/scipy, so nothing here adds a copyleft dependency.

ACX asks for -23 to -18 dB RMS, peaks no higher than -3 dB, and a noise floor
below -60 dB RMS. The limiter and the loudness search run in blocks, so memory
stays flat for long chapters.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter, uniform_filter1d
from scipy.signal import butter, istft, sosfilt, stft

from .audio import BLOCK, frame_db, noise_floor_db, rms_db, true_peak_db
from .config import MasterSettings


def _limit(y, gain, ceiling_db, sr, out=None, ms=6, block=1 << 20) -> float:
    """Apply gain then a look-ahead peak limiter; return the sum of squares of the result."""
    L = int(sr * ms / 1000)
    pad, ceiling, total = 3 * L, 10 ** (ceiling_db / 20), 0.0
    for a in range(0, len(y), block):
        lo, hi = max(0, a - pad), min(len(y), a + block + pad)
        z = y[lo:hi] * np.float32(gain)
        g = np.minimum(1.0, ceiling / (np.abs(z) + 1e-12)).astype(np.float32)
        g = uniform_filter1d(minimum_filter1d(g, size=2 * L + 1), size=L + 1)
        z = (z * g)[a - lo:a - lo + min(block, len(y) - a)]
        total += float(np.dot(z.astype(np.float64), z.astype(np.float64)))
        if out is not None:
            out[a:a + len(z)] = z
    return total


def _level(y, sr, ms: MasterSettings):
    gain = 1.0
    for _ in range(12):
        cur = 10 * np.log10(_limit(y, gain, ms.limiter_ceiling_db, sr) / max(1, len(y)) + 1e-24)
        err = ms.rms_db - cur
        if abs(err) < 0.05:
            break
        gain *= 10 ** (err / 20)
    out = np.empty_like(y)
    _limit(y, gain, ms.limiter_ceiling_db, sr, out=out)
    return out, gain


def highpass(y: np.ndarray, sr: int, hz: float, block=BLOCK) -> np.ndarray:
    """Second-order Butterworth high-pass (rumble, handling noise, plosive thumps)."""
    sos = butter(2, hz, btype="highpass", fs=sr, output="sos")
    zi = np.zeros((sos.shape[0], 2))
    out = np.empty(len(y), dtype=np.float32)
    for a in range(0, len(y), block):                        # filter state carries across blocks
        seg, zi = sosfilt(sos, y[a:a + block], zi=zi)
        out[a:a + len(seg)] = seg
    return out


def compress(y: np.ndarray, sr: int, threshold_db: float, ratio: float, attack_ms=10.0, release_ms=150.0,
             block=BLOCK) -> np.ndarray:
    """Gentle feed-forward compressor: RMS detector on 10 ms windows, hard knee, smoothed gain."""
    db, hop = frame_db(y, sr)
    over = np.maximum(0.0, db - threshold_db)
    target = -over * (1 - 1 / ratio)                         # gain change in dB per frame
    a_att = np.exp(-hop / (sr * attack_ms / 1000))
    a_rel = np.exp(-hop / (sr * release_ms / 1000))
    g, cur = np.empty_like(target), 0.0
    for i, t in enumerate(target):                           # 200 frames per second of audio
        a = a_att if t < cur else a_rel
        cur = a * cur + (1 - a) * t
        g[i] = cur
    centers = np.arange(len(g)) * hop + hop / 2
    out = np.empty(len(y), dtype=np.float32)
    for a in range(0, len(y), block):
        b = min(len(y), a + block)
        out[a:b] = y[a:b] * (10 ** (np.interp(np.arange(a, b), centers, g) / 20)).astype(np.float32)
    return out


def denoise(y: np.ndarray, sr: int, noise: np.ndarray, reduce: float = 0.6, n_std: float = 1.5,
            n_fft: int = 1024, hop: int = 256, chunk_s: float = 30.0) -> np.ndarray:
    """Stationary spectral gate: bins that don't rise above the room tone's level are turned down.

    Thresholds come from the room tone (mean + 1.5 standard deviations per frequency, in dB);
    the mask is smoothed over about 500 Hz and 50 ms and only reduces by `reduce`
    (0.6 = 60 %), so speech and breaths keep their natural texture.
    """
    kw = dict(fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    _, _, N = stft(noise.astype(np.float32), **kw)
    ndb = 20 * np.log10(np.abs(N) + 1e-10)
    thresh = (ndb.mean(axis=1) + n_std * ndb.std(axis=1))[:, None]
    fb, tb = max(1, round(500 / (sr / n_fft))), max(1, round(0.05 * sr / hop))
    out = np.empty_like(y)
    chunk, pad = int(chunk_s * sr), 4 * n_fft
    for a in range(0, len(y), chunk):
        lo, hi = max(0, a - pad), min(len(y), a + chunk + pad)
        _, _, S = stft(y[lo:hi], **kw)
        mask = uniform_filter((20 * np.log10(np.abs(S) + 1e-10) > thresh).astype(np.float32), size=(fb, tb))
        _, z = istft(S * (1 - reduce * (1 - mask)), **kw)
        n = min(chunk, len(y) - a)
        out[a:a + n] = z[a - lo:a - lo + n]
    return out


def master(y: np.ndarray, sr: int, ms: MasterSettings, room_tone: np.ndarray | None = None, log=print):
    pre = np.float32(10 ** ((-22 - rms_db(y)) / 20))

    def board(z):
        return compress(highpass(z, sr, ms.highpass_hz), sr, ms.compressor_threshold_db, ms.compressor_ratio)

    y *= pre                                   # in place: the caller hands over the edited audio
    z = board(y)
    del y
    out, gain = _level(z, sr, ms)
    del z
    nf = noise_floor_db(out, sr)
    if nf > ms.denoise_above_db and room_tone is not None and len(room_tone) > sr // 2:
        log(f"  noise floor {nf:.1f} dB is high; applying gentle noise reduction")
        noise = board(room_tone * pre) * np.float32(gain)
        out = denoise(out, sr, noise)
        out, g2 = _level(out, sr, ms)
        gain *= g2
    return out, acx_metrics(out, sr) | {"gain_db": round(20 * np.log10(gain * pre), 1)}


def acx_metrics(y: np.ndarray, sr: int) -> dict:
    rms, tp = rms_db(y), true_peak_db(y)
    peak = 20 * np.log10(max(float(y.max()), -float(y.min())) + 1e-12) if len(y) else -120.0
    nf = noise_floor_db(y, sr)
    return {"rms_db": round(rms, 1), "sample_peak_db": round(peak, 2), "true_peak_db": round(tp, 2),
            "noise_floor_db": round(nf, 1),
            "rms_ok": bool(-23 <= rms <= -18), "peak_ok": bool(peak < -3), "noise_ok": bool(nf < -60)}
