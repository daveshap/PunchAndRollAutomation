"""Enunciation on made-up recognizer output: the word list, the count of doubted words, and the scorecard column."""
import json
import math
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from punchroll import enunciation as en
from punchroll.cli import main


def words(texts, p=0.99, doubted=()):
    """Recognizer words with probability p, except those at the positions in `doubted`, at 0.5."""
    return [{"text": t, "start": float(k), "logp": math.log(0.5 if k in doubted else p)} for k, t in enumerate(texts)]


def test_everyday_words_are_those_in_a_third_of_the_recordings():
    recs = [words(["the", "Cammarata", "clock"]), words(["the", "clock"]), words(["The", "horse"]),
            words(["the", "Yudkowsky"]), words(["the", "barn"]), words(["the", "hay"])]
    assert en.everyday_words(recs) == ["clock", "the"]          # "clock" is in 2 of 6, a third; names are in 1


def test_doubted_counts_everyday_words_under_0_9():
    w = words(["the"] * 100 + ["Cammarata"] * 20, doubted=set(range(7)) | set(range(100, 120)))
    per100, n = en.doubted(w, ["the"])
    assert n == 100 and abs(per100 - 7.0) < 1e-9                 # the doubted names don't count


def test_too_few_everyday_words_say_nothing():
    per100, n = en.doubted(words(["the"] * 10), ["the"])
    assert n == 10 and np.isnan(per100)


def test_heard_joins_tokens_into_words_and_adds_their_log_probabilities():
    result = SimpleNamespace(tokens=["▁the", "▁cl", "ar", "ity"], timestamps=[0.0, 0.3, 0.4, 0.5],
                             ys_log_probs=[-0.01, -0.1, -0.2, -0.3])

    class Stream:
        result = None

        def accept_waveform(self, sr, x):
            self.result = result

    class Rec:
        def create_stream(self):
            return Stream()

        def decode_stream(self, st):
            pass

    w = en.heard(np.zeros(16000 * 2, dtype=np.float32), [(0, 16000)], SimpleNamespace(rec=Rec()))
    assert [x["text"] for x in w] == ["the", "clarity"]
    assert abs(w[1]["logp"] - (-0.6)) < 1e-9
