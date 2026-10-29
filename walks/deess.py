"""De-ess a voice so its loudest 's' sounds sit where they do in David's studio reads.

usage: deess.py in.wav out.wav [--target -12.1] [--ratio 4] [--max 10]

The strength of an 's' is measured as the 5 to 10 kHz energy of a 21 ms frame against the typical level of the
voice's body (300 Hz to 3 kHz). In his top three studio reads the 99th percentile of that sits at -11.4 to -13.4 dB
(mean -12.1). This finds the threshold that brings the voice's own 99th percentile to --target, then turns down
everything above 4 kHz in those frames only (a --ratio of 4 above the threshold, at most --max dB), with an instant
attack and a 40 ms release. The sparkle between the 's' sounds is left as it is.
"""
import sys

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

N, H = 1024, 256


def opt(name, default):
    a = sys.argv
    return float(a[a.index(name) + 1]) if name in a else default


x, sr = sf.read(sys.argv[1], dtype='float32', always_2d=True)
x = x.mean(axis=1)
target, ratio, mx = opt('--target', -12.1), opt('--ratio', 4.0), opt('--max', 10.0)
F = np.fft.rfftfreq(N, 1 / sr)
w = np.hanning(N + 1)[:N].astype(np.float32)
xp = np.pad(x, (N, N))
frames = sliding_window_view(xp, N)[::H]
nf = len(frames)
s, b = np.zeros(nf), np.zeros(nf)
for a in range(0, nf, 8192):
    P = np.abs(np.fft.rfft(frames[a:a + 8192] * w, axis=1)) ** 2
    s[a:a + 8192] = P[:, (F >= 5000) & (F < 10000)].sum(axis=1)
    b[a:a + 8192] = P[:, (F >= 300) & (F < 3000)].sum(axis=1)
bdb = 10 * np.log10(np.maximum(b, 1e-20))
ref = np.percentile(bdb[bdb > np.percentile(bdb, 95) - 12], 50)
sdb = 10 * np.log10(np.maximum(s, 1e-20)) - ref


def reduce(T):
    r = np.minimum(np.maximum(sdb - T, 0) * (1 - 1 / ratio), mx)
    out = np.empty_like(r)                      # instant attack, 40 ms release
    k = np.exp(-H / sr / 0.040)
    acc = 0.0
    for i, v in enumerate(r):
        acc = v if v > acc else acc * k
        out[i] = acc
    return out


lo, hi = target - 15, target + 15               # find the threshold that lands the 99th percentile on target
for _ in range(20):
    T = (lo + hi) / 2
    p99 = np.percentile(sdb - reduce(T), 99)
    lo, hi = (T, hi) if p99 < target else (lo, T)
red = reduce(T)
ramp = np.clip((F - 3500) / 1500, 0, 1)         # 0 below 3.5 kHz, full above 5 kHz
y = np.zeros(len(xp), dtype=np.float64)
for a in range(0, nf, 8192):
    X = np.fft.rfft(frames[a:a + 8192] * w, axis=1)
    g = 10 ** (-(red[a:a + 8192, None] * ramp[None, :]) / 20)
    seg = np.fft.irfft(X * g, n=N, axis=1) * w
    for k2 in range(len(seg)):
        o = (a + k2) * H
        y[o:o + N] += seg[k2]
y = (y / 1.5)[N:N + len(x)]
sf.write(sys.argv[2], y.astype(np.float32), sr, subtype='FLOAT')
after = sdb - red
print(f"threshold {T:+.1f} dB: 's' peaks 99th {np.percentile(sdb, 99):+.1f} -> {np.percentile(after, 99):+.1f} dB, "
      f"99.9th {np.percentile(sdb, 99.9):+.1f} -> {np.percentile(after, 99.9):+.1f} dB; frames touched {100 * (red > 0.5).mean():.1f} %")
