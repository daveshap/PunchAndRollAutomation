"""Changes to a mark-up made by method rather than by judgment, and a check of what is left to judge.

  check     the mark-up still holds every word and sound of its transcript, in order; then what to look at:
            short sounds left in (possible clicks), pauses of 0.12 s or more inside a sentence, and kept gaps over
            1.6 s (docs/how-it-works.md, "Pauses").
  declick   strike clicks the way docs/checking.md says ("Clicks left in a finished file"): a click is struck with
            the recorded pauses touching it and one fresh pause of the same total length is written after the
            struck run, so the gap is filled with room tone and no tail of the click is left. It rewrites a click
            struck alone and a short sound left in, and, given the clicks that `trace_clicks` found in the finished
            file, a click inside a kept pause (the pause is struck and written again) or inside a kept breath (the
            breath goes, with the pauses touching it).

Pauses written in by hand are told apart from recorded ones by setting the mark-up beside its transcript: a pause
token where the transcript has no pause next is one written in. Those are never struck here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .markup import STAMP, TOKEN

PAUSE = re.compile(r"\{\s*(\d+(?:\.\d+)?)\s*\}$")
SOUND = re.compile(r"\{\s*sound\s+(\d+(?:\.\d+)?)\s+([+-]?\d+)\s*\}$")
CLICK_MAX = 0.08          # a {sound} this short or shorter is a click; a longer one is a breath


@dataclass
class Tok:
    text: str
    struck: bool
    source: int | None     # its index among the transcript's tokens; None for a pause written in by hand


def _length(text: str) -> float | None:
    m = PAUSE.match(text) or SOUND.match(text)
    return float(m.group(1)) if m else None


def _is_click(text: str) -> bool:
    m = SOUND.match(text)
    return m is not None and float(m.group(1)) <= CLICK_MAX


def _lines(text: str) -> list[tuple[int, str, str]]:
    """(line number, time stamp, body) for every line that starts with a time stamp, outside comments."""
    body = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for n, raw in enumerate(body.splitlines()):
        m = re.match(r"^(\s*)((?:\d+:)?\d+:\d\d(?:\.\d+)?)  (.*)$", raw)
        if m:
            out.append((n, m.group(2), m.group(3)))
    return out


def _tokens(body: str) -> list[list]:
    out, struck = [], False
    for t in TOKEN.findall(body):
        if t == "~~":
            struck = not struck
            continue
        out.append([t, struck])
    return out


def _render(toks: list[Tok]) -> str:
    parts, struck = [], False
    for t in toks:
        text = t.text
        if t.struck and not struck:
            text = "~~" + text
        elif not t.struck and struck:
            parts[-1] = parts[-1] + "~~"
        parts.append(text)
        struck = t.struck
    if struck and parts:
        parts[-1] = parts[-1] + "~~"
    return " ".join(parts)


class MarkedUp:
    """A mark-up set beside its transcript, token by token."""

    def __init__(self, markup: str, transcript: str):
        self.text = markup
        self.lines = markup.split("\n")
        src_lines = _lines(transcript)
        self.source = [t for _, _, body in src_lines for t, _ in _tokens(body)]
        self.rows: list[tuple[int, str, list[Tok]]] = []
        k = 0
        for n, stamp, body in _lines(markup):
            toks = []
            for t, struck in _tokens(body):
                if PAUSE.match(t):
                    if k < len(self.source) and PAUSE.match(self.source[k]):
                        toks.append(Tok(t, struck, k))
                        k += 1
                    else:
                        toks.append(Tok(t, struck, None))
                    continue
                if k >= len(self.source) or self.source[k] != t:
                    raise ValueError(f"line {n + 1}: the mark-up has {t!r} where its transcript has "
                                     f"{self.source[k] if k < len(self.source) else 'nothing'!r}; only ~~ marks and "
                                     "pause lengths may differ")
                toks.append(Tok(t, struck, k))
                k += 1
            self.rows.append((n, stamp, toks))
        if k != len(self.source):
            raise ValueError(f"the mark-up stops before the end of its transcript ({self.source[k]!r} is next)")

    def render(self) -> str:
        lines = list(self.lines)
        for n, stamp, toks in self.rows:
            indent = re.match(r"^(\s*)", lines[n]).group(1)
            lines[n] = f"{indent}{stamp}  {_render(toks)}"
        return "\n".join(lines)

    def where(self, source_index: int):
        for r, (_, _, toks) in enumerate(self.rows):
            for i, t in enumerate(toks):
                if t.source == source_index:
                    return r, i
        return None


def _strike_run(toks: list[Tok], lo: int, hi: int) -> float:
    """Strike toks[lo..hi] and write one fresh pause after them, as long as what was kept there."""
    gap = sum(_length(t.text) or 0.0 for t in toks[lo:hi + 1] if not t.struck)
    for t in toks[lo:hi + 1]:
        t.struck = True
    toks.insert(hi + 1, Tok("{%.2f}" % max(gap, 0.05), False, None))
    return gap


def strike_short_sounds(m: MarkedUp) -> list[str]:
    """Every click (a {sound} of 0.08 s or less) struck with the recorded pauses and clicks touching it."""
    changes = []
    for _, stamp, toks in m.rows:
        k = 0
        while k < len(toks):
            if not _is_click(toks[k].text):
                k += 1
                continue
            lo = hi = k
            touch = lambda t: t.source is not None and (PAUSE.match(t.text) or _is_click(t.text))
            while lo - 1 >= 0 and touch(toks[lo - 1]):
                lo -= 1
            while hi + 1 < len(toks) and touch(toks[hi + 1]):
                hi += 1
            if all(t.struck for t in toks[lo:hi + 1]):
                k = hi + 1
                continue
            gap = _strike_run(toks, lo, hi)
            changes.append(f"{stamp}  click struck with the pauses around it; fresh pause {gap:.2f} s")
            k = hi + 2
    return changes


def strike_traced(m: MarkedUp, rows: list[dict], pieces) -> list[str]:
    """The clicks that trace_clicks found inside a kept pause or a kept sound, struck by the method."""
    shown = {}
    n = 0
    for i, p in enumerate(pieces):
        if getattr(p, "shown", True):
            shown[i] = n
            n += 1
    changes, done = [], set()
    for row in rows:
        k = row.get("piece")
        if k is None or row.get("where") not in ("inside a pause", "inside a sound") or k in done:
            continue
        done.add(k)
        if k not in shown:
            changes.append(f"{row['context']}: the click is in a pause too short to list; left")
            continue
        found = m.where(shown[k])
        if found is None:
            continue
        r, i = found
        stamp, toks = m.rows[r][1], m.rows[r][2]
        t = toks[i]
        if t.struck:
            continue
        if PAUSE.match(t.text):
            t.struck = True
            toks.insert(i + 1, Tok(t.text, False, None))
            changes.append(f"{stamp}  click in a pause: the pause struck and written again ({_length(t.text):.2f} s)")
        else:
            lo, hi = i, i
            if i - 1 >= 0 and PAUSE.match(toks[i - 1].text) and toks[i - 1].source is not None and not toks[i - 1].struck:
                lo = i - 1
            if i + 1 < len(toks) and PAUSE.match(toks[i + 1].text) and toks[i + 1].source is not None and not toks[i + 1].struck:
                hi = i + 1
            gap = _strike_run(toks, lo, hi)
            changes.append(f"{stamp}  click in a breath: the breath struck with the pauses touching it; fresh pause {gap:.2f} s")
    return changes


def strike_mouth_noises(m: MarkedUp, pieces, noises: dict) -> list[str]:
    """Each kept sound that mouth.mouth_noises names a mouth noise, struck with the pauses and clicks touching it.

    A fresh pause of their total length goes after them, so the room is heard there instead and the timeline
    stays as it was."""
    shown, n = {}, 0
    for i, p in enumerate(pieces):
        if getattr(p, "shown", True):
            shown[i] = n
            n += 1
    changes = []
    for k, r in sorted(noises.items()):
        if k not in shown:
            continue
        found = m.where(shown[k])
        if found is None:
            continue
        row, i = found
        stamp, toks = m.rows[row][1], m.rows[row][2]
        if toks[i].struck:
            continue
        lo = hi = i
        touch = lambda t: t.source is not None and not t.struck and (PAUSE.match(t.text) or _is_click(t.text))
        while lo - 1 >= 0 and touch(toks[lo - 1]):
            lo -= 1
        while hi + 1 < len(toks) and touch(toks[hi + 1]):
            hi += 1
        what = toks[i].text
        gap = _strike_run(toks, lo, hi)
        changes.append(f"{stamp}  mouth noise {what} struck with the pauses around it (level jumps {r['jagged_db']:.1f} dB, "
                       f"{r['low']:.0%} under 300 Hz, {r['peak']:.0%} in its loudest 10 ms); fresh pause {gap:.2f} s")
    return changes


def check(m: MarkedUp) -> dict:
    """What is left to judge: short sounds left in, pauses inside a sentence, long kept gaps."""
    clicks, inside, long_gaps = [], [], []
    kept = [(stamp, t) for _, stamp, toks in m.rows for t in toks if not t.struck]
    for stamp, t in kept:
        if _is_click(t.text):
            clicks.append(f"{stamp}  {t.text}")
    prev, gap, gap_toks, gap_at = None, 0.0, [], None
    for stamp, t in kept:
        length = _length(t.text)
        if length is not None:
            gap += length
            gap_toks.append(t.text)
            gap_at = gap_at or stamp
            continue
        if prev is not None and gap_toks:
            if prev[-1] not in ".?!,;:" and gap >= 0.12 and not any(x.startswith("{sound") for x in gap_toks):
                inside.append(f"{gap_at}  {prev} {' '.join(gap_toks)} {t.text}")
            if gap > 1.6:
                long_gaps.append(f"{gap_at}  {prev} ... {gap:.2f} s ... {t.text}")
        prev, gap, gap_toks, gap_at = t.text, 0.0, [], None
    return {"clicks": clicks, "inside": inside, "long": long_gaps}


def check_text(result: dict) -> str:
    out = [f"short sounds left in ({len(result['clicks'])}): " + ("; ".join(result["clicks"]) or "none"),
           f"pauses of 0.12 s or more inside a sentence ({len(result['inside'])}):"]
    out += ["    " + x for x in result["inside"]]
    out.append(f"kept gaps over 1.6 s ({len(result['long'])}):")
    out += ["    " + x for x in result["long"]]
    return "\n".join(out)
