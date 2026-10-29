"""Mouth clicks covered in place outside the words, and the mouth noises told from breaths."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from punchroll import markfix, mouth
from punchroll.config import Settings
from punchroll.master import master

SR = 44100


def room(seconds, seed=1):
    return np.random.default_rng(seed).normal(0, 1e-4, int(seconds * SR))


def vowel(seconds, f0=120.0, level=0.2):
    t = np.arange(int(seconds * SR)) / SR
    y = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 30))
    y *= np.hanning(len(t)) ** 0.2
    return level * y / np.max(np.abs(y))


def click(at, x, level=0.05):
    """A lip or tongue click: an impulse that rings for under a millisecond, in every band."""
    n = int(0.001 * SR)
    ring = np.exp(-np.arange(n) / (0.00015 * SR)) * np.sin(2 * np.pi * 6000 * np.arange(n) / SR)
    i = int(at * SR)
    x[i:i + n] += level * ring / np.max(np.abs(ring))


def speech_with_pauses():
    """Two seconds of voice, a second of room, two more seconds of voice: the voice sets the file's loud level."""
    x = room(5.0)
    x[0:int(2 * SR)] += vowel(2.0)
    x[int(3 * SR):int(5 * SR)] += vowel(2.0, f0=140)
    return x


def level_db(z):
    return 10 * np.log10(np.mean(np.asarray(z, dtype=np.float64) ** 2) + 1e-30)


def test_a_click_in_a_pause_is_covered_and_the_room_around_it_kept():
    x = speech_with_pauses()
    click(2.5, x)
    y = x.astype(np.float32).copy()
    found = mouth.repair_clicks(y, SR)
    assert [round(c["at"], 2) for c in found] == [2.5] and found[0]["repaired"]
    a, b = int(2.45 * SR), int(2.55 * SR)
    assert np.max(np.abs(y[a:b])) < 1e-3                            # the click is gone
    assert abs(level_db(y[a:b]) - level_db(room(0.1, seed=9))) < 3   # and the room is still there: no hole
    changed = np.flatnonzero(y != x.astype(np.float32))
    assert changed.min() > int(2.49 * SR) and changed.max() < int(2.51 * SR)   # nothing else was touched


def test_a_click_inside_a_breath_is_covered_and_the_breath_kept():
    x = speech_with_pauses()
    rng = np.random.default_rng(4)
    a = int(2.3 * SR)
    n = int(0.4 * SR)
    x[a:a + n] += rng.normal(0, 3e-3, n) * np.hanning(n)
    before = level_db(x[a:a + n])
    click(2.5, x)
    y = x.astype(np.float32).copy()
    mouth.repair_clicks(y, SR)
    assert np.max(np.abs(y[int(2.49 * SR):int(2.51 * SR)])) < 0.02
    assert abs(level_db(y[a:a + n]) - before) < 1.0


def test_a_consonant_released_into_breathy_noise_is_left_alone():
    """A "t" let go at the end of a word: a spike, then 40 ms of aspiration, right after the vowel."""
    x = speech_with_pauses()
    rng = np.random.default_rng(6)
    click(2.06, x, level=0.08)
    n = int(0.04 * SR)
    x[int(2.061 * SR):int(2.061 * SR) + n] += rng.normal(0, 0.01, n) * np.linspace(1, 0, n)
    y = x.astype(np.float32).copy()
    found = mouth.repair_clicks(y, SR)
    assert found == [] and np.array_equal(y, x.astype(np.float32))


def test_the_voice_itself_is_never_touched():
    x = speech_with_pauses()
    click(1.0, x, level=0.3)                                         # a spike in the middle of a vowel
    y = x.astype(np.float32).copy()
    mouth.repair_clicks(y, SR)
    assert np.array_equal(y[:int(2 * SR)], x[:int(2 * SR)].astype(np.float32))


