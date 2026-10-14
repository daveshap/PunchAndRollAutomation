"""What was said: a clean transcript of each finished recording, in the reader's own words.

    punchroll said draft project.toml [more.toml ...]
        writes <said>/NAME.review.md: every place where the words on the finished audio differ from the
        reference text, numbered; and <said>/NAME.decisions.json, with the ones that are only spelling decided.
    punchroll said build project.toml [more.toml ...]
        writes <transcripts>/NAME.md for each recording, and <transcripts>/All recordings.md for all of them.

The words come from the speech recognizer's transcript of the FINISHED file (the MP3 if there is one); it is
transcribed if it hasn't been. The reference text (the entry's `script` with `from`/`to` or `lines`, as for
the manuscript comparison) is used only for spelling, numbers, sentence breaks and paragraphs where the
words said match it.

Where they differ, the decisions file says what the transcript holds, by the number in the review file:
  "s"     what the recognizer heard: the reader's own wording
  "w"     the reference's words: the recognizer misheard, or spelled a word differently
  "text"  anything else: the exact words to write there (an empty string writes nothing). A leading "<" also
          takes the comma or full stop off the word before, for words added in the middle of a sentence.
"_fixes" is a list of [old, new] replacements made on the finished text, for capitals and commas where the
reader's own wording joins the written text. A decision follows its difference by what the difference says
when a new master renumbers them. Every difference needs a decision before build will run.

Punctuation is written plainly: where the reader read through a colon, a semicolon, a dash or a bracket, the
transcript has a comma or a full stop.

Project keys: `transcripts` (folder for the transcripts, default "transcripts"), `said` (folder for the review
and decision files, default "said"), `speaker` (the reader's name, for the headings). Entry keys: `title`
(default: the name) and `recorded` (when, as text).
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .asr import cached_words, transcribe
from .models import transcripts_dir
from .text import read_blocks, select_section, toks

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass
class Entry:
    name: str
    title: str
    recorded: str
    reference: Path
    start: str | None
    end: str | None
    lines: str | None
    finished: Path
    work: Path
    out: Path
    speaker: str | None


def entries(project, only: str | None = None) -> list[Entry]:
    """The recordings of a project file that have a finished file and a reference text."""
    path = Path(project)
    proj = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    out = base / proj.get("out", "edited")
    found = []
    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        if only and only not in name:
            continue
        script = ch.get("script") or (proj.get("script") if (ch.get("from") or ch.get("to") or ch.get("lines")) else None)
        if not script:
            raise ValueError(f"[{name}] needs a reference text: `script`, or `from`/`to` in a project with a `script`")
        finished = next((p for p in (out / f"{name}.mp3", out / f"{name}.wav") if p.is_file()), None)
        if finished is None:
            raise FileNotFoundError(f"[{name}] has no finished file in {out}")
        found.append(Entry(name, ch.get("title") or name, ch.get("recorded", ""), base / script, ch.get("from"),
                           ch.get("to"), ch.get("lines"), finished, base / proj.get("said", "said"),
                           base / proj.get("transcripts", "transcripts"), proj.get("speaker")))
    return found


def letters(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def reference(e: Entry) -> list[tuple[str, str]]:
    blocks = read_blocks(e.reference, e.lines)
    if e.start or e.end:
        blocks = select_section(blocks, e.start, e.end)
    return [(kind, re.sub(r"\s*[—–]\s*", " — ", text)) for kind, text in blocks]   # a dash is a word here


def heard(e: Entry, rec=None, log=print) -> dict:
    """The recognizer's transcript of the finished file: cached, or made now."""
    d = cached_words(e.finished, transcripts_dir())
    if d is None:
        from .audio import read_mono
        x, sr = read_mono(e.finished)
        d = transcribe(e.finished, x, sr, rec, transcripts_dir(), None, log)
    return d


