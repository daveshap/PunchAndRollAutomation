"""Score every finished chapter of a project, side by side: which recordings are cleanest and most alike.

Made for choosing among recordings (which ones go into a voice-clone training set, which chapter to
re-record first), where pass or fail against ACX is not enough to tell them apart. One row per chapter
that has a finished WAV and the edit list saved beside it, which lines the recording up with the finished file.

Columns:
  clicks     mouth clicks alone in pauses, per minute, counting those within 30 dB of the file's level
  room       how far the quietest moments of the RECORDING sit under the voice (300-4000 Hz); bigger is quieter
  cut        the share of the recorded words that were cut: a rough measure of how fluent the read was
  cuts       places per minute where the edit removed something
  tone       how far the file's balance by octave is from the middle of the set, in dB; smaller is more alike
  pitch      median pitch of the voice in Hz
  pace       words a minute
  breaths    breaths found in pauses the edit kept whole, and how many of them come through whole
  listener   with --listener: a trained model's estimate of PESQ, 1 to 4.5
  order      the average of the file's rank on clicks, tone, cut and (if run) listener; 1 is best

Use the individual measurements to compare the recordings and inspect specific passages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .asr import Recognizer, transcribe
from .audio import read_mono, resample
from .config import auto_threads, load_settings
from .measure import band_db, breaths_through, clicks_per_minute, pitch, room_under_voice, tone, tone_distance
from .models import transcripts_dir
from .pipeline import recording, saved_edit

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _level(db: np.ndarray, spans, step: float) -> float:
    """Mean power, in dB, of the steps inside the (start, end) spans."""
    parts = [db[int(a / step):int(b / step)] for a, b in spans]
    parts = [p for p in parts if len(p)]
    return float(10 * np.log10(np.mean(10 ** (np.concatenate(parts) / 10)))) if parts else -120.0


def kept_pauses(words: list[dict], edl: list[dict]) -> tuple[list, list]:
    """Words the edit kept, as (start, end) in the recording and in the finished file, and the pauses it kept whole.

    A pause counts when both words around it sit in one kept stretch of the recording, so nothing was cut
    from it and no room tone was let into it: (start in the recording, end in the recording, start in the
    finished file).
    """
    def span(t):
        return next((e for e in edl if e["raw_in"] <= t <= e["raw_out"]), None)

    kept = []
    for w in words:
        e = span(w["start"])
        if e is not None and w["end"] <= e["raw_out"]:
            kept.append((w, e))
    gaps = [(a["end"], b["start"], ea["clean_in"] + a["end"] - ea["raw_in"])
            for (a, ea), (b, eb) in zip(kept, kept[1:]) if ea is eb and b["start"] - a["end"] >= 0.15]
    spans = [((w["start"], w["end"]), (e["clean_in"] + w["start"] - e["raw_in"], e["clean_in"] + w["end"] - e["raw_in"]))
             for w, e in kept]
    return spans, gaps


def score_chapter(raw: np.ndarray, fin: np.ndarray, sr: int, words: list[dict], res: dict, listener: bool = False) -> dict:
    """The row for one chapter. raw: the recording; fin: the finished file; res: the saved edit (its list and counts)."""
    s = res["summary"]
    minutes = len(fin) / sr / 60
    spans, gaps = kept_pauses(words, res["edl"])
    raw_db, step = band_db(raw, sr, 500, 8000)
    fin_db, _ = band_db(fin, sr, 500, 8000)
    br = breaths_through(raw_db, fin_db, step, gaps, _level(raw_db, [a for a, _ in spans], step),
                         _level(fin_db, [b for _, b in spans], step))
    row = {"minutes": minutes, "clicks": clicks_per_minute(fin, sr), "room": room_under_voice(raw, sr),
           "cut": 100 * s["words_cut"] / max(1, s["words_heard"]), "cuts": s["cuts"] / max(minutes, 1e-9),
           "tone_bands": tone(fin, sr), "pitch": pitch(fin, sr),
           "pace": (s["words_heard"] - s["words_cut"]) / max(0.1, minutes - 0.075),
           "breaths": len(br), "breaths_whole": sum(1 for b in br if b["through"] > 0.8),
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
    keys = [("clicks", False), ("tone", False), ("cut", False)]
    if rows and all(r["pesq"] is not None for r in rows):
        keys.append(("pesq", True))
    places = np.zeros(len(rows))
    for key, high_is_good in keys:
        order = sorted(range(len(rows)), key=lambda i: rows[i][key], reverse=high_is_good)
        for place, i in enumerate(order, 1):
            places[i] += place
    for r, total in zip(rows, places):
        r["order"] = float(total / len(keys))


def scorecard(project, listener: bool = False, log=print) -> list[dict]:
    """Score every chapter of a project file that has a finished WAV in its output folder."""
    proj_path = Path(project)
    proj = tomllib.loads(proj_path.read_text(encoding="utf-8"))
    base = proj_path.parent
    settings = load_settings(base / proj["config"] if proj.get("config") else None)
    out = base / proj.get("out", "edited")
    cache, holder, rows = transcripts_dir(), {}, []

    def recognizer():                                    # loaded only if a recording has no cached transcript
        if "r" not in holder:
            holder["r"] = Recognizer(auto_threads(settings.threads), log)
        return holder["r"]

    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        fin_path, res = out / f"{name}.wav", saved_edit(out, name)
        if not fin_path.is_file() or res is None or not ch.get("audio"):
            log(f"{name}: no finished WAV or no edit list beside it, skipped")
            continue
        audio = recording(base, name, ch["audio"])
        x, sr = read_mono(audio)
        words = transcribe(audio, x, sr, recognizer, cache, None, log)["words"]
        fin, fsr = read_mono(fin_path)
        row = score_chapter(x, resample(fin, fsr, sr), sr, words, res, listener)
        row["name"] = name
        rows.append(row)
        log(f"{name}: clicks {row['clicks']:.1f}/min, cut {row['cut']:.0f} %, room {row['room']:.0f} dB"
            + (f", listener {row['pesq']:.2f}" if row["pesq"] is not None else ""))
    rank_rows(rows)
    return rows


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:02.0f}"


def scorecard_markdown(rows: list[dict]) -> str:
    total = sum(r["minutes"] for r in rows)
    heard = bool(rows) and all(r["pesq"] is not None for r in rows)
    md = ["# Recording scorecard", "",
          f"{len(rows)} finished recordings, {int(total // 60)} h {total % 60:.0f} min. Best first by \"order\": the average of each "
          "file's rank on clicks, tone, cut" + (" and listener" if heard else "") + ".", "",
          "| Recording | Min | Order | Clicks/min | Room dB | Cut % | Cuts/min | Tone dB | Pitch Hz | Words/min | Breaths (whole) |"
          + (" Listener | Lowest tenth | Lowest 10 s at |" if heard else ""),
          "|---|---|---|---|---|---|---|---|---|---|---|" + ("---|---|---|" if heard else "")]
    for r in sorted(rows, key=lambda r: r["order"]):
        line = (f"| {r['name']} | {r['minutes']:.1f} | {r['order']:.1f} | {r['clicks']:.1f} | {r['room']:.0f} | {r['cut']:.0f} | "
                f"{r['cuts']:.1f} | {r['tone']:.1f} | {r['pitch']:.0f} | {r['pace']:.0f} | {r['breaths']} ({r['breaths_whole']}) |"
                if r["pitch"] is not None else
                f"| {r['name']} | {r['minutes']:.1f} | {r['order']:.1f} | {r['clicks']:.1f} | {r['room']:.0f} | {r['cut']:.0f} | "
                f"{r['cuts']:.1f} | {r['tone']:.1f} | - | {r['pace']:.0f} | {r['breaths']} ({r['breaths_whole']}) |")
        if heard:
            line += f" {r['pesq']:.2f} | {r['pesq_low']:.2f} | {', '.join(_clock(t) for t, _ in r['lowest'])} |"
        md.append(line)
    md += ["", "Clicks: mouth clicks alone in pauses. Room: how far the recording's quietest moments sit under the voice. "
           "Cut: the share of the recorded words that were cut. Tone: distance from the middle of the set. "
           "Breaths: found in pauses the edit kept whole, and how many of those come through whole."
           + (" Listener: a trained model's estimate of PESQ out of 4.5." if heard else "")]
    return "\n".join(md) + "\n"
