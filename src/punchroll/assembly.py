"""Render an engineer's explicit selections across recordings, including pickups.

Ranges, order, gains and crossfades are decisions supplied by the caller. No
matching of words, take selection, silence trimming or mastering happens here.
The edit map includes overlaps: two sources contribute during a crossfade.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .audio import read_mono, resample


@dataclass(frozen=True)
class SourceSpan:
    source: str
    start: float
    end: float


@dataclass(frozen=True)
class AssemblyClip:
    span: SourceSpan
    crossfade: float = 0.0  # seconds overlapping the preceding clip
    gain_db: float = 0.0
    match_level_to: SourceSpan | None = None
    level_sample: SourceSpan | None = None
    note: str = ""


def load_plan(path: str | Path) -> tuple[dict[str, Path], list[AssemblyClip], int]:
    """Read explicit assembly JSON; audio paths are relative to the plan file."""
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read assembly plan {path}: {exc}") from exc

    def fields(obj, required, optional, where):
        if not isinstance(obj, dict):
            raise ValueError(f"{where} must be an object")
        missing = set(required) - obj.keys()
        unknown = obj.keys() - set(required) - set(optional)
        if missing or unknown:
            raise ValueError(f"{where}: missing fields {sorted(missing)}; unknown fields {sorted(unknown)}")

    def number(value, where):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value):
            raise ValueError(f"{where} must be a finite number")
        return float(value)

    fields(data, {"sources", "clips", "sample_rate"}, set(), "assembly plan")
    rate = data["sample_rate"]
    if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if not isinstance(data["sources"], dict) or not data["sources"]:
        raise ValueError("sources must be a nonempty object of names and file paths")
    paths = {}
    for name, value in data["sources"].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, str) or not value.strip():
            raise ValueError("every source needs a nonempty name and file path")
        paths[name] = (path.parent / value).resolve()
    if not isinstance(data["clips"], list) or not data["clips"]:
        raise ValueError("clips must be a nonempty array")

    def read_span(obj, where):
        fields(obj, {"source", "start", "end"}, set(), where)
        source = obj["source"]
        if not isinstance(source, str) or source not in paths:
            raise ValueError(f"{where}.source must name a source in sources")
        start, end = number(obj["start"], f"{where}.start"), number(obj["end"], f"{where}.end")
        if not 0 <= start < end:
            raise ValueError(f"{where} requires 0 <= start < end")
        return SourceSpan(source, start, end)

    clips = []
    for i, obj in enumerate(data["clips"]):
        where = f"clips[{i}]"
        fields(obj, {"source", "start", "end"},
               {"crossfade", "gain_db", "match_level_to", "level_sample", "note"}, where)
        selected = read_span({key: obj[key] for key in ("source", "start", "end")}, where)
        crossfade = number(obj.get("crossfade", 0), f"{where}.crossfade")
        if crossfade < 0 or (i == 0 and crossfade):
            raise ValueError(f"{where}.crossfade must be nonnegative and zero on the first clip")
        gain = number(obj.get("gain_db", 0), f"{where}.gain_db")
        note = obj.get("note", "")
        if not isinstance(note, str):
            raise ValueError(f"{where}.note must be text")
        reference = read_span(obj["match_level_to"], f"{where}.match_level_to") if "match_level_to" in obj else None
        sample = read_span(obj["level_sample"], f"{where}.level_sample") if "level_sample" in obj else None
        if sample and (not reference or sample.source != selected.source):
            raise ValueError(f"{where}.level_sample requires match_level_to and must use the clip's source")
        clips.append(AssemblyClip(selected, crossfade, gain, reference, sample, note))
    return paths, clips, rate


def assemble(sources: Mapping[str, tuple[np.ndarray, int]], clips: Sequence[AssemblyClip],
             sample_rate: int, *, render: bool = True) -> dict:
    """Assemble mono arrays at ``sample_rate`` and return audio plus an edit map.

Optional level matching measures RMS over the explicitly selected reference
and calibration spans. The calibration defaults to the clip's own span. The
resulting gain plus ``gain_db`` applies to that clip alone. Select comparable
speech for calibration; a span containing silence will bias its RMS.

