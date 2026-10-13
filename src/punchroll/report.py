"""What was done to a recording: a Markdown report to read, and the edit list as JSON for the scorecard."""
from __future__ import annotations

import json
from pathlib import Path

from .markup import clock
from .proof import manuscript_markdown


def _ok(flag: bool) -> str:
    return "pass" if flag else "CHECK"


def _cell(s: str, n: int = 200) -> str:
    s = s.replace("|", "/").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def _at(t) -> str:
    return "-" if t is None else clock(t)


def write_reports(out_dir: Path, name: str, res: dict, audio: str, markup: str, metrics: dict | None) -> dict:
    s = res["summary"]
    data = {"name": name, "audio": audio, "markup": markup, "summary": s, "master": metrics,
            "cuts": res["cuts"], "pauses": res["pauses"], "edl": res["edl"]}
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
    md += [f"| {_at(c['raw'])} | {_at(c['clean'])} | {c['seconds']:.2f} | "
           + ("-" if c["pause_s"] is None else f"{c['pause_s']:.2f} s") + f" | {_cell(c['words'])} |" for c in res["cuts"]]
    changed = [j for j in res["pauses"] if j["was_s"] is not None]
    if changed:
        md += ["", "## Pauses changed", "", "| Recorded at | Edited at | Was | Now |", "|---|---|---|---|"]
        md += [f"| {_at(j['raw'])} | {_at(j['clean'])} | {j['was_s']:.2f} s | {j['now_s']:.2f} s |" for j in changed]
    (out_dir / f"{stem}.report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return data
