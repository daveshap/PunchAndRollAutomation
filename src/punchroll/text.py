"""From a manuscript to the lines a narrator reads, and from words to comparable tokens.

The script you give punchroll should contain exactly what you say out loud,
headings included. Words you say that aren't in it are treated as asides and cut.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from num2words import num2words

# ---------------------------------------------------------------- tokens

def _num(s: str) -> str:
    s = s.replace(",", "")
    try:
        return num2words(float(s)) if "." in s else num2words(int(s))
    except (ValueError, OverflowError):
        return s


def _decade(m) -> str:
    w = num2words(int(m.group(1)), to="year")
    return (w[:-1] + "ies") if w.endswith("y") else w + "s"


_CURRENCY = {"$": "dollars", "€": "euros", "£": "pounds"}


def spoken_numbers(text: str) -> str:
    """Write numbers the way they're usually read: 1810s -> eighteen tens, 4% -> four percent."""
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), text)
    text = re.sub(r"\b(1[0-9]{3}|20[0-9]{2})s\b", _decade, text)
    text = re.sub(r"['‘’]([1-9]0)s\b", lambda m: _decade_short(int(m.group(1))), text)
    text = re.sub(r"\b(1[1-9][0-9]{2}|20[0-9]{2})\b(?![.,]\d)",
                  lambda m: num2words(int(m.group(1)), to="year"), text)
    text = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: _num(m.group(1)) + " percent", text)
    text = re.sub(r"([$€£])(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion))?",
                  lambda m: f"{_num(m.group(2))} {m.group(3) or ''} {_CURRENCY[m.group(1)]}", text)
    text = re.sub(r"\d[\d,]*(?:\.\d+)?", lambda m: _num(m.group(0)), text)
    return text


def _decade_short(n: int) -> str:
    w = num2words(n)
    return (w[:-1] + "ies") if w.endswith("y") else w + "s"


def toks(text: str) -> list[str]:
    """Lowercase word tokens with numbers spelled out; used for both script and transcript."""
    text = text.replace("’", "'").replace("‘", "'").replace("&", " and ")
    text = spoken_numbers(text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[-/]", " ", text)
    return [w.strip("'") for w in re.sub(r"[^a-z0-9' ]+", " ", text).split() if w.strip("'")]


# ---------------------------------------------------------------- script

@dataclass
class Line:
    text: str
    kind: str                 # "heading" or "body"
    para: int                 # paragraph number; headings get their own
    tokens: list = field(default_factory=list)

    @property
    def is_title(self) -> bool:
        return self.kind == "heading" and bool(TITLE_RE.match(self.text))


TITLE_RE = re.compile(r"^(chapter|part|book|section|appendix)\b", re.I)
ABBREV = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "prof", "gen", "gov", "sen", "rep", "rev",
          "no", "vol", "fig", "approx", "est", "inc", "ltd", "co", "corp", "e.g", "i.e", "etc", "u.s",
          "u.k", "a.m", "p.m", "ph.d", "b.c", "a.d"}

_INLINE = [
    (r"\[\^[^\]]*\]", ""),                    # footnote markers
    (r"\{[#.][^}]*\}", ""),                   # pandoc attributes
    (r"!\[[^\]]*\]\([^)]*\)", ""),            # images
    (r"\[([^\]]+)\]\([^)]*\)", r"\1"),        # links -> text
    (r"<[^>]+>", ""),                         # html tags
    (r"\\([\\`*_{}\[\]()#+\-.!])", r"\1"),    # escapes
]


