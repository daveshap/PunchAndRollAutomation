"""The two steps for one recording: write its transcript for mark-up, then cut and master it as marked."""
from __future__ import annotations

import gc
import glob
import json
import re
import time
from pathlib import Path

from .asr import Recognizer, transcribe
from .audio import read_mono, wav_subtype, write_mp3, write_wav
from .config import Settings, auto_threads
from .cut import cut
from .markup import read_markup, write_transcript
from .master import master
from .models import transcripts_dir
from .pieces import Room, stray_sounds
from .proof import compare
from .report import write_reports


def measure(audio, settings: Settings, log=print):
    """Samples, sample rate, the room, and the recording as pieces. Transcribes the file if that hasn't been done."""
    x, sr = read_mono(audio)
    holder = {}

    def recognizer():                      # load the 600 MB model only if the file needs transcribing
        if "rec" not in holder:
            holder["rec"] = Recognizer(auto_threads(settings.threads), log)
        return holder["rec"]

    heard = transcribe(audio, x, sr, recognizer, transcripts_dir(), None, log)["words"]
    holder.clear()
    gc.collect()
    if not heard:
        raise ValueError(f"no speech was recognized in {audio}")
    words = sorted(heard + stray_sounds(x, sr, heard), key=lambda w: w["start"])
    room = Room(x, sr, words)
    return x, sr, room, room.pieces()


def transcript(audio, dest, settings: Settings | None = None, log=print) -> Path:
    """Write the recording's transcript, ready to be marked up, and return where it went."""
    _, _, _, pieces = measure(audio, settings or Settings(), log)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(write_transcript(pieces, Path(audio).name), encoding="utf-8")
    log(f"Transcript: {dest}")
    return dest


def finished(out_dir, name, inputs, mp3=True) -> bool:
    """Whether this recording's finished files are there and newer than everything they were made from."""
    out = Path(out_dir)
    made = [out / f"{name}.wav"] + ([out / f"{name}.mp3"] if mp3 else [])
    if not all(p.is_file() for p in made):
        return False
    return min(p.stat().st_mtime for p in made) > max(Path(p).stat().st_mtime for p in inputs)


def cut_and_master(audio, markup, out_dir, name=None, settings: Settings | None = None, mp3=True,
                   report_only=False, log=print, lines=None, script="") -> dict:
    """Cut the recording as its marked-up transcript says, master it, and write the files and the report.

    lines: the manuscript's lines for this recording, if there is a manuscript. The report then also sets
    the words that were kept beside it. That is a report only: it changes nothing about the cut.
    """
    settings = settings or Settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = name or Path(audio).stem
    t0 = time.time()
    x, sr, room, pieces = measure(audio, settings, log)
    marks = read_markup(Path(markup).read_text(encoding="utf-8"), pieces)
    res = cut(x, sr, room, pieces, marks, settings, log, render=not report_only)
    del x
    gc.collect()
    kept = res.pop("kept")
    if lines:
        res["manuscript"] = dict(compare(lines, kept), script=script)
        m = res["manuscript"]
        log(f"  against the manuscript: {m['lines_found']}/{m['lines']} lines found, {len(m['pickups'])} pickup(s), "
            f"{len(m['small'])} small difference(s), {len(m['not_found'])} line(s) not found")
    s = res["summary"]
    log(f"  {s['cuts']} cut(s): {s['words_cut']} of {s['words_heard']} words and {s['sounds_cut']} sound(s) out, "
        f"{s['pauses_changed']} pause(s) changed")
    metrics = None
    if not report_only:
        y, metrics = master(res.pop("audio"), sr, settings.master, log)
        subtype = wav_subtype([audio], settings.master.wav_bits)
        write_wav(out / f"{name}.wav", y, sr, subtype)
        metrics["wav_bits"] = int(subtype[-2:])
        if mp3:
            tp = write_mp3(out / f"{name}.mp3", y, sr, settings.master.mp3_kbps, settings.master.mp3_sample_rate,
                           settings.master.limiter_ceiling_db)
            metrics["mp3_true_peak_db"] = None if tp is None else round(tp, 2)
            metrics["peak_ok"] = bool(metrics["peak_ok"] and (tp is None or tp <= -3))
        log(f"  RMS {metrics['rms_db']} dB, true peak {metrics['true_peak_db']} dB"
            + (f" (MP3 {metrics['mp3_true_peak_db']} dB)" if metrics.get("mp3_true_peak_db") is not None else "")
            + f", noise floor {metrics['noise_floor_db']} dB")
    data = write_reports(out, name, res, str(audio), str(markup), metrics)
    log(f"Done in {(time.time() - t0) / 60:.1f} min: {s['raw_minutes']:.1f} min recorded -> {s['edited_minutes']:.1f} min. "
        f"Report: {out / (name + '.report.md')}")
    return data


def recordings(base, audio) -> list[str]:
    """Every file a project entry names, in natural order."""
    hits = []
    for pat in audio if isinstance(audio, list) else [audio]:
        hits += [f for f in sorted(glob.glob(str(Path(base) / pat)), key=natural) if f not in hits]
    return hits


def natural(s: str):
    """Sort key that puts ch01-2.wav before ch01-10.wav."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def recording(base, name: str, audio) -> str:
    """The one recording a project entry names."""
    hits = []
    for pat in audio if isinstance(audio, list) else [audio]:
        hits += [f for f in sorted(glob.glob(str(Path(base) / pat)), key=natural) if f not in hits]
    if len(hits) != 1:
        raise FileNotFoundError(f"[{name}] audio must name one recording; it matches {len(hits)}: {audio}")
    return hits[0]


def saved_edit(out_dir, name) -> dict | None:
    """The edit list and counts saved beside a finished file, if there are any."""
    p = Path(out_dir) / f"{name}.edit.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
