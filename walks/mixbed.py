"""Put some of the background back under a cleaned and mastered voice.

usage: mixbed.py mastered_voice.wav original.wav cleaned_voice.wav out.wav [background level in dB, default -17]

The background is what the cleaning took out (original minus cleaned voice). All three inputs must be mono, at the
same sample rate and in step with each other. The output is 32-bit float.
"""
import sys

import numpy as np
import soundfile as sf

v, sr = sf.read(sys.argv[1], dtype='float64', always_2d=True)
x, sr_x = sf.read(sys.argv[2], dtype='float64', always_2d=True)
e, sr_e = sf.read(sys.argv[3], dtype='float64', always_2d=True)
assert sr == sr_x == sr_e, (sr, sr_x, sr_e)
k = 10 ** (float(sys.argv[5]) / 20) if len(sys.argv) > 5 else 10 ** (-17 / 20)
n = min(len(v), len(x), len(e))
out = v[:n, 0] + k * (x[:n, 0] - e[:n, 0])
sf.write(sys.argv[4], out.astype(np.float32), sr, subtype='FLOAT')
