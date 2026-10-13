"""Check finished files against what ACX and ElevenLabs ask for. No speech recognition, so it is quick.

ACX's figures are its audio submission requirements. ElevenLabs' are from its guide to Professional
Voice Cloning (training audio for a voice clone). Both pages were read on READ; the publishers change
them, so check the links before relying on a figure. Where a publisher gives no number ("no long gaps
of silence", "consistent in sound") the limit used here is ours and is marked so in the report.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import read_mono
from .master import acx_metrics
from .measure import clicks_per_minute, pauses, tone, tone_distance

READ = "11 October 2026"
ACX_SOURCE = "https://help.acx.com/s/article/acx-audio-submission-requirements"
PVC_SOURCE = "https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/professional-voice-cloning"
LONG_GAP_S = 3.0            # ours: ElevenLabs says only to avoid "long gaps of silence"
TONE_APART_DB = 2.0         # ours: a file this far from the set's balance sounds like a different setup
PVC_MINUTES = (30, 120, 180)   # ElevenLabs: 30 minutes at the least, two to three hours for the best clone


def measure_file(path) -> dict:
    """Everything the checks need from one finished file."""
    x, sr = read_mono(path)
    dur = len(x) / sr
    m = acx_metrics(x, sr)
    try:
        info = sf.info(str(path))
        fmt, channels, rate = info.format, info.channels, info.samplerate
    except Exception:                                    # a format only ffmpeg reads
        fmt, channels, rate = Path(path).suffix.lstrip(".").upper(), None, sr
    ps = pauses(x, sr)
    head = ps[0][1] if ps and ps[0][0] < 0.05 else 0.0
    tail = dur - ps[-1][0] if ps and ps[-1][1] > dur - 0.05 else 0.0
    inner = [b - a for a, b in ps if a >= 0.05 and b <= dur - 0.05]
    return {"file": str(path), "minutes": dur / 60, "rms_db": m["rms_db"], "true_peak_db": m["true_peak_db"],
            "noise_floor_db": m["noise_floor_db"], "head_s": round(head, 2), "tail_s": round(tail, 2),
            "longest_pause_s": round(max(inner, default=0.0), 2), "format": fmt, "channels": channels, "sample_rate": rate,
            "kbps": round(Path(path).stat().st_size * 8 / dur / 1000) if dur else 0,
            "clicks_per_minute": round(clicks_per_minute(x, sr), 1), "tone": tone(x, sr)}


def acx_problems(f: dict) -> list[str]:
    """What ACX would send this file back for. Empty when it passes."""
    out = []
    if not -23 <= f["rms_db"] <= -18:
        out.append(f"RMS {f['rms_db']} dB is outside −23 to −18")
    if f["true_peak_db"] > -3:
        out.append(f"peak {f['true_peak_db']} dB is over −3")
    if f["noise_floor_db"] > -60:
        out.append(f"noise floor {f['noise_floor_db']} dB is over −60")
    for end in ("head", "tail"):
        if not 1 <= f[f"{end}_s"] <= 5:
            out.append(f"{f[f'{end}_s']} s of room tone at the {end} (1 to 5 s recommended)")
    if f["longest_pause_s"] > 5:
        out.append(f"a pause of {f['longest_pause_s']} s (over 5 s)")
    if f["format"] != "MP3" or f["kbps"] < 190 or f["sample_rate"] != 44100:
        out.append(f"{f['format']} at about {f['kbps']} kbps and {f['sample_rate']} Hz (ACX takes 192 kbps or higher CBR MP3 at 44,100 Hz)")
    if f["minutes"] > 120:
        out.append(f"{f['minutes']:.0f} minutes long (120 at most)")
    return out


def pvc_problems(f: dict) -> list[str]:
    """What departs from ElevenLabs' advice for voice-clone training audio. Empty when nothing does."""
    out = []
    if not -23 <= f["rms_db"] <= -18:
        out.append(f"RMS {f['rms_db']} dB is outside −23 to −18")
    if f["true_peak_db"] > -3:
        out.append(f"true peak {f['true_peak_db']} dB is over −3")
    if f["longest_pause_s"] > LONG_GAP_S:
        out.append(f"a pause of {f['longest_pause_s']} s (the clone copies long pauses; over {LONG_GAP_S:g} s is our limit)")
    if f["format"] != "MP3" or f["kbps"] < 190:
        out.append(f"{f['format']} at about {f['kbps']} kbps (MP3 at 192 kbps or above is what they recommend; WAV does not improve the clone)")
    return out


