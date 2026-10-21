"""Score every finished recording of one or more projects, side by side: which finished files have the most fire,
and which are cleanest and most alike.

Made for choosing among recordings (which ones go into a voice-clone training set, which chapter to
re-record first), where pass or fail against ACX is not enough to tell them apart. Everything is measured
on the finished file itself, never on the raw recording: how a take went in the room doesn't score.

Columns:
  recorded     the date in the project file's chapter entry, if it has one
  fire         lift, movement, range and brightness of the delivery on one scale (fire.py): 50 is the reference set's
               average and every 10 is a standard deviation. The table is sorted by it, highest first. David,
               17 Oct 2026: fire "will be the prime determinant of the files that get used for the PVC".
  lift         median pitch in semitones above the reference set's average
  movement     how fast the pitch moves while voiced, semitones per second
  range        how far the pitch swings: 10th to 90th percentile while voiced, semitones
  brightness   centre of mass of the voice's spectrum up to 8 kHz, Hz
  hottest      the minutes of the file with the most fire, with their fire
  composure    with --composure: enunciation, landing and reset on one scale like fire's (clarity.py; first called
               clarity). David, 17 Oct 2026, on enunciation: "for most listeners, particularly for audiobooks, that
               is the entire job". Renamed on 21 Oct 2026: "let's change that composite to composure, which really
               is the parity of fire."
  enunciation  everyday words per hundred that the speech recognizer doubts; fewer is clearer (enunciation.py)
  landing      how far each statement falls at its end, in the file's pitch ranges (median)
  reset        how far the next sentence starts up again, in the file's pitch ranges (median)
  clicks       mouth clicks alone in pauses, per minute, counting those within 30 dB of the file's level
  noise floor  the finished file's noise floor in dB, as ACX measures it
  tone         how far the file's balance by octave is from the middle of the set, in dB; smaller is more alike
  pitch        median pitch of the voice over the whole file, in Hz
  pace         words a minute, from the transcript of the finished file if it has been transcribed
  listener     with --listener: a trained model's estimate of PESQ, 1 to 4.5
  order        the average of the file's rank on clicks, tone and (if run) listener; 1 is best

The parts of fire are shown beside it, so a change in fire can be traced to the part that moved (David,
17 Oct 2026: "also present those three components as well just for reference so I can see my progress").
Use the individual measurements to compare the recordings and inspect specific passages.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

from .asr import cached_words
from .audio import noise_floor_db, read_mono
from .fire import fire_measures, fire_score, hottest_minutes, load_reference, reference_from, save_reference
from .measure import clicks_per_minute, pitch, tone, tone_distance
from .models import transcripts_dir

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

REFERENCE_NAME = "fire-reference.json"


def score_file(fin: np.ndarray, sr: int, words: int | None = None, listener: bool = False) -> dict:
    """The row for one finished file. words: how many words its transcript has, if it has been transcribed."""
    minutes = len(fin) / sr / 60
    fm = fire_measures(fin, sr)
    row = {"minutes": minutes, "clicks": clicks_per_minute(fin, sr), "noise_floor": noise_floor_db(fin, sr),
           "tone_bands": tone(fin, sr), "pitch": fm["pitch_hz"] if fm else pitch(fin, sr),
           "pace": words / max(0.1, minutes) if words else None, "fire_measures": fm,
           "pesq": None, "pesq_low": None, "lowest": []}
    if listener:
        from .listen import pesq_estimate
        est = pesq_estimate(fin, sr)
        row["pesq"], row["pesq_low"], row["lowest"] = est["mean"], est["low"], est["lowest"]
    return row


def rank_rows(rows: list[dict]) -> None:
    """Add 'tone' (distance from the set's middle) and 'order' (average rank; 1 is best) to each row."""
    for r, apart in zip(rows, tone_distance([r["tone_bands"] for r in rows])):
        r["tone"] = apart
    keys = [("clicks", False), ("tone", False)]
    if rows and all(r["pesq"] is not None for r in rows):
        keys.append(("pesq", True))
    places = np.zeros(len(rows))
    for key, high_is_good in keys:
        order = sorted(range(len(rows)), key=lambda i: rows[i][key], reverse=high_is_good)
        for place, i in enumerate(order, 1):
            places[i] += place
    for r, total in zip(rows, places):
        r["order"] = float(total / len(keys))


def add_fire(rows: list[dict], ref: dict) -> None:
    """Add 'fire', 'lift' (semitones above the reference's average), 'movement', 'range', 'brightness', 'hottest'."""
    for r in rows:
        fm = r.get("fire_measures")
        if not fm:
            continue
        r["fire"] = fire_score(fm, ref)
        r["lift"] = fm["lift"] - ref["mean"]["lift"]
        r["movement"], r["range"], r["brightness"] = fm["movement"], fm.get("range", float("nan")), fm["brightness"]
        r["hottest"] = hottest_minutes(fm, ref)


def fire_reference(rows: list[dict], path: Path | None, calibrate: bool, log=print) -> tuple[dict, str]:
    """The fire scale and a line saying where it comes from.

    calibrate: set the scale from these recordings and save it to path. Otherwise read it from path if there is
    one; failing that, use these recordings without saving (the numbers then move as recordings are added).
    """
    measured = [r["fire_measures"] for r in rows if r.get("fire_measures")]
    if calibrate:
        ref = reference_from(measured, note=f"set on {date.today().isoformat()} from {len(measured)} finished recordings")
        if path is not None:
            save_reference(ref, path)
            log(f"fire scale saved to {path}")
        return ref, f"Fire scale: {ref['note']}."
    if path is not None and Path(path).is_file():
        ref = load_reference(path)
        return ref, f"Fire scale: {ref.get('note', 'from ' + Path(path).name)} ({Path(path).name})."
    ref = reference_from(measured)
    return ref, (f"Fire scale: these {len(measured)} recordings (no {REFERENCE_NAME} yet, so the numbers move as "
                 "recordings are added; run with --calibrate-fire to fix the scale).")


def _timed_words(fin_path: Path) -> tuple[list[dict] | None, Path | None]:
    """The recognizer's words, with their timings, for the finished WAV or its MP3, if they are cached; and the
    file they were timed on. Measure on that same file: an MP3 can run tens of milliseconds behind its WAV (25 ms
    here), and a statement's fall is in its last tens of milliseconds."""
    for p in (fin_path, fin_path.with_suffix(".mp3")):
        if p.is_file():
            d = cached_words(p, transcripts_dir())
            if d is not None:
                return d["words"], p
    return None, None


def _finished_text(proj_path: Path, proj: dict, name: str) -> str | None:
    """The body of the recording's finished transcript (punchroll said build), if it has one."""
    path = proj_path.parent / proj.get("transcripts", "transcripts") / f"{name}.md"
    if not path.is_file():
        return None
    parts = path.read_text(encoding="utf-8").split("\n\n", 2)
    return parts[2] if len(parts) == 3 else None


def _word_count(fin_path: Path) -> int | None:
    """Words in the cached transcript of the finished MP3 or WAV (punchroll verify leaves one), if there is one."""
    for p in (fin_path.with_suffix(".mp3"), fin_path):
        if p.is_file():
            d = cached_words(p, transcripts_dir())
            if d is not None:
                return len(d["words"])
    return None


def scorecard(project, listener: bool = False, log=print, reference: Path | None = None,
              calibrate_fire: bool = False, clarity: bool = False, clarity_reference: Path | None = None,
              calibrate_clarity: bool = False) -> list[dict]:
    """Score every chapter, of one project file or several, that has a finished WAV in its output folder.

    reference: the fire scale file (default: fire-reference.json beside the first project file).
    calibrate_fire: set the fire scale from these recordings and save it there.
    clarity: also score enunciation (about 30 s a file the first time; cached after that), landing and reset, and
    put them on one scale. Landing and reset need the finished transcript (punchroll said build). The scale and
    its everyday words are clarity-reference.json beside the first project file, set from these recordings when
    there is none yet, or again with calibrate_clarity.
    """
    projects = [Path(p) for p in ([project] if isinstance(project, (str, Path)) else project)]
    rows = []
    holder: dict = {}

    def recognizer():
        if "r" not in holder:
            from .asr import Recognizer
            from .config import auto_threads
            holder["r"] = Recognizer(auto_threads(0), log)
        return holder["r"]
    for proj_path in projects:
        proj = tomllib.loads(proj_path.read_text(encoding="utf-8"))
        out = proj_path.parent / proj.get("out", "edited")
        for n, ch in enumerate(proj.get("chapter", []), 1):
            name = ch.get("name") or f"chapter-{n:02d}"
            fin_path = out / f"{name}.wav"
            if not fin_path.is_file():
                log(f"{name}: no finished WAV, skipped")
                continue
            fin, sr = read_mono(fin_path)
            row = score_file(fin, sr, _word_count(fin_path), listener)
            row["name"], row["recorded"] = name, ch.get("recorded")
            if clarity:
                from .clarity import landing_and_reset
                from .enunciation import confidences
                row["heard"] = confidences(fin_path, fin, sr, recognizer, transcripts_dir())
                (timed, timed_on), text = _timed_words(fin_path), _finished_text(proj_path, proj, name)
                if timed and text:
                    xa, sra = (fin, sr) if timed_on == fin_path else read_mono(timed_on)
                    row.update(landing_and_reset(timed, text, xa, sra))
                else:
                    row.update({"landing": float("nan"), "reset": float("nan")})
            rows.append(row)
            fm = row["fire_measures"]
            log(f"{name}: clicks {row['clicks']:.1f}/min, noise floor {row['noise_floor']:.1f} dB"
                + (f", listener {row['pesq']:.2f}" if row["pesq"] is not None else "")
                + (f", pitch {fm['pitch_hz']:.0f} Hz, movement {fm['movement']:.1f} st/s, range {fm['range']:.1f} st, brightness "
                   f"{fm['brightness']:.0f} Hz" if fm else ", too little voiced speech for fire"))
    rank_rows(rows)
    if any(r.get("fire_measures") for r in rows):
        path = Path(reference) if reference else projects[0].parent / REFERENCE_NAME
        ref, note = fire_reference(rows, path, calibrate_fire, log)
        add_fire(rows, ref)
        for r in rows:
            r["fire_note"] = note
    if clarity and rows:
        from . import clarity as cl
        from .enunciation import doubted
        path = Path(clarity_reference) if clarity_reference else projects[0].parent / cl.REFERENCE_NAME
        ref, note = cl.reference(rows, path, calibrate_clarity, log)
        for r in rows:
            r["enunciation"], r["enunciation_words"] = doubted(r["heard"], ref["everyday"])
            r["clarity"] = cl.clarity_score(r, ref)
            r["clarity_note"] = note
    return rows


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:02.0f}"


