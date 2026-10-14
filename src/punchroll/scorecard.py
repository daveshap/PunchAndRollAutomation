"""Score every finished recording of a project, side by side: which finished files are cleanest and most alike.

Made for choosing among recordings (which ones go into a voice-clone training set, which chapter to
re-record first), where pass or fail against ACX is not enough to tell them apart. Everything is measured
on the finished file itself, never on the raw recording: how a take went in the room doesn't score.

Columns:
  clicks       mouth clicks alone in pauses, per minute, counting those within 30 dB of the file's level
  noise floor  the finished file's noise floor in dB, as ACX measures it
  tone         how far the file's balance by octave is from the middle of the set, in dB; smaller is more alike
  pitch        median pitch of the voice in Hz
  pace         words a minute, from the transcript of the finished file if it has been transcribed
  listener     with --listener: a trained model's estimate of PESQ, 1 to 4.5
  order        the average of the file's rank on clicks, tone and (if run) listener; 1 is best

Use the individual measurements to compare the recordings and inspect specific passages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .asr import cached_words
from .audio import noise_floor_db, read_mono
from .measure import clicks_per_minute, pitch, tone, tone_distance
from .models import transcripts_dir

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def score_file(fin: np.ndarray, sr: int, words: int | None = None, listener: bool = False) -> dict:
    """The row for one finished file. words: how many words its transcript has, if it has been transcribed."""
    minutes = len(fin) / sr / 60
    row = {"minutes": minutes, "clicks": clicks_per_minute(fin, sr), "noise_floor": noise_floor_db(fin, sr),
           "tone_bands": tone(fin, sr), "pitch": pitch(fin, sr),
           "pace": words / max(0.1, minutes) if words else None,
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


def _word_count(fin_path: Path) -> int | None:
    """Words in the cached transcript of the finished MP3 or WAV (punchroll verify leaves one), if there is one."""
    for p in (fin_path.with_suffix(".mp3"), fin_path):
        if p.is_file():
            d = cached_words(p, transcripts_dir())
            if d is not None:
                return len(d["words"])
    return None


def scorecard(project, listener: bool = False, log=print) -> list[dict]:
    """Score every chapter of a project file that has a finished WAV in its output folder."""
    proj_path = Path(project)
    proj = tomllib.loads(proj_path.read_text(encoding="utf-8"))
    out = proj_path.parent / proj.get("out", "edited")
    rows = []
    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        fin_path = out / f"{name}.wav"
        if not fin_path.is_file():
            log(f"{name}: no finished WAV, skipped")
            continue
        fin, sr = read_mono(fin_path)
        row = score_file(fin, sr, _word_count(fin_path), listener)
        row["name"] = name
        rows.append(row)
        log(f"{name}: clicks {row['clicks']:.1f}/min, noise floor {row['noise_floor']:.1f} dB"
            + (f", listener {row['pesq']:.2f}" if row["pesq"] is not None else ""))
    rank_rows(rows)
    return rows


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:02.0f}"


def scorecard_markdown(rows: list[dict]) -> str:
    total = sum(r["minutes"] for r in rows)
    heard = bool(rows) and all(r["pesq"] is not None for r in rows)
    md = ["# Recording scorecard", "",
          f"{len(rows)} finished recordings, {int(total // 60)} h {total % 60:.0f} min, all measured on the finished files. "
          "Best first by \"order\": the average of each file's rank on clicks, tone" + (" and listener" if heard else "") + ".", "",
          "| Recording | Min | Order | Clicks/min | Noise floor dB | Tone dB | Pitch Hz | Words/min |"
          + (" Listener | Lowest tenth | Lowest 10 s at |" if heard else ""),
          "|---|---|---|---|---|---|---|---|" + ("---|---|---|" if heard else "")]
    for r in sorted(rows, key=lambda r: r["order"]):
        pitch_ = f"{r['pitch']:.0f}" if r["pitch"] is not None else "-"
        pace = f"{r['pace']:.0f}" if r["pace"] is not None else "-"
        line = (f"| {r['name']} | {r['minutes']:.1f} | {r['order']:.1f} | {r['clicks']:.1f} | {r['noise_floor']:.1f} | "
                f"{r['tone']:.1f} | {pitch_} | {pace} |")
        if heard:
            line += f" {r['pesq']:.2f} | {r['pesq_low']:.2f} | {', '.join(_clock(t) for t, _ in r['lowest'])} |"
        md.append(line)
    md += ["", "Clicks: mouth clicks alone in pauses. Noise floor: as ACX measures it. Tone: how far the file's balance of "
           "low, middle and high frequencies is from the middle of the set. Words/min: from the finished file's transcript."
           + (" Listener: a trained model's estimate of PESQ out of 4.5." if heard else "")]
    return "\n".join(md) + "\n"
