"""Rebuild the top of a speech recording with AP-BWE (the 16 kHz to 48 kHz model).

Below the crossover the output is the input, untouched. Above it comes what the model generates from the
part of the voice that is below 8 kHz.

usage: apbwe_run.py --repo <AP-BWE code dir> --weights <g_16kto48k.safetensors> in.wav out.wav
                    [--cross 7700] [--amount 1.0] [--model-out file.wav] [--chunk 15] [--device cuda|cpu]

The input is read as mono. The output is 48 kHz, 32-bit float, the same length as the input and in step with it.
The model runs on the graphics card when torch can see one (added 2026-10-14), otherwise on the processor.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch
import torchaudio.functional as aF
from safetensors.torch import load_file
from scipy.signal import fftconvolve, firwin

ap = argparse.ArgumentParser()
ap.add_argument('--repo', required=True)
ap.add_argument('--weights', required=True)
ap.add_argument('--cross', type=float, default=7700.0, help='crossover in Hz between the input and the generated top')
ap.add_argument('--amount', type=float, default=1.0, help='level of the generated top, 1.0 = as the model made it')
ap.add_argument('--model-out', default=None, help="also save the model's own full-band output")
ap.add_argument('--chunk', type=float, default=15.0, help='seconds per chunk')
ap.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu', help='cuda (graphics card) or cpu')
ap.add_argument('src')
ap.add_argument('dst')
a = ap.parse_args()

sys.path.insert(0, os.path.abspath(a.repo))
from models.model import APNet_BWE_Model  # noqa: E402  (the repo's own model definition)


class H(dict):
    __getattr__ = dict.__getitem__


h = H(json.load(open(os.path.join(os.path.dirname(os.path.abspath(a.weights)), 'config.json'))))
HR, LR = h.hr_sampling_rate, h.lr_sampling_rate
torch.manual_seed(h.seed)
torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

model = APNet_BWE_Model(h)
state = load_file(a.weights)
if all(k.startswith('generator.') for k in state):
    state = {k[len('generator.'):]: v for k, v in state.items()}
model.load_state_dict(state)
model.eval().to(a.device)

x, sr = sf.read(a.src, dtype='float32', always_2d=True)
x = torch.from_numpy(x.mean(axis=1))[None, :]
if sr != HR:
    x = aF.resample(x, sr, HR)
n = x.shape[1]
lr = aF.resample(aF.resample(x, HR, LR), LR, HR)[:, :n]       # what the model was trained to take: nothing above LR/2
if lr.shape[1] < n:
    lr = torch.nn.functional.pad(lr, (0, n - lr.shape[1]))

win = torch.hann_window(h.win_size, device=a.device)


def run(seg):
    seg = seg.to(a.device)
    spec = torch.stft(seg, h.n_fft, hop_length=h.hop_size, win_length=h.win_size, window=win, center=True,
                      pad_mode='reflect', normalized=False, return_complex=True)
    amp, pha = torch.log(torch.abs(spec) + 1e-4), torch.angle(spec)
    amp_g, pha_g, _ = model(amp, pha)
    g = torch.exp(amp_g)
    out = torch.istft(torch.complex(g * torch.cos(pha_g), g * torch.sin(pha_g)), h.n_fft, hop_length=h.hop_size,
                      win_length=h.win_size, window=win, center=True, length=seg.shape[1])
    return out[0].cpu().numpy()


C = int(a.chunk * HR) // h.hop_size * h.hop_size
OV = HR // 2 // h.hop_size * h.hop_size                         # half a second shared by neighbouring chunks
y = np.zeros(n, dtype=np.float32)
t0 = time.time()
with torch.inference_mode():
    pos = 0
    while pos < n:
        end = min(n, pos + C + OV)
        seg = run(lr[:, pos:end])
        if pos == 0:
            y[pos:end] = seg
        else:
            k = min(OV, end - pos)
            fade = np.linspace(0.0, 1.0, k, dtype=np.float32)
            y[pos:pos + k] = y[pos:pos + k] * (1 - fade) + seg[:k] * fade
            y[pos + k:end] = seg[k:]
        pos += C
        print(f'\r{min(end, n) / HR:7.1f} s of {n / HR:.1f} s', end='', file=sys.stderr)
dt = time.time() - t0
where = torch.cuda.get_device_name(a.device) if a.device.startswith('cuda') else f'{torch.get_num_threads()} threads'
print(f'\nmodel: {n / HR / dt:.1f} times real time on {where}', file=sys.stderr)

if a.model_out:
    sf.write(a.model_out, y, HR, subtype='FLOAT')

# crossover: a linear-phase high-pass for the generated top and its exact complement for the input
taps = 2047
hp = firwin(taps, a.cross, fs=HR, pass_zero=False, window=('kaiser', 9.0))
xn = x[0].numpy().astype(np.float64)
top = fftconvolve(y.astype(np.float64), hp, mode='same')
low = xn - fftconvolve(xn, hp, mode='same')
sf.write(a.dst, (low + a.amount * top).astype(np.float32), HR, subtype='FLOAT')
