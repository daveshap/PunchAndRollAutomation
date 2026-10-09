"""Mastering and export: the peak ceiling has to hold between samples and in the MP3, the WAV keeps its bit depth,
and noise reduction takes the room down without taking the voice with it."""
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

from punchroll.audio import read_mono, true_peak_db, wav_subtype, write_mp3, write_wav
from punchroll.config import Settings, load_settings
from punchroll.master import master, noise_profile, reduce_noise

SR = 44100


def test_true_peak_reads_the_same_wherever_the_blocks_fall():
    y = (0.5 * np.sin(2 * np.pi * 997 * np.arange(60000) / SR)).astype(np.float32)
    whole = true_peak_db(y)
    assert abs(whole - 20 * np.log10(0.5)) < 0.02
    for block in (1000, 4096, 9973):                               # a block edge inside loud audio once read as a peak
        assert abs(true_peak_db(y, block) - whole) < 0.01


def test_loudness_is_kept_when_a_block_edge_lands_on_a_peak():
    rng = np.random.default_rng(5)
    n = (1 << 20) + 60000                                          # the levelling works in blocks of 2**20 samples
    t = np.arange(n) / SR
    y = 0.02 * np.sin(2 * np.pi * 150 * t)
    edge = (1 << 20) - 64                                          # where the meter's second block starts reading
    for a in list(range(20000, n - 3000, 60000)) + [edge - 1000]:  # short loud syllables, one cresting right there
        y[a:a + 2000] += 0.5 * np.cos(2 * np.pi * 310 * (np.arange(a, a + 2000) - edge) / SR) * np.hanning(2000)
    out, m = master((y + rng.normal(0, 1e-4, n)).astype(np.float32), SR, Settings().master)
    assert abs(m["rms_db"] + 20) < 0.1 and abs(m["true_peak_db"] + 3.5) < 0.05


def bright_voice(seconds=20, seed=3):
    """A low buzz with sixty short, loud bursts of hiss: a sibilant voice in caricature.

    The bursts set the peaks, and hiss swings well above its own samples between them.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    buzz = sum(np.sin(2 * np.pi * 140 * k * t) / k for k in range(1, 9)) * (np.sin(2 * np.pi * 0.7 * t) > -0.3)
    hiss = np.diff(rng.normal(0, 1, n), prepend=0.0)              # white noise tilted up toward the top of the band
    on = np.zeros(n)
    for a in rng.integers(0, n - 2000, 60):
        on[a:a + 900] = 1.0
    return (0.03 * buzz + 0.25 * hiss * on + rng.normal(0, 1e-4, n)).astype(np.float32)


def test_ceiling_holds_between_samples_and_in_the_mp3(tmp_path):
    ms = Settings().master
    y, m = master(bright_voice(), SR, ms)
    assert m["true_peak_db"] <= ms.limiter_ceiling_db + 0.03 and m["peak_ok"]   # limiting the samples alone leaves this near -1 dB
    assert abs(m["rms_db"] + 20) < 0.3
    tp = write_mp3(tmp_path / "a.mp3", y, SR, 192, 44100, ms.limiter_ceiling_db)
    assert tp is None or tp <= ms.limiter_ceiling_db               # None only where nothing can decode an MP3


def narration(seconds=12.8, hiss=0.001, hum=0.002, rumble=0.0, pitch=130.0, voice=0.1, seed=2):
    """Words 0.6 s long on a buzzing voice, a second of pause after each, in a room with hiss, a 120 Hz hum, and rumble.

    The voice's pitch wavers by 4 % five times a second, as a voice's does: a dead-steady note is a different animal.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    at = t % 1.6                                                   # words fill 0 to 0.6 of every 1.6 s
    word = np.clip(at / 0.02, 0, 1) * np.clip((0.6 - at) / 0.02, 0, 1)
    turn = 2 * np.pi * pitch * (t + 0.04 / (2 * np.pi * 5) * np.sin(2 * np.pi * 5 * t))
    y = voice * word * sum(np.sin(k * turn) / k for k in range(1, 21))
    y += rng.normal(0, hiss, n) + hum * np.sin(2 * np.pi * 120 * t)
    if rumble:
        low = sosfilt(butter(4, 50, fs=SR, output="sos"), rng.normal(0, 1, n))
        y += rumble * low / np.sqrt(np.mean(low ** 2))
    return y.astype(np.float32), at


def level(y, where):
    return 10 * np.log10(np.mean(y[where].astype(np.float64) ** 2))


def tone(y, where, hz):
    """Level of the one frequency `hz` over the samples picked out by `where`."""
    t = np.flatnonzero(where) / SR
    return 20 * np.log10(abs(np.sum(y[where] * np.exp(-2j * np.pi * hz * t))) / len(t))


