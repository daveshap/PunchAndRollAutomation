"""Mastering to ACX specs: noise reduction where it is asked for or needed, high-pass, gentle
compression, a look-ahead limiter, and loudness.

Pure numpy/scipy, so nothing here adds a copyleft dependency.

ACX asks for -23 to -18 dB RMS, peaks no higher than -3 dB, and a noise floor
below -60 dB RMS. Every whole-file pass runs in blocks, so memory stays flat
for long chapters.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_erosion, binary_opening, minimum_filter1d, uniform_filter1d
from scipy.signal import butter, get_window, istft, sosfilt, stft

from .audio import BLOCK, frame_db, noise_floor_db, rms_db, true_abs, true_peak_db
from .config import MasterSettings


def _limit(y, mag, gain, ceiling_db, sr, out=None, ms=6, block=1 << 20) -> float:
    """Apply gain then a look-ahead peak limiter; return the sum of squares of the result.

    mag is |y| with its level between samples counted in (audio.true_abs), so the ceiling holds
    for the true peak and not only for the samples.
    """
    L = int(sr * ms / 1000)
    pad, ceiling, total = 3 * L, 10 ** (ceiling_db / 20), 0.0
    for a in range(0, len(y), block):
        lo, hi = max(0, a - pad), min(len(y), a + block + pad)
        z = y[lo:hi] * np.float32(gain)
        g = np.minimum(1.0, ceiling / (mag[lo:hi] * np.float32(gain) + 1e-12)).astype(np.float32)
        g = uniform_filter1d(minimum_filter1d(g, size=2 * L + 1), size=L + 1)
        z = (z * g)[a - lo:a - lo + min(block, len(y) - a)]
        total += float(np.dot(z.astype(np.float64), z.astype(np.float64)))
        if out is not None:
            out[a:a + len(z)] = z
    return total


def _level(y, sr, ms: MasterSettings):
    mag, gain = true_abs(y), 1.0
    for _ in range(12):
        cur = 10 * np.log10(_limit(y, mag, gain, ms.limiter_ceiling_db, sr) / max(1, len(y)) + 1e-24)
        err = ms.rms_db - cur
        if abs(err) < 0.05:
            break
        gain *= 10 ** (err / 20)
    out = np.empty_like(y)
    _limit(y, mag, gain, ms.limiter_ceiling_db, sr, out=out)
    over = true_peak_db(out) - ms.limiter_ceiling_db
    if over > 0.02:                                    # the limiter's gain moves a little between samples too
        out *= np.float32(10 ** (-over / 20))
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


def _nr_window(sr: int) -> int:
    """Samples per window for noise reduction: 2048 at 44.1 and 48 kHz, in step with other sample rates."""
    return 1 << int(round(np.log2(2048 * sr / 44100)))


def noise_profile(y: np.ndarray, sr: int) -> np.ndarray | None:
    """The noise sample: average power in each frequency band over the quieter half of the recording's pauses.

    A pause is a stretch where the level from 200 to 4000 Hz stays within 25 dB of the quietest twentieth
    of the recording (and 20 dB or more under the voice), counted from a quarter second after the last
    louder sound to a quarter second before the next. Of those windows the quieter half is averaged, which
    leaves out thumps and the fuller breaths.

    The sample is taken from the pauses as a whole and not from their single quietest moment, because a
    pause holds more than the room: faint mouth sounds, the low end of a breath. With only the room's hiss
    in the sample those are left standing in a pause that is otherwise 20 dB quieter, and the leftover
    crackles. Returns None when the pauses come to under half a second, or the quiet isn't 20 dB below
    the voice: a recording with no pauses in it has nothing to take a sample from.
    """
    n = _nr_window(sr)
    hop = n // 4
    count = (len(y) - n) // hop + 1 if len(y) >= n else 0
    if count * hop < sr:
        return None
    win = get_window("hann", n).astype(np.float32)
    f = np.fft.rfftfreq(n, 1 / sr)
    voice = (f >= 200) & (f < 4000)
    windows = np.lib.stride_tricks.sliding_window_view(y, n)[::hop]      # a view: nothing is copied until it is read

    def power(rows):
        return np.abs(np.fft.rfft(windows[rows] * win, axis=1)) ** 2

    level, total = np.empty(count, np.float32), np.empty(count, np.float32)
    for a in range(0, count, 2048):
        P = power(slice(a, a + 2048))
        level[a:a + len(P)], total[a:a + len(P)] = P[:, voice].sum(axis=1), P.sum(axis=1)
    level = 10 * np.log10(level / win.sum() ** 2 + 1e-30)
    live = level > -130                                                  # digital silence is not room tone
    if live.sum() * hop < sr // 2:
        return None
    floor, top = np.percentile(level[live], [5, 95])
    if top - floor < 20:
        return None
    clear = max(2, int(0.25 * sr / hop))                                 # windows in a quarter second
    quiet = binary_opening(live & (level < max(floor + 6, min(floor + 25, top - 20))), np.ones(clear, bool))
    rows = np.flatnonzero(binary_erosion(quiet, np.ones(2 * clear + 1, bool)))
    if len(rows) * hop < sr // 2:
        return None
    rows = np.sort(rows[np.argsort(total[rows])[:len(rows) // 2]])
    rows = rows[::max(1, len(rows) // 20000)]                            # four minutes of pauses is plenty
    mean = np.zeros(n // 2 + 1)
    for a in range(0, len(rows), 2048):
        mean += power(rows[a:a + 2048]).sum(axis=0)
    return (mean / len(rows) / win.sum() ** 2).astype(np.float32)        # on the scale scipy's stft uses


def _noise_gains(P, profile, sr, hop, reduce_db, sensitivity, smoothing, first, attack=0.02, release=0.10):
    """Gain for each window (down) and band (across) of the power spectra P, by the rules of Audacity's Noise Reduction.

    A band holds only noise at some moment unless the second loudest of five neighbouring windows is more
    than sensitivity x ln(10) times the noise's average there (11 dB over it at 6, which noise alone reaches
    about one time in a million). Noise is turned down by reduce_db. The turning down fades in over `release`
    seconds after a sound and lifts `attack` seconds ahead of one, and each band's gain is then averaged, in
    decibels, with `smoothing` bands on either side.

    One departure from Audacity: bands below `first` take no part in that averaging. The high-pass removes
    them anyway, and being empty they would pull the lowest note of the voice down with them.
    """
    count, bands = P.shape
    pad = np.pad(P, ((2, 2), (0, 0)), mode="edge")
    top, second = np.maximum(pad[:count], pad[1:count + 1]), np.minimum(pad[:count], pad[1:count + 1])
    for i in (2, 3, 4):                                    # the two loudest of each window and its four neighbours
        np.maximum(second, np.minimum(top, pad[i:i + count]), out=second)
        np.maximum(top, pad[i:i + count], out=top)
    low = 10 ** (-reduce_db / 20)
    G = np.where(second <= sensitivity * np.log(10) * profile, np.float32(low), np.float32(1))
    fade = np.float32(low ** (1 / (1 + int(release * sr / hop))))
    lift = np.float32(low ** (1 / (1 + int(attack * sr / hop))))
    for i in range(1, count):
        np.maximum(G[i], G[i - 1] * fade, out=G[i])
    for i in range(count - 2, -1, -1):
        np.maximum(G[i], G[i + 1] * lift, out=G[i])
    if smoothing > 0 and first < bands:
        width = 2 * smoothing + 1                          # a window that runs off either end averages what it has
        share = uniform_filter1d(np.ones(bands - first, np.float32), width, mode="constant")
        G[:, first:] = np.exp(uniform_filter1d(np.log(G[:, first:]), width, axis=1, mode="constant") / share)
    return G


def reduce_noise(y: np.ndarray, sr: int, profile: np.ndarray, reduce_db: float = 12.0, sensitivity: float = 6.0,
                 smoothing: int = 3, highpass_hz: float = 70.0, chunk_s: float = 30.0) -> np.ndarray:
    """Turn the room's noise down by reduce_db through the whole recording, pauses and speech alike. In place.

    The recording is split into overlapping windows and each window into frequency bands; a band is turned
    down wherever it holds nothing more than the noise in `profile` (see noise_profile and _noise_gains).
    The one rule runs from the first sample to the last. A hum pitched inside the voice's range passes
    while the voice is sounding there, covered by it, and is down by the full amount in every pause.
    """
    n = _nr_window(sr)
    if len(y) < n or reduce_db <= 0:
        return y
    hop = n // 4
    kw = dict(fs=sr, window="hann", nperseg=n, noverlap=n - hop)
    first = int(np.ceil(max(0.0, highpass_hz) * n / sr))
    chunk, pad = max(1, int(chunk_s * sr) // hop) * hop, 32 * hop
    before = y[:0]
    for a in range(0, len(y), chunk):
        own = y[a:a + chunk].copy()                       # as recorded: the next chunk needs its end for context
        _, _, S = stft(np.concatenate([before, own, y[a + chunk:a + chunk + pad]]), **kw)
        G = _noise_gains(np.ascontiguousarray((np.abs(S) ** 2).T), profile, sr, hop, reduce_db, sensitivity,
                         int(smoothing), first)
        _, z = istft(S * G.T, **kw)
        y[a:a + len(own)] = z[len(before):len(before) + len(own)]
        before = np.concatenate([before, own])[-pad:]
    return y


def master(y: np.ndarray, sr: int, ms: MasterSettings, log=print):
    pre = np.float32(10 ** ((-22 - rms_db(y)) / 20))

    def board(z):
        return compress(highpass(z, sr, ms.highpass_hz), sr, ms.compressor_threshold_db, ms.compressor_ratio)

    def quieten(z) -> float:
        profile = noise_profile(z, sr)
        if profile is None:
            log("  noise reduction skipped: no quiet stretch to take a sample of the room's noise from")
            return 0.0
        reduce_noise(z, sr, profile, ms.noise_reduction_db, ms.noise_sensitivity, ms.noise_smoothing, ms.highpass_hz)
        return float(ms.noise_reduction_db)

    y *= pre                                   # in place: the caller hands over the edited audio
    mode = ms.noise_reduction if ms.noise_reduction_db > 0 else "off"
    reduced = 0.0
    if mode == "on":                           # ahead of the compressor, which would lift the noise in every pause
        log(f"  turning the room's noise down by {ms.noise_reduction_db:g} dB")
        reduced = quieten(y)
    z = board(y)
    if mode == "auto":
        floor = noise_floor_db(z, sr) + ms.rms_db - rms_db(z)      # where the noise floor will sit once the level is set
        if floor > ms.denoise_above_db:
            log(f"  noise floor would be {floor:.1f} dB: turning the room's noise down by {ms.noise_reduction_db:g} dB")
            reduced = quieten(y)
            if reduced:
                del z
                z = board(y)
    del y
    out, gain = _level(z, sr, ms)
    del z
    return out, acx_metrics(out, sr) | {"gain_db": round(20 * np.log10(gain * pre), 1), "noise_reduction_db": reduced}


def acx_metrics(y: np.ndarray, sr: int) -> dict:
    rms, tp = rms_db(y), true_peak_db(y)
    peak = 20 * np.log10(max(float(y.max()), -float(y.min())) + 1e-12) if len(y) else -120.0
    nf = noise_floor_db(y, sr)
    return {"rms_db": round(rms, 1), "sample_peak_db": round(peak, 2), "true_peak_db": round(tp, 2),
            "noise_floor_db": round(nf, 1),
            "rms_ok": bool(-23 <= rms <= -18), "peak_ok": bool(tp <= -3), "noise_ok": bool(nf < -60)}
