"""Align a narration read to its script, allowing restarts, skips, asides, and slips.

The transcript is consumed in order while a pointer moves through the script.
Each move has a cost (see AlignSettings); the cheapest path explains the whole
read. Because a restart is cheaper than even one repeated word, "in each case,
in each case" and whole-paragraph retakes both come out as restarts. For every
script word the last reading of it wins: the editor's rule "keep the last good take".

Costs are integers, so the dynamic programming is exact. Memory is one int32 per
(spoken token x script token): a 60-minute chapter is roughly 8,000 x 8,000, or
about 250 MB.
"""
from __future__ import annotations

import bisect
from collections import defaultdict

import numpy as np

from .config import AlignSettings

SOUND = "[sound]"        # stands in the transcript for sound at the voice's level that the recognizer gave no word for
FILLERS = {"uh", "um", "erm", "uhm", "hmm", "mm", "ah", "er", "sorry", "yeah", "okay", "ok", "oops", SOUND}
INF = 1_000_000_000


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
    """Make compounds comparable: script 'chatgpt' vs heard 'chat gpt', script 'cow paths' vs heard 'cowpaths'.

    A script word that never appears in the transcript but equals two adjacent heard
    tokens is split in the script; a heard word that isn't in the script but equals
    two adjacent script tokens is split in the transcript (both halves keep the same
    audio word, so nothing is lost from the edit).
    """
    hv = set(hyp)
    sv = {t for toks_ in line_tokens for t in toks_}
    hb = {a + b: (a, b) for a, b in zip(hyp, hyp[1:]) if a + b not in hv}
    sb = {}
    for toks_ in line_tokens:
        for a, b in zip(toks_, toks_[1:]):
            sb.setdefault(a + b, (a, b))
    new_lines = []
    for toks_ in line_tokens:
        out = []
        for t in toks_:
            out.extend(hb[t] if t not in hv and t in hb else (t,))
        new_lines.append(out)
    new_hyp, new_w = [], []
    for t, w in zip(hyp, hyp_w):
        parts = sb[t] if t not in sv and t in sb else (t,)
        new_hyp.extend(parts)
        new_w.extend([w] * len(parts))
    return new_lines, new_hyp, new_w


