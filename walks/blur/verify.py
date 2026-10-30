"""Check sheets of a blurred clip: crops around the tracked box, no drawing on them, so nothing hides what's there.
verify.py <clip> <clip's first frame> <motion.npy> <keys.json> <first> <last> <step> <half w> <half h> <scale> <cols> <out prefix> [per sheet]
Crops are centred on the tracked box (whole frame when half w is 0). Writes <out prefix>_NN.jpg."""
import subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from track import load
FN, FD = 60000, 1001
clip, base = sys.argv[1], int(sys.argv[2])
box, _ = load(sys.argv[3], sys.argv[4])
f0, f1, step, hw, hh = map(int, sys.argv[5:10])
sc, cols, out = float(sys.argv[10]), int(sys.argv[11]), sys.argv[12]
per = int(sys.argv[13]) if len(sys.argv) > 13 else 10 ** 6
whole = hw == 0
if whole:
    hw, hh = 1920, 1080
W, H = 3840, 2160
w, h = round(2 * hw * sc), round(2 * hh * sc)
dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-hwaccel', 'cuda', '-ss', f'{((f0 - base) * FD - FD / 4) / FN:.6f}', '-i', clip,
                        '-frames:v', str(f1 - f0 + 1), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 16)
tiles = []
for f in range(f0, f1 + 1):
    raw = dec.stdout.read(W * H * 3)
    if len(raw) < W * H * 3:
        break
    if (f - f0) % step:
        continue
    b = [0, 0, W, H] if whole else box(f)
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    x0 = int(np.clip(cx - hw, 0, W - 2 * hw)); y0 = int(np.clip(cy - hh, 0, H - 2 * hh))
    im = Image.fromarray(np.frombuffer(raw, np.uint8).reshape(H, W, 3)[y0:y0 + 2 * hh, x0:x0 + 2 * hw]).resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    t = f * FD / FN
    d.text((3, 1), f'{f} {int(t // 60)}:{t % 60:05.2f}', fill='yellow', font=font, stroke_width=2, stroke_fill='black')
    tiles.append(im)
dec.kill()
for s0 in range(0, len(tiles), per):
    grp = tiles[s0:s0 + per]
    rows = (len(grp) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (w + 4), rows * (h + 4)), 'black')
    for k, im in enumerate(grp):
        sheet.paste(im, ((k % cols) * (w + 4), (k // cols) * (h + 4)))
    sheet.save(f'{out}_{s0 // per:02d}.jpg', quality=90)
print(len(tiles), 'crops on', (len(tiles) + per - 1) // per, 'sheets', out)
