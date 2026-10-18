"""Clarity: enunciation, how each statement lands, and how the next one starts, on one scale.

David, 17 Oct 2026, on the narration of "How Jobs Actually Disappear", which scored an average 50 on fire: "a sober,
self-possessed clarity with still really good prosody", "exactly the kind of cadence/prosody for my audiobook too",
and "what people are noticing is just how entirely clear the enunciation is. But the thing is, for most listeners,
particularly for audiobooks, that is the entire job. it's not just the words being spoken, it's HOW they are spoken
(clarity, emphasis) so yeah if you can find a way to also measure prosody and enunciation that would be a good measure."

Three parts, each a z-score against the reference set; their average is scaled like fire's, so that the reference set
averages 50 and every 10 is a standard deviation:

  enunciation  everyday words per hundred that the speech recognizer doubts (enunciation.py); fewer is clearer
  landing      for each statement (a sentence that ends in a full stop), how far the pitch drops where the voice stops:
               from the top of its last 1.5 s of voice to the bottom of its last 0.3 s, in semitones. The median over
               the file. Skilled readers end statements with large falls, and a falling end is heard as confident.
  reset        the top of the first second of the next sentence (90th percentile) minus that bottom, in semitones; the
               median over the file. The new sentence starts afresh.

Measured this way, landing and reset are unrelated to fire on the 31 recordings of 2 to 17 Oct 2026 (correlations
-0.01 and -0.20), so they don't measure how lively a read is. Pauses don't count: punchroll sets them in the edit, so they would score the editor.
Sentence ends come from the punctuation of the finished transcript (punchroll said), matched to the recognizer's word
timings for the finished file.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import date
from pathlib import Path

import numpy as np

from .audio import resample
from .enunciation import everyday_words
from .fire import FS, semitones, track

PARTS = ("enunciation", "landing", "reset")
SIGN = {"enunciation": -1.0, "landing": 1.0, "reset": 1.0}     # fewer doubted words is clearer
REFERENCE_NAME = "clarity-reference.json"
MIN_STATEMENTS = 15


def _letters(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _ends(token: str) -> str | None:
    """'.' if the token ends a statement, '?' if it ends a question or exclamation, None otherwise."""
    last = token.rstrip("\"”’')")[-1:]
    return "." if last == "." else "?" if last in ("?", "!") else None


def sentence_ends(words: list[dict], text: str) -> dict[int, str]:
    """The recognizer's words that end a sentence in the finished transcript, by index: '.' or '?'."""
    tokens = text.split()
    tt, rw = [_letters(t) for t in tokens], [_letters(w["text"]) for w in words]
    match = {}
    for a, b, n in difflib.SequenceMatcher(None, tt, rw, autojunk=False).get_matching_blocks():
        for k in range(n):
            match[a + k] = b + k
    return {match[k]: kind for k, tok in enumerate(tokens) if (kind := _ends(tok)) and k in match}