class Aligner:
    def __init__(self, hyp: list[str], script: list[str], settings: AlignSettings | None = None,
                 free_jumps=()):
        """free_jumps: spoken-token indices where a new recording starts (a pickup file,
        the next session). The pointer may move anywhere there at no cost, and at the end
        of the last recording it may jump to the end of the script, so a pickup recorded
        after the chapter replaces the line it re-reads."""
        s = settings or AlignSettings()
        self.hyp, self.script, self.s = hyp, script, s
        N, M = len(hyp), len(script)
        self.N, self.M = N, M
        self.free = set(free_jumps) | ({N} if free_jumps else set())
        if (N + 1) * (M + 1) > s.max_cells:
            raise ValueError(f"too big to align in one piece ({N} spoken words x {M} script words); "
                             "split the recording and the script into smaller sections")
        vs = {w: i for i, w in enumerate(sorted(set(script)))}
        vh = {w: i for i, w in enumerate(sorted(set(hyp)))}
        self.sid = np.array([vs[w] for w in script], dtype=np.int32)
        self.hid = np.array([vh[w] for w in hyp], dtype=np.int32)
        by_len, by_stem = defaultdict(list), defaultdict(list)
        for w in vs:
            by_len[len(w)].append(w)
            by_stem[w.rstrip("s")].append(w)
        cm = np.full((len(vh), len(vs)), s.substitute, dtype=np.int32)
        for h, a in vh.items():
            cands = set(by_stem.get(h.rstrip("s"), ()))
            if len(h) >= 4:
                for L in (len(h) - 1, len(h), len(h) + 1):
                    cands.update(by_len.get(L, ()))
            if h.startswith("assist"):
                cands.update(w for w in vs if w.startswith("assist"))
            for w in cands:
                if w == h:
                    cm[a, vs[w]] = 0
                elif near(h, w):
                    cm[a, vs[w]] = s.near
            if h in vs:
                cm[a, vs[h]] = 0
        self.cm = cm
        self.filler = np.array([w in FILLERS for w in hyp], dtype=bool)
        self.ins_norm = np.full(M + 1, s.insert, dtype=np.int32)
        self.ins_fill = np.full(M + 1, s.insert_filler, dtype=np.int32)
        for v in (self.ins_norm, self.ins_fill):
            v[0] = v[M] = min(s.insert_edge, v[1] if M else v[0])
        self.C = np.concatenate([[0], np.cumsum(np.full(M, s.delete, dtype=np.int64))]).astype(np.int32)
        self.D = None

    def _jump_costs(self, i):
        return (0, 0) if i in self.free else (self.s.skip, self.s.restart)

    def _within(self, D0, i):
        C = self.C
        skip, restart = self._jump_costs(i)
        D1a = np.minimum.accumulate(D0 - C) + C                                  # deletions
        fj = np.empty_like(D0)
        fj[0] = INF
        fj[1:] = np.minimum.accumulate(D0)[:-1] + skip                           # skip forward
        D1 = np.minimum(D1a, fj)
        bj = np.empty_like(D0)
        bj[-1] = INF
        bj[:-1] = np.minimum.accumulate(D1[::-1])[::-1][1:] + restart            # restart
        return D1a, D1, np.minimum(D1, bj)

    def _row0(self, i):
        if i == 0:
            D0 = np.full(self.M + 1, INF, dtype=np.int32)
            D0[0] = 0
            return D0
        prev = self.D[i - 1]
        D0 = prev + (self.ins_fill if self.filler[i - 1] else self.ins_norm)
        np.minimum(D0[1:], prev[:-1] + self.cm[self.hid[i - 1]][self.sid], out=D0[1:])
        return D0

    def run(self):
        self.D = np.empty((self.N + 1, self.M + 1), dtype=np.int32)
        for i in range(self.N + 1):
            self.D[i] = self._within(self._row0(i), i)[2]
        return self._backtrace()

    def _backtrace(self):
        ev, i, p, stage = [], self.N, self.M, 2
        cache = {}
        while not (i == 0 and p == 0 and stage == 0):
            if i not in cache:
                D0 = self._row0(i)
                cache = {i: (D0,) + self._within(D0, i)}
            D0, D1a, D1, D2 = cache[i]
            skip, restart = self._jump_costs(i)
            if stage == 2:
                if D2[p] == D1[p]:
                    stage = 1
                    continue
                pp = p + 1 + int(np.argmax(D1[p + 1:] + restart == D2[p]))
                ev.append(("restart", i, pp, p))
                p, stage = pp, 1
                continue
            if stage == 1:
                if D1[p] == D0[p]:
                    stage = 0
                    continue
                if D1[p] == D1a[p]:
                    vals = D0[:p] - self.C[:p] + self.C[p]
                    pp = int(np.flatnonzero(vals == D1[p])[-1])
                    for q in range(p - 1, pp - 1, -1):
                        ev.append(("del", i, q))
                else:
                    pp = int(np.argmax(D0[:p] + skip == D1[p]))
                    ev.append(("skip", i, pp, p))
                p, stage = pp, 0
                continue
            prev = self.D[i - 1]
            c = int(self.cm[self.hid[i - 1], self.sid[p - 1]]) if p >= 1 else None
            if p >= 1 and D0[p] == prev[p - 1] + c:
                ev.append(("match" if c == 0 else "sub", i - 1, p - 1))
                p -= 1
            else:
                ev.append(("ins", i - 1, p))
            i, stage = i - 1, 2
        ev.reverse()
        cost = int(self.D[self.N][self.M]) / 10.0
        self.D = None                                  # free the matrix
        return ev, cost


