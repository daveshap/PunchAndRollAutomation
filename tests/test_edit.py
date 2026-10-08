"""End-to-end edit on synthetic audio: every 'word' is a tone at its own pitch.

The recording restarts the first sentence halfway through. The edited audio must
contain each word exactly once, in script order, and the master must meet ACX levels.
"""
import numpy as np

from punchroll.config import Settings
from punchroll.edit import build_edit
from punchroll.master import master
from punchroll.text import Line

SR = 16000
NAMES = "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()
FREQ = {w: 400 + 130 * i for i, w in enumerate(NAMES)}


def synth(sequence):
    """sequence: list of words and pause lengths in seconds."""
    rng = np.random.default_rng(1)
    parts, words, t = [], [], 0.0
    for item in [1.0] + sequence + [1.0]:
        if isinstance(item, float):
            n = int(item * SR)
            parts.append(np.zeros(n, np.float32))
        else:
            n = int(0.25 * SR)
            tt = np.arange(n) / SR
            env = np.minimum(1, np.minimum(tt, tt[::-1]) / 0.02)
            parts.append((0.3 * env * np.sin(2 * np.pi * FREQ[item] * tt)).astype(np.float32))
            words.append({"text": item, "start": t, "end": t + 0.25})
        t += n / SR
    x = np.concatenate(parts)
    x += rng.normal(0, 10 ** (-62 / 20), len(x)).astype(np.float32)        # room noise
    return x, words


def detect(y):
    hop = int(0.05 * SR)
    seq = []
    for a in range(0, len(y) - hop, hop):
        fr = y[a:a + hop]
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        spec = np.abs(np.fft.rfft(fr * np.hanning(hop)))
        f = np.argmax(spec) * SR / hop
        w = min(FREQ, key=lambda k: abs(FREQ[k] - f))
        if not seq or seq[-1] != w:
            seq.append(w)
    return seq


def lines_for(sentences):
    return [Line(" ".join(s) + ".", "body", 0, list(s)) for s in sentences]


def test_restart_is_removed_and_order_kept():
    s1, s2 = NAMES[:6], NAMES[6:]
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.6,                       # abandoned start
           "alpha", 0.15, "bravo", 0.15, "charlie", 0.15, "delta", 0.15, "echo", 0.15, "foxtrot", 0.7,
           "golf", 0.15, "hotel", 0.15, "india", 0.15, "juliet"]
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines_for([s1, s2]), Settings(), log=lambda *a: None)
    assert res["summary"]["restarts"] == 1
    assert res["summary"]["words_cut"] == 3
    assert res["summary"]["lines_found"] == 2
    assert not res["pickups"]
    assert detect(res["audio"]) == NAMES
    # the abandoned start (about 1.5 s) is gone; 1.5 s of head and 3 s of tail room tone are added
    assert len(res["audio"]) < len(x) + 2.5 * SR

    y, m = master(res["audio"], SR, Settings().master, res["room_tone"], log=lambda *a: None)
    assert abs(m["rms_db"] + 20) < 0.3
    assert m["true_peak_db"] < -3


def test_adlib_that_runs_on_is_kept_and_a_stray_word_is_cut():
    lines = lines_for([NAMES[:3], NAMES[3:5], NAMES[5:7]])
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.05, "hotel", 0.7,      # "hotel" runs on from the line's end
           "india", 0.05, "delta", 0.15, "echo", 0.7,                          # "india" leads straight into the next line
           "juliet", 0.7,                                                      # "juliet" stands apart from both
           "foxtrot", 0.15, "golf"]
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines, Settings(), log=lambda *a: None)
    assert detect(res["audio"]) == "alpha bravo charlie hotel india delta echo foxtrot golf".split()
    assert res["summary"]["words_cut"] == 1
    assert [c["words"] for c in res["cuts"]] == ["juliet"]
    assert [p["problem"] for p in res["pickups"]] == ["added 'hotel'", "added 'india'"]
    assert [p["line"] for p in res["pickups"]] == [1, 2]                        # each stays with the line it joins


def test_earlier_take_is_spliced_in_only_when_comps_are_on():
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.3, "delta", 0.15, "echo", 0.15, "foxtrot", 0.8,
           "alpha", 0.15, "bravo", 0.15, "charlie", 0.3, "delta", 0.15, "golf", 0.15, "foxtrot"]   # "golf" is a slip
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), Settings(), log=lambda *a: None)
    assert len(res["comps"]) == 1 and not res["pickups"]
    assert detect(res["audio"]) == NAMES[:6]

    last_take_only = Settings()
    last_take_only.comps = False
    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), last_take_only, log=lambda *a: None)
    assert not res["comps"] and len(res["pickups"]) == 1
    assert detect(res["audio"]) == "alpha bravo charlie delta golf foxtrot".split()
