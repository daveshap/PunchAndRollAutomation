"""Checks on a finished file, for after the cut and master.

  readback  every word the mark-up kept is in the finished file, once and in order, and nothing struck came back.
            A recognizer spelling a word two ways ("EU V" and "EUV") shows up too; anything else is a fault.
  clicks    each mouth click the scorecard counts, traced back to the recording and its place in the mark-up,
            so it can be cut: a click inside a kept pause or breath can go (cut that pause and write a fresh
            pause of the same length after it, which is filled with room tone); a click inside a word's span
            can't be cut without cutting into the word.
  lost      words cut from the recording that are never said again: a retake repeats what it replaces, so
            these are either chatter (an aside, a slip, a false start) or something the reader said that the
            edit lost. Read each one.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from .asr import cached_words, transcribe
from .audio import read_mono
from .markup import STAMP, TOKEN, _token
from .models import transcripts_dir
from .text import toks


def heard_words(path, rec=None, log=print) -> list[dict]:
    """The recognizer's words for a file: cached, or transcribed now."""
    d = cached_words(path, transcripts_dir())
    if d is None:
        x, sr = read_mono(path)
        d = transcribe(path, x, sr, rec, transcripts_dir(), None, log)
    return d["words"]


def kept_words(markup: str) -> list[str]:
    """The word tokens a marked-up transcript keeps, in order."""
    body = re.sub(r"<!--.*?-->", "", markup, flags=re.S)
    kept, cutting = [], False
    for raw in body.splitlines():
        if not raw.strip() or raw.lstrip().startswith(("#", ">")):
            continue
        for tok in TOKEN.findall(STAMP.sub(r"\1", raw)):
            if tok == "~~":
                cutting = not cutting
            elif not cutting and not tok.startswith("{"):
                kept.append(tok)
    return toks(" ".join(kept))


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def edit_map(finished) -> dict:
    p = Path(finished).with_name(Path(finished).stem + ".edit.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def readback(markup: str, words: list[dict], edl: list[dict] | None = None) -> list[dict]:
    """Where the finished file's words differ from the words the mark-up kept."""
    kept = kept_words(markup)
    heard, at = [], []
    for w in words:
        for t in toks(w["text"]):
            heard.append(t)
            at.append(w["start"])
    joins = sorted({e["clean_in"] for e in (edl or [])[1:]})
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=kept, b=heard, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        t = at[b0] if b0 < len(at) else (at[-1] if at else 0.0)
        out.append({"at": t, "kept": " ".join(kept[a0:a1]), "heard": " ".join(heard[b0:b1]),
                    "before": " ".join(kept[max(0, a0 - 3):a0]), "after": " ".join(kept[a1:a1 + 3]),
                    "spelling": re.sub(r"[^a-z]", "", "".join(kept[a0:a1])) == re.sub(r"[^a-z]", "", "".join(heard[b0:b1])),
                    "nearest_join": min((abs(j - t) for j in joins), default=None)})
    return out


def readback_text(rows: list[dict], kept: int, heard: int) -> str:
    lines = []
    for r in rows:
        near = f"  (nearest join {r['nearest_join']:.1f} s away)" if r["nearest_join"] is not None else ""
        lines.append(f"{_clock(r['at'])}  kept: {r['before']} [{r['kept']}] {r['after']}")
        lines.append(f"{'':8s}heard: [{r['heard']}]{'  spelling only' if r['spelling'] else ''}{near}")
    lines.append(f"{kept} words kept by the mark-up, {heard} heard in the finished file, {len(rows)} difference(s)")
    return "\n".join(lines)


def trace_clicks(raw_path, fin_path, settings, within: float = 30.0, log=print, pieces_out: list | None = None) -> list[dict]:
    """Each click the scorecard counts in the finished file (within `within` dB of its level), traced back.

    Each row names the recording's piece the click falls in (`piece`, an index into the recording's pieces); pass a
    list as `pieces_out` to have those pieces added to it."""
    from .measure import clicks
    from .pipeline import measure
    x, sr = read_mono(fin_path)
    edl = edit_map(fin_path).get("edl", [])
    if not edl:
        raise ValueError(f"no edit map beside {fin_path}: trace_clicks needs the cut's .edit.json")
    _, _, _, pieces = measure(raw_path, settings, log=lambda *a: None)
    if pieces_out is not None:
        pieces_out.extend(pieces)
    out = []
    for t, level in clicks(x, sr):
        if level <= -within:
            continue
        seg = next((e for e in edl if e["clean_in"] - 1e-6 <= t <= e["clean_out"] + 1e-6), None)
        if seg is None:
            out.append({"at": t, "level": level, "raw": None, "where": "room tone added by the edit, or the head or tail",
                        "context": "", "piece": None})
            continue
        r = seg["raw_in"] + (t - seg["clean_in"])
        k = next((i for i, p in enumerate(pieces) if p.a <= r <= p.b), None)
        if k is None:
            k = min(range(len(pieces)), key=lambda i: min(abs(pieces[i].a - r), abs(pieces[i].b - r)))
        lo, hi = k, k
        while lo > 0 and pieces[lo].kind != "word":
            lo -= 1
        while hi < len(pieces) - 1 and pieces[hi].kind != "word":
            hi += 1
        ctx = " ".join((f"*{_token(pieces[i])}*" if i == k else _token(pieces[i])) for i in range(lo, hi + 1))
        out.append({"at": t, "level": level, "raw": r, "where": "inside a word" if pieces[k].kind == "word" else
                    ("inside a sound" if pieces[k].kind == "sound" else "inside a pause"), "context": ctx, "piece": k})
    return out


def clicks_text(rows: list[dict]) -> str:
    lines = [f"{_clock(r['at'])}  {r['level']:+.0f} dB  {r['where']}"
             + (f", recording {_clock(r['raw'])}: {r['context']}" if r["raw"] is not None else "") for r in rows]
    lines.append(f"{len(rows)} click(s)")
    return "\n".join(lines)


def lost_words(raw_words: list[dict], fin_words: list[dict], ahead: int = 80) -> list[dict]:
    """Stretches cut from the recording whose words don't come back within `ahead` words of the finished file."""
    raw = [(t, w["start"]) for w in raw_words for t in toks(w["text"])]
    fin = [t for w in fin_words for t in toks(w["text"])]
    R = [t for t, _ in raw]
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=R, b=fin, autojunk=False).get_opcodes():
        if op not in ("delete", "replace"):
            continue
        cut = R[a0:a1]
        window = " " + " ".join(fin[max(0, b0 - 3): b0 + ahead]) + " "
        missing = [w for k, w in enumerate(cut)                         # a cut word is accounted for when it comes back
                   if f" {w} " not in window and not any(f" {p} " in window for p in
                                                         (" ".join(cut[k:k + 2]), " ".join(cut[max(0, k - 1):k + 1])))]
        if missing and len(missing) >= max(1, len(cut) // 3):
            out.append({"at": raw[a0][1], "cut": " ".join(cut), "finished": " ".join(fin[b0:b1]) if op == "replace" else ""})
    return out


def lost_text(rows: list[dict]) -> str:
    lines = [f"recording {_clock(r['at'])}  cut: {r['cut'][:200]}" + (f"  | finished has: {r['finished'][:80]}" if r["finished"] else "")
             for r in rows]
    lines.append(f"{len(rows)} cut stretch(es) not said again")
    return "\n".join(lines)
