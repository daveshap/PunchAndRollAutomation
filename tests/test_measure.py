"""The measures on made-up signals: each has a known answer."""
import numpy as np

from punchroll.measure import (breaths_through, band_db, clicks, clicks_per_minute, pauses, pitch, room_by_minute,
                               room_under_voice, tone, tone_distance)

SR = 16000


def voice(seconds, f0=120.0, level=0.2, seed=0):
    """A buzzy stand-in for a voice: harmonics of f0 falling off with frequency."""
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t + k) / k for k in range(1, 30))
    return (level * x / np.max(np.abs(x))).astype(np.float32)


def room(seconds, db=-70.0, seed=1):
    return np.random.default_rng(seed).normal(0, 10 ** (db / 20), int(seconds * SR)).astype(np.float32)


def narration(pause_s=(0.5, 1.2, 0.8)):
    """Speech, pause, speech, ... with a second of room at each end."""
    parts = [np.zeros(SR, np.float32)]
    for p in pause_s:
        parts += [voice(2.0), np.zeros(int(p * SR), np.float32)]
    parts += [voice(2.0), np.zeros(SR, np.float32)]
    x = np.concatenate(parts)
    return x + room(len(x) / SR)[:len(x)]


def test_pauses_are_found_with_their_lengths():
    found = pauses(narration(), SR)
    lengths = [round(b - a, 1) for a, b in found]
    assert lengths == [1.0, 0.5, 1.2, 0.8, 1.0]


def test_a_click_in_a_pause_is_counted_and_one_beside_a_word_is_not():
    x = narration()
    rng = np.random.default_rng(3)
    mid = int((1 + 2 + 0.25) * SR)                          # the middle of the first pause
    x[mid:mid + 48] += rng.normal(0, 0.05, 48).astype(np.float32)
    edge = int((1 + 2 + 0.5 + 2 + 0.01) * SR)               # 10 ms after a word ends: a consonant's tail, not a click
    x[edge:edge + 48] += rng.normal(0, 0.05, 48).astype(np.float32)
    found = clicks(x, SR)
    assert len(found) == 1
    assert abs(found[0][0] - mid / SR) < 0.02
    assert clicks_per_minute(x, SR) > 0
    assert clicks(narration(), SR) == []


def test_a_click_does_not_split_its_pause():
    x = narration()
    mid = int((1 + 2 + 0.5 + 2 + 0.6) * SR)
    x[mid:mid + 48] += np.random.default_rng(4).normal(0, 0.05, 48).astype(np.float32)
    assert len(pauses(x, SR)) == 5


def test_room_under_voice_follows_the_noise():
    quiet = np.concatenate([voice(3.0), np.zeros(SR, np.float32)] * 3)
    a = room_under_voice(quiet + room(len(quiet) / SR, -80)[:len(quiet)], SR)
    b = room_under_voice(quiet + room(len(quiet) / SR, -60)[:len(quiet)], SR)
    assert 15 < a - b < 25


def test_room_by_minute_shows_noise_that_comes_and_goes():
    base = np.concatenate([voice(4.0), np.zeros(SR, np.float32)] * 36)          # three minutes
    noise = room(len(base) / SR, -75)[:len(base)]
    noise[60 * SR:120 * SR] *= 10 ** (12 / 20)                                  # the second minute is 12 dB noisier
    row = room_by_minute(base + noise, SR)
    assert len(row) == 3
    assert 9 < row[1] - row[0] < 15 and abs(row[2] - row[0]) < 2


def test_pitch_of_a_known_voice():
    assert abs(pitch(voice(6.0, f0=140.0), SR) - 140.0) < 2.0
    assert abs(pitch(voice(6.0, f0=95.0), SR) - 95.0) < 2.0
    assert pitch(room(6.0), SR) is None


def test_tone_distance_picks_out_the_file_that_sounds_different():
    plain = [tone(voice(5.0, seed=k) + room(5.0, -70, seed=k), SR) for k in range(3)]
    t = np.arange(5 * SR) / SR
    bright = voice(5.0) + (0.2 * np.sin(2 * np.pi * 4000 * t)).astype(np.float32)   # far more energy at 4 kHz
    apart = tone_distance(plain + [tone(bright, SR)])
    assert apart[3] > 5 and max(apart[:3]) < 1


def test_band_db_reads_a_tone_at_its_level():
    t = np.arange(2 * SR) / SR
    level, step = band_db((0.1 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32), SR, 500, 2000, 0.05)
    assert abs(step - 0.05) < 1e-9
    assert abs(np.median(level) - (20 * np.log10(0.1) - 3.01)) < 0.3            # a sine's RMS is 3 dB under its peak


def test_breaths_through_tells_whole_from_thinned_from_gone():
    step = 0.01
    n = 1000                                                                    # ten seconds of 10 ms steps
    raw = np.full(n, -90.0)
    raw[0:100] = raw[300:400] = raw[600:700] = raw[900:1000] = -30.0            # words
    for a in (150, 450, 750):                                                   # a breath in each of three pauses
        raw[a:a + 40] = -60.0
    fin = raw.copy()
    fin[fin == -90.0] = -110.0                                                  # noise reduction took the room down
    fin[450:470] = -80.0                                                        # the second breath lost its first half
    fin[750:790] = -80.0                                                        # the third is gone
    gaps = [(1.0, 3.0, 1.0), (4.0, 6.0, 4.0), (7.0, 9.0, 7.0)]
    found = breaths_through(raw, fin, step, gaps, -30.0, -30.0)
    assert [round(b["through"], 1) for b in found] == [1.0, 0.5, 0.0]
    assert all(abs(b["under_voice_db"] - 30.0) < 0.1 and abs(b["seconds"] - 0.4) < 0.011 for b in found)
