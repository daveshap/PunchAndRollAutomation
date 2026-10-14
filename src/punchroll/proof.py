"""What was read, set beside the manuscript: every place the two differ, with the manuscript's sentence and the time.

A report, and nothing more. It never decides what is cut; Claude's mark-up does that. It is for work that
has to follow a script word for word, where the differences are the pickup list, and for proofing audio
that is already finished.
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from html import escape

from .markup import clock
from .text import Line, toks

ARTICLES = {"a", "an", "the", "this", "that", "these", "those"}
SMALL = ARTICLES | {"and"}


def _lev1(a: str, b: str) -> bool:
    if len(a) > len(b):
        a, b = b, a
    if len(b) - len(a) > 1:
        return False
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] if len(a) == len(b) else a[i:] == b[i + 1:]


def near(a: str, b: str) -> bool:
    """Spellings the recognizer mixes up, or tiny inflection differences."""
    if a == b or a.rstrip("s") == b.rstrip("s"):
        return True
    if {a, b} <= {"assistance", "assistants", "assistant"}:
        return True
    return min(len(a), len(b)) >= 5 and _lev1(a, b)


def harmonize(line_tokens: list[list[str]], hyp: list[str], hyp_w: list[int]):
    """Make compounds comparable: manuscript 'chatgpt' against heard 'chat gpt', 'cow paths' against 'cowpaths'."""
    hv = set(hyp)
    sv = {t for toks_ in line_tokens for t in toks_}
    hb = {a + b: (a, b) for a, b in zip(hyp, hyp[1:]) if a + b not in hv}
    sb = {}
    for toks_ in line_tokens:
        for a, b in zip(toks_, toks_[1:]):
            sb.setdefault(a + b, (a, b))
    new_lines = [[p for t in toks_ for p in (hb[t] if t not in hv and t in hb else (t,))] for toks_ in line_tokens]
    new_hyp, new_w = [], []
    for t, w in zip(hyp, hyp_w):
        parts = sb[t] if t not in sv and t in sb else (t,)
        new_hyp.extend(parts)
        new_w.extend([w] * len(parts))
    return new_lines, new_hyp, new_w


def diffs(book: list[str], read: list[str]) -> list[dict]:
    """Where a manuscript line and the words read for it differ. "at" is the place among the words read."""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, book, read, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        A, B = book[i1:i2], read[j1:j2]
        a, b = " ".join(A), " ".join(B)
        if a.replace(" ", "") == b.replace(" ", ""):
            continue                                       # "under way" / "underway"
        small = ((len(A) == len(B) and all(near(p, q) or (p in ARTICLES and q in ARTICLES) for p, q in zip(A, B)))
                 or (tag == "insert" and len(B) == 1 and B[0] in SMALL)
                 or (tag == "delete" and len(A) == 1 and A[0] in SMALL))
        out.append({"type": tag, "book": a, "read": b, "small": bool(small), "at": j1})
    return out


def compare(lines: list[Line], heard: list[dict]) -> dict:
    """Every difference between the manuscript's lines and the words in the audio.

    heard: the words in the audio, in order, each {"text", "at", "end"} in seconds. Where the audio is an
    edit of a recording, each word also has "raw" and "raw_end": its times in the recording.

    Nothing is left out and nothing is cut short. Differences of an article, a plural, or a spelling the
    recognizer varies on are listed apart as "small", because many are the recognizer's doing, but each
    carries its line and its time like any other: some of them are real misreads.
    """
    hyp, hyp_w = [], []
    for wi, w in enumerate(heard):
        for t in toks(w["text"]):
            hyp.append(t)
            hyp_w.append(wi)
    line_toks, hyp, hyp_w = harmonize([ln.tokens for ln in lines], hyp, hyp_w)
    script, sent_of = [], []
    for k, lt in enumerate(line_toks):
        script += lt
        sent_of += [k] * len(lt)

    owner, runs = [None] * len(hyp), []                # the line each word in the audio is read for
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, script, hyp, autojunk=False).get_opcodes():
        if tag == "equal":
            for d in range(j2 - j1):
                owner[j1 + d] = sent_of[i1 + d]
        elif tag == "replace":
            for d in range(j2 - j1):
                owner[j1 + d] = sent_of[i1 + min(i2 - i1 - 1, d * (i2 - i1) // (j2 - j1))]
        elif tag == "insert":
            between = i1 == 0 or i1 == len(script) or sent_of[i1 - 1] != sent_of[i1]
            if between:                              # report every addition outside a manuscript line, however short
                runs.append((j1, j2))
            else:
                for j in range(j1, j2):
                    owner[j] = sent_of[i1 - 1] if i1 > 0 else 0
    by_line = defaultdict(list)
    for j, k in enumerate(owner):
        if k is not None:
            by_line[k].append(j)

    def when(j, end=False):
        w = heard[hyp_w[j]]
        return (w["end"], w.get("raw_end")) if end else (w["at"], w.get("raw"))

    def row(k, found, read):
        parts, out = [], []
        for d in found:
            past = d["at"] >= len(read)
            at, raw = when(read[-1] if past else read[d["at"]], end=past)
            says = {"replace": f"read '{d['read']}' for '{d['book']}'", "delete": f"missing '{d['book']}'",
                    "insert": f"added '{d['read']}'"}[d["type"]]
            parts.append((says, at))
            out.append({"type": d["type"], "book": d["book"], "read": d["read"], "at": at, "raw": raw})
        problem = parts[0][0] if len(parts) == 1 else "; ".join(f"{says} ({clock(at)})" for says, at in parts)
        return {"line": k + 1, "at": out[0]["at"], "raw": out[0]["raw"], "problem": problem, "text": lines[k].text,
                "differences": out}

    pickups, small, not_found = [], [], []
    reached = (heard[0]["at"], heard[0].get("raw")) if heard else (0.0, None)
    for k in range(len(lines)):
        read = by_line.get(k)
        if not read:                                   # nothing was read for this line: say where it was expected
            not_found.append({"line": k + 1, "at": reached[0], "raw": reached[1], "text": lines[k].text})
            continue
        found = diffs(line_toks[k], [hyp[j] for j in read])
        for group, rows in (([d for d in found if not d["small"]], pickups), ([d for d in found if d["small"]], small)):
            if group:
                rows.append(row(k, group, read))
        reached = when(read[-1], end=True)
    extra = []
    for j1, j2 in runs:
        ws = list(dict.fromkeys(hyp_w[j1:j2]))
        at, raw = when(j1)
        extra.append({"at": at, "raw": raw, "count": len(ws), "words": " ".join(heard[w]["text"] for w in ws)})
    return {"lines": len(lines), "lines_found": len(lines) - len(not_found),
            "pickups": pickups, "small": small, "not_found": not_found, "extra": extra}


def _cell(s: str) -> str:
    """Keep all text while protecting Markdown table boundaries and literal markup."""
    s = escape(s, quote=False).replace("\r\n", "\n").replace("\r", "\n")
    for char in "\\`*_[]|~":
        s = s.replace(char, f"&#{ord(char)};")
    return s.replace("\n", "<br>")


def manuscript_markdown(c: dict, level: str = "##") -> list[str]:
    """The comparison as Markdown: the same sections whether the audio is a recording being cut or a finished file."""
    rows = c["pickups"] + c["small"] + c["not_found"] + c["extra"]
    two = any(r.get("raw") is not None for r in rows)
    head = "| Edited at | Recorded at " if two else "| At "
    rule = "|---|---" if two else "|---"

    def at(r):
        if not two:
            return f"| {clock(r['at'])} "
        return f"| {clock(r['at'])} | {'-' if r.get('raw') is None else clock(r['raw'])} "

    md = [f"{level} Against the manuscript", "",
          f"Lines found: {c['lines_found']} of {c['lines']}.", "",
          f"{level}# Pickups", ""]
    if c["pickups"]:
        md += ["Lines where what was read differs from the manuscript.", "",
               f"| Line {head}| What differs | Manuscript |", f"|---{rule}|---|---|"]
        md += [f"| {r['line']} {at(r)}| {_cell(r['problem'])} | {_cell(r['text'])} |" for r in c["pickups"]]
    else:
        md.append("None.")
    md += ["", f"{level}# Small differences", ""]
    if c["small"]:
        md += ["Article, plural and near-spelling differences.", "",
               f"| Line {head}| What differs | Manuscript |", f"|---{rule}|---|---|"]
        md += [f"| {r['line']} {at(r)}| {_cell(r['problem'])} | {_cell(r['text'])} |" for r in c["small"]]
    else:
        md.append("None.")
    md += ["", f"{level}# Not found", ""]
    if c["not_found"]:
        expected = "| Expected at, edited | Expected at, recorded " if two else "| Expected at "
        md += ["Manuscript lines with nothing read for them. The time is where the line was expected: the end of the last line read before it.", "",
               f"| Line {expected}| Manuscript |", f"|---{rule}|---|"]
        md += [f"| {r['line']} {at(r)}| {_cell(r['text'])} |" for r in c["not_found"]]
    else:
        md.append("None. Every line of the manuscript section was read.")
    if c["extra"]:
        md += ["", f"{level}# In the audio and not in the manuscript", "",
               "Words before, between, or after manuscript lines with no matching manuscript text.", "",
               f"{head}| Words | What was said |", f"{rule}|---|---|"]
        md += [f"{at(r)}| {r['count']} | {_cell(r['words'])} |" for r in c["extra"]]
    return md
