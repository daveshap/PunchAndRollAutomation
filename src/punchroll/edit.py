"""From an alignment to an edit: which stretches of the recording to keep, and the pauses between them.

1. For every line of the script, keep the last reading of each word (align.last_take).
2. If the last take of a line has a slip that an earlier take read correctly,
   splice the two at a natural pause (a "comp").
3. Keep the reader's own pauses and breaths wherever nothing was cut and the pause is
   in range. Where a take was cut, or a pause is too long or too short, rebuild it
   from the room's own tone. Pauses are measured from the audio, not from the
   recognizer's word times, which can swallow the silence after a word.
4. Join everything with short crossfades.
"""
from __future__ import annotations

import difflib
from collections import defaultdict

import numpy as np
from scipy.ndimage import binary_closing

from .align import FILLERS, Aligner, harmonize, last_take, near
from .audio import frame_db, rms_db
from .config import Settings
from .text import Line, toks

ARTICLES = {"a", "an", "the", "this", "that", "these", "those"}
SMALL = ARTICLES | {"and"}


def diffs(book: list[str], read: list[str]) -> list[dict]:
    """What still differs between a script line and the words kept for it."""
    out = []
    sm = difflib.SequenceMatcher(None, book, read, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        A, B = book[i1:i2], read[j1:j2]
        a, b = " ".join(A), " ".join(B)
        if a.replace(" ", "") == b.replace(" ", ""):
            continue                                       # "under way" / "underway"
        minor = ((len(A) == len(B) and all(near(p, q) or (p in ARTICLES and q in ARTICLES) for p, q in zip(A, B)))
                 or (tag == "insert" and len(B) == 1 and B[0] in SMALL)
                 or (tag == "delete" and len(A) == 1 and A[0] in SMALL))
        out.append({"type": tag, "book": a, "read": b, "minor": bool(minor)})
    return out


def n_major(book, read) -> int:
    return sum(1 for d in diffs(book, read) if not d["minor"])


def build_edit(x: np.ndarray, sr: int, words: list[dict], lines: list[Line], settings: Settings, log=print,
               take_starts=()) -> dict:
    """take_starts: timeline seconds where each recording after the first begins (pickups, sessions)."""
    P = settings.pauses
    dur = len(x) / sr

    # ---- align: the last reading of every word wins
    hyp, hyp_w = [], []
    for wi, w in enumerate(words):
        for t in toks(w["text"]):
            hyp.append(t)
            hyp_w.append(wi)
    if not hyp:
        raise ValueError("no speech was recognized in the recording")
    line_toks, hyp, hyp_w = harmonize([ln.tokens for ln in lines], hyp, hyp_w)
    script, sent_of, s_start = [], [], []
    for k, lt in enumerate(line_toks):
        s_start.append(len(script))
        script += lt
        sent_of += [k] * len(lt)
    s_end = s_start[1:] + [len(script)]
    free = []
    for t in take_starts:
        first = next((i for i, w in enumerate(hyp_w) if words[w]["start"] >= t), None)
        if first:
            free.append(first)
    ev, cost = Aligner(hyp, script, settings.align, free).run()
    info = last_take(ev, hyp, sent_of)
    restarts = sum(1 for e in ev if e[0] == "restart")

    # ---- where the voice is
    e_db, hop = frame_db(x, sr)
    nfr = len(e_db)
    speech = np.zeros(nfr, bool)
    for w in words:
        speech[max(0, int((w["start"] - 0.15) * sr / hop)):int((w["end"] + 0.15) * sr / hop)] = True
    quiet_db = e_db[~speech & (e_db > -90)]
    floor = float(np.percentile(quiet_db, 20)) if len(quiet_db) else -70.0
    quiet = e_db < floor + 12
    calm = binary_closing(quiet, structure=np.ones(13, bool)) | quiet   # bridges clicks under 60 ms

    def frames(a, b):
        return max(0, int(a * sr / hop)), min(nfr, int(b * sr / hop))

    def runs(lo, hi, mask=quiet):
        a, b = frames(lo, hi)
        if b <= a:
            return []
        d = np.diff(np.concatenate([[0], mask[a:b].astype(np.int8), [0]]))
        return [((a + s0) * hop / sr, (a + s1) * hop / sr)
                for s0, s1 in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if (s1 - s0) * hop / sr >= 0.04]

    def voice_end(w):
        hi = words[w + 1]["start"] + 0.08 if w + 1 < len(words) else dur
        rs = runs(words[w]["start"] + 0.10, hi)
        long = [r for r in rs if r[1] - r[0] >= 0.12]
        return long[0] if long else (max(rs, key=lambda r: r[1] - r[0]) if rs else None)

    def voice_start(w):
        lo = words[w - 1]["start"] + 0.10 if w > 0 else 0.0
        rs = runs(lo, words[w]["start"] + 0.02)
        return rs[-1] if rs else None

    def pause_after(w):
        if w < 0 or w + 1 >= len(words):
            return 9.0
        ve, vs = voice_end(w), voice_start(w + 1)
        e = ve[0] if ve else words[w + 1]["start"]
        s = vs[1] if vs else words[w + 1]["start"]
        return max(0.0, s - e)

    def longest_quiet(w):
        hi = words[w + 1]["start"] + 0.02 if w + 1 < len(words) else dur
        rs = runs(words[w]["start"] + 0.10, hi, calm)
        return max(rs, key=lambda r: r[1] - r[0]) if rs else None

    # ---- ad-libs at the edge of a line: "...until they were cheap enough.", "And groceries don't fall."
    # A word or two that runs straight on from the kept word beside it is part of the reading, and
    # cutting it would mean cutting where there is no pause. An aside or a stray sound stands apart.
    leads = set()                                      # ad-libs that open the next line instead of closing this one
    i = 0
    while i < len(hyp):
        j = i
        while j < len(hyp) and info[j]["why"] == "between lines":
            j += 1
        if j == i:
            i += 1
            continue
        groups = []                                    # the run's words, split wherever the reader paused
        for w in dict.fromkeys(hyp_w[i:j]):
            if groups and w == groups[-1][-1] + 1 and pause_after(w - 1) < P.adlib:
                groups[-1].append(w)
            else:
                groups.append([w])
        w0, w1 = groups[0][0], groups[-1][-1]
        after = i > 0 and info[i - 1]["kept"] and w0 == hyp_w[i - 1] + 1 and pause_after(w0 - 1) < P.adlib
        before = j < len(hyp) and info[j]["kept"] and hyp_w[j] == w1 + 1 and pause_after(w1) < P.adlib
        joined = (groups[0] if after and len(groups[0]) <= 2 else [],
                  groups[-1] if before and len(groups[-1]) <= 2 else [])
        for g in range(i, j):
            if hyp_w[g] in joined[0] or hyp_w[g] in joined[1]:
                info[g]["kept"], info[g]["why"] = True, None
                if hyp_w[g] not in joined[0]:
                    leads.add(g)
        i = j

    # where each spoken token sits in the script: an inserted word sits just after the word before it,
    # or just before the word after it when it opens that line
    anchors, last = [], -1.0
    for i in range(len(hyp)):
        if info[i]["kind"] != "ins":
            last = float(info[i]["pos"])
            anchors.append(last)
        elif i in leads:
            anchors.append(next(info[n]["pos"] for n in range(i + 1, len(hyp)) if info[n]["kind"] != "ins") - 0.5)
        else:
            anchors.append(last + 0.5 if last >= 0 else -1.0)
    by_line = defaultdict(list)
    for i, a in enumerate(anchors):
        if a >= 0:
            by_line[sent_of[int(a + 0.5) if i in leads else int(a)]].append(i)

    def reading(k, pred):
        return [i for _, i in sorted((anchors[i], i) for i in by_line[k] if pred(i))]

    readings = [reading(k, lambda i: info[i]["kept"]) for k in range(len(lines))]

    # ---- comps: an earlier take fixes a slip in the last one, spliced at a pause
    comps = []
    for k, ln in enumerate(lines) if settings.comps else ():
        st, base = line_toks[k], readings[k]
        if not base:
            continue
        base_major = n_major(st, [hyp[i] for i in base])
        if base_major == 0:
            continue
        passes = sorted({info[i]["pass"] for i in by_line[k] if info[i]["kind"] != "ins"})
        best = None
        for P_ in passes:
            pr = reading(k, lambda i, P_=P_: info[i]["pass"] == P_ and (info[i]["kind"] != "ins" or hyp[i] not in FILLERS))
            if set(pr) <= set(base) or len(pr) < 3:
                continue
            pmap = {info[i]["pos"]: i for i in pr if info[i]["kind"] == "match"}
            bmap = {info[i]["pos"]: i for i in base if info[i]["kind"] == "match"}
            for b in range(s_start[k] + 1, s_end[k]):
                for first, second, fmap, smap in ((pr, base, pmap, bmap), (base, pr, bmap, pmap)):
                    if b - 1 not in fmap or b not in smap:
                        continue
                    if pause_after(hyp_w[fmap[b - 1]]) < 0.12 or pause_after(hyp_w[smap[b]] - 1) < 0.12:
                        continue
                    head = [i for i in first if anchors[i] < b]
                    tail = [i for i in second if anchors[i] >= b]
                    if not head or not tail or anchors[head[0]] > s_start[k] or max(anchors[i] for i in tail) < s_end[k] - 1:
                        continue
                    if head[-1] != fmap[b - 1] or tail[0] != smap[b]:
                        continue                       # nothing of either take may straddle the splice
                    m = n_major(st, [hyp[i] for i in head + tail])
                    if m < base_major and (best is None or m < best[0]):
                        best = (m, head + tail, b)
        if best:
            m, new, b = best
            for i in set(base) - set(new):
                info[i]["kept"], info[i]["why"] = False, "replaced by a better take"
            for i in set(new) - set(base):
                info[i]["kept"], info[i]["why"] = True, None
            readings[k] = new
            comps.append({"line": k + 1, "splice_before": script[b], "majors_before": base_major, "majors_after": m})

    # ---- pieces: runs of consecutive words inside one line
    pieces = []
    for k, r in enumerate(readings):
        ws = []
        for i in r:
            if not ws or ws[-1] != hyp_w[i]:
                ws.append(hyp_w[i])
        for w in ws:
            if pieces and pieces[-1]["k"] == k and w == pieces[-1]["w"][-1] + 1:
                pieces[-1]["w"].append(w)
            else:
                pieces.append({"k": k, "w": [w]})
    if not pieces:
        raise ValueError("nothing in the recording matched the script; check the script section")

    def limits(ka, kb):
        a, b = lines[ka], lines[kb]
        if ka == kb:
            return 0.0, 1.0, None
        if a.kind == "heading":
            if a.is_title:
                return P.after_title
            return P.heading_to_body if b.kind == "body" else P.heading_to_heading
        if b.kind == "heading":
            return P.before_heading
        if a.para != b.para:
            return P.paragraph
        return (P.sentence[0], P.sentence[1], None)

    plan = [("tone", P.head, "head")]
    vs = voice_start(pieces[0]["w"][0])
    span_in = vs[1] - min(0.25, vs[1] - vs[0] - 0.02) if vs else words[pieces[0]["w"][0]]["start"] - 0.03
    span_note = "start"
    joins = {"natural": 0, "pause retimed": 0, "cut": 0}
    join_log = []
    for pa, pb in zip(pieces, pieces[1:]):
        wa, wb = pa["w"][-1], pb["w"][0]
        gmin, gmax, target = limits(pa["k"], pb["k"])
        g = pause_after(wa)
        if wb == wa + 1:
            q = longest_quiet(wa)
            if (g <= gmax + P.tolerance_long and (g >= gmin - P.tolerance_short or pa["k"] == pb["k"])) or q is None:
                joins["natural"] += 1                  # the reader's own pause, untouched
                continue
            G = float(np.clip(g, gmin, gmax))
            ql = q[1] - q[0]
            if g > G:                                  # shorten: take quiet out of the middle
                cut = min(g - G, ql - 0.15)
                if cut < 0.10:
                    joins["natural"] += 1
                    continue
                keep = ql - cut
                E, S, F = q[0] + 0.4 * keep, q[1] - 0.6 * keep, 0.0
                G = g - cut
            else:                                      # open up: room tone mid-pause
                E = S = (q[0] + q[1]) / 2
                F = G - g
            note = "pause retimed"
        else:
            ve, vs = voice_end(wa), voice_start(wb)
            if target is None:
                lo, hi = P.cut_within if pa["k"] == pb["k"] else P.cut_sentence
                G = float(np.clip(g, lo, hi))
            else:
                G = target
            ta = min(0.15, max(0.0, ve[1] - ve[0] - 0.04)) if ve else 0.0
            hb = min(0.25, max(0.0, vs[1] - vs[0] - 0.02)) if vs else 0.0
            if ta + hb > G:
                sc = G / (ta + hb)
                ta, hb = ta * sc, hb * sc
            if ve:
                E = ve[0] + ta
            else:
                E = words[wa + 1]["start"] - 0.01 if wa + 1 < len(words) else min(dur, words[wa]["end"] + 0.1)
            S = vs[1] - hb if vs else words[wb]["start"] - 0.03
            F, note = G - ta - hb, "cut"
        joins[note] += 1
        join_log.append({"raw": words[wa]["start"], "lines": [pa["k"] + 1, pb["k"] + 1], "kind": note,
                         "was_s": round(g, 2), "now_s": round(G, 2)})
        plan.append(("span", span_in, E, span_note))
        plan.append(("tone", max(0.0, F), note))
        span_in, span_note = S, note
    ve = voice_end(pieces[-1]["w"][-1])
    span_out = ve[0] + min(0.30, max(0.0, ve[1] - ve[0] - 0.04)) if ve else dur
    plan.append(("span", span_in, span_out, span_note))
    plan.append(("tone", P.tail, "tail"))

    # ---- room tone: typical quiet, no clicks, several stretches joined
    L = int(0.5 * sr)
    step = max(1, L // hop // 2)
    cands = []
    for f0 in range(0, max(0, nfr - L // hop), step):
        if not speech[f0:f0 + L // hop].any():
            seg = x[f0 * hop:f0 * hop + L]
            r = rms_db(seg)
            if r > -90:
                cands.append((r, 20 * np.log10(np.max(np.abs(seg)) + 1e-12) - r, f0 * hop))
    xf = int(0.02 * sr)
    ramp = (np.sin(np.linspace(0, np.pi / 2, xf)) ** 2).astype(np.float32)
    if cands:
        ref = np.percentile([c[0] for c in cands], 30)
        pool = (sorted([c for c in cands if abs(c[0] - ref) < 2.0], key=lambda c: c[1])[:6]
                or [min(cands, key=lambda c: abs(c[0] - ref))])
        bed = x[pool[0][2]:pool[0][2] + L].copy()
        for c in pool[1:]:
            nxt = x[c[2]:c[2] + L]
            bed = np.concatenate([bed[:-xf], bed[-xf:] * ramp[::-1] + nxt[:xf] * ramp, nxt[xf:]])
    else:
        log("  warning: no clean room tone found; gaps will be silent. Record a few seconds of silence first.")
        bed = np.zeros(L, dtype=np.float32)

    def tone(n):
        out = bed.copy()
        while len(out) < n:
            out = np.concatenate([out[:-xf], out[-xf:] * ramp[::-1] + bed[:xf] * ramp, bed[xf:]])
        return out[:n].astype(np.float32)

    # ---- render: overlap-add with 8 ms crossfades
    xfade = int(0.008 * sr)
    ramp_in = (np.sin(np.linspace(0, np.pi / 2, xfade)) ** 2).astype(np.float32)
    steps = []
    for st_ in plan:
        if st_[0] == "tone":
            n = int(round(st_[1] * sr))
            if n >= 3 * xfade:
                steps.append(("tone", n, None))
        else:
            a, b = int(st_[1] * sr), int(st_[2] * sr)
            if b - a >= 3 * xfade:
                steps.append(("span", (a, b), st_[3]))
    lens = [s[1] if s[0] == "tone" else s[1][1] - s[1][0] for s in steps]
    y = np.zeros(sum(lens) - xfade * (len(steps) - 1), dtype=np.float32)
    first_word = {}
    for p in pieces:
        first_word.setdefault(p["k"], p["w"][0])
    pos, edl, line_at = 0, [], {}
    for n_, (kind, arg, note) in enumerate(steps):
        c = tone(arg) if kind == "tone" else x[arg[0]:arg[1]].copy()
        if n_ > 0:
            c[:xfade] *= ramp_in
        if n_ < len(steps) - 1:
            c[-xfade:] *= ramp_in[::-1]
        y[pos:pos + len(c)] += c
        if kind == "span":
            a, b = arg[0] / sr, arg[1] / sr
            for kk, w0 in first_word.items():
                if kk not in line_at and a <= words[w0]["start"] <= b:
                    line_at[kk] = pos / sr + words[w0]["start"] - a
            edl.append({"raw_in": a, "raw_out": b, "clean_in": pos / sr, "clean_out": (pos + len(c)) / sr, "join": note})
        pos += len(c) - xfade

    # ---- what was cut, what still differs
    kept_w = {hyp_w[i] for r in readings for i in r}
    cuts, run = [], []
    for wi in list(range(len(words))) + [None]:
        if wi is not None and wi not in kept_w:
            run.append(wi)
            continue
        if run:
            whys = sorted({info[i]["why"] for i in range(len(hyp)) if hyp_w[i] in run and info[i]["why"]})
            cuts.append({"raw": words[run[0]]["start"], "words": " ".join(words[w]["text"] for w in run),
                         "why": ", ".join(whys)})
        run = []
    pickups, minor = [], []
    passes = defaultdict(set)
    for i in range(len(hyp)):
        if info[i]["kind"] != "ins":
            passes[sent_of[info[i]["pos"]]].add(info[i]["pass"])
    for k, ln in enumerate(lines):
        r = readings[k]
        if not r:
            pickups.append({"line": k + 1, "clean": None, "raw": None, "text": ln.text, "problem": "not found in the recording"})
            continue
        df = diffs(line_toks[k], [hyp[i] for i in r])
        minor += [{"line": k + 1, "book": d["book"], "read": d["read"]} for d in df if d["minor"]]
        major = [d for d in df if not d["minor"]]
        if major:
            pickups.append({"line": k + 1, "clean": line_at.get(k), "raw": words[hyp_w[r[0]]]["start"], "text": ln.text,
                            "problem": "; ".join({"replace": f"read '{d['read']}' for '{d['book']}'",
                                                  "delete": f"missing '{d['book']}'",
                                                  "insert": f"added '{d['read']}'"}[d["type"]] for d in major)})
    return {
        "audio": y, "room_tone": tone(2 * sr), "sr": sr,
        "summary": {
            "raw_minutes": round(dur / 60, 2), "edited_minutes": round(len(y) / sr / 60, 2),
            "lines": len(lines), "lines_found": sum(1 for r in readings if r),
            "lines_with_retakes": sum(1 for v in passes.values() if len(v) > 1),
            "restarts": restarts, "comps": len(comps), "joins": joins,
            "words_heard": len(words), "words_cut": len(words) - len(kept_w),
            "alignment_cost": cost, "raw_noise_floor_db": round(floor, 1),
        },
        "pickups": pickups, "minor": minor, "cuts": cuts, "comps": comps,
        "join_log": join_log, "edl": edl, "line_at": line_at,
    }
