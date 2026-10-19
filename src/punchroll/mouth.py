"""Mouth clicks: found by the audio alone and repaired in place, so the timeline doesn't move.

A mouth click is a spike of a few milliseconds: the lips or the tongue parting before a breath, saliva, a
swallow. It shows in the high band (2.5 kHz and up) as a jump of 15 dB or more over what is around it,
and it dies as fast as it came: within 3 ms the level is back down, and stays down. That is what tells it
from a consonant. A "t", "k" or "p" that is let go makes a spike too, but breathy noise follows it for
10 to 50 ms, and a fricative ("s", "f") is noise from the start. So a spike is a click only when the
level is 15 dB under its peak over the 3 to 20 ms on both sides of it (25 dB when it sits within 120 ms
after the voice or 40 ms before it, where the releases of word-final and word-initial consonants fall),
and the voice is not sounding at that moment.

Noise reduction leaves clicks alone and makes the pause around them quieter, which is why they stand out
in a clean master even when the transcript shows nothing there: a click of 2 ms averages into its 10 ms
step as quiet, and a click with no quiet before the next word is measured as part of that word.

Each click is covered with the few milliseconds of sound just beside it, faded in and out at equal power:
the breath or the room it sat in, from whichever side holds no other click. (Interpolating with an AR
model, the textbook repair, leaves a small hole in breath noise, which can itself be heard.) Nothing is
cut and no sample moves.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import butter, sosfiltfilt

STAND_DB = 15.0          # how far a click rises over the median of the 40 ms around it
CLEAR_DB = 15.0          # how far under its peak the level must be over the 3-20 ms on both sides
NEAR_VOICE_DB = 25.0     # the same, within NEAR_AFTER_S after the voice or NEAR_BEFORE_S before it
NEAR_AFTER_S = 0.12
NEAR_BEFORE_S = 0.04
WIDEST_MS = 4.0          # a click is no wider than this (time within 12 dB of its peak)
VOICE_UNDER_DB = 30.0    # the voice: the speech band within this many dB of its loud level


def _band(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    hi = min(hi, 0.45 * sr)
    return sosfiltfilt(butter(4, [lo, hi], btype="band", fs=sr, output="sos"), x)


def _frames_db(z: np.ndarray, hop: int) -> np.ndarray:
    n = len(z) // hop
    out = np.empty(n)
    step = max(1, (1 << 22) // hop)
    for a in range(0, n, step):
        b = min(n, a + step)
        fr = z[a * hop:b * hop].reshape(b - a, hop)
        out[a:b] = 10 * np.log10(np.einsum("ij,ij->i", fr, fr) / hop + 1e-20)
    return out


def find_clicks(x: np.ndarray, sr: int, block_s: float = 60.0) -> list[dict]:
    """Every mouth click in a recording: where it starts and ends (in samples), its peak, and how far it stands out."""
    x = np.asarray(x, dtype=np.float64)
    hop = max(1, int(round(0.0005 * sr)))            # 0.5 ms steps in the high band
    fr = hop / sr
    vhop = int(round(0.01 * sr))                      # 10 ms steps in the speech band
    out = []
    pad = int(0.5 * sr)
    blocks = range(0, len(x), int(block_s * sr))
    sp_all = _frames_db(_band(x, sr, 100, 4000), vhop)
    loud = float(np.percentile(sp_all, 95)) if len(sp_all) else -20.0
    voiced = median_filter(sp_all, size=5, mode="nearest") > loud - VOICE_UNDER_DB   # a click can't make 50 ms of voice
    n3, n20, n40 = int(round(0.003 / fr)), int(round(0.02 / fr)), int(round(0.04 / fr)) | 1
    near_a, near_b = int(round(NEAR_AFTER_S / 0.01)), int(round(NEAR_BEFORE_S / 0.01))
    for a0 in blocks:
        lo, hi_ = max(0, a0 - pad), min(len(x), a0 + int(block_s * sr) + pad)
        seg = x[lo:hi_]
        hi = _frames_db(_band(seg, sr, 2500, 14000), hop)
        base = median_filter(hi, size=n40, mode="nearest")
        # every spike on its own: a frame that stands out and is the loudest within 2 ms either side, so two clicks
        # a few milliseconds apart are two clicks, not one
        top = maximum_filter1d(hi, size=9, mode="nearest")
        for pk in np.flatnonzero((hi - base > STAND_DB) & (hi >= top)):
            t = lo + pk * hop
            if not (a0 <= t < a0 + int(block_s * sr)):
                continue                                   # the next block's, or the pad's
            peak = hi[pk]
            if pk - n20 < 0 or pk + n20 >= len(hi):
                continue
            a = pk
            while a > 0 and hi[a - 1] > peak - 12:
                a -= 1
            b = pk
            while b + 1 < len(hi) and hi[b + 1] > peak - 12:
                b += 1
            if (b - a + 1) * fr * 1000 > WIDEST_MS:
                continue
            after = float(np.median(hi[pk + n3:pk + n20])) - peak
            before = float(np.median(hi[pk - n20:pk - n3])) - peak
            f = t // vhop
            if voiced[max(0, f - 1):f + 2].any():
                continue                                   # inside the voice
            near = voiced[max(0, f - near_a):f].any() or voiced[f + 1:f + 1 + near_b].any()
            need = NEAR_VOICE_DB if near else CLEAR_DB
            if after > -need or before > -need:
                continue
            # the stretch to repair: where it stands 6 dB or more over what was there, at most 3 ms either side of its peak
            floor = base[pk] + 6
            a2 = pk
            while a2 > 0 and pk - a2 < n3 and hi[a2 - 1] > floor:
                a2 -= 1
            b2 = pk
            while b2 + 1 < len(hi) and b2 - pk < n3 and hi[b2 + 1] > floor:
                b2 += 1
            start = lo + a2 * hop - int(0.001 * sr)
            end = lo + (b2 + 1) * hop + int(0.0015 * sr)
            out.append({"start": max(0, start), "end": min(len(x), end), "at": t / sr,
                        "level_db": float(peak - loud), "stands_db": float(peak - base[pk]), "near_voice": bool(near)})
    out.sort(key=lambda c: c["start"])
    merged = []
    for c in out:                                      # clicks closer than 1 ms are one repair
        if merged and c["start"] <= merged[-1]["end"] + int(0.001 * sr):
            m = merged[-1]
            m["end"] = max(m["end"], c["end"])
            if c["stands_db"] > m["stands_db"]:
                m.update(at=c["at"], level_db=c["level_db"], stands_db=c["stands_db"])
            continue
        merged.append(dict(c))
    return merged


def patch(x: np.ndarray, start: int, end: int, sr: int, avoid: list[tuple[int, int]] = ()) -> bool:
    """Cover x[start:end] in place with the sound just beside it, faded in and out at equal power.

    The patch is taken from whichever side holds no other click and is quieter at its loudest, so
    a click inside a breath is covered by that breath and one in a pause by the room."""
    n = end - start
    guard = int(0.0005 * sr)
    sides = []
    for a in (start - guard - n, end + guard):
        b = a + n
        if a < 0 or b > len(x) or any(a < e2 and s2 < b for s2, e2 in avoid):
            continue
        sides.append((float(np.max(np.abs(x[a:b]))), a))
    if not sides:
        return False
    a = min(sides)[1]
    src = x[a:a + n].astype(np.float64)
    r = max(1, min(int(0.00075 * sr), n // 3))
    th = np.linspace(0, np.pi / 2, r)
    w = np.ones(n)
    w[:r] = np.sin(th)
    w[n - r:] = np.cos(th)
    keep = np.sqrt(np.clip(1 - w ** 2, 0, 1))         # equal power: the two are unrelated noise
    x[start:end] = (x[start:end].astype(np.float64) * keep + src * w).astype(x.dtype)
    return True


def repair_clicks(x: np.ndarray, sr: int, passes: int = 3) -> list[dict]:
    """Find every mouth click and repair it in place. Returns the clicks, each with `repaired` set.

    Then look again, up to `passes` times in all: in a run of wet clicks, one that stood under the
    threshold beside a louder one stands out once that one is gone, and a patch can carry one in."""
    found: list[dict] = []
    for _ in range(passes):
        clicks = find_clicks(x, sr)
        spans = [(c["start"], c["end"]) for c in clicks]
        for k, c in enumerate(clicks):
            others = spans[max(0, k - 8):k] + spans[k + 1:k + 9]
            c["repaired"] = patch(x, c["start"], c["end"], sr, others)
        found += clicks
        if not any(c["repaired"] for c in clicks):
            break
    return found


JAGGED_DB = 4.0          # a breath's level moves smoothly: the steps of its 5 ms level vary by under about 3 dB
LOW_SHARE = 0.5          # a swallow or a gulp: more than half of its energy under 300 Hz
PEAK_SHARE = 0.4         # a smack or a "tch": more than 40% of its energy in its loudest 10 ms


def sound_kind(x: np.ndarray, sr: int, a: float, b: float) -> dict:
    """Whether a sound between words is a breath or a mouth noise, measured with its clicks already covered.

    A breath is moving air: noise that swells and fades. A swallow, a smack, or a run of wet clicks
    jumps about instead, or sits low (a gulp), or puts most of its energy in one burst."""
    i, j = int(a * sr), int(b * sr)
    z = np.asarray(x[i:j], dtype=np.float64)
    hop = max(1, int(0.005 * sr))
    n = len(z) // hop
    if n < 4:
        return {"kind": "click", "jagged_db": 0.0, "low": 0.0, "peak": 1.0}
    e = np.einsum("ij,ij->i", z[:n * hop].reshape(n, hop), z[:n * hop].reshape(n, hop)) / hop
    jagged = float(np.std(np.diff(10 * np.log10(e + 1e-20))))
    peak = float(np.max(e[:-1] + e[1:]) / (e.sum() + 1e-20))
    pad = min(i, int(0.05 * sr))
    w = np.asarray(x[i - pad:j + pad], dtype=np.float64)
    low = _band(w, sr, 50, 300)[pad:pad + len(z)]
    wide = _band(w, sr, 50, 8000)[pad:pad + len(z)]
    low_share = float(np.sum(low ** 2) / (np.sum(wide ** 2) + 1e-20))
    mouth = jagged > JAGGED_DB or low_share > LOW_SHARE or peak > PEAK_SHARE
    return {"kind": "mouth" if mouth else "breath", "jagged_db": jagged, "low": low_share, "peak": peak}


def mouth_noises(x: np.ndarray, sr: int, pieces, longest_click: float = 0.08) -> dict[int, dict]:
    """Every sound piece longer than a click that is a mouth noise rather than a breath, by piece index."""
    y = np.array(x, dtype=np.float32, copy=True)
    repair_clicks(y, sr)
    out = {}
    for k, p in enumerate(pieces):
        if p.kind == "sound" and p.b - p.a > longest_click:
            r = sound_kind(y, sr, p.a, p.b)
            if r["kind"] == "mouth":
                out[k] = r
    return out