Nothing is limited or clipped: peak/overload measurements let the engineer
choose any subsequent mastering. ``render=False`` validates and plans without
allocating the complete output. Times in the map use actual rounded samples.
"""
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if not clips:
        raise ValueError("assembly needs at least one clip")
    checked = {}
    for name, (audio, sr) in sources.items():
        audio = np.asarray(audio)
        if (isinstance(sr, bool) or not isinstance(sr, (int, np.integer)) or sr <= 0
                or audio.ndim != 1 or not np.issubdtype(audio.dtype, np.number)
                or np.iscomplexobj(audio) or not np.isfinite(audio).all()):
            raise ValueError(f"invalid mono audio or sample rate for {name!r}")
        checked[name] = (audio, int(sr))

    def extract(span):
        if span.source not in checked:
            raise ValueError(f"unknown source {span.source!r}")
        audio, sr = checked[span.source]
        if (not np.isfinite([span.start, span.end]).all()
                or not 0 <= span.start < span.end <= len(audio) / sr):
            raise ValueError(f"invalid range for {span.source!r}: {span.start}..{span.end}")
        a, b = round(span.start * sr), round(span.end * sr)
        if b <= a:
            raise ValueError("source range is shorter than one sample")
        return audio[a:b], sr, a, b

    def energy(span):
        audio = extract(span)[0].astype(np.float64)
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            value = float(np.mean(audio * audio))
        if not np.isfinite(value) or value <= 0:
            raise ValueError("cannot match levels using silent or unmeasurable audio")
        return value

    planned, edl, pos = [], [], 0
    for i, clip in enumerate(clips):
        audio, sr, a, b = extract(clip.span)
        if not np.isfinite([clip.crossfade, clip.gain_db]).all() or clip.crossfade < 0:
            raise ValueError("gain and crossfade must be finite; crossfade cannot be negative")
        if i == 0 and clip.crossfade:
            raise ValueError("the first clip cannot crossfade with a preceding clip")
        if clip.level_sample is not None and clip.match_level_to is None:
            raise ValueError("level_sample requires match_level_to")
        if clip.level_sample is not None and clip.level_sample.source != clip.span.source:
            raise ValueError("level_sample must come from the clip's source")
        matched = 0.0
        if clip.match_level_to is not None:
            matched = 10 * (np.log10(energy(clip.match_level_to))
                            - np.log10(energy(clip.level_sample or clip.span)))
        gain = float(clip.gain_db + matched)
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            factor = float(np.power(10.0, gain / 20))
        if not np.isfinite(factor) or factor == 0:
            raise ValueError("gain is outside the representable audio range")
        # resample_poly uses ceil for the output length. Record the actual length,
        # including in a dry run, rather than assuming all rates divide evenly.
        size = (len(audio) * int(sample_rate) + sr - 1) // sr
        overlap = round(clip.crossfade * sample_rate)
        if overlap > size or (i and overlap > planned[-1]["size"] - planned[-1]["overlap"]):
            raise ValueError("crossfades exceed available clip audio or would overlap each other")
        pos -= overlap
        edl.append({"source": clip.span.source, "source_sr": sr,
                    "source_in_sample": a, "source_out_sample": b,
                    "raw_in": a / sr, "raw_out": b / sr,
                    "clean_in_sample": pos, "clean_out_sample": pos + size,
                    "clean_in": pos / sample_rate, "clean_out": (pos + size) / sample_rate,
                    "crossfade_samples": overlap, "crossfade_s": overlap / sample_rate,
                    "gain_db": gain, "matched_gain_db": float(matched),
                    "level_reference": vars(clip.match_level_to) if clip.match_level_to else None,
                    "level_sample": vars(clip.level_sample or clip.span) if clip.match_level_to else None,
                    "note": clip.note})
        planned.append({"audio": audio, "sr": sr, "factor": factor,
                        "size": size, "overlap": overlap, "position": pos})
        pos += size

    output = np.zeros(pos, dtype=np.float32) if render else None
    if render:
        for i, item in enumerate(planned):
            with np.errstate(over="ignore", invalid="ignore"):
                audio = resample(item["audio"].astype(np.float32), item["sr"], sample_rate).copy()
                audio *= item["factor"]
            if not np.isfinite(audio).all():
                raise ValueError("gain or source samples overflowed the render format")
            incoming = item["overlap"]
            outgoing = planned[i + 1]["overlap"] if i + 1 < len(planned) else 0
            for length, at_start in ((incoming, True), (outgoing, False)):
                if length:
                    ramp = (np.sin(np.linspace(0, np.pi / 2, length)) ** 2
                            if length > 1 else np.array([0.5]))
                    if at_start:
                        audio[:length] *= ramp
                    else:
                        audio[-length:] *= ramp[::-1]
            start = item["position"]
            output[start:start + item["size"]] += audio
        if not np.isfinite(output).all():
            raise ValueError("assembly overflowed the render format")
    peak = float(np.max(np.abs(output))) if render else None
    return {"audio": output, "sr": sample_rate, "edl": edl,
            "summary": {"clips": len(clips), "sources": len({c.span.source for c in clips}),
                        "samples": pos, "seconds": pos / sample_rate,
                        "peak": peak, "samples_over_full_scale": int(np.sum(np.abs(output) > 1)) if render else None}}


def assemble_files(paths: Mapping[str, str | Path], clips: Sequence[AssemblyClip],
                   sample_rate: int, *, render: bool = True) -> dict:
    """Load named recordings with punchroll's mono reader, then assemble them.

Does not write or overwrite files. The caller can inspect the edit map and
master/export the returned audio with the existing pipeline.
"""
    result = assemble({name: read_mono(path) for name, path in paths.items()}, clips,
                      sample_rate, render=render)
    result["sources"] = {name: str(Path(path).resolve()) for name, path in paths.items()}
    return result