def check_files(paths, log=lambda *a: None) -> dict:
    """Measure each file and judge it, then judge the set: total length, one channel format, files that sound alike."""
    files = []
    for p in paths:
        log(f"  {Path(p).name}")
        files.append(measure_file(p))
    for f, apart in zip(files, tone_distance([f["tone"] for f in files])):
        f["tone_apart_db"] = round(apart, 1)
        f["acx"], f["pvc"] = acx_problems(f), pvc_problems(f)
        if len(files) > 2 and apart > TONE_APART_DB:
            note = f"its tone is {apart:.1f} dB from the rest of the set (over {TONE_APART_DB:g} dB is our limit)"
            f["acx"].append(note)
            f["pvc"].append(note)
        del f["tone"]
    total = sum(f["minutes"] for f in files)
    notes = []
    if len({f["channels"] for f in files if f["channels"]}) > 1:
        notes.append("ACX: the files are not all mono or all stereo.")
    spread = max((f["rms_db"] for f in files), default=0) - min((f["rms_db"] for f in files), default=0)
    if spread > 2:
        notes.append(f"The files differ by {spread:.1f} dB in loudness; ACX and ElevenLabs both ask for a consistent level.")
    low, good, most = PVC_MINUTES
    if total < low:
        notes.append(f"ElevenLabs: {total:.0f} minutes in all, under the {low}-minute minimum for a Professional Voice Clone.")
    elif total < good:
        notes.append(f"ElevenLabs: {total:.0f} minutes in all. {low} is the minimum; {good} to {most} gives the best clone.")
    else:
        notes.append(f"ElevenLabs: {total:.0f} minutes in all, in or past the {good} to {most} minutes they recommend.")
    return {"files": files, "total_minutes": total, "notes": notes}


def standards_markdown(res: dict) -> str:
    md = ["# Standards check", "",
          f"{len(res['files'])} file(s), {res['total_minutes']:.0f} minutes. Checked against "
          f"[ACX's audio submission requirements]({ACX_SOURCE}) and "
          f"[ElevenLabs' guide to Professional Voice Cloning]({PVC_SOURCE}), as read on {READ}.", "",
          "| File | Min | RMS dB | True peak dB | Noise floor dB | Head / tail s | Longest pause s | Format | Clicks/min | Tone apart dB | ACX | ElevenLabs |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in res["files"]:
        md.append(f"| {Path(f['file']).name} | {f['minutes']:.1f} | {f['rms_db']} | {f['true_peak_db']} | {f['noise_floor_db']} | "
                  f"{f['head_s']} / {f['tail_s']} | {f['longest_pause_s']} | {f['format']} {f['kbps']} kbps | {f['clicks_per_minute']} | "
                  f"{f['tone_apart_db']} | {'pass' if not f['acx'] else 'CHECK'} | {'pass' if not f['pvc'] else 'CHECK'} |")
    flagged = [f for f in res["files"] if f["acx"] or f["pvc"]]
    if flagged:
        md += ["", "## To check", ""]
        for f in flagged:
            for who, items in (("ACX", f["acx"]), ("ElevenLabs", f["pvc"])):
                md += [f"- {Path(f['file']).name}, {who}: {item}" for item in items]
    md += ["", "## The set", ""] + [f"- {n}" for n in res["notes"]]
    md += ["", "## What this does not check", "",
           "- Mouth clicks are counted, not judged. ACX asks for files free of \"excessive mouth noise\" and gives no figure; "
           "ElevenLabs says the clone copies everything in the audio.",
           "- Breaths. Neither publisher gives a rule. Audiobook practice is to leave them in and lower only the loud ones.",
           "- Wording, retakes left in, and stray sounds: `punchroll transcript` on the finished file writes it out to be read.",
           "- Whether it sounds good. These are measurements."]
    return "\n".join(md) + "\n"
