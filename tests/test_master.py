"""Mastering and export: the peak ceiling has to hold between samples and in the MP3, and the WAV keeps its bit depth."""
import numpy as np
import soundfile as sf

from punchroll.audio import read_mono, wav_subtype, write_mp3, write_wav
from punchroll.config import Settings
from punchroll.master import master

SR = 44100


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
