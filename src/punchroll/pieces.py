"""A recording laid out as pieces: every word, every quiet stretch between words, every sound no word covers.

This is measurement. Nothing here decides what is kept. The pieces go into the transcript that Claude
reads and marks up (markup.py), and the marked-up file says what happens to each one (cut.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_closing

from .audio import frame_db

SOUND = "[sound]"        # stands in the word list for sound at the voice's level that the recognizer gave no word for


@dataclass
class Piece:
    kind: str            # "word", "sound" (sound that is not a recognized word), or "quiet"
    a: float             # where it starts in the recording, in seconds
    b: float             # where it ends
    text: str = ""       # a word, as the recognizer wrote it
    level: float = 0.0   # a sound's loudest moment, in dB relative to the voice (negative is under it)
    shown: bool = True   # a quiet too short to list is not shown in the transcript; it goes with the word after it

    @property
    def length(self) -> float:
        return self.b - self.a


def stray_sounds(x: np.ndarray, sr: int, words: list[dict]) -> list[dict]:
    """Sound at the voice's level that no recognized word covers, as entries shaped like the recognizer's words.

    The recognizer smooths over a cut-off syllable ("Th- The easy things...") and has no word for a bump
    or a cough. Any sound that stays within 25 dB of the voice for 0.1 s or more, comes within 15 dB of
    it, and touches no word (each word's time widened by 0.08 s) gets an entry with the text SOUND, so
    it shows in the transcript and can be struck like a word.

    A word whose own reported time holds no sound has had its time misplaced, and the nearest sound is
    probably that word, so sound within 0.35 s of such a word is left alone.
    """
    if not words:
        return []
    db, hop = frame_db(x, sr, 0.01)
    step = hop / sr

    def frames(a, b):
        return max(0, int(a / step)), min(len(db), int(b / step) + 1)

    covered = np.zeros(len(db), bool)
    for w in words:
        a, b = frames(w["start"] - 0.08, w["end"] + 0.08)
        covered[a:b] = True
    rest = db[~covered & (db > -90)]
    if not covered.any() or not len(rest):
        return []
    level, floor = float(np.percentile(db[covered], 90)), float(np.percentile(rest, 20))
    gate = max(level - 25, floor + 12)
    if gate > level - 10:                              # too noisy to tell the voice from the room by level
        return []
    loud = db > gate
    hollow = [w for w in words if not loud[slice(*frames(w["start"] - 0.08, w["end"] + 0.08))].any()]
    d = np.diff(np.concatenate([[0], binary_closing(loud, structure=np.ones(7, bool)).astype(np.int8), [0]]))
    out = []
    for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):   # runs of sound, dips under 70 ms bridged
        t0, t1 = s * step, e * step
        if (e - s < 10 or db[s:e].max() < level - 15 or covered[s:e].any()
                or any(t0 - 0.35 <= w["start"] <= t1 + 0.35 for w in hollow)):
            continue
        out.append({"text": SOUND, "start": round(float(t0), 3), "end": round(float(t1), 3)})
    return out


class Room:
    """Where the voice is and where it isn't, taken from the level of the recording.

    The recognizer's word times can swallow the silence after a word, so the edges of words and of
    pauses are measured from the audio: quiet is anything within 12 dB of the room's own level.
    """

    def __init__(self, x: np.ndarray, sr: int, words: list[dict]):
        self.sr, self.words, self.dur = sr, words, len(x) / sr
        self.db, self.hop = frame_db(x, sr)
        speech = np.zeros(len(self.db), bool)
        for w in words:
            if w["text"] != SOUND:                     # the room's level is judged without the stray sounds
                speech[max(0, int((w["start"] - 0.15) * sr / self.hop)):int((w["end"] + 0.15) * sr / self.hop)] = True
        quiet_db = self.db[~speech & (self.db > -90)]
        self.floor = float(np.percentile(quiet_db, 20)) if len(quiet_db) else -70.0
        self.voice = float(np.percentile(self.db[speech], 90)) if speech.any() else self.floor + 40.0
        self.quiet = self.db < self.floor + 12
        self.speech = speech

    def _frames(self, a: float, b: float) -> tuple[int, int]:
        return max(0, int(a * self.sr / self.hop)), min(len(self.db), int(b * self.sr / self.hop))

    def runs(self, lo: float, hi: float) -> list[tuple[float, float]]:
        """Stretches of quiet of 0.04 s or more between two times."""
        a, b = self._frames(lo, hi)
        if b <= a:
            return []
        d = np.diff(np.concatenate([[0], self.quiet[a:b].astype(np.int8), [0]]))
        step = self.hop / self.sr
        return [((a + s0) * step, (a + s1) * step)
                for s0, s1 in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if (s1 - s0) * step >= 0.04]

    def after(self, w: int):
        """The quiet that follows word w: the first stretch of 0.12 s or more, or failing that the longest."""
        hi = self.words[w + 1]["start"] + 0.08 if w + 1 < len(self.words) else self.dur
        rs = self.runs(self.words[w]["start"] + 0.10, hi)
        long = [r for r in rs if r[1] - r[0] >= 0.12]
        return long[0] if long else (max(rs, key=lambda r: r[1] - r[0]) if rs else None)

    def before(self, w: int):
        """The quiet that leads into word w."""
        lo = self.words[w - 1]["start"] + 0.10 if w > 0 else 0.0
        rs = self.runs(lo, self.words[w]["start"] + 0.02)
        return rs[-1] if rs else None

    def peak(self, a: float, b: float) -> float:
        """The loudest moment between two times, in dB relative to the voice."""
        i, j = self._frames(a, b)
        return float(self.db[i:max(j, i + 1)].max()) - self.voice

    def pieces(self) -> list[Piece]:
        """The recording from the first word to the last, as one unbroken run of pieces.

        Each word (or stray sound) runs from where the voice starts to where it stops. What lies between
        two words is split where the level crosses in and out of quiet: the quiet stretches, and any
        sound among them that no word covers (a breath, a click, a bump). A gap is listed in the
        transcript when it lasts 0.15 s or more or has a sound in it.
        """
        words, out = self.words, []
        lead = self.before(0)
        start = lead[1] if lead else max(0.0, words[0]["start"] - 0.03)
        for w, word in enumerate(words):
            if w + 1 < len(words):
                ve, vs = self.after(w), self.before(w + 1)
                if ve and vs and vs[1] > ve[0]:
                    end, nxt = ve[0], vs[1]
                else:                                   # the two run together: the edge is just ahead of the next word
                    end = nxt = max(start + 0.01, words[w + 1]["start"] - 0.02)
            else:
                ve = self.after(w)
                end = nxt = ve[0] if ve else min(self.dur, word["end"] + 0.10)
            sound = word["text"] == SOUND
            out.append(Piece("sound" if sound else "word", start, end, "" if sound else word["text"],
                             self.peak(start, end) if sound else 0.0))
            if nxt > end:
                gap, at = [], end
                for qa, qb in self.runs(end, nxt) or [(end, nxt)]:
                    qa, qb = max(qa, at), min(qb, nxt)
                    if qa > at + 1e-6:
                        level = self.peak(at, qa)
                        if qa - at < 0.04 and level < -30 and gap:     # a flicker of the room's own noise: part of the quiet
                            qa = gap.pop().a
                        else:
                            gap.append(Piece("sound", at, qa, level=level))
                    gap.append(Piece("quiet", qa, qb))
                    at = qb
                gap[0].a, gap[-1].b = end, nxt
                listed = nxt - end >= 0.15 or any(p.kind == "sound" for p in gap)
                for p in gap:
                    p.shown = listed
                out += gap
            start = nxt
        return out
