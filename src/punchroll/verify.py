"""Proof a finished file: transcribe it, set it beside the manuscript, and measure it against ACX.

Works on any finished audio, whoever made it. Writes no audio. The comparison is the same one a cut's
report carries when the recording is cut with a script given (proof.compare), so the two reports read alike.
"""
from __future__ import annotations

from pathlib import Path

import soundfile as sf

from .asr import transcribe
from .audio import read_mono
from .markup import clock
from .master import acx_metrics
from .proof import compare, manuscript_markdown
from .text import Line


def verify(path, lines: list[Line], rec, cache_dir, log=print) -> dict:
    x, sr = read_mono(path)
    words = transcribe(path, x, sr, rec, cache_dir, log=log)["words"]
    heard = [{"text": w["text"], "at": w["start"], "end": w["end"]} for w in words]
    metrics = acx_metrics(x, sr)
    info = sf.info(str(path))
    dur = len(x) / sr
    metrics |= {"head_s": round(words[0]["start"], 2) if words else None,
                "tail_s": round(dur - words[-1]["end"], 2) if words else None,
                "sample_rate": info.samplerate, "channels": info.channels, "format": info.format,
                "approx_kbps": round(Path(path).stat().st_size * 8 / dur / 1000) if dur else None}
    return {"file": str(path), "duration": clock(dur), "words_heard": len(words), "acx": metrics, **compare(lines, heard)}


def verify_markdown(v: dict, script: str = "") -> str:
    a = v["acx"]
    md = [f"# Proof: {Path(v['file']).name}", ""]
    if script:
        md += [f"Manuscript: {script}  "]
    md += [f"Duration {v['duration']} · words heard {v['words_heard']} · pickups {len(v['pickups'])} · "
           f"small differences {len(v['small'])} · lines not found {len(v['not_found'])}", "",
           "## ACX", "", "| Measure | Value | Target |", "|---|---|---|",
           f"| RMS loudness | {a['rms_db']} dB | −23 to −18 dB |",
           f"| True peak | {a['true_peak_db']} dB (highest sample {a['sample_peak_db']} dB) | −3 dB or lower |",
           f"| Noise floor | {a['noise_floor_db']} dB | below −60 dB |",
           f"| Room tone at head / tail | {a['head_s']} s / {a['tail_s']} s | 1 to 5 s |",
           f"| Format | {a['format']}, {a['sample_rate']} Hz, {a['channels']} channel(s), about {a['approx_kbps']} kbps | MP3, 44,100 Hz, 192 kbps CBR, mono |",
           ""]
    return "\n".join(md + manuscript_markdown(v)) + "\n"
