"""Labelled contact sheets of a stretch of the walk: sheet.py <video> <start s> <end s> <fps> <out prefix> [w]"""
import subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
src, t0, t1, fps, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
W = int(sys.argv[6]) if len(sys.argv) > 6 else 480
H = W * 9 // 16
raw = subprocess.run(['ffmpeg', '-v', 'error', '-hwaccel', 'cuda', '-ss', f'{t0}', '-t', f'{t1 - t0}', '-i', src,
                      '-vf', f'fps={fps},scale={W}:{H},format=rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', max(14, W // 24))
C, R = 6, 5
for s in range(0, len(fr), C * R):
    grp = fr[s:s + C * R]
    sheet = Image.new('RGB', (C * W, ((len(grp) + C - 1) // C) * (H + 4)), 'black')
    d = ImageDraw.Draw(sheet)
    for k, f in enumerate(grp):
        x, y = (k % C) * W, (k // C) * (H + 4)
        sheet.paste(Image.fromarray(f), (x, y))
        t = t0 + (s + k) / fps
        d.rectangle([x, y, x + W // 5, y + W // 20], fill='black')
        d.text((x + 3, y + 1), f'{int(t // 60)}:{t % 60:05.2f}', fill='yellow', font=font)
    sheet.save(f'{out}_{s // (C * R):02d}.jpg', quality=85)
print(len(fr), 'frames')
