"""Blur a passer-by along a tracked box (walk 0044, 30 Oct 2026; boxes from track.py).
  blur.py segment <video> <motion.npy> <keys.json> <first> <last> <out.nut>
      frames first..last, each blurred along the track, kept lossless (FFV1 in NUT, exact timestamps); through
      Python, about 6 frames a second
  blur.py final <video> <segment.nut> <its first frame> <out.mp4> [frames]
      one encode of the whole walk: the segment laid over its own frames (overlay, frame-exact), every other
      frame as decoded, the audio copied; NVENC at about the source's 240 Mbps (ENC)
Why one encode: NVENC's parameter sets depend on where its input comes from (frames piped in raw got a 5-frame
DPB, frames decoded from the camera's HEVC a 6-frame one), so parts encoded separately can't be joined by
stream copy.
The blur works on the decoded 10-bit planes (p010, full range) on the GPU, so nothing outside the box changes
colour. The box gets a margin (30 % of its width a side, 12 % of its height, at least 40 px), a superellipse
mask with a soft edge, and a Gaussian blur of sigma max(24, 15 % of the box's smaller side)."""
import subprocess, sys
import numpy as np
import torch
import torch.nn.functional as F
from track import load

FN, FD = 60000, 1001
W, H = 3840, 2160
FRAME = W * H * 3  # p010: Y (W*H*2 bytes) + interleaved UV (W*H/2*2 bytes)
dev = 'cuda'


def gauss1d(sigma):
    r = int(3 * sigma) + 1
    x = torch.arange(-r, r + 1, device=dev, dtype=torch.float32)
    k = torch.exp(-x * x / (2 * sigma * sigma))
    return k / k.sum()


def blur_plane(p, sigma):
    """p: (C, h, w) float. Gaussian blur via 4x downsample, separable conv, upsample."""
    C, h, w = p.shape
    q = 4 if sigma >= 12 else 1
    x = p[None]
    if q > 1:
        x = F.avg_pool2d(F.pad(x, (0, (-w) % q, 0, (-h) % q), mode='replicate'), q)
    k = gauss1d(sigma / q)
    r = (len(k) - 1) // 2
    x = F.pad(x, (r, r, 0, 0), mode='replicate')
    x = F.conv2d(x, k.view(1, 1, 1, -1).repeat(C, 1, 1, 1), groups=C)
    x = F.pad(x, (0, 0, r, r), mode='replicate')
    x = F.conv2d(x, k.view(1, 1, -1, 1).repeat(C, 1, 1, 1), groups=C)
    if q > 1:
        x = F.interpolate(x, scale_factor=q, mode='bilinear', align_corners=False)[..., :h, :w]
    return x[0]


