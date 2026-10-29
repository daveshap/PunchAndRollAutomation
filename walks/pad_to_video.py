"""Put a voice that is on the joined-WAV timeline onto the joined-video timeline.

usage: pad_to_video.py <walk folder> in.wav out.wav <chapter> [<chapter> ...]    (chapter names without extension, in order)
   e.g. pad_to_video.py "C:/Users/daves/Videos/2026-10-29 hike" voice.wav voice_sync.wav GX010044 GX020044 GX030044 GX010045

The concat of the MP4 chapters starts each chapter at the sum of the earlier chapters' video lengths. Each raw WAV is
usually exactly as long as its chapter's video, but not always: on the hike of 29 Oct 2026 GX030044's WAV was 8.5 ms
short and GX010045's 13.5 ms short. For each chapter this writes the WAV's samples and then silence up to the video's
length (or cuts the excess, if the WAV is longer), so every chapter starts on its frame. Prints what it did."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

D, IN, OUT, CH = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]


def vdur(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


x, sr = sf.read(IN, dtype="float32")
out, pos, vt = [], 0, 0.0
for c in CH:
    n = sf.info(D / f"{c}.WAV").frames
    seg = x[pos:pos + n]
    pos += n
    vt += vdur(D / f"{c}.MP4")
    want = round(vt * sr) - sum(len(s) for s in out)
    fix = want - len(seg)
    seg = np.concatenate([seg, np.zeros(fix, np.float32)]) if fix >= 0 else seg[:want]
    out.append(seg)
    print(f"{c}: WAV {n} samples, video to {vt:.6f} s, {'+' if fix >= 0 else ''}{fix} samples")
assert pos == len(x), f"the input has {len(x)} samples, the WAVs {pos}"
y = np.concatenate(out)
sf.write(OUT, y, sr, subtype="FLOAT")
print(f"{len(x)} -> {len(y)} samples ({len(y) / sr:.6f} s)")