def align(e: Entry, words: list[dict]):
    """Paragraphs of segments: ("w", text) where the words match, ("d", n) for difference n; and the differences."""
    blocks = reference(e)
    items = []                                                # (block, surface word, its tokens)
    for b, (kind, text) in enumerate(blocks):
        for word in text.split():
            items.append((b, word, toks(word)))
    W = [(t, k) for k, (_, _, ts) in enumerate(items) for t in ts]
    S = [(t, k) for k, w in enumerate(words) for t in toks(w["text"])]
    sm = difflib.SequenceMatcher(a=[t for t, _ in W], b=[t for t, _ in S], autojunk=False)
    at = [None] * len(W)
    for blk in sm.get_matching_blocks():
        for o in range(blk.size):
            at[blk.a + o] = blk.b + o
    span = {}                                                 # item -> (first spoken token, end) when it matches cleanly
    k0 = 0
    for k, (_, _, ts) in enumerate(items):
        js = [at[i] for i in range(k0, k0 + len(ts))]
        k0 += len(ts)
        if ts and all(j is not None for j in js) and js == list(range(js[0], js[0] + len(js))):
            span[k] = (js[0], js[-1] + 1)

    def spoken(p, q):
        seen, out = set(), []
        for t in range(p, q):
            w = S[t][1]
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out

    paras = [[] for _ in blocks]
    diffs, pend, p = [], [], 0

    def flush(q, b, k_next):
        nonlocal pend, p
        ws = spoken(p, q) if q > p else []
        if pend or ws:
            n = len(diffs) + 1
            k0 = pend[0] if pend else k_next
            k1 = pend[-1] + 1 if pend else k_next
            diffs.append({"n": n, "block": b, "written": " ".join(items[k][1] for k in pend),
                          "said": " ".join(words[w]["text"] for w in ws),
                          "at": round(words[ws[0]]["start"], 2) if ws else None,
                          "before": " ".join(items[k][1] for k in range(max(0, k0 - 7), k0)),
                          "after": " ".join(items[k][1] for k in range(k1, min(len(items), k1 + 7)))})
            paras[items[pend[0]][0] if pend else b].append(("d", n))
        pend, p = [], max(p, q)

    for k, (b, word, ts) in enumerate(items):
        if k in span:
            j0, j1 = span[k]
            if j0 < p:                                        # its spoken words were taken by an earlier difference
                pend.append(k)
                continue
            flush(j0, b, k)
            paras[b].append(("w", word))
            p = j1
        elif not ts and not pend:                             # punctuation between matching words
            paras[b].append(("w", word))
        else:
            pend.append(k)
    flush(len(S), len(blocks) - 1, len(items))
    return blocks, paras, diffs


