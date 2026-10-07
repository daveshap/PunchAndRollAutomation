"""Check an edited chapter the way a proofer and ACX would.

Re-transcribes the finished file from scratch, aligns it to the script (allowing
restarts, so any that survived the edit show up), lists what still differs, and
measures the ACX specs on the file itself.
"""
from __future__ import annotations

from pathlib import Path

import soundfile as sf

from .align import Aligner, harmonize, near
from .asr import transcribe
from .audio import read_mono
from .master import acx_metrics
from .report import fmt
from .text import Line, toks


def verify(path, lines: list[Line], rec, cache_dir, settings, log=print) -> dict:
    x, sr = read_mono(path)
    tr = transcribe(path, x, sr, rec, cache_dir, log=log)
    words = tr["words"]
    hyp, hyp_w = [], []
    for wi, w in enumerate(words):
        for t in toks(w["text"]):
            hyp.append(t)
            hyp_w.append(wi)
    line_toks, hyp, hyp_w = harmonize([ln.tokens for ln in lines], hyp, hyp_w)
    script, sent_of = [], []
    for k, lt in enumerate(line_toks):
        script += lt
        sent_of += [k] * len(lt)
    ev, cost = Aligner(hyp, script, settings.align).run()

    def at(i):
        return words[hyp_w[min(i, len(hyp) - 1)]]["start"] if hyp else 0.0

    problems = []
    for e in ev:
        kind = e[0]
        if kind in ("restart", "skip"):
            i = min(e[1], len(hyp) - 1)
            problems.append((at(i), kind, f"line {sent_of[min(e[3], len(sent_of) - 1)] + 1}",
                             " ".join(hyp[max(0, i - 5):i]) + " ‖ " + " ".join(hyp[i:i + 5])))
        elif kind == "ins":
            problems.append((at(e[1]), "extra word", f"'{hyp[e[1]]}'", " ".join(hyp[max(0, e[1] - 4):e[1] + 5])))
        elif kind == "sub" and not near(hyp[e[1]], script[e[2]]):
            problems.append((at(e[1]), "differs", f"line {sent_of[e[2]] + 1}: script '{script[e[2]]}', heard '{hyp[e[1]]}'",
                             " ".join(hyp[max(0, e[1] - 4):e[1] + 5])))
        elif kind == "del":
            problems.append((at(e[1]), "missing", f"line {sent_of[e[2]] + 1}: '{script[e[2]]}'",
                             " ".join(hyp[max(0, e[1] - 4):e[1] + 4])))
    problems.sort(key=lambda p: p[0])
    metrics = acx_metrics(x, sr)
    info = sf.info(str(path))
    dur = len(x) / sr
    metrics |= {"head_s": round(words[0]["start"], 2) if words else None,
                "tail_s": round(dur - words[-1]["end"], 2) if words else None,
                "sample_rate": info.samplerate, "channels": info.channels, "format": info.format,
                "approx_kbps": round(Path(path).stat().st_size * 8 / dur / 1000) if dur else None}
    return {"file": str(path), "duration": fmt(dur), "words_heard": len(words), "alignment_cost": cost,
            "restarts_left": sum(1 for p in problems if p[1] == "restart"),
            "problems": [{"at": fmt(p[0]), "kind": p[1], "what": p[2], "context": p[3]} for p in problems],
            "acx": metrics}


def verify_markdown(v: dict) -> str:
    a = v["acx"]
    md = [f"# Check: {Path(v['file']).name}", "",
          f"Duration {v['duration']} · words heard {v['words_heard']} · restarts left {v['restarts_left']}", "",
          "## ACX", "", "| Measure | Value | Target |", "|---|---|---|",
          f"| RMS loudness | {a['rms_db']} dB | −23 to −18 dB |",
          f"| Peak | {a['sample_peak_db']} dB (true peak {a['true_peak_db']} dB) | below −3 dB |",
          f"| Noise floor | {a['noise_floor_db']} dB | below −60 dB |",
          f"| Room tone at head / tail | {a['head_s']} s / {a['tail_s']} s | 1 to 5 s |",
          f"| Format | {a['format']}, {a['sample_rate']} Hz, {a['channels']} channel(s), about {a['approx_kbps']} kbps | MP3, 44,100 Hz, 192 kbps CBR, mono |",
          "", "## Differences from the script", "",
          "The recognizer mishears sometimes; treat these as places to listen, not verdicts.", ""]
    if v["problems"]:
        md += ["| At | Kind | What | Heard around it |", "|---|---|---|---|"]
        md += [f"| {p['at']} | {p['kind']} | {p['what']} | {p['context']} |" for p in v["problems"]]
    else:
        md.append("None.")
    return "\n".join(md) + "\n"
