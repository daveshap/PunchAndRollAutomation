"""What was said: a clean transcript of each finished recording, in the reader's own words.

    punchroll said draft project.toml [more.toml ...]
        writes <said>/NAME.review.md: every place where the words on the finished audio differ from the
        reference text, numbered; and <said>/NAME.decisions.json, with the ones that are only spelling decided.
    punchroll said build project.toml [more.toml ...]
        writes <transcripts>/NAME.md for each recording, and <transcripts>/All recordings.md for all of them.
    punchroll said changes project.toml [more.toml ...] [--into NOTES.md]
        every sentence the reader changed from the text he was given, set beside what he said, with the
        changed words marked (~~cut~~ in the written sentence, **added** in the said one), and a count per
        recording. With --into, both go into NOTES.md between its markers and nothing else in it changes.

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
(default: the name) and `recorded` (when, as text). For `changes`: `written` with `written_from` and
`written_to`, the text the reader was given when it isn't the reference text (a whole file when they are
left out); and `heading`, the recording's heading in the log (default: the title and when it was recorded).
`changes` reads the transcripts that `build` wrote: what was said is the finished transcript, never the
recognizer's raw words.
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
from .text import load_script, read_blocks, select_section, toks

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
    written: Path | None = None
    written_start: str | None = None
    written_end: str | None = None
    heading: str | None = None


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
                           base / proj.get("transcripts", "transcripts"), proj.get("speaker"),
                           base / ch["written"] if ch.get("written") else None, ch.get("written_from"),
                           ch.get("written_to"), ch.get("heading")))
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


COUNTS = ("<!-- counts:start -->", "<!-- counts:end -->")
LOG = "<!-- log:start -->"


def given(e: Entry):
    """The sentences of the text the reader was given: the entry's `written` text, or its reference."""
    if e.written:
        return load_script(e.written, e.written_start, e.written_end)
    return load_script(e.reference, e.start, e.end, e.lines)


def finished_text(e: Entry) -> str:
    """The body of the recording's finished transcript."""
    path = e.out / f"{e.name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"[{e.name}] has no finished transcript yet: run `punchroll said build`")
    return path.read_text(encoding="utf-8").split("\n\n", 2)[2]


def _ends(word: str) -> bool:
    """The word ends a sentence: a full stop, question or exclamation mark, before any closing quote."""
    return word.rstrip("\"”’')")[-1:] in (".", "?", "!")


def changed(lines, said_words: list[str]):
    """The sentences the reader changed, as (written, said); how many sentences were read; the body sentences
    left unread. Sentences he ran together are shown together; a heading he didn't read is left out."""
    S = [(t, i) for i, w in enumerate(said_words) for t in toks(w)]

    def opcodes(lines):
        W = [(t, k) for k, ln in enumerate(lines) for t in ln.tokens]
        return W, difflib.SequenceMatcher(a=[t for t, _ in W], b=[t for t, _ in S], autojunk=False).get_opcodes()

    W, ops = opcodes(lines)                                # a heading counts as read when most of its words were
    hit = [0] * len(lines)
    for op, i1, i2, _, _ in ops:
        if op == "equal":
            for i in range(i1, i2):
                hit[W[i][1]] += 1
    lines = [ln for k, ln in enumerate(lines) if ln.kind != "heading" or 2 * hit[k] >= len(ln.tokens)]
    W, ops = opcodes(lines)
    line_of, touched, unread = {}, set(), set(range(len(lines)))
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            for d in range(i2 - i1):
                line_of.setdefault(S[j1 + d][1], W[i1 + d][1])
                unread.discard(W[i1 + d][1])
            continue
        first = S[j1][1] if j1 < len(S) else len(said_words)
        if op == "insert":
            k = W[i1 - 1][1] if i1 > 0 else 0
            if (i1 < len(W) and (i1 == 0 or W[i1][1] != W[i1 - 1][1]) and first > 0
                    and _ends(said_words[first - 1])):
                k = W[i1][1]                               # said after a full stop: it opens the next sentence
        else:
            k = W[i1][1]
            if j2 > j1:
                unread.difference_update(q for _, q in W[i1:i2])
        for _, i in S[j1:j2]:
            line_of.setdefault(i, k)
        if "".join(t for t, _ in W[i1:i2]) != "".join(t for t, _ in S[j1:j2]):
            touched.add(k)
    said = {}
    for i, w in enumerate(said_words):
        if i in line_of:
            said.setdefault(line_of[i], []).append(w)

    def runs_on(k):                                        # he ran sentence k into the next one
        return bool(said.get(k)) and not _ends(said[k][-1]) and k + 1 < len(lines) and k + 1 not in unread

    found, used = [], set()
    for k in sorted(touched - unread):
        if k in used:
            continue
        a = b = k
        while a > 0 and a - 1 not in unread and a - 1 not in used and runs_on(a - 1):
            a -= 1
        while runs_on(b):
            b += 1
        used.update(range(a, b + 1))
        w = " ".join(lines[g].text for g in range(a, b + 1))
        s = " ".join(" ".join(said.get(g, [])) for g in range(a, b + 1))
        if letters(w) != letters(s):                       # not just punctuation, capitals or a number's spelling
            found.append((w, s[:1].upper() + s[1:]))
    read = sum(1 for k in range(len(lines)) if k not in unread)
    return found, read, [lines[k].text for k in sorted(unread) if lines[k].kind == "body"]