def draft(projects, only=None, rec=None, log=print) -> int:
    """Write the review and decisions files; return how many differences are still to decide."""
    left = 0
    for e in (e for p in projects for e in entries(p, only)):
        _, _, diffs = align(e, heard(e, rec, log)["words"])
        e.work.mkdir(parents=True, exist_ok=True)
        dec_path = e.work / f"{e.name}.decisions.json"
        old = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.is_file() else {}
        dec, open_ = ({"_fixes": old["_fixes"]} if "_fixes" in old else {}), 0
        by_sig = {}                                    # a decision follows its difference when the numbers move
        for k, v in old.items():
            if k != "_fixes" and v.get("use") is not None:
                by_sig.setdefault(v["sig"], v)
        where = e.reference.name + (f", from \"{e.start}\" to \"{e.end}\"" if e.start else "")
        lines = [f"# {e.name}: where the finished audio differs from the reference", "", f"Reference: {where}", "",
                 "| # | at | before | written | said | after | decision |", "|---|---|---|---|---|---|---|"]
        for d in diffs:
            key = str(d["n"])
            sig = d["written"] + " | " + d["said"]
            if key in old and old[key].get("sig") == sig:
                dec[key] = old[key]
            elif sig in by_sig:
                dec[key] = dict(by_sig[sig])
            elif letters(d["written"]) == letters(d["said"]):
                dec[key] = {"sig": sig, "use": "w", "why": "same words, spelled differently"}
            else:
                dec[key] = {"sig": sig, "use": None}
            if dec[key]["use"] is None:
                open_ += 1
            t = d["at"]
            when = f"{int(t // 60)}:{t % 60:04.1f}" if t is not None else "-"
            lines.append(f"| {d['n']} | {when} | {d['before']} | {d['written']} | {d['said']} | {d['after']} | "
                         f"{dec[key]['use'] if dec[key]['use'] is not None else '?'} |")
        (e.work / f"{e.name}.review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        dec_path.write_text(json.dumps(dec, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"{e.name}: {len(diffs)} difference(s), {open_} to decide")
        left += open_
    return left


def plain(text: str) -> str:
    """The transcript's punctuation: no colons, semicolons, dashes or brackets doing the work of words."""
    text = re.sub(r"\s+—\s+(?=[A-Z])", ". ", text)
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r";\s+", ". ", text)
    text = re.sub(r":\s+", ", ", text)                                   # a clock time (8:00) has no space after it
    text = re.sub(r"([.?!])\s*\(\s*", r"\1 ", text)                     # a whole sentence in brackets is just a sentence
    text = re.sub(r"([.?!])\s*\)", r"\1", text)
    text = re.sub(r"\s*\(\s*", ", ", text)
    text = re.sub(r"\s*\)\s*", ", ", text)
    text = re.sub(r",\s*([,.?!])", r"\1", text)
    text = re.sub(r"([.?!]),", r"\1", text)
    text = re.sub(r"\s+([,.?!])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"([.?!][\"”']?\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r"^([\"“']?)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def hours(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60} min"


def body(e: Entry, words: list[dict], dec: dict) -> str:
    """The transcript's paragraphs, as the decisions say."""
    blocks, paras, diffs = align(e, words)
    missing = [d["n"] for d in diffs if not isinstance(dec.get(str(d["n"])), dict) or dec[str(d["n"])].get("use") is None
               or dec[str(d["n"])].get("sig") != d["written"] + " | " + d["said"]]
    if missing:
        raise ValueError(f"[{e.name}] no decision yet for difference(s) {missing}: run `punchroll said draft` and decide them")
    by_n = {d["n"]: d for d in diffs}
    built = []
    for segs in paras:
        parts = []
        built.append(parts)
        for kind, v in segs:
            if kind == "w":
                parts.append(v)
                continue
            use = dec[str(v)]["use"]
            into = parts
            if use not in ("s", "w") and use.startswith("<"):    # "<" takes the comma or full stop off the word before
                use = use[1:]
                if not [p for p in parts if p]:                  # and goes on the end of the paragraph before
                    into = next((q for q in reversed(built[:-1]) if [p for p in q if p]), parts)
                while into and into[-1] in ("—", "–", ""):
                    into.pop()
                if into:
                    into[-1] = into[-1].rstrip(",.;:")
            into.append(by_n[v]["said"] if use == "s" else by_n[v]["written"] if use == "w" else use)
    text = "\n\n".join(t for t in (plain(" ".join(p for p in parts if p)) for parts in built) if t)
    for old, new in dec.get("_fixes", []):                        # capitals and commas around the reader's own wording
        if old not in text:
            raise ValueError(f"[{e.name}] the fix {old!r} matches nothing in the transcript")
        text = text.replace(old, new)
    return text


def build(projects, only=None, rec=None, log=print) -> list[Path]:
    """Write each recording's transcript, and the combined file when every recording of the projects is built."""
    done, written = [], []
    for e in (e for p in projects for e in entries(p, only)):
        d = heard(e, rec, log)
        dec_path = e.work / f"{e.name}.decisions.json"
        dec = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.is_file() else {}
        text = body(e, d["words"], dec)
        who = f"What {e.speaker} said" if e.speaker else "What was said"
        when = f", recorded {e.recorded}" if e.recorded else ""
        e.out.mkdir(parents=True, exist_ok=True)
        dest = e.out / f"{e.name}.md"
        dest.write_text(f"# {e.title}\n\n{who} on the finished recording \"{e.name}\" ({clock(d['duration'])}){when}.\n\n{text}\n",
                        encoding="utf-8")
        written.append(dest)
        done.append((e, text, d["duration"]))
        log(f"{e.name}: {len(text.split())} words")
    if done and not only:
        total = sum(len(t.split()) for _, t, _ in done)
        e0 = done[0][0]
        parts = [f"# What {e0.speaker} actually said" if e0.speaker else "# What was said", "",
                 f"The finished transcript of every finished recording, in the order recorded: {len(done)} recordings, "
                 f"{total:,} words, {hours(sum(d for _, _, d in done))} of audio.", ""]
        for e, text, dur in done:
            when = f", recorded {e.recorded}" if e.recorded else ""
            parts += [f"## {e.title}", "", f"\"{e.name}\", {clock(dur)}{when}.", "", text, ""]
        dest = e0.out / "All recordings.md"
        dest.write_text("\n".join(parts), encoding="utf-8")
        written.append(dest)
        log(f"All recordings.md: {total:,} words")
    return written
