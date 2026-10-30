"""Frame-to-frame camera motion in the background around the passer-by (walk 0044 blur).
motion.py <video> <first frame> <last frame> <x0> <y0> <x1> <y1> <out.npy>
Phase correlation on a quarter-size crop of the 4K frame (the region must leave David out); writes the
cumulative shift C[f] in 4K pixels, so a point fixed in the scene sits at p0 + C[f] - C[f0]."""
import subprocess, sys
import numpy as np
from skimage.registration import phase_cross_correlation
FN, FD = 60000, 1001
src = sys.argv[1]
f0, f1 = int(sys.argv[2]), int(sys.argv[3])
x0, y0, x1, y1 = map(int, sys.argv[4:8])
Q = 4
w, h = (x1 - x0) // Q, (y1 - y0) // Q
ts = (f0 * FD - FD / 4) / FN
raw = subprocess.run(['ffmpeg', '-v', 'error', '-hwaccel', 'cuda', '-ss', f'{ts:.6f}', '-i', src, '-frames:v', str(f1 - f0 + 1),
                      '-vf', f'crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale={w}:{h},format=gray', '-f', 'rawvideo', '-'],
                     capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
C = np.zeros((len(fr), 2))
err = np.zeros(len(fr))
for i in range(1, len(fr)):
    a, b = fr[i - 1] - fr[i - 1].mean(), fr[i] - fr[i].mean()
    sh, e, _ = phase_cross_correlation(a * win, b * win, upsample_factor=8, normalization=None)
    # sh is the shift that registers b onto a, so content moved by -sh (dy, dx)
    C[i] = C[i - 1] + np.array([-sh[1], -sh[0]]) * Q
    err[i] = e
np.save(sys.argv[8], np.column_stack([np.arange(f0, f0 + len(fr)), C, err]))
d = np.diff(C, axis=0)
print(len(fr), 'frames; per-frame shift x/y: median', np.median(np.abs(d), 0).round(1), 'max', np.abs(d).max(0).round(1))
print('net', C[-1].round(0))
