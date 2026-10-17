"""Fire: the lift, movement, range and brightness of a narrator's delivery, measured on the finished file alone.

David, 17 Oct 2026, once the basic production quality was solved: "I want to add this brightness/fire as a
standard measurement to all files as this, I think, now that we've solved the basic production quality, will be
the prime determinant of the files that get used for the PVC" and "put a number on it, and include it in the
standard report". He had heard it first: three recordings made back to back on 15 Oct 2026 (the Scion, essential
demand and communism scripts) have "the pop and fire that we want to focus on".

Four measurements of the voice while speaking:
  lift        the median pitch, in semitones above 100 Hz. The scorecard shows it against the speaker's own
              reference, so +1.0 means a semitone higher than his typical recording.
  movement    how fast the pitch moves along each voiced stretch, in semitones per second: an animated read moves,
              a flat one doesn't. Steps over 1.5 semitones in 10 ms (octave slips, new syllables) are left out.
  range       how far the pitch swings: the distance in semitones from its 10th to its 90th percentile while voiced
              (the "80-percentile range"). Of the voice measures studied for charisma, this one has the best
              evidence: across 51 speakers it correlated .52 with rated charisma, .62 for men, where the plain
              lowest-to-highest range gave .04 (Niebuhr and Skarnitzl, ICPhS 2019); and widening a voice's range by
              half raised its ratings while moving its pitch up or down by 2 semitones did not (Berger et al., DAGA
              2017). Added 17 Oct 2026 at David's word: "if that is something we can measure and quantify,
              absolutely. Let's science the shit out of making the perfect PVC".
  brightness  the centre of mass of the spectrum up to 8 kHz, in Hz, on the louder half of the voiced frames: how
              much of the voice's energy sits up high, the way it does when a speaker leans in and projects.

Fire puts the four on one scale against a reference set of the same speaker's recordings: each measurement
becomes standard deviations from the reference mean, the four are averaged, and the average is scaled so that the
reference set has a mean of 50 and a standard deviation of 10. So 60 is a step above his typical recording and 70
two steps. The reference is fixed once (`fire-reference.json`), so a recording made next month lands on the same
scale as these.

How it was found (17 Oct 2026, 28 finished recordings of 2 to 16 Oct). Timing, phrasing and the voice-source
measures (glottal closure by inverse filtering, H1-H2, CPP, HNR) did not set the 15 Oct session apart. Pitch height
and movement tracked how warmed up the voice was: lowest in the 7 a.m. sessions of 14 and 16 Oct, as high in the
late-morning sessions as on 15 Oct. Brightness was the one measure on which 15 Oct stood above every other
session, the next morning's included. Brightness also moves with microphone placement, so compare recordings made
with the microphone where it usually is.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.signal import medfilt, resample_poly

FS, HOP, N = 16000, 160, 640                 # 10 ms frames, 40 ms YIN window
LO, HI = 60.0, 320.0
TMAX, TMIN = int(FS / LO), int(FS / HI)
PARTS = ("lift", "movement", "range", "brightness")


def _differences(frames: np.ndarray) -> np.ndarray:
    from .gpu import torch_cuda, yin_differences
    if torch_cuda() is not None:
        return yin_differences(frames, N, TMAX)
    d = np.empty((len(frames), TMAX + 1))
    d[:, 0] = 1.0
    head = frames[:, :N]
    for tau in range(1, TMAX + 1):
        d[:, tau] = np.sum((head - frames[:, tau:tau + N]) ** 2, axis=1)
    return d


def track(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each 10 ms frame of a 16 kHz signal: its level in dB, and its pitch in Hz (nan where unvoiced). YIN."""
    if len(y) < N + TMAX + HOP:
        return np.zeros(0), np.zeros(0)
    fr = np.lib.stride_tricks.sliding_window_view(y, N + TMAX)[::HOP]
    level = 10 * np.log10(np.mean(np.asarray(fr[:, :N], dtype=np.float64) ** 2, axis=1) + 1e-20)
    f0 = np.full(len(fr), np.nan)
    idx = np.flatnonzero(level > np.percentile(level, 95) - 30)
    for a in range(0, len(idx), 6000):
        sel = idx[a:a + 6000]
        d = _differences(np.asarray(fr[sel], dtype=np.float64))
        norm = d[:, 1:] * np.arange(1, TMAX + 1) / (np.cumsum(d[:, 1:], axis=1) + 1e-20)
        for j, row in zip(sel, norm):
            under = np.flatnonzero(row[TMIN - 1:] < 0.15)
            if not len(under):
                continue
            k = under[0] + TMIN - 1
            while k + 1 < len(row) and row[k + 1] < row[k]:
                k += 1
            if 0 < k < len(row) - 1:                          # the bottom of the dip, between samples
                p, q, r = row[k - 1], row[k], row[k + 1]
                den = p - 2 * q + r
                k = k + (0.5 * (p - r) / den if den > 1e-12 else 0.0)
            f0[j] = FS / (k + 1)
    return level, f0


