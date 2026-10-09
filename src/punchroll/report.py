"""Edit reports: JSON for tools, CSV for the edit list, Markdown for people."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def fmt(t) -> str:
    if t is None:
        return "-"
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def where(t, takes) -> str:
    """Timeline seconds -> 'file.wav 12:34.5'."""
    if t is None:
        return "-"
    for tk in reversed(takes):
        if t >= tk.start - 1e-6:
            return f"{Path(tk.path).name} {fmt(t - tk.start)}"
    return fmt(t)


def _ok(flag: bool) -> str:
    return "pass" if flag else "CHECK"


def write_reports(out_dir: Path, name: str, res: dict, takes, metrics: dict | None, script_desc: str) -> dict:
    s = res["summary"]
    data = {"name": name, "script": script_desc,
            "takes": [{"file": tk.path, "start_s": round(tk.start, 3), "duration_s": round(tk.duration, 3),
                       "gain_db": round(tk.gain_db, 1)} for tk in takes],
            "summary": s, "master": metrics,
            "pickups": [dict(p, clean_at=fmt(p["clean"]), raw_at=where(p["raw"], takes)) for p in res["pickups"]],
            "minor_differences": res["minor"], "comps": res["comps"],
            "cuts": [dict(c, raw_at=where(c["raw"], takes)) for c in res["cuts"]],
            "pause_edits": [dict(j, raw_at=where(j["raw"], takes)) for j in res["join_log"]]}
    (out_dir / f"{name}.report.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    with open(out_dir / f"{name}.edl.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "source_in", "source_out", "edited_in", "edited_out", "join_before"])
        for e in res["edl"]:
            tk = take_of(e["raw_in"], takes)
            w.writerow([Path(tk.path).name, fmt(e["raw_in"] - tk.start), fmt(e["raw_out"] - tk.start),
                        fmt(e["clean_in"]), fmt(e["clean_out"]), e["join"]])

    md = [f"# {name}", "",
          f"Script: {script_desc}  ",
          f"Recording: {s['raw_minutes']:.1f} min in {len(takes)} file(s) → edited: {s['edited_minutes']:.1f} min  ",
          f"Lines found: {s['lines_found']} of {s['lines']} · restarts cut: {s['restarts']} · "
          f"lines with retakes: {s['lines_with_retakes']} · two-take splices: {s['comps']} · "
          f"words cut: {s['words_cut']} of {s['words_heard']}"
          + (f" · stray sounds cut: {s['stray_sounds']}" if s.get("stray_sounds") else ""), ""]
    if metrics:
        mp3 = metrics.get("mp3_true_peak_db")
        in_mp3 = f", and {mp3} dB in the MP3" if mp3 is not None else ""
        wav = f"{metrics['wav_bits']}-bit WAV and a " if metrics.get("wav_bits") else ""
        quieter = (f"Noise reduction: the room's noise turned down by {metrics['noise_reduction_db']:g} dB, "
                   "set in [master]. ") if metrics.get("noise_reduction_db") else ""
        md += ["## ACX check", "",
               "| Measure | Value | ACX range | |", "|---|---|---|---|",
               f"| RMS loudness | {metrics['rms_db']} dB | −23 to −18 dB | {_ok(metrics['rms_ok'])} |",
               f"| True peak | {metrics['true_peak_db']} dB{in_mp3} (highest sample {metrics['sample_peak_db']} dB) "
               f"| −3 dB or lower | {_ok(metrics['peak_ok'])} |",
               f"| Noise floor | {metrics['noise_floor_db']} dB | below −60 dB | {_ok(metrics['noise_ok'])} |",
               "", "Room tone: 1–5 s at the head and tail, set in [pauses] head/tail. " + quieter
               + f"Export: {wav}44.1 kHz mono MP3, constant bit rate.", ""]
    md += ["## Pickups", ""]
    if res["pickups"]:
        md += ["Lines whose kept reading still differs from the script. Check by ear; the recognizer can mishear too.", "",
               "| Line | Edited at | Recorded at | What differs | Text |", "|---|---|---|---|---|"]
        for p in res["pickups"]:
            md.append(f"| {p['line']} | {fmt(p['clean'])} | {where(p['raw'], takes)} | {p['problem']} | {_cell(p['text'])} |")
    else:
        md.append("None. Every line was found and matches the script.")
    if res["minor"]:
        md += ["", "Small differences (articles, plurals, spellings the recognizer varies on): "
               + "; ".join(f"line {m['line']}: '{m['book']}' → '{m['read']}'" for m in res["minor"][:40])]
    md += ["", "## Cuts", "", "| Recorded at | Why | Words |", "|---|---|---|"]
    for c in res["cuts"]:
        md.append(f"| {where(c['raw'], takes)} | {c['why']} | {_cell(c['words'], 120)} |")
    if res["comps"]:
        md += ["", "## Two-take splices", ""]
        md += [f"- Line {c['line']}: spliced before \"{c['splice_before']}\" to fix a slip in the last take" for c in res["comps"]]
    md += ["", "## Pauses", "",
           f"Joins kept as recorded: {s['joins']['natural']} · pauses retimed: {s['joins']['pause retimed']} · "
           f"joins rebuilt after a cut: {s['joins']['cut']}", ""]
    (out_dir / f"{name}.report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return data


def take_of(t, takes):
    for tk in reversed(takes):
        if t >= tk.start - 1e-6:
            return tk
    return takes[0]


def _cell(s: str, n: int = 160) -> str:
    s = s.replace("|", "/").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"
