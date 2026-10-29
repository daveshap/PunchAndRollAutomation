"""Stills from a walk for David to make a thumbnail from (first done for walk 0040, 22 Oct 2026; this tool from walk 0044).

  thumbnail_stills.py scan   <video> <work dir> [--every 5]
      Decode only the keyframes (one a second on the HERO11's HEVC) at 384 x 216 and make labelled contact sheets of
      every 5th second (sheet_NN.jpg). Look at them and list the moments worth a closer look.
  thumbnail_stills.py pick   <video> <work dir> <candidates.json>
      candidates.json: [["m:ss", "why"], ...]. For each, decode 1.2 s of frames around it and keep the sharpest
      (walking blurs most frames; a frame a few hundredths of a second away is often much crisper). Sharpness is the
      variance of the Laplacian, centre-weighted when he is in the frame (his face sits in the upper middle); a "why"
      that says "dog" or "no person" uses the whole frame. Writes picks.json, cand/*.png and review sheets (#n, m:ss).
  thumbnail_stills.py export <video> <work dir> <final.json> <out folder>
      final.json: [[frame number or "m:ss" of a pick, "description"], ...], in the order to show them (eye contact
      first, then gestures, then places and the dog). Writes 4K PNGs named "NN - MmSSs - description.png", JPEGs
      (quality 95, 4:4:4) in "jpg for uploading", and "00 - contact sheet.jpg"; checks each PNG is the frame that was
      measured. Look at the faces and hands at 960 px before exporting: a label like "hand out" can be a few frames
      early. The camera's full-range BT.709 converts right with zscale or ffmpeg's default scaler (identical RGB)."""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FN, FD = 60000, 1001
mode, SRC, WORK = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(WORK, exist_ok=True)