def clean_inline(s: str, keep_emphasis: bool = False) -> str:
    for pat, rep in _INLINE:
        s = re.sub(pat, rep, s)
    if not keep_emphasis:
        s = re.sub(r"[*_`]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _markdown_blocks(lines: list[str]) -> list[tuple[str, str]]:
    blocks, para = [], []
    in_code = in_front = in_note = False

    def flush():
        if para:
            blocks.append(("body", clean_inline(" ".join(para))))
            para.clear()

    for i, raw in enumerate(lines):
        s = raw.rstrip()
        if i == 0 and s == "---":
            in_front = True
            continue
        if in_front:
            in_front = s not in ("---", "...")
            continue
        if s.lstrip().startswith(("```", "~~~")):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s.strip():
            flush()
            in_note = False
            continue
        if in_note and raw.startswith((" ", "\t")):
            continue
        if re.match(r"^\s{0,3}#{1,6}\s", s):
            flush()
            blocks.append(("heading", clean_inline(re.sub(r"\s#+\s*$", "", s.strip().lstrip("#")))))
            continue
        if re.match(r"^\s*\|", s) or re.match(r"^\s*([-*_]\s*){3,}$", s) or s.lstrip().startswith("<!--"):
            flush()
            continue
        if re.match(r"^\s*\[\^[^\]]+\]:", s):
            flush()
            in_note = True
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", s):
            flush()
        para.append(re.sub(r"^\s*(>+\s*)?([-*+]\s+|\d+[.)]\s+)?", "", s).strip())
    flush()
    return [(k, t) for k, t in blocks if t]


def _docx_blocks(path: Path) -> list[tuple[str, str]]:
    try:
        import docx
    except ImportError as e:
        raise RuntimeError("Reading .docx scripts needs python-docx: pip install python-docx") from e
    out = []
    for p in docx.Document(str(path)).paragraphs:
        t = re.sub(r"\s+", " ", p.text).strip()
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        out.append(("heading" if style.startswith(("heading", "title")) else "body", t))
    return out


def read_blocks(path: str | Path, line_range: str | None = None) -> list[tuple[str, str]]:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        if line_range:
            raise ValueError("--lines works with Markdown or text scripts; use --from/--to for .docx")
        return _docx_blocks(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    if line_range:
        a, b = (int(v) for v in line_range.split("-"))
        lines = lines[a - 1:b]
    return _markdown_blocks(lines)


def select_section(blocks, start: str | None = None, end: str | None = None):
    """Blocks from the first heading containing `start` up to (not including) the next heading containing `end`."""
    if not start and not end:
        return blocks
    heads = [(i, t) for i, (k, t) in enumerate(blocks) if k == "heading"]
    i0 = 0
    if start:
        hit = [i for i, t in heads if start.lower() in t.lower()]
        if not hit:
            raise ValueError(f"no heading contains {start!r}. Headings: " + "; ".join(t for _, t in heads[:60]))
        i0 = hit[0]
    i1 = len(blocks)
    if end:
        hit = [i for i, t in heads if i > i0 and end.lower() in t.lower()]
        if not hit:
            raise ValueError(f"no heading after {start!r} contains {end!r}")
        i1 = hit[0]
    return blocks[i0:i1]


def split_sentences(text: str) -> list[str]:
    out, last = [], 0
    for m in re.finditer(r"([.?!])([\"”’)]*)(\s+)(?=[\"“‘(A-Z0-9])", text):
        before = text[last:m.start(1)].split()
        word = before[-1].lower().strip("(\"“‘") if before else ""
        if m.group(1) == "." and (word in ABBREV or re.fullmatch(r"[a-z]", word)
                                  or re.fullmatch(r"([a-z]\.)+[a-z]", word)):
            continue                       # Mr. Smith, U.S. Navy, J. R. R. Tolkien, 6 a.m. Monday
        out.append(text[last:m.end(2)].strip())
        last = m.end(3)
    out.append(text[last:].strip())
    return [s for s in out if s]


def build_lines(blocks) -> list[Line]:
    lines, para = [], 0
    for kind, text in blocks:
        if kind == "heading":
            t = text.strip()
            if t and t[-1] not in ".?!:":
                t += "."
            lines.append(Line(t, "heading", para, toks(t)))
        else:
            for s in split_sentences(text):
                lines.append(Line(s, "body", para, toks(s)))
        para += 1
    return [ln for ln in lines if ln.tokens]


def load_script(path, start=None, end=None, line_range=None) -> list[Line]:
    lines = build_lines(select_section(read_blocks(path, line_range), start, end))
    if not lines:
        raise ValueError("the script section is empty")
    return lines
