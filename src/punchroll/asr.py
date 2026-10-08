"""Voice activity detection and speech recognition with word timings. Runs offline on CPU.

Speech is found with the Silero voice activity detector, grouped into chunks of up
to 20 seconds (a short phrase decoded on its own can come back empty; with its
neighbors it doesn't), and transcribed with NVIDIA Parakeet TDT 0.6B v2 through
sherpa-onnx. Results are cached per file, chunk by chunk, so an interrupted run
picks up where it stopped.

Two checks keep speech from going unheard, because the editor treats whatever lies
between two recognized words as a pause and keeps it: sound at the voice's level that
the detector left out is added to its stretches (add_missed_speech), and a stretch
that comes back without words from its chunk is decoded again on its own.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_closing

from . import models
from .audio import frame_db, resample

SR16 = 16000
SEGMENTER = "2"          # part of the cache key: raise it when the stretches or the retry change


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))]


def add_missed_speech(x16: np.ndarray, segs, sr: int = SR16, max_len: float = 25.0):
    """The detector's stretches, plus sound at the voice's level that it left out.

    The detector sometimes starts a stretch late, ends one early, or misses a short
    phrase between two pauses. A false start it misses would stay in the edit, and a
    line it misses would be reported as not read. So any sound that stays within 25 dB
    of the voice for 0.15 s or more, and comes within 15 dB of it, is added: joined to
    the stretch it touches, or as a stretch of its own. Breaths and clicks fall short.
    """
    segs = [(int(a), int(b)) for a, b in segs]
    if not segs:
        return segs
    db, hop = frame_db(x16, sr, 0.01)
    held = np.zeros(len(db), bool)                 # frames the detector already has
    for a, b in segs:
        held[a // hop:-(-b // hop)] = True
    rest = db[~held & (db > -90)]
    if not held.any() or not len(rest):
        return segs
    level, floor = float(np.percentile(db[held], 90)), float(np.percentile(rest, 20))
    gate = max(level - 25, floor + 12)
    if gate > level - 10:                          # too noisy to tell the voice from the room by level
        return segs
    extra = []
    for s, e in _runs(binary_closing(db > gate, structure=np.ones(15, bool))):   # bridges dips under 150 ms
        if e - s < 15 or db[s:e].max() < level - 15:
            continue
        extra += [((s + a) * hop, (s + b) * hop) for a, b in _runs(~held[s:e]) if b - a >= 10]
    out = []
    for a, b in sorted(segs + extra):
        if out and a - out[-1][1] <= hop and b - out[-1][0] <= max_len * sr:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def merge_segments(segs, max_gap=1.2 * SR16, max_len=20 * SR16):
    chunks = []
    for a, b in segs:
        if chunks and a - chunks[-1][1] < max_gap and b - chunks[-1][0] < max_len:
            chunks[-1] = (chunks[-1][0], b)
        else:
            chunks.append((a, b))
    return chunks


class Recognizer:
    def __init__(self, threads: int = 2, log=print):
        import sherpa_onnx
        paths = models.ensure_models(log)
        d = paths["asr_dir"]
        self._so = sherpa_onnx
        self.vad_model = str(paths["vad"])
        self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
            num_threads=threads, model_type="nemo_transducer")

    def vad(self, x16: np.ndarray) -> list[tuple[int, int]]:
        so = self._so
        cfg = so.VadModelConfig(
            silero_vad=so.SileroVadModelConfig(model=self.vad_model, threshold=0.5, min_silence_duration=0.3,
                                               min_speech_duration=0.2, max_speech_duration=25),
            sample_rate=SR16, num_threads=1)
        vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
        segs = []

        def drain():
            while not vad.empty():
                s = vad.front
                segs.append((int(s.start), int(s.start + len(s.samples))))
                vad.pop()

        for i in range(0, len(x16), 512):
            vad.accept_waveform(x16[i:i + 512])
            drain()
        vad.flush()
        drain()
        return segs

    def decode(self, x16: np.ndarray, a: int, b: int) -> list[dict]:
        a0, b0 = max(0, a - 3200), min(len(x16), b + 3200)
        st = self.rec.create_stream()
        st.accept_waveform(SR16, x16[a0:b0])
        self.rec.decode_stream(st)
        r = st.result
        toks, ts = list(r.tokens), list(r.timestamps)
        durs = list(getattr(r, "durations", []) or [])
        off, seg_end = a0 / SR16, b / SR16
        words: list[dict] = []
        boundary = False                           # a bare word-boundary token ("▁") before digits etc.
        for i, tok in enumerate(toks):
            raw = tok.replace("▁", " ")
            text = raw.strip()
            if not text:
                boundary = boundary or bool(raw)
                continue
            start = off + ts[i]
            end = start + (durs[i] if len(durs) == len(toks) and durs[i] > 0 else 0.0)
            punct = not any(c.isalnum() for c in text)
            starts_word = raw.startswith(" ") or boundary or not words
            boundary = False
            if starts_word and not punct:
                words.append({"text": text, "start": start, "end": end})
            elif words:
                words[-1]["text"] += text
                if not punct:                      # punctuation never stretches a word
                    words[-1]["end"] = max(words[-1]["end"], end)
        for i, w in enumerate(words):
            if w["end"] <= w["start"]:
                nxt = words[i + 1]["start"] if i + 1 < len(words) else seg_end
                w["end"] = min(nxt, w["start"] + 0.6, seg_end + 0.1)
        return [w for w in words if any(c.isalnum() for c in w["text"])]


def file_key(path: str | Path) -> str:
    """Identifies a recording by its size and its first and last megabyte (fast, survives renames)."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(f"{size}:{models.ASR_NAME}:{SEGMENTER}".encode())
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:12]