def test_noise_reduction_turns_the_room_down_and_leaves_the_voice():
    y, at = narration()
    words, pauses = (at > 0.1) & (at < 0.5), (at > 0.85) & (at < 1.45)
    z = reduce_noise(y.copy(), SR, noise_profile(y, SR), reduce_db=20)
    assert 19 < level(y, pauses) - level(z, pauses) < 20.5        # hiss and hum, down by what was asked
    assert 19 < tone(y, pauses, 120) - tone(z, pauses, 120) < 20.5
    assert abs(level(z, words) - level(y, words)) < 0.1
    again = reduce_noise(y.copy(), SR, noise_profile(y, SR), reduce_db=20, chunk_s=0.5)
    assert np.max(np.abs(again - z)) < 1e-6                        # the same whatever size of piece it is worked in


def test_rumble_under_the_voice_does_not_cost_the_voice_its_lowest_note():
    y, at = narration(hiss=0.0002, hum=0.0, rumble=0.003, pitch=123.0, voice=0.05)
    words = (at > 0.1) & (at < 0.5)
    profile = noise_profile(y, SR)
    kept = reduce_noise(y.copy(), SR, profile, reduce_db=20, smoothing=6)
    assert tone(kept, words, 123) > tone(y, words, 123) - 0.5
    # Without the 70 Hz line the bands of rumble below the voice share their gain with the note above them:
    plain = reduce_noise(y.copy(), SR, profile, reduce_db=20, smoothing=6, highpass_hz=0)
    assert tone(plain, words, 123) < tone(y, words, 123) - 4


def test_noise_reduction_steps_in_only_where_the_floor_would_fail_unless_told_otherwise():
    quiet = lambda *a: None                                        # noqa: E731
    noisy, clean = narration(hiss=0.0008, hum=0.0006)[0], narration(hiss=0.0002, hum=0.0)[0]
    auto, off, on = (replace(Settings().master, noise_reduction=mode) for mode in ("auto", "off", "on"))
    left = master(noisy.copy(), SR, off, quiet)[1]
    fixed = master(noisy.copy(), SR, auto, quiet)[1]
    assert not left["noise_ok"] and left["noise_reduction_db"] == 0
    assert fixed["noise_ok"] and fixed["noise_reduction_db"] == 12
    assert 11 < left["noise_floor_db"] - fixed["noise_floor_db"] < 12.5
    alone = master(clean.copy(), SR, auto, quiet)[1]
    assert alone["noise_ok"] and alone["noise_reduction_db"] == 0  # already under the limit
    asked = master(clean.copy(), SR, replace(on, noise_reduction_db=20.0), quiet)[1]
    assert asked["noise_reduction_db"] == 20 and 19 < alone["noise_floor_db"] - asked["noise_floor_db"] < 20.5


def test_a_recording_with_no_pauses_gives_no_noise_sample():
    rng = np.random.default_rng(4)
    t = np.arange(6 * SR) / SR
    drone = (0.05 * np.sin(2 * np.pi * 220 * t) + rng.normal(0, 0.001, len(t))).astype(np.float32)
    assert noise_profile(drone, SR) is None                        # all one level: nothing says which part is the room
    said = []
    out, m = master(drone.copy(), SR, replace(Settings().master, noise_reduction="on"), said.append)
    assert m["noise_reduction_db"] == 0 and any("skipped" in line for line in said)


def test_noise_reduction_setting_takes_a_word_or_true_false(tmp_path):
    def mode(text):
        (tmp_path / "s.toml").write_text(f"[master]\nnoise_reduction = {text}\n", encoding="utf-8")
        return load_settings(tmp_path / "s.toml").master.noise_reduction

    assert Settings().master.noise_reduction == "auto"
    assert (mode('"on"'), mode("true"), mode("false"), mode('"auto"')) == ("on", "on", "off", "auto")
    with pytest.raises(ValueError):
        mode('"sometimes"')


def test_wav_master_keeps_the_recordings_bit_depth(tmp_path):
    y = (0.1 * np.sin(2 * np.pi * 440 * np.arange(SR) / SR)).astype(np.float32)
    for sub in ("PCM_16", "PCM_24", "FLOAT"):
        sf.write(str(tmp_path / f"{sub}.wav"), y, SR, subtype=sub)
    assert wav_subtype([tmp_path / "PCM_16.wav"]) == "PCM_16"
    assert wav_subtype([tmp_path / "PCM_16.wav", tmp_path / "PCM_24.wav"]) == "PCM_24"    # a deeper pickups file wins
    assert wav_subtype([tmp_path / "FLOAT.wav"]) == "PCM_24"
    assert wav_subtype([tmp_path / "PCM_24.wav"], bits=16) == "PCM_16"                    # wav_bits in the settings
    assert wav_subtype([tmp_path / "only-ffmpeg-reads-this.m4a"]) == "PCM_16"
    write_wav(tmp_path / "out.wav", y, SR, "PCM_16")
    assert sf.info(str(tmp_path / "out.wav")).subtype == "PCM_16"
    z, _ = read_mono(tmp_path / "out.wav")
    assert np.max(np.abs(z - y)) < 3 / 32768                                              # dither and rounding, nothing more
