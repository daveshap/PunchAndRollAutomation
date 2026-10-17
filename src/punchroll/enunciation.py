"""Enunciation: how sure a machine listener is of the everyday words in a finished recording.

David, 17 Oct 2026, on the narration of "How Jobs Actually Disappear": "what people are noticing is just how entirely
clear the enunciation is. But the thing is, for most listeners, particularly for audiobooks, that is the entire job.
it's not just the words being spoken, it's HOW they are spoken (clarity, emphasis) so yeah if you can find a way to
also measure prosody and enunciation that would be a good measure."

The recognizer that punchroll transcribes with reports a log-probability for every token it hears, and a word's
probability is the product of its tokens'. Everyday words are those found in at least a third of the reference
recordings, so names and jargon, which a recognizer doubts whoever says them, drop out. Enunciation is the number of
everyday words per hundred that the recognizer doubts (probability under 0.9): fewer is clearer. On the 28 recordings
of 2 to 16 Oct 2026 it ran from 4.3 to 7.9, put "labor attrition" (the narration of that film) third, and was
unrelated to fire (correlation 0.07).

The word list is fixed with the clarity scale (clarity.py), so that new recordings are counted on the same words.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

from .asr import SR16, Recognizer, file_key, merge_segments
from .audio import resample

DOUBT = 0.9                 # a word the recognizer gives less than this probability is doubted
EVERYDAY_SHARE = 1 / 3      # an everyday word is in at least this share of the reference recordings
MIN_WORDS = 50              # fewer everyday words than this and the count says nothing


def norm(text: str) -> str:
    return re.sub(r"[^a-z']", "", text.lower())


def heard(x16: np.ndarray, segments, rec) -> list[dict]:
    """Every word the recognizer hears in 16 kHz audio: text, start (s) and logp, the sum of its tokens' log-probabilities."""
    words: list[dict] = []
    for a, b in merge_segments(segments):
        a0, b0 = max(0, a - 3200), min(len(x16), b + 3200)
        st = rec.rec.create_stream()
        st.accept_waveform(SR16, x16[a0:b0])
        rec.rec.decode_stream(st)
        r = st.result
        off, cur = a0 / SR16, None
        for tok, t, lp in zip(r.tokens, r.timestamps, r.ys_log_probs):
            raw = tok.replace("▁", " ")
            if raw.startswith(" ") or cur is None:
                if cur and cur["text"]:
                    words.append(cur)
                cur = {"text": raw.strip(), "start": round(off + float(t), 3), "logp": float(lp)}
            else:
                cur["text"] += raw.strip()
                cur["logp"] += float(lp)
        if cur and cur["text"]:
            words.append(cur)
    return words


def confidences(path, x: np.ndarray, sr: int, rec, cache_dir) -> list[dict]:
    """The words of this exact file with the recognizer's confidence in each, cached beside the transcripts.

    rec: a Recognizer, or a function that makes one (called only when the file isn't cached yet).
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / f"{Path(path).stem}-{file_key(path)}.confidence.json"
    if final.is_file():
        return json.loads(final.read_text(encoding="utf-8"))
    if callable(rec) and not isinstance(rec, Recognizer):
        rec = rec()
    x16 = resample(x, sr, SR16)
    words = heard(x16, rec.vad(x16), rec)
    final.write_text(json.dumps(words), encoding="utf-8")
    return words


def everyday_words(recordings: list[list[dict]], share: float = EVERYDAY_SHARE) -> list[str]:
    """The words found in at least `share` of these recordings."""
    need = max(1, int(np.ceil(share * len(recordings))))
    count = Counter(w for words in recordings for w in {norm(x["text"]) for x in words} - {""})
    return sorted(w for w, c in count.items() if c >= need)


def doubted(words: list[dict], everyday) -> tuple[float, int]:
    """Everyday words per hundred that the recognizer doubts, and how many everyday words were counted."""
    every = set(everyday)
    lp = np.array([w["logp"] for w in words if norm(w["text"]) in every])
    if len(lp) < MIN_WORDS:
        return float("nan"), int(len(lp))
    return float(100 * np.mean(np.exp(lp) < DOUBT)), int(len(lp))

