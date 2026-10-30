"""Track a passer-by for blurring (walk 0044, 30 Oct 2026).
Boxes marked by eye at keyframes (absolute 4K pixels) are moved into the camera-stabilised frame given by
motion.py (box - C[f]), interpolated there, and moved back (+ C[f]); between marks the box rides the camera.
  track.py sheet <video> <motion.npy> <keys.json> <first> <last> <step> <half w> <half h> <scale> <cols> <out.jpg>
      crops centred on the tracked box, grid every 80 px (labelled in 4K pixels), tracked box drawn in red,
      marked frames starred
  track.py nudge <motion.npy> <keys.json> <frame>:<dx0>,<dy0>,<dx1>,<dy1> ...
      move each edge of the tracked box at that frame (4K px) and keep it as a mark: read the sheet, say how far
      each edge is off, nudge
keys.json: [[frame, x0, y0, x1, y1], ...]. Keep marks only where you've looked: one rough leftover mark pulled the
box 100 px off him on walk 0044."""
import json, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
FN, FD = 60000, 1001


def load(motion, keys):
    """box(f) for every frame motion.npy covers, and the marked frames. (Tried on walk 0044: a local similarity
    transform fitted to patch shifts across the frame, to follow the camera's roll. Leaving each mark out in turn,
    it predicted the mark no better than this single shift: 90 % within 24 px either way.)"""
    K = sorted(json.load(open(keys)))
    kf = np.array([k[0] for k in K])
    M = np.load(motion)
    frames = M[:, 0].astype(int)
    C = {f: M[i, 1:3] for i, f in enumerate(frames)}
    st = np.array([[k[1] - C[k[0]][0], k[2] - C[k[0]][1], k[3] - C[k[0]][0], k[4] - C[k[0]][1]] for k in K])

    def box(f):
        s = [np.interp(f, kf, st[:, j]) for j in range(4)]
        c = C[f]
        return np.array([s[0] + c[0], s[1] + c[1], s[2] + c[0], s[3] + c[1]])
    return box, kf


if __name__ == '__main__' and sys.argv[1] == 'sheet':
    src, motion, keys = sys.argv[2:5]
    f0, f1, step, hw, hh = map(int, sys.argv[5:10])
    sc, cols, out = float(sys.argv[10]), int(sys.argv[11]), sys.argv[12]
    box, kf = load(motion, keys)
    want = list(range(f0, f1 + 1, step))
    w, h = round(2 * hw * sc), round(2 * hh * sc)
    font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 16)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 11)
    tiles = []
    for f in want:   # one decode per crop: seek, 1 frame
        b = box(f)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        x0 = int(np.clip(cx - hw, 0, 3840 - 2 * hw)); y0 = int(np.clip(cy - hh, 0, 2160 - 2 * hh))
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{(f * FD - FD / 4) / FN:.6f}', '-i', src, '-frames:v', '1',
                              '-vf', f'crop={2 * hw}:{2 * hh}:{x0}:{y0},scale={w}:{h},format=rgb24', '-f', 'rawvideo', '-'],
                             capture_output=True, check=True).stdout
        im = Image.fromarray(np.frombuffer(raw, np.uint8).reshape(h, w, 3)).copy()
        d = ImageDraw.Draw(im)
        for gx in range((x0 // 80 + 1) * 80, x0 + 2 * hw, 80):
            X = round((gx - x0) * sc); d.line([(X, 0), (X, h)], fill=(0, 200, 255) if gx % 160 else (0, 255, 255), width=1)
            if gx % 160 == 0: d.text((X + 2, h - 13), str(gx), fill=(0, 255, 255), font=small)
        for gy in range((y0 // 80 + 1) * 80, y0 + 2 * hh, 80):
            Y = round((gy - y0) * sc); d.line([(0, Y), (w, Y)], fill=(0, 200, 255) if gy % 160 else (0, 255, 255), width=1)
            if gy % 160 == 0: d.text((2, Y + 1), str(gy), fill=(0, 255, 255), font=small)
        d.rectangle([(b[0] - x0) * sc, (b[1] - y0) * sc, (b[2] - x0) * sc, (b[3] - y0) * sc], outline=(255, 0, 0), width=2)
        t = f * FD / FN
        d.rectangle([0, 0, 125, 19], fill='black')
        d.text((3, 1), f'{f} {int(t // 60)}:{t % 60:05.2f}{"*" if f in kf else ""}', fill='yellow', font=font)
        tiles.append(im)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (w + 4), rows * (h + 4)), 'black')
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % cols) * (w + 4), (k // cols) * (h + 4)))
    sheet.save(out, quality=90)
    print(len(tiles), 'crops', sheet.size)

if __name__ == '__main__' and sys.argv[1] == 'nudge':
    motion, keys = sys.argv[2:4]
    box, _ = load(motion, keys)
    K = {k[0]: k[1:] for k in json.load(open(keys))}
    new = {}
    for a in sys.argv[4:]:
        f, v = a.split(':')
        v = [float(x) for x in v.split(',')]
        b = box(int(f))
        new[int(f)] = [round(b[j] + v[j]) for j in range(4)]
    K.update(new)
    json.dump([[f] + K[f] for f in sorted(K)], open(keys, 'w'))
    for f in sorted(new): print(f, new[f])
