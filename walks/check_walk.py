"""Two checks for a walk's master.

  check_walk.py limiter DRY.wav LIMITED.wav
      How hard the limiter works: the share of speech frames (10 ms) it takes 3 dB and 6 dB or more off, and the
      deepest cut. DRY is the voice with only the gain applied. Walk 0038, which David approved: 0.2 % at 6 dB, at
      most 6.3 dB. When it runs well over that, put the light compressor in front (see README).

  check_walk.py sync list.txt out.mp4 [seconds ...]
      The finished file's audio against the camera's own audio track, at the given times (default: spread along
      the file and just after every chapter join). The camera audio is decoded on its timestamps
      (aresample=async=1:min_hard_comp=0.001): the default threshold of 0.1 s leaves the few-millisecond gaps at the
      joins unfilled and fakes a shift. On the hike of 29 Oct 2026 the offset was a constant +5.5 ms everywhere."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

mode = sys.argv[1]
if mode == "limiter":
    d, sr = sf.read(sys.argv[2], dtype="float32")
    l, _ = sf.read(sys.argv[3], dtype="float32")
    n = min(len(d), len(l))
    h = sr // 100
    k = n // h
    rd = np.sqrt(np.mean(d[:k * h].reshape(k, h) ** 2, axis=1)) + 1e-9
    rl = np.sqrt(np.mean(l[:k * h].reshape(k, h) ** 2, axis=1)) + 1e-9
    speech = 20 * np.log10(rd) > 20 * np.log10(rd.max()) - 40
    red = 20 * np.log10(rd / rl)[speech]
    print(f"speech frames {speech.sum()}: 3 dB or more on {np.mean(red >= 3) * 100:.2f}%, "
          f"6 dB or more on {np.mean(red >= 6) * 100:.2f}%, deepest {red.max():.1f} dB")
    sys.exit()

lst, mp4, times = sys.argv[2], sys.argv[3], [float(t) for t in sys.argv[4:]]
SR = 16000
tmp = Path(tempfile.mkdtemp())
subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:a:0", "-af",
                "aresample=async=1:min_hard_comp=0.001:first_pts=0", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le",
                str(tmp / "cam.wav")], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le",
                str(tmp / "out.wav")], check=True)
c, _ = sf.read(tmp / "cam.wav", dtype="float32")
o, _ = sf.read(tmp / "out.wav", dtype="float32")
if not times:
    joins, t = [], 0.0
    for line in open(lst, encoding="utf-8"):
        p = line.strip()[6:-1]
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                            "-of", "csv=p=0", p], capture_output=True, text=True, check=True)
        t += float(r.stdout)
        joins.append(t)
    times = sorted({20.0, len(o) / SR / 2} | {j + 1.0 for j in joins[:-1]} | {len(o) / SR - 8})
for t in times:
    i, n, M = int(t * SR), 3 * SR, 800
    x = o[i:i + n]
    best = max(((lag, float(np.dot(x, c[i + lag:i + lag + n]) / (np.linalg.norm(x) * np.linalg.norm(c[i + lag:i + lag + n]) + 1e-9)))
                for lag in range(-M, M + 1) if 0 <= i + lag and len(c[i + lag:i + lag + n]) == n), key=lambda b: b[1])
    print(f"{t:8.1f} s  offset {best[0] / SR * 1000:+6.2f} ms  correlation {best[1]:.2f}")