def landing_and_reset(words: list[dict], text: str, x: np.ndarray, sr: int) -> dict:
    """landing and reset (medians, in semitones), and how many statements and restarts were measured. landing and
    reset are nan when fewer than MIN_STATEMENTS statements are measured.

    Each sentence end is taken where his voice stops: the last voiced frame between the start of the sentence's last
    word and the start of the next word. landing is the drop from the top of the last 1.5 s of voice (90th percentile)
    to the bottom of its last 0.3 s (10th percentile); reset is the top of the first second of the next sentence minus
    that bottom. A window tied to the last word's span (the first version) missed the fall in about two thirds of the
    sentences: the recognizer's end times run into the pause, and a final syllable that trails into creak has no
    pitch to track, so the window fell back onto the word before, which in an energetic read carries the accent.
    """
    ends = sentence_ends(words, text)
    _, f0 = track(resample(x, sr, FS) if sr != FS else x)
    st = semitones(f0)
    t = np.arange(len(st)) * 0.01 + 0.02
    voiced = ~np.isnan(st)
    nan = {"landing": float("nan"), "reset": float("nan"), "statements": 0, "restarts": 0}
    if voiced.sum() < 500 or not ends:
        return nan

    def frames(t0, t1):
        return st[(t >= t0) & (t <= t1) & voiced]

    starts = [w["start"] for w in words]
    falls, lows = [], {}
    for i in sorted(ends):
        nxt = starts[i + 1] if i + 1 < len(words) else starts[i] + 2.0
        sel = np.flatnonzero((t >= starts[i]) & (t < nxt) & voiced)
        if not len(sel):
            continue
        e = t[sel[-1]]
        last, top = frames(e - 0.3, e), frames(e - 1.5, e)
        if len(last) >= 5 and len(top) >= 20:
            lows[i] = float(np.percentile(last, 10))
            if ends[i] == ".":
                falls.append(float(np.percentile(top, 90)) - lows[i])
    resets = []
    for i, low in lows.items():
        if i + 1 < len(words):
            f = frames(starts[i + 1], starts[i + 1] + 1.0)
            if len(f) >= 10:
                resets.append(float(np.percentile(f, 90)) - low)
    if len(falls) < MIN_STATEMENTS:
        return nan | {"statements": len(falls), "restarts": len(resets)}
    return {"landing": float(np.median(falls)), "reset": float(np.median(resets)) if resets else float("nan"),
            "statements": len(falls), "restarts": len(resets)}


def _raw(m: dict, ref: dict) -> float:
    z = [SIGN[p] * (m[p] - ref["mean"][p]) / ref["sd"][p] for p in PARTS]
    return float(np.mean(z)) if all(np.isfinite(z)) else float("nan")


def reference_from(measures: list[dict], everyday: list[str], note: str = "") -> dict:
    """The clarity scale from a reference set: each part's mean and SD, and the spread of their average."""
    full = [m for m in measures if all(np.isfinite(m.get(p, np.nan)) for p in PARTS)]
    ref = {"everyday": everyday, "mean": {}, "sd": {}, "recordings": len(full), "note": note}
    for p in PARTS:
        v = np.array([m[p] for m in full])
        ref["mean"][p], ref["sd"][p] = float(v.mean()), float(v.std()) or 1.0
    raw = np.array([_raw(m, ref | {"raw_mean": 0.0, "raw_sd": 1.0}) for m in full])
    ref["raw_mean"], ref["raw_sd"] = float(raw.mean()), float(raw.std()) or 1.0
    return ref


def clarity_score(m: dict, ref: dict) -> float:
    return 50 + 10 * (_raw(m, ref) - ref["raw_mean"]) / ref["raw_sd"]


def reference(rows: list[dict], path: Path | None, calibrate: bool, log=print) -> tuple[dict, str]:
    """The clarity scale (with the everyday words) and a line saying where it comes from.

    rows: each with "heard" (the recognizer's words) and its measured parts once the words are counted. calibrate:
    set the scale from these recordings and save it to path. Otherwise read it from path; if there is no file yet,
    set it from these recordings and save it, so that later recordings land on the same scale.
    """
    if path is not None and Path(path).is_file() and not calibrate:
        ref = json.loads(Path(path).read_text(encoding="utf-8"))
        return ref, f"Clarity scale: {ref.get('note', 'from ' + Path(path).name)} ({Path(path).name})."
    from .enunciation import doubted
    words = everyday_words([r["heard"] for r in rows])
    measures = [{"enunciation": doubted(r["heard"], words)[0], "landing": r.get("landing", np.nan),
                 "reset": r.get("reset", np.nan)} for r in rows]
    n = sum(all(np.isfinite(m[p]) for p in PARTS) for m in measures)
    ref = reference_from(measures, words, note=f"set on {date.today().isoformat()} from {n} finished recordings, "
                                               f"with the {len(words)} words found in at least a third of them")
    if path is not None:
        Path(path).write_text(json.dumps(ref, indent=1), encoding="utf-8")
        log(f"clarity scale saved to {path}")
    return ref, f"Clarity scale: {ref['note']}."
