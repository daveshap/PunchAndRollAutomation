"""Equalise a voice recording toward the average spectrum of David's studio voice.

  matcheq.py ref   out_ref.json studio1.wav [studio2.wav ...]      measure the studio recordings (once)
  matcheq.py fit   ref.json voice.wav out_curve.json [--max 9] [--low 6] [--iters 5]
  matcheq.py apply curve.json in.wav out.wav [--strength 1.0]
  matcheq.py show  ref.json file.wav [file.wav ...]                how far each file is from the studio voice

The spectrum is the average of the loud speech frames in sixth-octave bands from 80 Hz to 20 kHz, levelled to
the body of the voice (300 Hz to 3 kHz). 'fit' finds, by trying, the gain per band that brings voice.wav to the
studio's shape, within limits: at most --max dB either way, at most --low dB of boost below 140 Hz (the camera
barely records down there), and no boost above 18.5 kHz. 'apply' uses a minimum-phase filter, so there is no
ringing ahead of a sound and no delay. --strength 0.6 applies 60 % of the correction, in dB.
"""
import json
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

SR, N, HOP = 48000, 4096, 2048
C = np.array([80 * 2 ** (i / 6) for i in range(49)])
F = np.fft.rfftfreq(N, 1 / SR)


def load(path, start=None, dur=None):
    cmd = ['ffmpeg', '-v', 'error'] + (['-ss', str(start), '-t', str(dur)] if start is not None else [])
    cmd += ['-i', path, '-map', '0:a:0', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)


def ltas(x):
    n = (len(x) - N) // HOP
    idx = np.arange(N)[None, :] + HOP * np.arange(n)[:, None]
    w = np.hanning(N).astype(np.float32)
    acc, cnt, bodies, blocks = np.zeros(N // 2 + 1), 0, [], []
    for a in range(0, n, 2000):                       # two passes over blocks, to keep memory down
        P = np.abs(np.fft.rfft(x[idx[a:a + 2000]] * w, axis=1)) ** 2
        bodies.append(10 * np.log10(np.maximum(P[:, (F >= 300) & (F < 3000)].sum(axis=1), 1e-20)))
        blocks.append(P)
    thr = np.percentile(np.concatenate(bodies), 95) - 12
    for P, b in zip(blocks, bodies):
        acc += P[b > thr].sum(axis=0)
        cnt += int((b > thr).sum())
    avg = acc / max(cnt, 1)
    ref = 10 * np.log10(avg[(F >= 300) & (F < 3000)].sum())
    return np.array([10 * np.log10(max(avg[(F >= c / 2 ** (1 / 12)) & (F < c * 2 ** (1 / 12))].sum(), 1e-30)) - ref for c in C])


def fir(gain_db, taps=8192, nfft=1 << 16):
    f = np.fft.rfftfreq(nfft, 1 / SR)
    g = np.interp(np.log2(np.maximum(f, 20.0)), np.log2(C), gain_db, left=gain_db[0], right=gain_db[-1])
    cep = np.fft.irfft(np.log(10 ** (g / 20)), n=nfft)
    cep[1:nfft // 2] *= 2                               # fold the cepstrum: same loudness curve, minimum phase
    cep[nfft // 2 + 1:] = 0
    h = np.fft.irfft(np.exp(np.fft.rfft(cep, n=nfft)), n=nfft)[:taps]
    h[taps // 2:] *= np.hanning(taps)[taps // 2:]
    return h


def run(x, gain_db):
    return fftconvolve(x.astype(np.float64), fir(gain_db))[:len(x)].astype(np.float32)


def opt(args, name, default):
    return float(args[args.index(name) + 1]) if name in args else default


mode, args = sys.argv[1], sys.argv[2:]
if mode == 'ref':
    cur = [ltas(load(p)) for p in args[1:]]
    json.dump({'centres': C.tolist(), 'studio': np.mean(cur, axis=0).round(2).tolist(), 'from': args[1:]}, open(args[0], 'w'), indent=1)
    print('studio reference from', len(cur), 'recordings ->', args[0])
elif mode == 'fit':
    target = np.array(json.load(open(args[0]))['studio'])
    x = load(args[1])
    mx, low, iters = opt(args, '--max', 9.0), opt(args, '--low', 6.0), int(opt(args, '--iters', 5))
    hi = np.where(C < 140, low, np.where(C > 18500, 0.0, mx))
    gain = np.zeros(len(C))
    for it in range(iters):
        diff = ltas(run(x, gain)) - target
        m = (C >= 140) & (C <= 18500)
        print(f'pass {it + 1}: {np.sqrt(np.mean(diff[m] ** 2)):.2f} dB RMS from the studio voice, largest {np.abs(diff[m]).max():.1f} dB')
        gain = np.clip(gain - 0.9 * diff, -mx, hi)
        gain = np.convolve(np.pad(gain, 1, mode='edge'), [0.15, 0.7, 0.15], mode='valid')
    json.dump({'centres': C.tolist(), 'gain_db': gain.round(2).tolist(), 'fitted_on': args[1]}, open(args[2], 'w'), indent=1)
    print(' '.join(f'{c:.0f}:{g:+.1f}' for c, g in zip(C, gain)))
elif mode == 'apply':
    curve = np.array(json.load(open(args[0]))['gain_db']) * opt(args, '--strength', 1.0)
    x, sr = sf.read(args[1], dtype='float32', always_2d=True)
    assert sr == SR, sr
    sf.write(args[2], run(x.mean(axis=1), curve), SR, subtype='FLOAT')
elif mode == 'show':
    target = np.array(json.load(open(args[0]))['studio'])
    cols = [ltas(load(p)) - target for p in args[1:]]
    for i, c in enumerate(C):
        if c >= 100:
            print(f'{c:7.0f}' + ''.join(f'{col[i]:+8.1f}' for col in cols))
    m = (C >= 140) & (C <= 18500)
    for p, col in zip(args[1:], cols):
        print(f'{p}: RMS {np.sqrt(np.mean(col[m] ** 2)):.1f} dB, largest {np.abs(col[m]).max():.1f} dB (140 Hz to 18 kHz)')
