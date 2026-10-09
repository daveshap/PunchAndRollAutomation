"""The whole job for one chapter: recordings + script in, edited and mastered audio + reports out."""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path

from .asr import Recognizer, cached_words, transcribe
from .audio import load_takes, wav_subtype, write_mp3, write_wav
from .config import Settings, auto_threads
from .edit import build_edit
from .master import master
from .models import transcripts_dir
from .report import write_reports
from .text import load_script


def describe(script, start=None, end=None, line_range=None) -> str:
    """The script section a chapter is matched against, as recorded in its report."""
    return (Path(script).name + (f" from '{start}'" if start else "") + (f" to '{end}'" if end else "")
            + (f" lines {line_range}" if line_range else ""))


def finished_report(out_dir, name, audio_paths, script, desc, mp3=True, extra=()):
    """The saved report if this chapter was already edited from exactly these inputs, else None.

    That means its report, WAV, and MP3 (if wanted) exist, the report came from a full
    run (not --report-only) over the same recordings and script section, and none of the
    recordings, the script, or `extra` files (a settings file) changed after that.
    """
    out = Path(out_dir)
    report = out / f"{name}.report.json"
    outputs = [report, out / f"{name}.wav"] + ([out / f"{name}.mp3"] if mp3 else [])
    if not all(p.is_file() for p in outputs):
        return None
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if (data.get("master") is None or data.get("script") != desc
            or [t.get("file") for t in data.get("takes", [])] != [str(p) for p in audio_paths]):
        return None
    newest = max(Path(p).stat().st_mtime for p in [*audio_paths, script, *extra])
    return data if min(p.stat().st_mtime for p in outputs) > newest else None


def clean(audio_paths, script, out_dir, name=None, start=None, end=None, line_range=None,
          settings: Settings | None = None, mp3=True, report_only=False, max_seconds=None, log=print):
    """Returns the report dict, or None if transcription paused because of max_seconds."""
    settings = settings or Settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = name or (Path(audio_paths[0]).stem + "-edited")
    t0 = time.time()

    lines = load_script(script, start, end, line_range)
    desc = describe(script, start, end, line_range)
    log(f"Script: {len(lines)} lines, {sum(len(ln.tokens) for ln in lines):,} words ({desc})")

    x, sr, takes = load_takes([str(p) for p in audio_paths], settings.level_match, log=log)
    log(f"Recording: {len(x) / sr / 60:.1f} min in {len(takes)} file(s) at {sr} Hz")

    holder = {}

    def recognizer():                      # load the 600 MB model only if something needs transcribing
        if "rec" not in holder:
            holder["rec"] = Recognizer(auto_threads(settings.threads), log)
        return holder["rec"]

    cache = transcripts_dir()
    words = []
    for tk in takes:
        left = None if not max_seconds else max_seconds - (time.time() - t0)
        if left is not None and left <= 0 and cached_words(tk.path, cache) is None:
            log("Paused before transcribing everything; run the same command again to continue.")
            return None
        a, b = int(round(tk.start * sr)), int(round((tk.start + tk.duration) * sr))
        tr = transcribe(tk.path, x[a:b], sr, recognizer, cache, left, log)
        if tr is None:
            return None
        words += [{"text": w["text"], "start": w["start"] + tk.start, "end": w["end"] + tk.start} for w in tr["words"]]
    holder.clear()                         # free the speech model before editing and mastering
    gc.collect()
    log(f"Heard {len(words):,} words. Aligning to the script and building the edit ...")

    res = build_edit(x, sr, words, lines, settings, log, take_starts=[tk.start for tk in takes[1:]])
    del x                                  # the edit holds everything it needs from here on
    gc.collect()
    s = res["summary"]
    log(f"  {s['lines_found']}/{s['lines']} lines found, {s['restarts']} restarts cut, "
        f"{s['words_cut']} words removed, {s['comps']} two-take splices"
        + (f", {s['stray_sounds']} stray sound(s) cut" if s["stray_sounds"] else ""))
    metrics = None
    if not report_only:
        log("Mastering ...")
        y, metrics = master(res.pop("audio"), sr, settings.master, log)
        subtype = wav_subtype(audio_paths, settings.master.wav_bits)
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
    data = write_reports(out, name, res, takes, metrics, desc)
    log(f"Done in {(time.time() - t0) / 60:.1f} min: {s['raw_minutes']:.1f} min recorded -> "
        f"{s['edited_minutes']:.1f} min edited, {len(res['pickups'])} line(s) to check. "
        f"Report: {out / (name + '.report.md')}")
    return data