def region(b):
    """Margin, minimum size, blur sigma and the padded work region for box b (4K px)."""
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    mx, my = max(40, 0.3 * w), max(40, 0.12 * h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a, bb = max(w / 2 + mx, 80), max(h / 2 + my, 150)      # half sizes of the blurred shape
    sigma = max(24.0, 0.15 * min(w, h))
    pad = 3 * sigma + 8
    return cx, cy, a, bb, sigma, pad


def apply(buf, b):
    """Blur box b into one p010 frame held in buf (numpy uint8, FRAME bytes), in place."""
    cx, cy, a, bb, sigma, pad = region(b)
    X0, X1 = int(max(0, cx - a - pad)) & ~1, min(W, int(cx + a + pad + 2)) & ~1
    Y0, Y1 = int(max(0, cy - bb - pad)) & ~1, min(H, int(cy + bb + pad + 2)) & ~1
    if X1 - X0 < 4 or Y1 - Y0 < 4:
        return False
    Yp = np.frombuffer(buf, np.uint16, W * H).reshape(H, W)
    UV = np.frombuffer(buf, np.uint16, W * H // 2, W * H * 2).reshape(H // 2, W // 2, 2)
    feather = max(12.0, 0.25 * min(a, bb))
    for plane, s in ((Yp, 1), (UV, 2)):
        ys, xs = slice(Y0 // s, Y1 // s), slice(X0 // s, X1 // s)
        sub = plane[ys, xs]
        t = torch.from_numpy(sub.astype(np.float32)).to(dev)
        t = t[None] if t.ndim == 2 else t.permute(2, 0, 1)
        bl = blur_plane(t, sigma / s)
        yy = (torch.arange(Y0 // s, Y1 // s, device=dev, dtype=torch.float32) * s + (s - 1) / 2 - cy)[:, None]
        xx = (torch.arange(X0 // s, X1 // s, device=dev, dtype=torch.float32) * s + (s - 1) / 2 - cx)[None, :]
        d = ((xx.abs() / a) ** 4 + (yy.abs() / bb) ** 4) ** 0.25          # 1 on the shape's edge
        m = ((1 - d) * min(a, bb) / feather + 1).clamp(0, 1)            # soft edge reaching outside by feather px
        m = m * m * (3 - 2 * m)
        out = t + (bl - t) * m
        out = out.round().clamp(0, 65535).to(torch.int32)
        out = out[0] if sub.ndim == 2 else out.permute(1, 2, 0)
        plane[ys, xs] = out.cpu().numpy().astype(np.uint16) & 0xFFC0   # p010 keeps 10 bits in the top of 16
    return True


def decoder(src, first=0, count=None):
    cmd = ['ffmpeg', '-v', 'error', '-hwaccel', 'cuda']
    if first:
        cmd += ['-ss', f'{(first * FD - FD / 4) / FN:.6f}']
    cmd += ['-i', src, '-map', '0:v:0']
    if count:
        cmd += ['-frames:v', str(count)]
    cmd += ['-f', 'rawvideo', '-pix_fmt', 'p010le', '-']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=FRAME * 2)


ENC = ['-c:v', 'hevc_nvenc', '-preset', 'p6', '-tune', 'hq', '-profile:v', 'main10', '-rc', 'vbr', '-cq', '16', '-b:v', '0',
       '-maxrate', '300M', '-bufsize', '600M', '-spatial-aq', '1', '-bf', '3', '-g', '60',
       '-color_range', 'pc', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-tag:v', 'hvc1']


def encoder(out):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'p010le', '-s', f'{W}x{H}', '-framerate', f'{FN}/{FD}',
           '-color_range', 'pc', '-i', '-', '-c:v', 'ffv1', '-level', '3', '-slices', '16', '-pix_fmt', 'yuv420p10le',
           '-color_range', 'pc', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', out]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, bufsize=FRAME * 2)


def final(src, seg, first, out, frames=None):
    off = f'{first * FD}/{FN}/TB'                       # the segment's first frame lands on frame `first`
    graph = (f'[1:v]setpts=PTS-STARTPTS+{off}[b];[0:v]format=yuv420p10le[m];'
             '[m][b]overlay=eof_action=pass:format=yuv420p10,format=p010le[v]')
    cmd = ['ffmpeg', '-v', 'error', '-stats', '-y', '-hwaccel', 'cuda', '-i', src, '-i', seg, '-filter_complex', graph,
           '-map', '[v]', '-map', '0:a', '-c:a', 'copy', '-fps_mode', 'passthrough']
    if frames:
        cmd += ['-frames:v', str(frames)]
    subprocess.run(cmd + ENC + [out], check=True)


def run(src, motion, keys, first, count, on, off, out):
    box, _ = load(motion, keys)
    dec = decoder(src, first, count)
    enc = encoder(out)
    buf = bytearray(FRAME)
    mv = memoryview(buf)
    f, done = first, 0
    while True:
        n = 0
        while n < FRAME:
            r = dec.stdout.readinto(mv[n:])
            if not r:
                break
            n += r
        if n < FRAME:
            break
        if on <= f <= off:
            apply(buf, box(f))
            done += 1
        enc.stdin.write(buf)
        f += 1
        if (f - first) % 3000 == 0:
            print(f'frame {f}', flush=True)
    enc.stdin.close()
    enc.wait(); dec.wait()
    print(f'{f - first} frames written, {done} blurred ({on}..{off}) -> {out}')
    return f - first


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'segment':
        src, motion, keys = sys.argv[2:5]
        first, last = map(int, sys.argv[5:7])
        run(src, motion, keys, first, last - first + 1, first, last, sys.argv[7])
    elif mode == 'final':
        final(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], int(sys.argv[6]) if len(sys.argv) > 6 else None)