def _wrap(words: list[str], mark: str) -> str:
    """Words inside a mark, with the punctuation around them left outside it."""
    s = " ".join(words)
    lead = len(s) - len(s.lstrip("“\"'(‘"))
    end = len(s.rstrip(".,;:?!”\"')’"))
    return s[:lead] + mark + s[lead:end] + mark + s[end:] if end > lead else s


def marked(written: str, spoken: str) -> tuple[str, str]:
    """The written sentence with the words he didn't say struck (~~), the said one with his own words in bold."""
    a = re.sub(r"\s*([—–])\s*", r" \1 ", written).split()
    b = spoken.split()
    ia = [i for i, x in enumerate(a) if letters(x)]
    ib = [j for j, x in enumerate(b) if letters(x)]
    sm = difflib.SequenceMatcher(a=[letters(a[i]) for i in ia], b=[letters(b[j]) for j in ib], autojunk=False)
    same_a, same_b = set(), set()
    for blk in sm.get_matching_blocks():
        same_a.update(ia[blk.a + o] for o in range(blk.size))
        same_b.update(ib[blk.b + o] for o in range(blk.size))

    def runs(words, same, mark):
        out, run = [], []
        for i, x in enumerate(words):
            if i in same or not letters(x):
                if run:
                    out.append(_wrap(run, mark))
                    run = []
                out.append(x)
            else:
                run.append(x)
        if run:
            out.append(_wrap(run, mark))
        return re.sub(r" ([—–]) ", r"\1", " ".join(out))

    return runs(a, same_a, "~~"), runs(b, same_b, "**")


def changes(projects, into=None, only=None, log=print) -> int:
    """List every sentence the reader changed, recording by recording; return how many."""
    if into and only:
        raise ValueError("--into rewrites the whole log, so it takes every recording: leave out --only")
    rows, parts, total, read = [], [], 0, 0
    for e in (e for p in projects for e in entries(p, only)):
        found, n_read, left = changed(given(e), finished_text(e).split())
        total, read = total + len(found), read + n_read
        head = e.heading or (f"{e.title} ({e.recorded})" if e.recorded else e.title)
        rows.append(f"| {head} | {n_read} | {len(found)} | {100 * len(found) / max(n_read, 1):.0f} % |")
        parts += [f"### {head}", "",
                  f"{len(found)} of {n_read} sentences changed." + (" Left unread: " + " ".join(left) if left else ""), ""]
        for n, (w, s) in enumerate(found, 1):
            mw, ms = marked(w, s)
            parts += [f"{n}. W: {mw}", f"   S: {ms}"]
        parts.append("")
    counts = "\n".join(["| Recording, in the order recorded | Sentences read | Changed | Share |", "|---|---|---|---|"]
                       + rows + ["", f"{total} sentences changed out of {read:,} read."])
    text_log = "\n".join(parts).rstrip() + "\n"
    if not into:
        log(counts + "\n\n" + text_log)
        return total
    path = Path(into)
    text = path.read_text(encoding="utf-8")
    if not all(m in text for m in (*COUNTS, LOG)):
        raise ValueError(f"{path} needs the markers {COUNTS[0]}, {COUNTS[1]} and {LOG}")
    head, rest = text.split(COUNTS[0], 1)
    middle = rest.split(COUNTS[1], 1)[1].split(LOG, 1)[0]
    path.write_text(f"{head}{COUNTS[0]}\n{counts}\n{COUNTS[1]}{middle}{LOG}\n\n{text_log}", encoding="utf-8", newline="\n")
    log(f"{path.name}: {total} changed sentences out of {read:,} read")
    return total