def semitones(f0: np.ndarray) -> np.ndarray:
    """Pitch in semitones above 100 Hz; octave slips (more than 9 semitones from the median) dropped, each voiced
    stretch smoothed over three frames."""
    st = 12 * np.log2(f0 / 100.0)
    if np.all(np.isnan(st)):
        return st
    st[np.abs(st - np.nanmedian(st)) > 9] = np.nan
    out = st.copy()
    voiced = ~np.isnan(st)
    i = 0
    while i < len(st):
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j < len(st) and voiced[j]:
            j += 1
        if j - i >= 3:
            out[i:j] = medfilt(st[i:j], 3)
        i = j
    return out


def _brightness(y: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """Spectral centroid (Hz, up to 8 kHz) of a 64 ms window at each of these frames."""
    n_fft = 1024
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / FS)
    pad = np.concatenate([y, np.zeros(n_fft)])
    out = np.empty(len(frames))
    for a in range(0, len(frames), 8000):
        sel = frames[a:a + 8000]
        seg = np.stack([pad[i * HOP:i * HOP + n_fft] for i in sel]) * win
        p = np.abs(np.fft.rfft(seg, axis=1)) ** 2 + 1e-20
        out[a:a + len(sel)] = (p * freqs).sum(axis=1) / p.sum(axis=1)
    return out


def _parts(level, st, bright, speaking_db) -> dict | None:
    """The three measurements over one stretch of frames, or None if it has too little voiced speech."""
    speech = level > speaking_db
    voiced = ~np.isnan(st) & speech
    if speech.sum() < 500 or voiced.sum() < 300:
        return None
    steps = np.diff(st)
    ok = ~np.isnan(steps) & (np.abs(steps) < 1.5)
    loud = voiced & (level >= np.median(level[voiced]))
    return {"lift": float(np.median(st[voiced])),
            "movement": float(np.mean(np.abs(steps[ok])) * 100) if ok.sum() > 100 else float("nan"),
            "range": float(np.percentile(st[voiced], 90) - np.percentile(st[voiced], 10)),
            "brightness": float(np.nanmedian(bright[loud]))}


def fire_measures(x: np.ndarray, sr: int, minute_s: float = 60.0) -> dict | None:
    """Lift, movement, range and brightness of a finished file, for the whole file and for each minute of it.

    Returns {"pitch_hz", "lift", "movement", "range", "brightness", "minutes": [{"at", "lift", ...}]},
    or None if the file has too little voiced speech to measure.
    """
    y = np.asarray(x, dtype=np.float64)
    if sr != FS:
        y = resample_poly(y, FS, sr)
    level, f0 = track(y)
    if not len(level):
        return None
    st = semitones(f0)
    speaking_db = np.percentile(level, 95) - 30
    bright = np.full(len(level), np.nan)
    voiced = np.flatnonzero(~np.isnan(st) & (level > speaking_db))
    if len(voiced):
        bright[voiced] = _brightness(y, voiced)
    whole = _parts(level, st, bright, speaking_db)
    if whole is None:
        return None
    per = int(minute_s * 100)
    minutes = []
    for a in range(0, len(level), per):
        if len(level) - a < per // 2:
            break
        m = _parts(level[a:a + per], st[a:a + per], bright[a:a + per], speaking_db)
        if m is not None:
            minutes.append({"at": a / 100} | m)
    return {"pitch_hz": float(100 * 2 ** (whole["lift"] / 12))} | whole | {"minutes": minutes}


def reference_from(measures: list[dict], note: str = "") -> dict:
    """The scale: the mean and standard deviation of each part over these recordings, and of their average."""
    m = [r for r in measures if r]
    if not m:
        raise ValueError("no recording with enough voiced speech to set the fire scale from")
    ref = {"mean": {}, "sd": {}}
    for k in PARTS:
        v = np.array([r[k] for r in m], dtype=float)
        ref["mean"][k] = float(np.nanmean(v))
        ref["sd"][k] = float(np.nanstd(v)) or 1.0
    raw = np.array([_raw(r, ref) for r in m])
    ref["raw_mean"], ref["raw_sd"] = float(np.mean(raw)), float(np.std(raw)) or 1.0
    ref["recordings"] = len(m)
    if note:
        ref["note"] = note
    return ref


def _raw(r: dict, ref: dict) -> float:
    """The parts' average distance from the reference, in standard deviations (only the parts the reference has,
    so a scale set before a part was added still reads)."""
    return float(np.nanmean([(r[k] - ref["mean"][k]) / ref["sd"][k] for k in PARTS if k in ref["mean"]]))


def fire_score(r: dict, ref: dict) -> float:
    """Fire on the reference's scale: the reference set has a mean of 50 and a standard deviation of 10."""
    return 50 + 10 * (_raw(r, ref) - ref["raw_mean"]) / ref["raw_sd"]


def hottest_minutes(r: dict, ref: dict, n: int = 3) -> list[tuple[float, float]]:
    """The n minutes with the most fire, as (start in seconds, fire), hottest first."""
    scored = [(m["at"], fire_score(m, ref)) for m in r.get("minutes", [])]
    return sorted(scored, key=lambda t: -t[1])[:n]


def load_reference(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_reference(ref: dict, path) -> None:
    Path(path).write_text(json.dumps(ref, indent=1) + "\n", encoding="utf-8")
