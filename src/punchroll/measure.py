"""Measures of a recording that the ACX numbers don't cover: mouth clicks, pauses, the room, tone, pitch, breaths.

Each takes plain samples and returns plain numbers, so it can be tested on a made-up signal. Levels are in
dB relative to full scale. Whole-file passes run in blocks, so memory stays flat for long chapters.

Pure numpy/scipy, like the mastering.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import butter, sosfilt, welch

from .audio import BLOCK, resample, rms_db

OCTAVES = (125, 250, 500, 1000, 2000, 4000, 8000)


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Start and end (exclusive) of every run of True."""
    d = np.diff(np.concatenate([[0], np.asarray(mask, dtype=np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def band_db(x: np.ndarray, sr: int, lo: float, hi: float, step_s: float = 0.01) -> tuple[np.ndarray, float]:
    """Level of the band lo..hi Hz in each step, and the step's true length in seconds."""
    sos = butter(4, [lo, min(hi, 0.45 * sr)], btype="bandpass", fs=sr, output="sos")
    n = max(1, int(step_s * sr))
    zi = np.zeros((sos.shape[0], 2))
    out, carry = [], np.zeros(0)
    for a in range(0, len(x), BLOCK):                       # filter state carries across blocks
        seg, zi = sosfilt(sos, x[a:a + BLOCK].astype(np.float64), zi=zi)
        seg = np.concatenate([carry, seg])
        m = len(seg) // n
        out.append(np.mean(seg[:m * n].reshape(m, n) ** 2, axis=1))
        carry = seg[m * n:]
    e = np.concatenate(out) if out else np.zeros(0)
    return 10 * np.log10(e + 1e-20), n / sr


def pauses(x: np.ndarray, sr: int, under_voice_db: float = 35.0, least_s: float = 0.2) -> list[tuple[float, float]]:
    """Every stretch of `least_s` or more where the level stays `under_voice_db` under the voice: (start, end) in seconds.

    The voice's level is the loudest twentieth of the file. The level is smoothed over 35 ms first, so a
    click inside a pause doesn't split it. Room tone at the head and tail counts as a pause.
    """
    full, step = band_db(x, sr, 80, 12000, 0.005)
    if not len(full):
        return []
    smooth = median_filter(full, size=7, mode="nearest")
    quiet = smooth < np.percentile(full, 95) - under_voice_db
    return [(a * step, b * step) for a, b in runs(quiet) if (b - a) * step >= least_s]


def clicks(x: np.ndarray, sr: int, edge_s: float = 0.06, over_db: float = 15.0) -> list[tuple[float, float]]:
    """Mouth clicks standing alone in pauses: (time in seconds, level in dB under the file's RMS level).

    A click is a spike of 25 ms or less in 1-10 kHz that stands `over_db` or more over the pause around
    it and at least `edge_s` clear of both ends of the pause, so the last consonant of a word and the
    first of the next are not counted. The level is that of its loudest 5 ms. Noise reduction leaves
    clicks alone and makes the pause around them quieter, which is why they stand out in a clean master.
    """
    hi, step = band_db(x, sr, 1000, 10000, 0.005)
    ref = rms_db(x)
    edge = int(round(edge_s / step))
    found = []
    for t0, t1 in pauses(x, sr):
        a, b = int(round(t0 / step)) + edge, min(len(hi), int(round(t1 / step))) - edge
        if b - a < 4:
            continue
        seg = hi[a:b]
        floor = np.median(seg)
        for c, d in runs(seg > max(floor + over_db, ref - 55)):
            if d - c <= 5:
                found.append(((a + c) * step, float(seg[c:d].max() - ref)))
    return found


def clicks_per_minute(x: np.ndarray, sr: int, within_db: float = 30.0) -> float:
    """Clicks in pauses that come within `within_db` of the file's RMS level, per minute of the file."""
    minutes = len(x) / sr / 60
    return sum(1 for _, level in clicks(x, sr) if level > -within_db) / minutes if minutes else 0.0


def room_under_voice(x: np.ndarray, sr: int) -> float:
    """How far the quietest moments sit under the voice, in dB, from 300 to 4000 Hz. Bigger is quieter."""
    level, _ = band_db(x, sr, 300, 4000, 0.05)
    return float(np.percentile(level, 95) - np.percentile(level, 5)) if len(level) else 0.0


def room_by_minute(x: np.ndarray, sr: int) -> list[float]:
    """The room's level in each minute (the quietest twentieth of its 50 ms steps, 300-4000 Hz).

    A steady room gives a flat row. Weather, traffic, or a fan that comes on show as a row that
    rises and falls, which no single noise-floor figure will show.
    """
    level, step = band_db(x, sr, 300, 4000, 0.05)
    per = int(round(60 / step))
    return [float(np.percentile(level[a:a + per], 5)) for a in range(0, len(level) - per // 2, per)]


def tone(x: np.ndarray, sr: int) -> np.ndarray:
    """The voice's balance: the energy in each octave of OCTAVES, in dB relative to 200-4000 Hz, while speaking."""
    n = 2048
    if len(x) < 4 * n:
        return np.zeros(len(OCTAVES))
    idx = np.arange(0, len(x) - n, n // 2)
    level = np.array([rms_db(x[i:i + n]) for i in idx])
    loud = idx[level > np.percentile(level, 95) - 20]
    seg = np.concatenate([x[i:i + n] for i in loud[::max(1, len(loud) // 6000)]]).astype(np.float64)
    f, p = welch(seg, sr, nperseg=min(8192, len(seg)))
    ref = p[(f >= 200) & (f < 4000)].sum() + 1e-30
    return np.array([10 * np.log10(p[(f >= c / 2 ** 0.5) & (f < min(c * 2 ** 0.5, sr / 2))].sum() / ref + 1e-30) for c in OCTAVES])


def tone_distance(tones: list[np.ndarray]) -> list[float]:
    """How far each file's balance is from the middle of the set, in dB (root mean square across the octaves)."""
    if not tones:
        return []
    middle = np.median(np.array(tones), axis=0)
    return [float(np.sqrt(np.mean((t - middle) ** 2))) for t in tones]


def pitch(x: np.ndarray, sr: int, seconds: float = 100.0, lo: float = 60.0, hi: float = 320.0) -> float | None:
    """Median pitch of the voice in Hz over the middle `seconds` of the file, or None if nothing is voiced.

    The YIN method: for each 64 ms frame, the lag at which the frame best matches itself shifted, taking
    the first lag whose normalized difference falls under 0.15 so that an octave below isn't chosen.
    """
    fs = 16000
    mid, half = len(x) // 2, int(seconds * sr / 2)
    y = resample(np.asarray(x[max(0, mid - half):mid + half], dtype=np.float32), sr, fs).astype(np.float64)
    n, hop, tmax, tmin = 1024, 256, int(fs / lo), int(fs / hi)
    if len(y) < n + tmax + hop:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(y, n + tmax)[::hop]
    level = 10 * np.log10(np.mean(frames[:, :n] ** 2, axis=1) + 1e-20)
    frames = frames[level > np.percentile(level, 95) - 25]
    from .gpu import torch_cuda, yin_differences
    if torch_cuda() is not None:                       # the same sums, worked out on the graphics card
        d = yin_differences(frames, n, tmax)
    else:
        d = np.empty((len(frames), tmax + 1))
        d[:, 0] = 1.0
        for tau in range(1, tmax + 1):
            d[:, tau] = np.sum((frames[:, :n] - frames[:, tau:tau + n]) ** 2, axis=1)
    norm = d[:, 1:] * np.arange(1, tmax + 1) / (np.cumsum(d[:, 1:], axis=1) + 1e-20)     # cumulative mean normalized difference
    found = []
    for row in norm:
        under = np.flatnonzero(row[tmin - 1:] < 0.15)
        if not len(under):
            continue
        k = under[0] + tmin - 1
        while k + 1 < len(row) and row[k + 1] < row[k]:      # walk down to the bottom of that dip
            k += 1
        found.append(fs / (k + 1))
    return float(np.median(found)) if len(found) >= 10 else None


def breaths_through(raw_db: np.ndarray, fin_db: np.ndarray, step: float, gaps, raw_voice: float, fin_voice: float,
                    over_room_db: float = 12.0, least_s: float = 0.12) -> list[dict]:
    """What became of each breath between the recording and the finished file.

    raw_db, fin_db: level of 500-8000 Hz in each `step` of the recording and of the finished file.
    gaps: (start in the recording, end in the recording, start in the finished file) for each pause the edit
    kept whole. raw_voice, fin_voice: the voice's own level in that band in each file.

    A breath is `least_s` or more of sound that stands `over_room_db` over the room and clear of both ends
    of its pause. For each: where it is in the finished file, how long it is, how far its loudest tenth of
    a second sits under the voice, and the share of it that comes through (is turned down by less than
    6 dB, relative to the voice). Noise reduction is what thins a breath: one near the room's own level
    is treated as room.
    """
    inside = np.concatenate([raw_db[int(g0 / step):int(g1 / step)] for g0, g1, _ in gaps]) if gaps else np.zeros(0)
    if not len(inside):
        return []
    room = np.percentile(inside, 10)
    out = []
    for g0, g1, c0 in gaps:
        i0, i1 = int((g0 + 0.10) / step), int((g1 - 0.06) / step)
        if i1 - i0 < int(least_s / step):
            continue
        seg = raw_db[i0:i1]
        for a, b in runs(seg > room + over_room_db):
            if (b - a) * step < least_s or a == 0 or b == len(seg):
                continue
            fr = np.arange(i0 + a, i0 + b)
            mfr = np.minimum(len(fin_db) - 1, np.round((fr * step - g0 + c0) / step).astype(int))
            through = ((raw_db[fr] - raw_voice) - (fin_db[mfr] - fin_voice)) < 6
            top = np.sort(seg[a:b])[-max(1, int(0.1 / step)):]
            out.append({"at": float((i0 + a) * step - g0 + c0), "seconds": float((b - a) * step),
                        "under_voice_db": float(raw_voice - 10 * np.log10(np.mean(10 ** (top / 10)))),
                        "through": float(np.mean(through))})
    return out
