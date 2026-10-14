"""Render the selected source pieces and written pauses without making editorial choices."""
from __future__ import annotations

import math
import numpy as np

from .audio import rms_db
from .config import Settings
from .markup import Marks
from .pieces import Piece, Room

RENDER_VERSION = 2
JOIN_FADE = 0.004       # fades on either side of a splice; never overlap or shorten the timeline


def cut(x: np.ndarray, sr: int, room: Room, pieces: list[Piece], marks: Marks, settings: Settings,
        log=print, render: bool = True) -> dict:
    if sr <= 0 or len(marks.keep) != len(pieces) or len(marks.length) != len(pieces):
        raise ValueError("invalid sample rate or mark-up piece count")
    keep, dur = marks.keep, len(x) / sr

    def samples(seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("pause lengths must be finite and nonnegative")
        return int(round(seconds * sr))

    for k, value in marks.added.items():
        if not isinstance(k, int) or not 0 <= k <= len(pieces):
            raise ValueError("inserted pause has an invalid piece position")
        samples(value)
    for k, value in enumerate(marks.length):
        if value is not None:
            samples(value)
            if pieces[k].kind != "quiet":
                raise ValueError("only quiet pieces can have a changed duration")

    # A plan uses integer sample boundaries, so nothing disappears below a fade's length.
    steps, pos = [], 0

    def span(a, b):
        nonlocal pos
        a, b = max(0, int(round(a * sr))), min(len(x), int(round(b * sr)))
        if b <= a:
            return
        if steps and steps[-1][0] == "span" and steps[-1][2] == a:
            steps[-1] = ("span", steps[-1][1], b)
        else:
            steps.append(("span", a, b))
        pos += b - a

    def tone_step(n):
        nonlocal pos
        if n > 0:
            if steps and steps[-1][0] == "tone":
                steps[-1] = ("tone", steps[-1][1] + n)
            else:
                steps.append(("tone", n))
            pos += n

    tone_step(samples(settings.head))
    # Old transcripts describe the first through last measured words. Retain their
    # small exterior source handles; explicit endpoint pieces are obeyed directly.
    if pieces and keep[0] and pieces[0].kind != "quiet":
        q = room.before(0) if room.words else None
        lead = min(0.25, max(0.0, q[1] - q[0] - 0.02)) if q else 0.0
        span(max(0.0, pieces[0].a - lead), pieces[0].a)
    output, insertions = {}, {}
    for i in range(len(pieces) + 1):
        if i in marks.added:
            start = pos
            tone_step(samples(marks.added[i]))
            insertions[i] = (start / sr, pos / sr)
        if i == len(pieces):
            break
        p = pieces[i]
        if not keep[i]:
            continue
        start = pos
        if p.kind != "quiet" or marks.length[i] is None:
            span(p.a, p.b)
        else:
            wanted = samples(marks.length[i])
            a, b = max(0, int(round(p.a * sr))), min(len(x), int(round(p.b * sr)))
            available = max(0, b - a)
            if wanted == available:
                span(p.a, p.b)
            elif wanted < available:
                # Keep both sides of a shortened quiet, with no compulsory edge floor.
                left = wanted // 2
                span(a / sr, (a + left) / sr)
                span((b - wanted + left) / sr, b / sr)
            else:
                middle = a + available // 2
                span(a / sr, middle / sr)
                tone_step(wanted - available)
                span(middle / sr, b / sr)
        output[i] = (start / sr, pos / sr)
    if pieces and keep[-1] and pieces[-1].kind != "quiet":
        q = room.after(len(room.words) - 1) if room.words else None
        trail = min(0.30, max(0.0, q[1] - q[0] - 0.04)) if q else 0.0
        span(pieces[-1].b, min(dur, pieces[-1].b + trail))
    tone_step(samples(settings.tail))
    total = pos

    # Build a reusable room bed only when audio is requested and the plan needs it.
    bed = None
    if render and any(s[0] == "tone" for s in steps):
        hop, nfr, length = room.hop, len(room.db), max(1, int(0.5 * sr))
        frames = max(1, length // hop)
        occupied = room.speech.copy()
        for p in pieces:
            if p.kind != "quiet":
                a = max(0, int(p.a * sr // hop))
                b = min(nfr, int(np.ceil(p.b * sr / hop)))
                occupied[a:b] = True
        candidates = []
        for f0 in range(0, max(0, nfr - frames + 1), max(1, frames // 2)):
            if not occupied[f0:f0 + frames].any():
                seg = x[f0 * hop:f0 * hop + length]
                level = rms_db(seg)
                if len(seg) == length and level > -90:
                    crest = 20 * np.log10(np.max(np.abs(seg)) + 1e-12) - level
                    candidates.append((level, crest, f0 * hop))
        xf = min(max(1, int(0.02 * sr)), length // 2)
        bed_ramp = np.sin(np.linspace(0, np.pi / 2, xf)).astype(np.float32) ** 2
        if candidates:
            ref = np.percentile([c[0] for c in candidates], 30)
            pool = (sorted([c for c in candidates if abs(c[0] - ref) < 2.0], key=lambda c: c[1])[:6]
                    or [min(candidates, key=lambda c: abs(c[0] - ref))])
            bed = x[pool[0][2]:pool[0][2] + length].copy()
            for c in pool[1:]:
                nxt = x[c[2]:c[2] + length]
                if xf:
                    bed = np.concatenate([bed[:-xf], bed[-xf:] * bed_ramp[::-1] + nxt[:xf] * bed_ramp, nxt[xf:]])
                else:
                    bed = np.concatenate([bed, nxt])
        else:
            log("  warning: no clean room tone found; inserted room tone will be silent.")
            bed = np.zeros(length, dtype=np.float32)

    def tone(n):
        # Preallocate instead of repeatedly copying an ever-growing long pause.
        if len(bed) >= n:
            return bed[:n].copy()
        out = np.empty(n, dtype=np.float32)
        out[:len(bed)] = bed
        at = len(bed)
        while at < n:
            overlap = min(xf, at)
            take = min(len(bed) - overlap, n - at)
            if overlap:
                out[at - overlap:at] = out[at - overlap:at] * bed_ramp[:overlap][::-1] + bed[:overlap] * bed_ramp[:overlap]
            out[at:at + take] = bed[overlap:overlap + take]
            at += take
        return out

    y = np.zeros(total, dtype=np.float32) if render else None
    pos, edl = 0, []
    for i, step in enumerate(steps):
        kind = step[0]
        size = step[1] if kind == "tone" else step[2] - step[1]
        if render:
            chunk = tone(size) if kind == "tone" else x[step[1]:step[2]].copy()
            # Short fades suppress splice clicks without changing chosen durations or
            # importing audio from a cut region. Short pieces retain a full-level centre.
            fade = min(int(JOIN_FADE * sr), (size - 1) // 2)
            if fade:
                ramp = np.sin(np.linspace(0, np.pi / 2, fade)).astype(np.float32) ** 2
                if i:
                    chunk[:fade] *= ramp
                if i < len(steps) - 1:
                    chunk[-fade:] *= ramp[::-1]
            y[pos:pos + size] = chunk
        if kind == "span":
            edl.append({"raw_in": step[1] / sr, "raw_out": step[2] / sr,
                        "clean_in": pos / sr, "clean_out": (pos + size) / sr})
        pos += size

    voiced = [i for i, p in enumerate(pieces) if p.kind != "quiet" and keep[i]]
    joins = []
    for a, b in zip(voiced, voiced[1:]):
        mid = range(a + 1, b)
        cut_any = any(not keep[k] for k in mid)
        content_cut = any(not keep[k] and pieces[k].kind != "quiet" for k in mid)
        changed = cut_any or any(marks.length[k] is not None for k in mid) or any(k in marks.added for k in range(a + 1, b + 1))
        if changed:
            now = output[b][0] - output[a][1]
            joins.append({"raw": pieces[a].b, "clean": output[a][1],
                          "was_s": None if content_cut else pieces[b].a - pieces[a].b,
                          "asked_s": now, "now_s": now})
    # Include explicit changes before the first retained sound/word and after the last.
    first, last = (voiced[0], voiced[-1]) if voiced else (len(pieces), -1)
    for i, p in enumerate(pieces):
        if p.kind == "quiet" and (i < first or i > last) and (not keep[i] or marks.length[i] is not None):
            now = output[i][1] - output[i][0] if i in output else 0.0
            joins.append({"raw": p.a, "clean": output[i][0] if i in output else None,
                          "was_s": p.length, "asked_s": now, "now_s": now})
    for i, (a, b) in insertions.items():
        if i <= first or i > last:
            joins.append({"raw": pieces[i].a if i < len(pieces) else (pieces[-1].b if pieces else 0.0),
                          "clean": a, "was_s": 0.0, "asked_s": b - a, "now_s": b - a})

    cuts, run = [], []
    for i in list(range(len(pieces))) + [None]:
        if i is not None and not keep[i]:
            run.append(i)
            continue
        said = [k for k in run if pieces[k].kind != "quiet"]
        if said:
            nxt = next((v for v in voiced if v > run[-1]), None)
            prev = next((v for v in reversed(voiced) if v < run[0]), None)
            a = next((k for k in reversed(voiced) if k < run[0] and pieces[k].kind == "word"), None)
            b = next((k for k in voiced if k > run[-1] and pieces[k].kind == "word"), None)
            left = output[b][0] - output[a][1] if a is not None and b is not None else None
            clean = output[nxt][0] if nxt is not None else (output[prev][1] if prev is not None else samples(settings.head) / sr)
            cuts.append({"raw": pieces[said[0]].a, "clean": clean,
                         "seconds": pieces[run[-1]].b - pieces[run[0]].a, "pause_s": left,
                         "words": " ".join(pieces[k].text or f"[sound {pieces[k].length:.2f} s]" for k in said)})
        run = []
    kept = [{"text": p.text, "at": output[i][0], "end": output[i][1], "raw": p.a, "raw_end": p.b}
            for i, p in enumerate(pieces) if p.kind == "word" and keep[i]]
    sounds = [{"piece": i, "raw": p.a, "raw_end": p.b, "seconds": p.length,
               "level_db": p.level, "kept": bool(keep[i]),
               "at": output[i][0] if i in output else None, "end": output[i][1] if i in output else None}
              for i, p in enumerate(pieces) if p.kind == "sound"]
    removed_words = [{"text": p.text, "raw": p.a, "raw_end": p.b}
                     for i, p in enumerate(pieces) if p.kind == "word" and not keep[i]]
    return {"audio": y, "sr": sr, "cuts": cuts, "pauses": joins, "edl": edl, "kept": kept,
            "sounds": sounds, "removed_words": removed_words, "render_version": RENDER_VERSION,
            "summary": {"raw_minutes": round(dur / 60, 2), "edited_minutes": round(total / sr / 60, 2),
                        "words_heard": sum(p.kind == "word" for p in pieces), "words_cut": len(removed_words),
                        "sounds_cut": sum(not s["kept"] for s in sounds), "cuts": len(cuts),
                        "pauses_changed": sum(j["was_s"] is not None for j in joins),
                        "raw_noise_floor_db": round(room.floor, 1)}}
