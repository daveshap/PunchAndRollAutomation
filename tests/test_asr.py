"""Sound at the voice's level that the voice detector left out is added to its stretches.

Synthetic audio again: speech is a tone at the voice's level, a breath is a much quieter one.
"""
import json

import numpy as np

from punchroll.asr import add_missed_speech

SR = 16000


def recording(parts, noise_db=-65.0):
    """parts: (seconds, level in dB, or None for a pause). Returns the audio and each part's (start, end) in samples."""
    rng = np.random.default_rng(1)
    xs, spans, n = [], [], 0
    for seconds, level in parts:
        t = np.arange(int(seconds * SR)) / SR
        env = np.minimum(1, np.minimum(t, t[::-1]) / 0.02)
        amp = 0.0 if level is None else 10 ** (level / 20)
        xs.append((amp * env * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
        spans.append((n, n + len(t)))
        n += len(t)
    x = np.concatenate(xs)
    return x + rng.normal(0, 10 ** (noise_db / 20), len(x)).astype(np.float32), spans


def close(a, b, tol=0.03):
    return abs(a - b) <= tol * SR


def test_missed_phrase_late_start_and_early_end_are_added():
    x, sp = recording([(1.0, None), (2.0, -15), (1.5, None), (0.5, -16), (1.5, None), (0.4, -45), (0.6, None),
                       (2.0, -15), (1.5, None), (2.0, -15), (1.0, None)])
    first, phrase, breath, late, early = sp[1], sp[3], sp[5], sp[7], sp[9]
    found = [first, (late[0] + int(0.6 * SR), late[1]), (early[0], early[1] - int(0.5 * SR))]
    out = add_missed_speech(x, found, SR)
    assert json.dumps(out)                                       # plain ints: it goes into the cache as JSON
    assert len(out) == 4
    assert out[0] == first                                       # nothing was missing here, so nothing changed
    assert close(out[1][0], phrase[0]) and close(out[1][1], phrase[1])
    assert close(out[2][0], late[0]) and out[2][1] == late[1]
    assert out[3][0] == early[0] and close(out[3][1], early[1])
    assert not any(a < breath[1] and b > breath[0] for a, b in out)


def test_complete_stretches_are_left_alone():
    x, sp = recording([(1.0, None), (2.0, -15), (1.0, None), (2.0, -18), (1.0, None)])
    found = [sp[1], sp[3]]
    assert add_missed_speech(x, found, SR) == found
    assert add_missed_speech(x, [], SR) == []


def test_noisy_room_is_left_to_the_detector():
    x, sp = recording([(1.0, None), (2.0, -20), (1.0, None), (0.5, -20), (1.0, None)], noise_db=-28.0)
    assert add_missed_speech(x, [sp[1]], SR) == [sp[1]]


def test_joined_stretches_stay_short_enough_to_decode():
    x, sp = recording([(1.0, None), (30.0, -15), (1.0, None)])
    a, b = sp[1]
    found = [(a, a + 14 * SR), (a + 16 * SR, b)]                 # the detector dropped out for 2 s mid-speech
    out = add_missed_speech(x, found, SR, max_len=25.0)
    assert out[0][0] == a and out[-1][1] == b
    assert all(e - s <= 25 * SR for s, e in out)
    assert all(nxt[0] - prev[1] <= 0.02 * SR for prev, nxt in zip(out, out[1:]))   # and nothing is left out