def cached_words(path, cache_dir):
    """The finished transcript for this exact file, if one is cached."""
    final = Path(cache_dir) / f"{Path(path).stem}-{file_key(path)}.words.json"
    return json.loads(final.read_text(encoding="utf-8")) if final.is_file() else None


def transcribe(path, x: np.ndarray, sr: int, rec, cache_dir, max_seconds=None, log=print):
    """Words (text, start, end in seconds from the start of this file), or None if paused.

    Each finished chunk is written to disk right away, so stopping and re-running
    continues where it left off. With max_seconds, it stops on purpose after that
    long (useful for shells with a time limit) and returns None.
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{Path(path).stem}-{file_key(path)}"
    final = cache / f"{key}.words.json"
    if final.is_file():
        return json.loads(final.read_text(encoding="utf-8"))
    part, vadf = cache / f"{key}.partial.jsonl", cache / f"{key}.vad.json"
    if callable(rec) and not isinstance(rec, Recognizer):
        rec = rec()
    x16 = resample(x, sr, SR16)
    if vadf.is_file():
        segs = [tuple(s) for s in json.loads(vadf.read_text())]
    else:
        t0 = time.time()
        found = rec.vad(x16)
        segs = add_missed_speech(x16, found)
        vadf.write_text(json.dumps(segs))
        added = (sum(b - a for a, b in segs) - sum(b - a for a, b in found)) / SR16
        log(f"  {Path(path).name}: {len(segs)} stretches of speech found in {time.time() - t0:.0f} s"
            + (f" ({added:.1f} s of it missed by the voice detector)" if added >= 0.1 else ""))
    chunks = merge_segments(segs)
    done = {}
    if part.is_file():
        for line in part.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["chunk"]] = d["words"]
    todo = [i for i in range(len(chunks)) if i not in done]
    if todo:
        total_s = sum((chunks[i][1] - chunks[i][0]) / SR16 for i in todo)
        log(f"  {Path(path).name}: transcribing {total_s / 60:.1f} min of speech in {len(todo)} chunks"
            + (f" ({len(done)} already done)" if done else ""))
    t0, spoken = time.time(), 0.0
    with open(part, "a", encoding="utf-8") as f:
        for n, i in enumerate(todo, 1):
            a, b = chunks[i]
            done[i] = rec.decode(x16, a, b)
            inside = [s for s in segs if a <= s[0] and s[1] <= b]
            for sa, sb in inside if len(inside) > 1 else ():
                lo, hi = sa / SR16, sb / SR16
                if any(lo - 0.3 <= w["start"] <= hi + 0.2 for w in done[i]):
                    continue
                # the recognizer can drop a short stretch at the end of a long chunk; alone, it hears it
                done[i] += [w for w in rec.decode(x16, sa, sb) if lo - 0.1 <= w["start"] <= hi]
            done[i].sort(key=lambda w: w["start"])
            f.write(json.dumps({"chunk": i, "words": done[i]}) + "\n")
            f.flush()
            spoken += (b - a) / SR16
            el = time.time() - t0
            if n % 25 == 0 or n == len(todo):
                rate = spoken / el if el else 0
                left = (total_s - spoken) / rate if rate else 0
                log(f"    {n}/{len(todo)} chunks, {rate:.1f}x real time, about {left / 60:.1f} min left")
            if max_seconds and el > max_seconds and n < len(todo):
                log(f"  paused after {len(done)}/{len(chunks)} chunks; run the same command again to continue")
                return None
    words = [w for i in range(len(chunks)) for w in done.get(i, [])]
    out = {"file": str(path), "duration": round(len(x) / sr, 3),
           "segments": [(round(a / SR16, 3), round(b / SR16, 3)) for a, b in segs],
           "words": [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in words]}
    final.write_text(json.dumps(out), encoding="utf-8")
    part.unlink(missing_ok=True)
    return out
