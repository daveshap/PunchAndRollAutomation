"""Settings and their defaults.

Every value can be overridden from a TOML file passed with --config, using the
section names below, for example:

    [pauses]
    paragraph = [0.9, 1.8, 1.3]

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
class AlignSettings:
    """Costs for explaining the read against the script, in tenths.

    Integers keep the dynamic programming exact. A restart costs less than one
    inserted word, so a repeated word or phrase is treated as a restart, and a
    substitution costs a little more than an insertion, so the stray word in
    front of a restart is cut instead of being passed off as a misread.
    """
    restart: int = 9          # jump back to any earlier word of the script
    skip: int = 40            # jump forward over text that was not read
    insert: int = 10          # a spoken word that is not in the script
    insert_filler: int = 4    # um, uh, sorry, okay, ...
    insert_edge: int = 6      # chatter before the first or after the last word
    delete: int = 10          # a script word that was not read
    substitute: int = 11      # a different word in place of the script word
    near: int = 3             # toward / towards, assistant / assistants
    max_cells: int = 400_000_000  # read tokens x script tokens; split longer jobs


@dataclass
class PauseSettings:
    """Pause rules in seconds. Triples are (min, max, target when rebuilt)."""
    head: float = 1.5                       # room tone before the first word (ACX: 1-5 s)
    tail: float = 3.0                       # room tone after the last word (ACX: 1-5 s)
    sentence: tuple = (0.30, 1.10)          # natural pause kept if inside this range
    paragraph: tuple = (0.80, 1.70, 1.20)
    after_title: tuple = (0.80, 1.50, 1.00)  # after "Chapter One." / "Part Two."
    heading_to_body: tuple = (1.50, 2.50, 2.00)
    heading_to_heading: tuple = (1.00, 2.00, 1.50)
    before_heading: tuple = (1.80, 3.00, 2.20)
    cut_sentence: tuple = (0.55, 0.90)      # pause rebuilt where a take was cut between sentences
    cut_within: tuple = (0.12, 0.45)        # pause rebuilt where a take was cut inside a sentence
    tolerance_short: float = 0.08           # leave a pause alone if it is this close to the minimum
    tolerance_long: float = 0.15            # ... or this close to the maximum


@dataclass
class MasterSettings:
    rms_db: float = -20.0              # ACX: -23 to -18 dB RMS
    limiter_ceiling_db: float = -3.6   # sample-peak ceiling; true peak lands under -3 dB
    highpass_hz: float = 70.0
    compressor_threshold_db: float = -26.0
    compressor_ratio: float = 2.0
    denoise_above_db: float = -62.0    # run gentle noise reduction only if the floor is above this
    mp3_kbps: int = 192                # ACX: 192 kbps or higher, constant bit rate
    mp3_sample_rate: int = 44100       # ACX: 44.1 kHz


@dataclass
class Settings:
    align: AlignSettings = field(default_factory=AlignSettings)
    pauses: PauseSettings = field(default_factory=PauseSettings)
    master: MasterSettings = field(default_factory=MasterSettings)
    threads: int = 0              # speech recognition threads; 0 = pick automatically
    level_match: bool = True      # match the speech level of later takes to the first one


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
    for section in ("align", "pauses", "master"):
        target = getattr(s, section)
        for k, v in (data.get(section) or {}).items():
            names = {f.name for f in fields(target)}
            if k not in names:
                raise ValueError(f"unknown setting [{section}] {k}")
            setattr(target, k, tuple(v) if isinstance(v, list) else v)
    for k in ("threads", "level_match"):
        if k in data:
            setattr(s, k, data[k])
    return s
