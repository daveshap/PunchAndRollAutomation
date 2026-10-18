"""What was done to a recording: a Markdown report to read, and the edit list as JSON."""
from __future__ import annotations

import json
from pathlib import Path

from .proof import _cell, manuscript_markdown
from .text import toks


def _ok(flag: bool) -> str:
    return "pass" if flag else "CHECK"


def _at(t) -> str:
    if t is None:
        return "-"
    seconds, milliseconds = divmod(round(max(0, float(t)) * 1000), 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def removed_words_not_retained(removed: list[dict], kept: list[dict]) -> list[dict]:
    """Source words containing normalized tokens absent from the entire retained transcript."""
    retained = {t for word in kept for t in toks(word["text"])}
    return [dict(word, unmatched_tokens=missing) for word in removed
            if (missing := [t for t in toks(word["text"]) if t not in retained])]


def write_reports(out_dir: Path, name: str, res: dict, audio: str, markup: str, metrics: dict | None) -> dict:
    s = res["summary"]
    data = {"name": name, "audio": audio, "markup": markup, "summary": s, "master": metrics,
            "cuts": res["cuts"], "pauses": res["pauses"], "edl": res["edl"]}
    for key in ("kept", "sounds", "removed_words", "render_version"):
        if key in res:
            data[key] = res[key]
    if "removed_words" in res and "kept" in res:
        data["removed_words_not_retained"] = removed_words_not_retained(res["removed_words"], res["kept"])
    if res.get("manuscript"):
        data["manuscript"] = res["manuscript"]
    stem = name if metrics else f"{name}.dry-run"      # a dry run never overwrites a finished recording's files
    if metrics:
        (out_dir / f"{name}.edit.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    md = [f"# {name}", "",
          f"Recording: {Path(audio).name}, {s['raw_minutes']:.1f} min → {s['edited_minutes']:.1f} min  ",
          f"Mark-up: {Path(markup).name}  ",
          f"Cuts: {s['cuts']} · words cut: {s['words_cut']} of {s['words_heard']} · sounds cut: {s['sounds_cut']} · "
          f"pauses changed: {s['pauses_changed']}", ""]
    if metrics:
        mp3 = metrics.get("mp3_true_peak_db")
        in_mp3 = f", and {mp3} dB in the MP3" if mp3 is not None else ""
        quieter = (f" Noise reduction: the room's noise turned down by {metrics['noise_reduction_db']:g} dB."
                   if metrics.get("noise_reduction_db") else "")
        if metrics.get("mouth_clicks"):
            quieter += f" Mouth clicks covered: {metrics['mouth_clicks']}."
        md += ["## ACX check", "",
               "| Measure | Value | ACX range | |", "|---|---|---|---|",
               f"| RMS loudness | {metrics['rms_db']} dB | −23 to −18 dB | {_ok(metrics['rms_ok'])} |",
               f"| True peak | {metrics['true_peak_db']} dB{in_mp3} (highest sample {metrics['sample_peak_db']} dB) "
               f"| −3 dB or lower | {_ok(metrics['peak_ok'])} |",
               f"| Noise floor | {metrics['noise_floor_db']} dB | below −60 dB | {_ok(metrics['noise_ok'])} |",
               "", f"Room tone at the head and tail is set in the settings.{quieter}", ""]
    else:
        md += ["Dry run: nothing was rendered or mastered.", ""]
    if res.get("manuscript"):
        md += [f"Manuscript: {res['manuscript']['script']}", ""] + manuscript_markdown(res["manuscript"]) + [""]
    md += ["## Cuts", "", "Everything the mark-up struck, in order, and the pause that now stands between the words either side.", "",
           "| Recorded at | Edited at | Seconds out | Pause left | What |", "|---|---|---|---|---|"]
    md += [f"| {_at(c['raw'])} | {_at(c['clean'])} | {c['seconds']:.3f} | "
           + ("-" if c["pause_s"] is None else f"{c['pause_s']:.3f} s") + f" | {_cell(c['words'])} |" for c in res["cuts"]]
    if "removed_words_not_retained" in data:
        md += ["", "## Removed words absent from the retained transcript", "",
               "Every cut word containing a normalized token that appears nowhere in the retained transcript. "
               "Vocabulary uses the same number and spelling normalization as manuscript proofing.", ""]
        if data["removed_words_not_retained"]:
            md += ["| Recorded from | Recorded to | Removed word | Tokens absent |", "|---|---|---|---|"]
            md += [f"| {_at(w['raw'])} | {_at(w['raw_end'])} | {_cell(w['text'])} | "
                   f"{_cell(' '.join(w['unmatched_tokens']))} |" for w in data["removed_words_not_retained"]]
        else:
            md.append("None.")
    if "sounds" in res:
        md += ["", "## Nonword sounds", "",
               "Every marked nonword sound, including those retained, with its measured level relative to the voice.", ""]
        if res["sounds"]:
            md += ["| Piece | Decision | Recorded from | Recorded to | Edited from | Edited to | Seconds | Level (dB) |",
                   "|---|---|---|---|---|---|---|---|"]
            md += [f"| {p['piece']} | {'kept' if p['kept'] else 'cut'} | {_at(p['raw'])} | {_at(p['raw_end'])} | "
                   f"{_at(p['at'])} | {_at(p['end'])} | {p['seconds']:.3f} | "
                   + ("-" if p.get("level_db") is None else f"{p['level_db']:.1f}") + " |" for p in res["sounds"]]
        else:
            md.append("None.")
    changed = [j for j in res["pauses"] if j["was_s"] is not None]
    if changed:
        md += ["", "## Pauses changed", "", "| Recorded at | Edited at | Was | Now |", "|---|---|---|---|"]
        md += [f"| {_at(j['raw'])} | {_at(j['clean'])} | {j['was_s']:.3f} s | {j['now_s']:.3f} s |" for j in changed]
    (out_dir / f"{stem}.report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return data
