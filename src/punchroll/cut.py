"""Apply a marked-up transcript to the recording: cut what was struck, set the pauses that were written, join the rest.

Nothing here decides anything about the reading. Every cut and every pause comes from the mark-up.
What this file adds is the handiwork of a join: a few hundredths of a second of the room on each
side of it so no word is clipped, a short crossfade, and room tone taken from the recording itself
where a pause was made longer than the recording has.
"""
from __future__ import annotations

import numpy as np

from .audio import rms_db
from .config import Settings
from .markup import Marks
from .pieces import Piece, Room

EDGE_OUT = 0.05          # room kept after the word before a cut, even if the pause there was struck
EDGE_IN = 0.03           # room kept ahead of the word after a cut
XFADE = 0.008            # crossfade at every join


def cut(x: np.ndarray, sr: int, room: Room, pieces: list[Piece], marks: Marks, settings: Settings,
        log=print, render: bool = True) -> dict:
    keep, dur = marks.keep, len(x) / sr
    voiced = [i for i, p in enumerate(pieces) if p.kind != "quiet" and keep[i]]
    if not voiced:
        raise ValueError("the mark-up cuts every word of the recording")

    def want(k):                                       # how long a kept pause is to be
        return pieces[k].length if marks.length[k] is None else marks.length[k]

    # ---- the plan: stretches of the recording, with room tone between them where the mark-up asks for more
    first, last = voiced[0], voiced[-1]
    if first > 0:
        lead = pieces[first - 1].length if pieces[first - 1].kind == "quiet" else 0.0
    else:
        q = room.before(0)
        lead = q[1] - q[0] if q else 0.0
    span_in = max(0.0, pieces[first].a - min(0.25, max(0.0, lead - 0.02)))
    plan, joins = [("tone", settings.head)], []
    for A, B in zip(voiced, voiced[1:]):
        mid = range(A + 1, B)
        asked = sum(want(k) for k in mid if pieces[k].kind == "quiet" and keep[k])
        asked += sum(marks.added.get(k, 0.0) for k in range(A + 1, B + 1))
        was = pieces[B].a - pieces[A].b                # all that lay between the two in the recording
        cut_any = any(not keep[k] for k in mid)
        if not cut_any and abs(asked - was) < 0.005:
            continue                                   # as recorded: nothing to join
        if not cut_any:                                # a pause made shorter or longer, nothing taken out
            if asked < was:
                E, S, F = pieces[A].b + 0.4 * asked, pieces[B].a - 0.6 * asked, 0.0
            else:
                E = S = (pieces[A].b + pieces[B].a) / 2
                F = asked - was
        else:
            qa = A + 1 if pieces[A + 1].kind == "quiet" else None      # the quiet right after A in the recording
            qb = B - 1 if pieces[B - 1].kind == "quiet" else None      # the quiet that leads into B
            a_len = pieces[qa].length if qa is not None else 0.0
            b_len = pieces[qb].length if qb is not None else 0.0
            if qa is not None and qa == qb:
                a_len = b_len = a_len / 2
            a_kept, b_kept = qa is not None and keep[qa], qb is not None and keep[qb]
            a_use = min(want(qa), a_len) if a_kept else min(EDGE_OUT, a_len)
            b_use = min(want(qb), b_len) if b_kept else min(EDGE_IN, b_len)
            over = a_use + b_use - asked               # the edges come out of the pause that was asked for
            if over > 0 and b_kept:
                give = min(over, max(0.0, b_use - min(EDGE_IN, b_len)))
                b_use, over = b_use - give, over - give
            if over > 0 and a_kept:
                a_use -= min(over, max(0.0, a_use - min(EDGE_OUT, a_len)))
            F = max(0.0, asked - a_use - b_use)
            E, S = pieces[A].b + a_use, pieces[B].a - b_use
        joins.append({"raw": pieces[A].b, "was_s": None if cut_any else round(was, 2), "asked_s": round(asked, 2),
                      "now_s": round((E - pieces[A].b) + F + (pieces[B].a - S), 2), "after": A})
        plan += [("span", span_in, E), ("tone", F)]
        span_in = S
    if last + 1 < len(pieces):
        trail = pieces[last + 1].length if pieces[last + 1].kind == "quiet" else 0.0
    else:
        q = room.after(len(room.words) - 1)
        trail = q[1] - q[0] if q else 0.0
    plan += [("span", span_in, min(dur, pieces[last].b + min(0.30, max(0.0, trail - 0.04)))), ("tone", settings.tail)]

    # ---- room tone for the head, the tail and any pause made longer: typical quiet, no clicks, several stretches joined
    hop, nfr, L = room.hop, len(room.db), int(0.5 * sr)
    cands = []
    for f0 in range(0, max(0, nfr - L // hop), max(1, L // hop // 2)):
        if not room.speech[f0:f0 + L // hop].any():
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
        log("  warning: no clean room tone found; the head, the tail and lengthened pauses will be silent.")
        bed = np.zeros(L, dtype=np.float32)

    def tone(n):
        out = bed.copy()
        while len(out) < n:
            out = np.concatenate([out[:-xf], out[-xf:] * ramp[::-1] + bed[:xf] * ramp, bed[xf:]])
        return out[:n].astype(np.float32)

    # ---- render: overlap-add with short crossfades
    xfade = int(XFADE * sr)
    ramp_in = (np.sin(np.linspace(0, np.pi / 2, xfade)) ** 2).astype(np.float32)
    steps = []
    for st in plan:
        if st[0] == "tone":
            n = int(round(st[1] * sr))
            if n >= 3 * xfade:
                steps.append(("tone", n))
        else:
            a, b = int(st[1] * sr), int(st[2] * sr)
            if b - a >= 3 * xfade:
                steps.append(("span", (a, b)))
    total = sum(s[1] if s[0] == "tone" else s[1][1] - s[1][0] for s in steps) - xfade * (len(steps) - 1)
    y = np.zeros(total, dtype=np.float32) if render else None
    pos, edl = 0, []
    for n, (kind, arg) in enumerate(steps):
        size = arg if kind == "tone" else arg[1] - arg[0]
        if render:
            c = tone(arg) if kind == "tone" else x[arg[0]:arg[1]].copy()
            if n > 0:
                c[:xfade] *= ramp_in
            if n < len(steps) - 1:
                c[-xfade:] *= ramp_in[::-1]
            y[pos:pos + size] += c
        if kind == "span":
            edl.append({"raw_in": arg[0] / sr, "raw_out": arg[1] / sr, "clean_in": pos / sr, "clean_out": (pos + size) / sr})
        pos += size - xfade

    def clean_at(t):                                   # where a moment of the recording sits in the finished file
        for e in edl:
            if e["raw_in"] - 1e-6 <= t <= e["raw_out"] + 1e-6:
                return e["clean_in"] + t - e["raw_in"]
        return None

    # ---- what was done, for the report
    cuts, run = [], []
    for i in list(range(len(pieces))) + [None]:
        if i is not None and not keep[i]:
            run.append(i)
            continue
        said = [k for k in run if pieces[k].kind != "quiet"]
        if said:
            nxt = next((v for v in voiced if v > run[-1]), None)
            a = next((k for k in range(run[0] - 1, -1, -1) if pieces[k].kind == "word" and keep[k]), None)
            b = next((k for k in range(run[-1] + 1, len(pieces)) if pieces[k].kind == "word" and keep[k]), None)
            left = None                                # what now stands between the kept words on either side
            if a is not None and b is not None:
                left = sum(want(k) if pieces[k].kind == "quiet" else pieces[k].length for k in range(a + 1, b) if keep[k])
                left = round(left + sum(marks.added.get(k, 0.0) for k in range(a + 1, b + 1)), 2)
            cuts.append({"raw": pieces[said[0]].a,
                         "clean": clean_at(pieces[nxt].a) if nxt is not None else clean_at(pieces[last].b),
                         "seconds": round(pieces[run[-1]].b - pieces[run[0]].a, 2), "pause_s": left,
                         "words": " ".join(pieces[k].text or f"[sound {pieces[k].length:.2f} s]" for k in said)})
        run = []
    for j in joins:
        j["clean"] = clean_at(pieces[j.pop("after")].b)
    words = [p for p in pieces if p.kind == "word"]
    kept, at = [], 0.0                                 # the words that stay, with their times in the recording and in the edit
    for i in voiced:
        p = pieces[i]
        if p.kind == "word":
            mid = clean_at((p.a + p.b) / 2)
            at = at if mid is None else mid - p.length / 2
            kept.append({"text": p.text, "at": at, "end": at + p.length, "raw": p.a, "raw_end": p.b})
    return {
        "audio": y, "sr": sr, "cuts": cuts, "pauses": joins, "edl": edl, "kept": kept,
        "summary": {
            "raw_minutes": round(dur / 60, 2), "edited_minutes": round(total / sr / 60, 2),
            "words_heard": len(words), "words_cut": sum(1 for i, p in enumerate(pieces) if p.kind == "word" and not keep[i]),
            "sounds_cut": sum(1 for i, p in enumerate(pieces) if p.kind == "sound" and not keep[i]),
            "cuts": len(cuts), "pauses_changed": sum(1 for j in joins if j["was_s"] is not None),
            "raw_noise_floor_db": round(room.floor, 1),
        },
    }