def scorecard_markdown(rows: list[dict]) -> str:
    total = sum(r["minutes"] for r in rows)
    heard = bool(rows) and all(r["pesq"] is not None for r in rows)
    fired = bool(rows) and all("fire" in r for r in rows)
    dated = any(r.get("recorded") for r in rows)
    clear = bool(rows) and all("clarity" in r for r in rows)
    quality = "clicks, tone" + (" and listener" if heard else "")
    if fired:
        lead = (f"Best first by Fire: the lift, movement, range and brightness of the delivery (50 is the reference average, "
                f"every 10 a standard deviation). Order is each file's average rank on {quality}; 1 is best.")
        sort_key = lambda r: -r["fire"]                                   # noqa: E731
    else:
        lead = f"Best first by \"order\": the average of each file's rank on {quality}."
        sort_key = lambda r: r["order"]                                   # noqa: E731
    md = ["# Recording scorecard", "",
          f"{len(rows)} finished recordings, {int(total // 60)} h {total % 60:.0f} min, all measured on the finished files. "
          + lead, ""]
    if fired:
        md += [rows[0]["fire_note"], ""]
    if clear:
        md += [rows[0]["clarity_note"], ""]
    head = "| Recording |" + (" Recorded |" if dated else "") + " Min |"
    head += " Fire | Lift st | Movement st/s | Range st | Brightness Hz | Hottest minutes |" if fired else ""
    head += " Composure | Enunciation /100 | Landing st | Reset st |" if clear else ""
    head += " Order | Clicks/min | Noise floor dB | Tone dB | Pitch Hz | Words/min |"
    head += " Listener | Lowest tenth | Lowest 10 s at |" if heard else ""
    md += [head, "|" + "---|" * (head.count("|") - 1)]
    for r in sorted(rows, key=sort_key):
        pitch_ = f"{r['pitch']:.0f}" if r["pitch"] is not None else "-"
        pace = f"{r['pace']:.0f}" if r["pace"] is not None else "-"
        line = f"| {r['name']} |" + (f" {r.get('recorded') or '-'} |" if dated else "") + f" {r['minutes']:.1f} |"
        if fired:
            hot = ", ".join(f"{_clock(t)} ({f:.0f})" for t, f in r["hottest"]) or "-"
            line += (f" {r['fire']:.0f} | {r['lift']:+.1f} | {r['movement']:.1f} | {r['range']:.1f} | "
                     f"{r['brightness']:.0f} | {hot} |")
        if clear:
            line += "".join(f" {r[k]:{f}} |" if r[k] == r[k] else " - |"
                            for k, f in (("clarity", ".0f"), ("enunciation", ".1f"), ("landing", ".1f"),
                                         ("reset", ".1f")))
        line += (f" {r['order']:.1f} | {r['clicks']:.1f} | {r['noise_floor']:.1f} | "
                 f"{r['tone']:.1f} | {pitch_} | {pace} |")
        if heard:
            line += f" {r['pesq']:.2f} | {r['pesq_low']:.2f} | {', '.join(_clock(t) for t, _ in r['lowest'])} |"
        md.append(line)
    notes = []
    if fired:
        notes.append("Fire: lift, movement, range and brightness, each in standard deviations from the reference set, "
                     "averaged and scaled so the reference set averages 50. Lift: median pitch in semitones above the "
                     "reference average. Movement: how fast the pitch moves while voiced. Range: how far the pitch swings, "
                     "from its 10th to its 90th percentile, the best-evidenced voice measure of charisma. Brightness: "
                     "centre of mass of the voice's "
                     "spectrum up to 8 kHz, which also moves with microphone placement. Hottest minutes: where each "
                     "minute starts, with its fire.")
    if clear:
        notes.append("Composure: enunciation, landing and reset, each in standard deviations from the reference set, "
                     "averaged and scaled so the reference set averages 50; it doesn't depend on fire. Enunciation: of "
                     "the everyday words (those in at least a third of the reference recordings, so that names and "
                     "jargon drop out), how many per hundred the speech recognizer doubts; fewer is clearer. Landing: "
                     "how far a statement's pitch falls where the voice stops, in semitones. Reset: how far the "
                     "next sentence starts up again, in semitones. Sentence ends come from the finished "
                     "transcript; a dash means it has none yet.")
    notes.append("Clicks: mouth clicks alone in pauses. Noise floor: as ACX measures it. Tone: how far the file's balance "
                 "of low, middle and high frequencies is from the middle of the set. Pitch: median over the whole file. "
                 "Words/min: from the finished file's transcript."
                 + (" Listener: a trained model's estimate of PESQ out of 4.5." if heard else ""))
    md += [""] + "\n\n".join(notes).split("\n")
    return "\n".join(md) + "\n"