def test_breath_and_mouth_noise_are_told_apart_by_their_shape():
    x = speech_with_pauses()
    rng = np.random.default_rng(7)
    n = int(0.35 * SR)
    x[int(2.1 * SR):int(2.1 * SR) + n] += rng.normal(0, 3e-3, n) * np.hanning(n)               # a breath
    t = np.arange(int(0.25 * SR)) / SR
    x[int(2.6 * SR):int(2.6 * SR) + len(t)] += 0.01 * np.sin(2 * np.pi * 110 * t) * np.hanning(len(t))   # a gulp
    for k in range(6):                                                # a run of wet clicks with nothing between
        x[int((2.88 + 0.02 * k) * SR):int((2.88 + 0.02 * k) * SR) + 40] += rng.normal(0, 0.02, 40)
    assert mouth.sound_kind(x, SR, 2.1, 2.45)["kind"] == "breath"
    assert mouth.sound_kind(x, SR, 2.6, 2.85)["kind"] == "mouth"
    assert mouth.sound_kind(x, SR, 2.87, 2.99)["kind"] == "mouth"


def test_master_covers_mouth_clicks_unless_told_not_to():
    x = speech_with_pauses()
    click(2.5, x)
    s = Settings().master
    _, on = master(x.astype(np.float32).copy(), SR, s, log=lambda *a: None)
    _, off = master(x.astype(np.float32).copy(), SR, replace(s, mouth_clicks=False), log=lambda *a: None)
    assert on["mouth_clicks"] == 1 and off["mouth_clicks"] == 0


TRANSCRIPT = ("# take.wav\n\n<!--\nMark-up.\n-->\n\n"
              "0:01.0  The system receives a reward. {0.40} {sound 0.30 -35} {0.20} {sound 0.25 -38} {0.10}\n\n"
              "0:04.0  Done.\n")


def test_a_mouth_noise_is_struck_with_its_pauses_and_the_timeline_kept():
    m = markfix.MarkedUp(TRANSCRIPT, TRANSCRIPT)
    pieces = []
    for tok in m.source:
        kind = "quiet" if markfix.PAUSE.match(tok) else ("sound" if tok.startswith("{sound") else "word")
        pieces.append(SimpleNamespace(kind=kind, shown=True, text=tok))
    k = next(i for i, p in enumerate(pieces) if p.text == "{sound 0.30 -35}")
    changes = markfix.strike_mouth_noises(m, pieces, {k: {"jagged_db": 5.0, "low": 0.6, "peak": 0.2}})
    out = next(l for l in m.render().splitlines() if l.startswith("0:01.0"))
    assert out.endswith("~~{0.40} {sound 0.30 -35} {0.20}~~ {0.90} {sound 0.25 -38} {0.10}") and len(changes) == 1
    assert markfix.strike_mouth_noises(m, pieces, {k: {"jagged_db": 5.0, "low": 0.6, "peak": 0.2}}) == []


def test_a_loud_sound_inside_a_sentence_is_never_struck():
    text = ("# take.wav\n\n<!--\nMark-up.\n-->\n\n"
            "0:01.0  Claude {0.04} {sound 0.31 +2} {0.04} also flagged seven more. {0.40} {sound 0.30 -20} {0.20}\n\n"
            "0:04.0  Done.\n")
    m = markfix.MarkedUp(text, text)
    pieces = []
    for tok in m.source:
        kind = "quiet" if markfix.PAUSE.match(tok) else ("sound" if tok.startswith("{sound") else "word")
        pieces.append(SimpleNamespace(kind=kind, shown=True, text=tok))
    noisy = {"jagged_db": 5.0, "low": 0.1, "peak": 0.1}
    inside = next(i for i, p in enumerate(pieces) if p.text == "{sound 0.31 +2}")
    between = next(i for i, p in enumerate(pieces) if p.text == "{sound 0.30 -20}")
    assert markfix.strike_mouth_noises(m, pieces, {inside: noisy}) == []
    assert len(markfix.strike_mouth_noises(m, pieces, {between: noisy})) == 1   # loud, but after the sentence's end
