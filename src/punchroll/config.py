"""Settings and their defaults.

Any of them can be overridden from a TOML file passed with --config, for example:

    tail = 2.0

    [master]
    rms_db = -19.0
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass
class MasterSettings:
    rms_db: float = -20.0              # ACX: -23 to -18 dB RMS
    limiter_ceiling_db: float = -3.5   # true-peak ceiling; ACX's limit is -3 dB, the rest is room for their meter
    highpass_hz: float = 70.0
    compressor_threshold_db: float = -26.0
    compressor_ratio: float = 2.0
    noise_reduction: str = "auto"      # "auto": only if the noise floor would end above denoise_above_db; "on"; "off"
    noise_reduction_db: float = 12.0   # how far the room's noise is turned down
    noise_sensitivity: float = 6.0     # how far over the noise a sound must rise to be left alone (Audacity's scale)
    noise_smoothing: int = 3           # bands on either side that share each band's gain (Audacity's frequency smoothing)
    denoise_above_db: float = -62.0    # "auto" steps in when the floor would be above this
    wav_bits: int = 0                 # WAV master: 0 = the recording's own depth (16 to 24 bits), or 16, or 24
    mp3_kbps: int = 192                # ACX: 192 kbps or higher, constant bit rate
    mp3_sample_rate: int = 44100       # ACX: 44.1 kHz


@dataclass
class Settings:
    master: MasterSettings = field(default_factory=MasterSettings)
    head: float = 1.5             # room tone before the first word (ACX: 1 to 5 s at each end)
    tail: float = 3.0             # room tone after the last word
    threads: int = 0              # speech recognition threads; 0 = pick automatically


def auto_threads(requested: int = 0) -> int:
    if requested and requested > 0:
        return requested
    n = os.cpu_count() or 2
    return max(1, min(8, n - 1 if n > 2 else n))


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    s = Settings()
    if not path:
        return s
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    names = {f.name for f in fields(s.master)}
    for k, v in (data.get("master") or {}).items():
        if k not in names:
            raise ValueError(f"unknown setting [master] {k}")
        setattr(s.master, k, v)
    for k in ("head", "tail", "threads"):
        if k in data:
            setattr(s, k, data[k])
    s.master.noise_reduction = {True: "on", False: "off"}.get(s.master.noise_reduction, s.master.noise_reduction)
    if s.master.noise_reduction not in ("auto", "on", "off"):
        raise ValueError('[master] noise_reduction must be "auto", "on", or "off"')
    return s
