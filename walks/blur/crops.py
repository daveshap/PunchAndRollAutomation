"""Grid-labelled crop sheets for marking a passer-by (walk 0044 blur).
crops.py <video> <first frame> <last frame> <step> <x0> <y0> <x1> <y1> <scale> <cols> <grid> <out.jpg>
Coordinates are 4K pixels; grid lines every <grid> 4K px, labelled, so positions can be read off the sheet."""
import subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
FN, FD = 60000, 1001
src = sys.argv[1]
f0, f1, step = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
x0, y0, x1, y1 = map(int, sys.argv[5:9])
sc, cols, grid, out = float(sys.argv[9]), int(sys.argv[10]), int(sys.argv[11]), sys.argv[12]
w, h = round((x1 - x0) * sc), round((y1 - y0) * sc)
ts = (f0 * FD - FD / 4) / FN
n = f1 - f0 + 1
raw = subprocess.run(['ffmpeg', '-v', 'error', '-hwaccel', 'cuda', '-ss', f'{ts:.6f}', '-i', src, '-frames:v', str(n),
                      '-vf', f"crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale={w}:{h}:in_range=full:out_range=full,format=rgb24",
                      '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
idx = list(range(0, len(fr), step))
font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 18)
small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 12)
rows = (len(idx) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (w + 4), rows * (h + 4)), 'black')
for k, i in enumerate(idx):
    im = Image.fromarray(fr[i]).copy()
    d = ImageDraw.Draw(im)
    for gx in range((x0 // grid + 1) * grid, x1, grid):
        X = round((gx - x0) * sc); d.line([(X, 0), (X, h)], fill=(0, 255, 255), width=1); d.text((X + 2, h - 14), str(gx), fill=(0, 255, 255), font=small)
    for gy in range((y0 // grid + 1) * grid, y1, grid):
        Y = round((gy - y0) * sc); d.line([(0, Y), (w, Y)], fill=(0, 255, 255), width=1); d.text((2, Y + 1), str(gy), fill=(0, 255, 255), font=small)
    f = f0 + i
    t = f * FD / FN
    d.rectangle([0, 0, 150, 22], fill='black')
    d.text((3, 1), f'{f} {int(t // 60)}:{t % 60:05.2f}', fill='yellow', font=font)
    sheet.paste(im, ((k % cols) * (w + 4), (k // cols) * (h + 4)))
sheet.save(out, quality=90)
print(len(idx), 'crops', sheet.size)