def last_take(events, hyp: list[str], sent_of: list[int], whole: bool = False):
    """Apply 'last reading wins'. Returns one dict per spoken token:
    kind (match/sub/ins), pos (script index) or slot, pass, kept, why.

    whole: the last take of a line stands as it was read (comps off). A take that leaves the end of
    a sentence unread and reads on has dropped that ending, and an earlier take's is not put back.
    """
    n = len(hyp)
    info = [None] * n
    pass_id = 0
    for e in events:
        if e[0] == "restart":
            pass_id += 1
        elif e[0] in ("match", "sub"):
            info[e[1]] = {"kind": e[0], "pos": e[2], "pass": pass_id}
        elif e[0] == "ins":
            info[e[1]] = {"kind": "ins", "slot": e[2], "pass": pass_id}
    writer = {}
    for i, d in enumerate(info):
        if d["kind"] != "ins":
            writer[d["pos"]] = i
    for i, d in enumerate(info):
        if d["kind"] != "ins":
            d["kept"] = writer[d["pos"]] == i
            d["why"] = None if d["kept"] else "re-read later"
    # a word a later take read straight past is not part of the last reading: keeping the earlier
    # take's would drop one word or phrase of that take into the middle of the later one
    read, passed, dropped, pass_id = defaultdict(list), [], [], 0
    for e in events:
        if e[0] == "restart":
            pass_id += 1
        elif e[0] in ("match", "sub"):
            read[pass_id].append(e[2])
        elif e[0] == "del":
            passed.append((pass_id, e[2], False))
        elif e[0] == "skip":
            if sent_of[e[2]] == sent_of[e[3] - 1]:
                passed += [(pass_id, q, True) for q in range(e[2], e[3])]
            if whole:                                  # the rest of the sentence the take was in when it jumped ahead
                dropped += [(pass_id, q) for q in range(e[2], e[3]) if sent_of[q] == sent_of[e[2]]]
    for p, q, one_line in passed:
        got = read[p]
        at = bisect.bisect_left(got, q)
        if at in (0, len(got)) or one_line and not sent_of[got[at - 1]] == sent_of[q] == sent_of[got[at]]:
            continue                                   # the take started or stopped here; it didn't read past
        if q in writer and info[writer[q]]["pass"] < p:
            info[writer[q]]["kept"], info[writer[q]]["why"] = False, "re-read later"
    # with the last take kept whole: a take that was reading this sentence, left its ending unread and read on
    for p, q in dropped:
        got = read[p]
        at = bisect.bisect_left(got, q)
        if 0 < at < len(got) and sent_of[got[at - 1]] == sent_of[q] and q in writer and info[writer[q]]["pass"] < p:
            info[writer[q]]["kept"], info[writer[q]]["why"] = False, "left out of the last take"
    # a misread word right before a mid-line restart is what the reader stopped to fix;
    # if the restart didn't re-read it, drop it
    pass_id = 0
    for e in events:
        if e[0] != "restart":
            continue
        pass_id += 1
        q = e[3] - 1
        while q >= 0 and q in writer and sent_of[q] == sent_of[e[3]]:
            d = info[writer[q]]
            if d["pass"] >= pass_id or d["kind"] != "sub":
                break
            d["kept"], d["why"] = False, "misread before a restart"
            q -= 1
    # insertions: keep short ad-libs inside a kept stretch of one line; cut the rest
    i = 0
    while i < n:
        if info[i]["kind"] != "ins":
            i += 1
            continue
        j = i
        while j < n and info[j]["kind"] == "ins":
            j += 1
        prev = i - 1 if i > 0 else None
        nxt = j if j < n else None
        ok = (prev is not None and nxt is not None and info[prev]["kept"] and info[nxt]["kept"]
              and info[prev]["pass"] == info[nxt]["pass"]
              and sent_of[info[prev]["pos"]] == sent_of[info[nxt]["pos"]]
              and info[nxt]["pos"] > info[prev]["pos"] and j - i <= 2)
        for g in range(i, j):
            filler = hyp[g] in FILLERS
            info[g]["kept"] = ok and not filler
            if info[g]["kept"]:
                info[g]["why"] = None
            elif filler:
                info[g]["why"] = "stray sound" if hyp[g] == SOUND else "filler"
            elif prev is None or nxt is None:
                info[g]["why"] = "outside the text"
            elif not (info[prev]["kept"] and info[nxt]["kept"]):
                info[g]["why"] = "re-read later"
            elif sent_of[info[prev]["pos"]] != sent_of[info[nxt]["pos"]]:
                info[g]["why"] = "between lines"
            else:
                info[g]["why"] = "aside"
        i = j
    return info
