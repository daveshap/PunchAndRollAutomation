"""The outtakes: the struck takes worth hearing, cut from the raw recording as clips for a blooper reel.

Whoever marks up a recording also lists its outtakes (docs/marking-up.md, "The outtakes"): a JSON list of
{"n", "rating" (3 would make the reel, 2 usable, 1 filler), "profanity", "start", "end" (raw seconds), "words"}.
`clips` cuts each one from the raw sound as it was recorded: levelled to -20 dB RMS, peaks at or below -1 dBFS,
30 ms fades, named by number, rating and first words, with an outtakes.md table beside them. It writes only new
files and refuses to overwrite one. First done by hand for the recordings of 23 and 25 Oct 2026, whose reels
closed the films "Does AI Understand Anything?" and "The Real Fourth Sector".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from .audio import read_mono, write_wav

LEVEL_DB = -20.0
PEAK_DB = -1.0
FADE_S = 0.03


def load(path: str | Path) -> list[dict]:
    takes = json.loads(Path(path).read_text(encoding="utf-8"))
    for t in takes:
        for k in ("rating", "start", "end", "words"):
            if k not in t:
                raise ValueError(f"outtake {t.get('n', '?')} has no {k!r}")
        if not 0 <= t["start"] < t["end"]:
            raise ValueError(f"outtake {t.get('n', '?')}: start {t['start']} must come before end {t['end']}")
    return takes


def clip_name(k: int, take: dict) -> str:
    first = " ".join(re.sub(r"[^a-z0-9' ]", " ", take["words"].lower()).split()[:7]) or "take"
    return f"{k:02d} r{take['rating']} - {first}.wav"


def level(y: np.ndarray, sr: int) -> np.ndarray:
    y = y.astype(np.float64)
    rms = np.sqrt(np.mean(y ** 2) + 1e-12)
    y *= 10 ** (LEVEL_DB / 20) / rms
    pk = float(np.max(np.abs(y))) if len(y) else 0.0
    if pk > 10 ** (PEAK_DB / 20):
        y *= 10 ** (PEAK_DB / 20) / pk
    f = min(int(FADE_S * sr), len(y) // 2)
    if f:
        y[:f] *= np.linspace(0, 1, f)
        y[-f:] *= np.linspace(1, 0, f)
    return y.astype(np.float32)


def clips(raw: str | Path, listing: str | Path, out: str | Path, title: str | None = None) -> list[Path]:
    """Cut every listed take from `raw` into `out`; returns the clips written."""
    takes = load(listing)
    x, sr = read_mono(raw)
    out = Path(out)
    title = title or Path(raw).stem
    names = [clip_name(k, t) for k, t in enumerate(takes, 1)]
    for p in [out / n for n in names] + [out / "outtakes.md"]:
        if p.exists():
            raise FileExistsError(f"exists, not overwriting: {p}")
    out.mkdir(parents=True, exist_ok=True)
    rows, written = [], []
    for name, t in zip(names, takes):
        a, b = int(t["start"] * sr), min(int(t["end"] * sr), len(x))
        if a >= b:
            raise ValueError(f"outtake {t.get('n', '?')} starts past the end of {Path(raw).name}")
        write_wav(out / name, level(x[a:b], sr), sr, "PCM_24")
        written.append(out / name)
        rows.append(f"| {name} | {t['rating']} | {'yes' if t.get('profanity') else 'no'} | {t['start']:.2f} | "
                    f"{t['end']:.2f} | {t['words']} |")
    (out / "outtakes.md").write_text(
        f"# Outtakes: {title}\n\n"
        f"Clips cut from the raw recording `{Path(raw).name}` (raw sound, levelled to {LEVEL_DB:g} dB RMS, peaks at or "
        f"below {PEAK_DB:g} dBFS, {FADE_S * 1000:g} ms fades). Rating: 3 = would make the reel, 2 = usable, 1 = filler. "
        "The list is the mark-up editor's; times are raw seconds.\n\n"
        "| Clip | Rating | Profanity | Raw start | Raw end | Words |\n|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    return written