def secs(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + float(s)


def frames_at(k0, n, w=960, h=540, cuda=True):
    ts = max(0.0, (k0 * FD - FD / 4) / FN)            # a quarter frame early, so the seek lands on frame k0
    cmd = ['ffmpeg', '-v', 'error'] + (['-hwaccel', 'cuda'] if cuda else []) + ['-ss', f'{ts:.6f}', '-i', SRC,
           '-frames:v', str(n), '-vf', f'scale={w}:{h}:in_range=full:out_range=full,format=rgb24', '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def sharpness(rgb, person):
    g = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    H, W = g.shape
    if person:
        g = g[0:int(H * 0.62), int(W * 0.22):int(W * 0.78)]
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


font = lambda n: ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', n)

if mode == 'scan':
    every = int(sys.argv[sys.argv.index('--every') + 1]) if '--every' in sys.argv else 5
    W, H = 384, 216
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-skip_frame', 'nokey', '-i', SRC, '-vf', f'scale={W}:{H},format=rgb24',
                          '-fps_mode', 'passthrough', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    pts = subprocess.run(['ffprobe', '-v', 'error', '-skip_frame', 'nokey', '-select_streams', 'v:0', '-show_entries',
                          'frame=pts_time', '-of', 'csv=p=0', SRC], capture_output=True, text=True, check=True).stdout.split()
    times = [float(t) for t in pts][:len(fr)]
    sel = [i for i, t in enumerate(times) if round(t) % every == 0]
    for s in range(0, len(sel), 48):
        sheet = Image.new('RGB', (8 * W, 6 * (H + 24)), 'white')
        d = ImageDraw.Draw(sheet)
        for k, i in enumerate(sel[s:s + 48]):
            x, y = (k % 8) * W, (k // 8) * (H + 24)
            sheet.paste(Image.fromarray(fr[i]), (x, y + 24))
            d.text((x + 4, y + 2), f'{int(times[i] // 60)}:{int(times[i] % 60):02d}', fill='black', font=font(18))
        sheet.save(os.path.join(WORK, f'sheet_{s // 48 + 1:02d}.jpg'), quality=88)
    print(f'{len(fr)} keyframes, {len(sel)} on {(len(sel) + 47) // 48} sheets in {WORK}')

elif mode == 'pick':
    cands = json.load(open(sys.argv[4], encoding='utf-8'))
    os.makedirs(os.path.join(WORK, 'cand'), exist_ok=True)
    picks, SPAN = [], 72                                # 1.2 s at 59.94 fps
    for mmss, why in cands:
        k0 = max(0, round(secs(mmss) * FN / FD) - SPAN // 2)
        fr = frames_at(k0, SPAN).astype(np.float32) / 255
        person = 'no person' not in why and 'dog' not in why
        sc = [sharpness(f, person) for f in fr]
        i = int(np.argmax(sc))
        k = k0 + i
        Image.fromarray((fr[i] * 255).astype(np.uint8)).save(os.path.join(WORK, 'cand', f'f{k:06d}.png'))
        picks.append(dict(mmss=mmss, why=why, frame=k, time=round(k * FD / FN, 4), sharp=round(sc[i] * 1e4, 1),
                          median=round(float(np.median(sc)) * 1e4, 1)))
        print(f"{mmss:>6}  frame {k}  t {k * FD / FN:8.3f}  sharp {sc[i] * 1e4:6.1f} (median {np.median(sc) * 1e4:6.1f})  {why}", flush=True)
    json.dump(picks, open(os.path.join(WORK, 'picks.json'), 'w', encoding='utf-8'), indent=1)
    TW, TH, C = 480, 270, 5
    for s in range(0, len(picks), 25):
        grp = picks[s:s + 25]
        sheet = Image.new('RGB', (TW * C, (TH + 4) * ((len(grp) + C - 1) // C)), 'black')
        d = ImageDraw.Draw(sheet)
        for j, p in enumerate(grp):
            im = Image.open(os.path.join(WORK, 'cand', f"f{p['frame']:06d}.png")).resize((TW, TH), Image.LANCZOS)
            x, y = (j % C) * TW, (j // C) * (TH + 4)
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + 118, y + 26], fill=(0, 0, 0))
            d.text((x + 5, y + 2), f"#{s + j + 1}  {p['mmss']}", fill=(255, 255, 0), font=font(20))
        sheet.save(os.path.join(WORK, f'review{s // 25}.png'))

elif mode == 'export':
    picks = {p['mmss']: p['frame'] for p in json.load(open(os.path.join(WORK, 'picks.json'), encoding='utf-8'))}
    final = [(picks[k] if isinstance(k, str) else int(k), d) for k, d in json.load(open(sys.argv[4], encoding='utf-8'))]
    OUT = sys.argv[5]
    os.makedirs(os.path.join(OUT, 'jpg for uploading'), exist_ok=True)
    rows = []
    for n, (k, desc) in enumerate(final, 1):
        t = k * FD / FN
        name = f'{n:02d} - {int(t // 60)}m{int(t % 60):02d}s - {desc}'
        png = os.path.join(OUT, name + '.png')
        if os.path.exists(png):
            sys.exit(f'{png} exists already; this never writes over a file')
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{(k * FD - FD / 4) / FN:.6f}', '-i', SRC, '-frames:v', '1',
                        '-vf', 'zscale=min=709:rin=full:pin=709:tin=709,format=rgb24', png], check=True)
        im = Image.open(png)
        im.save(os.path.join(OUT, 'jpg for uploading', name + '.jpg'), quality=95, subsampling=0)
        a = frames_at(k, 1)[0].astype(np.float32)
        b = np.asarray(im.resize((960, 540), Image.BILINEAR), np.float32)
        corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        rows.append(dict(n=n, name=name, frame=k, t=round(t, 3), size=im.size, match=round(corr, 4)))
        print(f'{n:2d} frame {k} ({t:.3f} s) {im.size} match {corr:.4f}  {desc}', flush=True)
    TW, TH, C = 640, 360, 4
    sheet = Image.new('RGB', (TW * C, (TH + 34) * ((len(rows) + C - 1) // C)), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        im = Image.open(os.path.join(OUT, 'jpg for uploading', r['name'] + '.jpg')).resize((TW, TH), Image.LANCZOS)
        x, y = (i % C) * TW, (i // C) * (TH + 34)
        sheet.paste(im, (x, y))
        d.text((x + 8, y + TH + 5), r['name'].replace(' - ', '  ', 2), fill=(235, 235, 235), font=font(22))
    sheet.save(os.path.join(OUT, '00 - contact sheet.jpg'), quality=92)
    json.dump(rows, open(os.path.join(WORK, 'final_out.json'), 'w', encoding='utf-8'), indent=1)
    print(f'{len(rows)} stills in {OUT}')
