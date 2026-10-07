"""Reading, writing, resampling, and measuring audio."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def read_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """Read any file libsndfile understands (WAV, FLAC, AIFF, OGG, MP3); fall back to ffmpeg."""
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            return np.ascontiguousarray(data[:, 0]), int(sr)
        return data.mean(axis=1, dtype=np.float32), int(sr)
    except Exception as e:
        if not shutil.which("ffmpeg"):
            raise RuntimeError(f"can't read {path}: {e}") from e
        sr = 48000
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                            "-f", "f32le", "pipe:1"], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError(f"can't read {path}: {r.stderr.decode(errors='replace').strip()[-300:]}") from e
        return np.frombuffer(r.stdout, dtype="<f4").astype(np.float32), sr


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return x
    f = Fraction(sr_to, sr_from)
    return resample_poly(x, f.numerator, f.denominator).astype(np.float32)


BLOCK = 1 << 20          # samples per block for whole-file passes, so memory stays flat


def rms_db(z: np.ndarray) -> float:
    if len(z) == 0:
        return -120.0
    total = 0.0
    for a in range(0, len(z), BLOCK):
        seg = z[a:a + BLOCK].astype(np.float64)
        total += float(np.dot(seg, seg))
    return float(10 * np.log10(total / len(z) + 1e-24))


def frame_db(x: np.ndarray, sr: int, hop_s: float = 0.005) -> tuple[np.ndarray, int]:
    """Energy in dB per hop, smoothed over two hops (10 ms windows)."""
    hop = max(1, int(hop_s * sr))
    n = len(x) // hop
    out = np.empty(n, dtype=np.float32)
    step = max(1, (1 << 22) // hop)             # about 4 million samples per block keeps memory flat
    for a in range(0, n, step):
        b = min(n, a + step)
        fr = x[a * hop:b * hop].reshape(b - a, hop).astype(np.float64)
        np.square(fr, out=fr)
        out[a:b] = 10 * np.log10(fr.mean(axis=1) + 1e-20)
    out = np.maximum(out, np.concatenate([out[1:], out[-1:]])) if n else out
    return out, hop


def speech_level_db(x: np.ndarray, sr: int) -> float:
    """A robust 'how loud is the voice' number: the 90th percentile of 50 ms frame levels."""
    db, _ = frame_db(x, sr, 0.05)
    db = db[db > -80]
    return float(np.percentile(db, 90)) if len(db) else -30.0


@dataclass
class Take:
    path: str
    start: float      # where this file begins on the combined timeline, in seconds
    duration: float
    gain_db: float


def load_takes(paths: list[str], level_match: bool = True, gap_s: float = 1.0, log=print):
    """Load one or more recordings in the order they were made and join them.

    Later files (pickups, the next session) are matched in level to the first file,
    so a line re-recorded on another day doesn't jump out.
    """
    xs, takes, sr0, ref_db, t = [], [], None, None, 0.0
    for p in paths:
        x, sr = read_mono(p)
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            x = resample(x, sr, sr0)
        gain = 0.0
        lvl = speech_level_db(x, sr0)
        if ref_db is None:
            ref_db = lvl
        elif level_match:
            gain = float(np.clip(ref_db - lvl, -12, 12))
            if abs(gain) > 0.3:
                x = (x * 10 ** (gain / 20)).astype(np.float32)
                log(f"  {Path(p).name}: level matched by {gain:+.1f} dB")
        if xs:
            xs.append(np.zeros(int(gap_s * sr0), dtype=np.float32))
            t += gap_s
        takes.append(Take(str(p), t, len(x) / sr0, gain))
        xs.append(x)
        t += len(x) / sr0
    return (xs[0] if len(xs) == 1 else np.concatenate(xs)), sr0, takes


def write_wav(path: str | Path, y: np.ndarray, sr: int) -> None:
    with sf.SoundFile(str(path), "w", sr, 1, subtype="PCM_24") as f:
        for a in range(0, len(y), BLOCK):
            f.write(np.clip(y[a:a + BLOCK], -1, 1).astype(np.float32))


def _pcm16(z: np.ndarray):
    for a in range(0, len(z), BLOCK):
        yield (np.clip(z[a:a + BLOCK], -1, 1) * 32767).astype("<i2")


def write_mp3(path: str | Path, y: np.ndarray, sr: int, kbps: int = 192, out_sr: int = 44100) -> None:
    """Constant-bit-rate mono MP3 (ACX wants 192 kbps or more, 44.1 kHz)."""
    z = resample(y, sr, out_sr)
    try:
        import lameenc
    except ImportError:
        lameenc = None
    if lameenc is not None:
        enc = lameenc.Encoder()
        enc.set_bit_rate(int(kbps))
        enc.set_in_sample_rate(int(out_sr))
        enc.set_channels(1)
        enc.set_quality(2)
        with open(path, "wb") as f:
            for pcm in _pcm16(z):
                f.write(bytes(enc.encode(pcm.tobytes())))
            f.write(bytes(enc.flush()))
        return
    if not shutil.which("ffmpeg"):
        raise RuntimeError("MP3 export needs the 'lameenc' package or ffmpeg on the PATH")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "x.wav"
        with sf.SoundFile(str(tmp), "w", out_sr, 1, subtype="PCM_16") as f:
            for pcm in _pcm16(z):
                f.write(pcm)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-c:a", "libmp3lame",
                        "-b:a", f"{kbps}k", str(path)], check=True)


def true_peak_db(y: np.ndarray, block: int = 1 << 20) -> float:
    """Peak of the 4x oversampled signal, computed in blocks to keep memory flat."""
    peak, pad = 0.0, 64
    for a in range(0, len(y), block):
        seg = y[max(0, a - pad):min(len(y), a + block + pad)].astype(np.float64)
        if len(seg) < 8:
            continue
        peak = max(peak, float(np.max(np.abs(resample_poly(seg, 4, 1)))))
    return 20 * np.log10(peak + 1e-12)


def noise_floor_db(y: np.ndarray, sr: int, win_s: float = 0.5) -> float:
    """The quietest half second in the file (ACX measures something similar)."""
    w = int(win_s * sr)
    if len(y) < w * 2:
        return rms_db(y)
    least = np.inf
    for s in range(0, len(y) - w, w // 2):          # half-overlapping windows, one at a time
        z = y[s:s + w].astype(np.float64)
        least = min(least, float(np.dot(z, z)))
    return float(10 * np.log10(least / w + 1e-24))