def scorecard_csv(rows: list[dict]) -> str:
    """The same table as a CSV for a spreadsheet: one row per recording, in the same order, numbers unrounded
    past what the measurement supports."""
    import csv
    import io
    heard = bool(rows) and all(r["pesq"] is not None for r in rows)
    fired = bool(rows) and all("fire" in r for r in rows)
    clear = bool(rows) and all("clarity" in r for r in rows)
    cols = ["Recording", "Recorded", "Minutes"]
    cols += ["Fire", "Lift st", "Movement st/s", "Range st", "Brightness Hz", "Hottest minutes"] if fired else []
    cols += ["Composure", "Enunciation /100", "Landing st", "Reset st"] if clear else []
    cols += ["Order", "Clicks/min", "Noise floor dB", "Tone dB", "Pitch Hz", "Words/min"]
    cols += ["Listener", "Lowest tenth", "Lowest 10 s at"] if heard else []
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(cols)
    for r in sorted(rows, key=(lambda r: -r["fire"]) if fired else (lambda r: r["order"])):
        row = [r["name"], r.get("recorded") or "", round(r["minutes"], 2)]
        if fired:
            row += [round(r["fire"], 1), round(r["lift"], 2), round(r["movement"], 2), round(r["range"], 2),
                    round(r["brightness"], 1),
                    "; ".join(f"{_clock(t)} ({f:.0f})" for t, f in r["hottest"])]
        if clear:
            row += [round(r[k], n) if r[k] == r[k] else "" for k, n in (("clarity", 1), ("enunciation", 2),
                                                                     ("landing", 2), ("reset", 2))]
        row += [round(r["order"], 1), round(r["clicks"], 2), round(r["noise_floor"], 1), round(r["tone"], 2),
                round(r["pitch"], 1) if r["pitch"] is not None else "", round(r["pace"], 1) if r["pace"] is not None else ""]
        if heard:
            row += [round(r["pesq"], 3), round(r["pesq_low"], 3), "; ".join(_clock(t) for t, _ in r["lowest"])]
        w.writerow(row)
    return out.getvalue()
