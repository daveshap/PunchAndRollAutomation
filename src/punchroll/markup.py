"""The transcript as a file to mark up, and the marked-up file back as an edit.

punchroll writes out everything it measured, in order: each word, each pause with its length, each
sound that is not a word. Claude reads the whole thing and marks it:

    ~~struck through~~    cut
    {0.85}                a pause, in seconds. Change the number to change the pause.
    {sound 0.28 -31}      a sound that is not a word: how long, and how far under the voice in dB.
                          A breath is usually 0.2 to 0.5 s at -25 or lower; a click is a few hundredths.
    {0.60}                written where there was no pause: put one in.

What is not struck is what the finished file holds, in that order, with those pauses. The program
decides nothing. It checks only that the words in the marked-up file are still the words it wrote,
so a slip of the pen can't move a cut.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pieces import Piece

NEW_LINE_AFTER = 0.5         # a pause this long starts a new line in the transcript; layout only
TOKEN = re.compile(r"~~|\{[^{}]*\}|[^\s{}~]+")
STAMP = re.compile(r"^(\s*(?:~~)?\s*)(?:\d+:)?\d+:\d\d(?:\.\d+)?(?=\s|$)")
HOW_TO = """<!--
Mark-up: what is not struck is what the finished file holds.
  ~~words~~          cut. Strike a pause or a sound the same way.
  {0.85}             a pause, in seconds. Change the number to change the pause.
  {sound 0.28 -31}   a sound that is not a word: its length, and its level in dB against the voice.
  {0.60}             written where there is no pause: put one in.
Each line starts with its time in the recording. Leave the words themselves as they are.
-->"""


@dataclass
class Marks:
    keep: list[bool]                                 # per piece
    length: list[float | None]                       # per piece: a pause's new length, or None to leave it as recorded
    added: dict[int, float] = field(default_factory=dict)    # a pause put in ahead of this piece, where there was none


def clock(t: float) -> str:
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def _token(p: Piece) -> str:
    if p.kind == "quiet":
        return f"{{{p.length:.2f}}}"
    if p.kind == "sound":
        return f"{{sound {p.length:.2f} {p.level:+.0f}}}"
    return re.sub(r"[\s{}~]+", "", p.text) or "-"       # the three characters the mark-up uses never come in a word


def write_transcript(pieces: list[Piece], name: str) -> str:
    """The recording as text, one run of speech to a line, ready to be marked up."""
    words = sum(1 for p in pieces if p.kind == "word")
    span = pieces[-1].b - pieces[0].a
    out = [f"# {name}", "", HOW_TO.replace("-->", f"\n{words:,} words, {clock(span)} from the first to the last.\n-->"), ""]
    line, gap, said = [], 0.0, ""
    for p in pieces:
        if p.kind == "word" or (p.kind == "sound" and not gap):
            if line and (gap >= NEW_LINE_AFTER or (gap >= 0.25 and said[-1:] in ".?!")):
                out += [" ".join(line), ""]
                line = []
            if not line:
                line.append(clock(p.a) + " ")
            gap, said = 0.0, p.text or said
        else:
            gap += p.length
        if p.shown:
            line.append(_token(p))
    out += [" ".join(line), ""]
    return "\n".join(out)


def read_markup(text: str, pieces: list[Piece]) -> Marks:
    """What the marked-up file says to do with each piece. Raises ValueError where it no longer matches the recording."""
    marks = Marks([True] * len(pieces), [None] * len(pieces))
    body = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    i, cutting, opened = 0, False, 0

    def hidden_to(i):                                # a quiet that isn't listed waits for the word after it
        while i < len(pieces) and pieces[i].kind == "quiet" and not pieces[i].shown:
            i += 1
        return i

    for n, raw in enumerate(body.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith(("#", ">")):
            continue
        for tok in TOKEN.findall(STAMP.sub(r"\1", raw)):
            if tok == "~~":
                cutting, opened = not cutting, n
                continue
            pause = re.fullmatch(r"\{\s*(\d+(?:\.\d+)?)\s*\}", tok)
            here = pieces[i] if i < len(pieces) else None
            if pause and here is not None and here.kind == "quiet":          # a pause that was measured, listed or not
                marks.keep[i] = not cutting
                if tok != _token(here) or not here.shown:
                    marks.length[i] = float(pause.group(1))
                i += 1
                continue
            j = hidden_to(i)
            here = pieces[j] if j < len(pieces) else None
            if pause:                                                        # a pause where there was none
                if here is None:
                    raise ValueError(f"line {n}: the pause {tok} comes after the last word; the tail is set in the settings")
                if not cutting:
                    marks.added[j] = marks.added.get(j, 0.0) + float(pause.group(1))
                continue
            if here is None:
                raise ValueError(f"line {n}: '{tok}' is in the mark-up after the recording's last word")
            if tok.startswith("{"):
                if not re.fullmatch(r"\{\s*sound\b[^{}]*\}", tok):
                    raise ValueError(f"line {n}: can't read {tok}")
                if here.kind != "sound":
                    raise ValueError(f"line {n}: {tok} is in the mark-up where the recording has {_token(here)!r} at {clock(here.a)}")
            elif here.kind != "word" or _token(here) != tok:
                raise ValueError(f"line {n}: the mark-up has '{tok}' where the recording has {_token(here)!r} at {clock(here.a)}. "
                                 "Words, pauses and sounds must stay in the file, in order; strike them to cut them.")
            marks.keep[j] = not cutting
            i = j + 1
    if cutting:
        raise ValueError(f"line {opened}: a ~~ is opened here and never closed")
    i = hidden_to(i)
    if i < len(pieces):
        raise ValueError(f"the mark-up stops at {clock(pieces[i].a)}, before the end of the recording ({_token(pieces[i])!r} is next)")
    follows = False                                  # an unlisted quiet goes with the word (or sound) after it
    for k in range(len(pieces) - 1, -1, -1):
        if pieces[k].kind != "quiet":
            follows = marks.keep[k]
        elif not pieces[k].shown and marks.length[k] is None:
            marks.keep[k] = follows
    return marks
