"""Even out the tone of a voice over time: an automatic EQ that follows the speaker.

usage: adaptmatch.py in.wav out.wav [--win 3] [--boost 8] [--cut 6]

Outdoors the voice changes colour every time the speaker turns his head: on walk 0038 the 5 to 8 kHz band swung
over 20 dB from one 30-second stretch to the next, and the 2 to 5 kHz presence band over 7 dB. A fixed EQ can't
follow that. This measures the tone in six octave bands from 120 Hz to 8 kHz, relative to the body of the voice
(300 Hz to 3 kHz), over a sliding window of --win seconds of speech, and turns each band up or down toward the
recording's own long-term average (at most --boost dB up, --cut dB down). It only acts where the window holds
enough speech, and the gains glide, so it never pumps. The long-term tone is left as it was, for matcheq.py to
match to the studio afterwards. Above 8 kHz it holds the 4 to 8 kHz gain (AP-BWE rebuilds that range anyway).
"""
import sys

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

N, H = 2048, 512
EDGES = [120, 250, 500, 1000, 2000, 4000, 8000]


def opt(name, default):
    a = sys.argv
    return float(a[a.index(name) + 1]) if name in a else default


def movsum(v, n):
    c = np.cumsum(np.concatenate([np.zeros((1,) + v.shape[1:]), v]), axis=0)
    i = np.arange(len(v))
    lo, hi = np.clip(i - n // 2, 0, len(v)), np.clip(i + n // 2 + 1, 0, len(v))
    return c[hi] - c[lo]


x, sr = sf.read(sys.argv[1], dtype='float32', always_2d=True)
x = x.mean(axis=1)
win, boost, cut = opt('--win', 3.0), opt('--boost', 8.0), opt('--cut', 6.0)
F = np.fft.rfftfreq(N, 1 / sr)
w = np.hanning(N + 1)[:N].astype(np.float32)          # periodic Hann: analysis and synthesis, 75 % overlap
xp = np.pad(x, (N, N))
frames = sliding_window_view(xp, N)[::H]
nf = len(frames)
nb = len(EDGES) - 1
E, body = np.zeros((nf, nb)), np.zeros(nf)
for a in range(0, nf, 4096):
    P = np.abs(np.fft.rfft(frames[a:a + 4096] * w, axis=1)) ** 2
    for b in range(nb):
        E[a:a + 4096, b] = P[:, (F >= EDGES[b]) & (F < EDGES[b + 1])].sum(axis=1)
    body[a:a + 4096] = P[:, (F >= 300) & (F < 3000)].sum(axis=1)
bdb = 10 * np.log10(np.maximum(body, 1e-20))
speech = (bdb > np.percentile(bdb, 95) - 15).astype(float)
target = (speech[:, None] * E).sum(axis=0) / (speech * body).sum()
n = int(win * sr / H)
ratio = movsum(speech[:, None] * E, n) / np.maximum(movsum(speech * body, n), 1e-20)[:, None]
conf = np.clip(movsum(speech, n) / n / 0.3, 0, 1)          # full action when 30 % of the window is speech
gain = np.clip(10 * np.log10(np.maximum(target, 1e-30) / np.maximum(ratio, 1e-30)), -cut, boost) * conf[:, None]
gain = movsum(gain, int(1.0 * sr / H)) / movsum(np.ones((nf, 1)), int(1.0 * sr / H))   # glide over a second
centres = np.sqrt(np.array(EDGES[:-1]) * np.array(EDGES[1:]))
lf = np.log2(np.maximum(F, 1.0))
Wi = np.zeros((len(F), nb))
for b in range(nb):
    e = np.zeros(nb)
    e[b] = 1
    Wi[:, b] = np.interp(lf, np.log2(centres), e)
Wi *= np.clip((F - 100) / (centres[0] - 100), 0, 1)[:, None]   # fade to 0 dB below the lowest band
y = np.zeros(len(xp), dtype=np.float64)
for a in range(0, nf, 4096):
    X = np.fft.rfft(frames[a:a + 4096] * w, axis=1)
    g = 10 ** ((gain[a:a + 4096] @ Wi.T) / 20)
    seg = np.fft.irfft(X * g, n=N, axis=1) * w
    for k in range(len(seg)):
        s = (a + k) * H
        y[s:s + N] += seg[k]
y = (y / 1.5)[N:N + len(x)]                                  # Hann squared at 75 % overlap sums to 1.5
sf.write(sys.argv[2], y.astype(np.float32), sr, subtype='FLOAT')
g = gain[speech > 0]
print('band gains while speaking (dB, 5th to 95th percentile): ' + ', '.join(
    f'{EDGES[b]}-{EDGES[b + 1]} Hz {np.percentile(g[:, b], 5):+.1f}..{np.percentile(g[:, b], 95):+.1f}' for b in range(nb)))
