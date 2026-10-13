"""Transcript, mark-up and cut on synthetic audio: every 'word' is a tone at its own pitch.

The mark-up here stands in for what Claude writes after reading a transcript. The tests check that the
program does exactly what the mark-up says and nothing else.
"""
import re

import numpy as np
import pytest

from punchroll.config import Settings
from punchroll.cut import cut
from punchroll.markup import read_markup, write_transcript
from punchroll.pieces import Room

SR = 16000
NAMES = "alpha bravo charlie delta echo foxtrot golf hotel".split()
FREQ = {w: 400 + 130 * i for i, w in enumerate(NAMES)}


def synth(sequence):
    """sequence: words, pause lengths in seconds, and ("noise", seconds) for a sound that is not a word."""
    rng = np.random.default_rng(1)
    parts, words, t = [], [], 0.0
    for item in [1.0] + sequence + [1.0]:
        if isinstance(item, float):
            n = int(item * SR)
            parts.append(np.zeros(n, np.float32))
        elif isinstance(item, tuple):
            n = int(item[1] * SR)
            parts.append(rng.normal(0, 0.01, n).astype(np.float32))
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


def heard(y):
    """The words in a piece of audio, by pitch."""
    hop, seq = int(0.05 * SR), []
    for a in range(0, len(y) - hop, hop):
        fr = y[a:a + hop]
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        f = np.argmax(np.abs(np.fft.rfft(fr * np.hanning(hop)))) * SR / hop
        w = min(FREQ, key=lambda k: abs(FREQ[k] - f))
        if not seq or seq[-1] != w:
            seq.append(w)
    return seq


def laid_out(sequence):
    x, words = synth(sequence)
    room = Room(x, SR, words)
    pieces = room.pieces()
    text = write_transcript(pieces, "test.wav")
    assert "<!--" in text
    return x, room, pieces, re.sub(r"<!--.*?-->", "", text, flags=re.S)       # without the how-to, which has examples in it


def run(x, room, pieces, text):
    return cut(x, SR, room, pieces, read_markup(text, pieces), Settings(), log=lambda *a: None)


TAKE = ["alpha", 0.08, "bravo", 0.08, "charlie"]
REST = ["delta", 0.08, "echo", 0.7, "foxtrot", 0.08, "golf"]


def test_unmarked_transcript_keeps_the_recording_as_it_was():
    x, room, pieces, text = laid_out(TAKE + [0.6] + REST)
    assert all(abs(a.b - b.a) < 1e-9 for a, b in zip(pieces, pieces[1:]))     # the pieces leave nothing out
    assert text.count("{") == 2                                                # the two real pauses; the short gaps aren't listed
    res = run(x, room, pieces, text)
    assert heard(res["audio"]) == NAMES[:7] and not res["cuts"] and len(res["edl"]) == 1
    span = pieces[-1].b - pieces[0].a
    assert abs(len(res["audio"]) / SR - (span + 1.5 + 3.0)) < 0.7             # the words, a little room each side, head and tail


def test_what_is_struck_is_cut_and_the_pause_left_is_the_one_not_struck():
    x, room, pieces, text = laid_out(TAKE + [0.6] + TAKE + [0.4] + REST)       # the first take is abandoned
    marked = re.sub(r"(alpha bravo charlie \{[\d.]+\})", r"~~\1~~", text, count=1)
    res = run(x, room, pieces, marked)
    assert heard(res["audio"]) == NAMES[:7]
    assert [c["words"] for c in res["cuts"]] == ["alpha bravo charlie"] and res["summary"]["words_cut"] == 3
    # struck the other way round, the second take goes and the first take's pause stays
    marked = re.sub(r"(\{[\d.]+\})(\s+\S+\s+)(alpha bravo charlie)", r"\1\2~~\3~~", text, count=1)
    marked = re.sub(r"(~~alpha bravo charlie~~ )(\{[\d.]+\})", r"\1~~\2~~", marked, count=1)
    res = run(x, room, pieces, marked)
    assert heard(res["audio"]) == NAMES[:7] and res["edl"][1]["raw_in"] > 3.0


def test_a_pause_is_as_long_as_the_number_written():
    x, room, pieces, text = laid_out(TAKE + [0.4] + REST)
    base = len(run(x, room, pieces, text)["audio"]) / SR
    pause = max(re.finditer(r"\{(\d\.\d\d)\}", text), key=lambda m: float(m.group(1)))       # the 0.7 s one
    shorter = run(x, room, pieces, text.replace(pause.group(0), "{0.30}"))
    assert abs(base - len(shorter["audio"]) / SR - (float(pause.group(1)) - 0.30)) < 0.03
    assert heard(shorter["audio"]) == NAMES[:7] and shorter["summary"]["pauses_changed"] == 1
    longer = run(x, room, pieces, text.replace(pause.group(0), "{2.00}"))
    assert abs(len(longer["audio"]) / SR - base - (2.00 - float(pause.group(1)))) < 0.03
    put_in = run(x, room, pieces, text.replace("alpha bravo", "alpha {0.50} bravo"))      # where there was no pause
    assert abs(len(put_in["audio"]) / SR - base - 0.5) < 0.12 and heard(put_in["audio"]) == NAMES[:7]


def test_a_sound_between_words_is_listed_and_can_be_struck():
    x, room, pieces, text = laid_out(TAKE + [0.3, ("noise", 0.2), 0.3] + REST)
    sound = re.search(r"\{sound [\d.]+ [+-]\d+\}", text)
    assert sound and [p.kind for p in pieces].count("sound") == 1
    kept, gone = run(x, room, pieces, text), run(x, room, pieces, text.replace(sound.group(0), f"~~{sound.group(0)}~~"))
    assert heard(gone["audio"]) == NAMES[:7] and gone["summary"]["sounds_cut"] == 1
    assert 0.15 < (len(kept["audio"]) - len(gone["audio"])) / SR < 0.25       # the sound is out, the quiet either side stays


def test_markup_that_no_longer_matches_the_recording_is_refused():
    x, room, pieces, text = laid_out(TAKE + [0.6] + REST)
    for broken, says in ((text.replace("bravo", "brave"), "the mark-up has 'brave'"),
                         (re.sub(r" \{\d\.\d\d\}", "", text, count=1), "where the recording has"),
                         (text.replace("alpha", "~~alpha"), "never closed"),
                         (text.replace("golf", ""), "before the end of the recording")):
        with pytest.raises(ValueError, match=says):
            read_markup(broken, pieces)
