"""Make a 3D LUT (.cube) that gives a flat GoPro "Natural" picture richer, warmer colour.

usage: grade.py out.cube [--contrast 1.12] [--pivot 0.5] [--vibrance 0.32] [--warm 0.012] [--skin 0.4] [--size 33]

It works on the gamma-encoded BT.709 RGB of the picture (what ffmpeg's lut3d sees), in OKLab, which is close to
how we see:
- contrast: a gentle S-curve on lightness around L = 0.5, with the same slope (--contrast) on both sides, so
  shadows deepen a little and highlights lift a little, and black and white stay where they are;
- vibrance: chroma rises by up to --vibrance (32 %) for dull colours and by less as a colour gets richer, so the
  muted greens and browns come up more than colours that were already strong;
- skin: within the hue band of skin the boost is cut by --skin (40 %), so a face doesn't go orange;
- warmth: the highlights lean slightly gold (up to --warm on OKLab b, half that on a), like late sun.
Colours pushed out of gamut are pulled back towards grey at the same lightness and hue, not clipped.
"""
import sys

import numpy as np


def opt(name, default):
    a = sys.argv
    return float(a[a.index(name) + 1]) if name in a else default


def srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
               [0.2119034982, 0.6806995451, 0.1073969566],
               [0.0883024619, 0.2817188376, 0.6299787005]])
M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
               [1.9779984951, -2.4285922050, 0.4505937099],
               [0.0259040371, 0.7827717662, -0.8086757660]])
M1i, M2i = np.linalg.inv(M1), np.linalg.inv(M2)


def to_oklab(rgb_lin):
    return np.cbrt(rgb_lin @ M1.T) @ M2.T


def from_oklab(lab):
    return (lab @ M2i.T) ** 3 @ M1i.T


def grade(rgb, k=1.12, vib=0.32, warm=0.012, skin=0.4, p=0.5):
    lab = to_oklab(srgb_to_lin(rgb))
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    L2 = np.where(L < p, p * (np.clip(L, 0, None) / p) ** k, 1 - (1 - p) * (np.clip(1 - L, 0, None) / (1 - p)) ** k)
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360
    boost = vib * np.clip(1 - C / 0.22, 0, 1) ** 1.5
    skin_w = np.clip(1 - np.abs(((h - 60 + 180) % 360) - 180) / 30, 0, 1)   # 1 at 60 deg, 0 beyond +-30 deg
    boost *= 1 - skin * skin_w
    scale = np.where(C > 1e-6, 1 + boost, 1.0)
    a2, b2 = a * scale, b * scale
    w = np.clip((L2 - p) / (1 - p), 0, 1)
    w = w * w * (3 - 2 * w)
    b2 = b2 + warm * w
    a2 = a2 + 0.5 * warm * w
    out = np.stack([L2, a2, b2], axis=-1)
    lo, hi = np.zeros(L2.shape), np.ones(L2.shape)        # pull out-of-gamut colours towards grey
    for _ in range(12):
        lin = from_oklab(np.stack([L2, a2 * hi, b2 * hi], axis=-1))
        ok = np.all((lin >= -1e-4) & (lin <= 1 + 1e-4), axis=-1)
        if ok.all():
            break
        mid = (lo + hi) / 2
        lin_mid = from_oklab(np.stack([L2, a2 * mid, b2 * mid], axis=-1))
        okm = np.all((lin_mid >= -1e-4) & (lin_mid <= 1 + 1e-4), axis=-1)
        lo = np.where(~ok & okm, mid, lo)
        hi = np.where(ok, hi, np.where(okm, hi * 0 + mid, mid))
        hi = np.where(ok, 1.0, hi)
    f = np.where(np.all((from_oklab(out) >= -1e-4) & (from_oklab(out) <= 1 + 1e-4), axis=-1), 1.0, lo)
    out = np.stack([L2, a2 * f, b2 * f], axis=-1)
    return lin_to_srgb(from_oklab(out))


if __name__ == '__main__':
    n = int(opt('--size', 33))
    g = np.linspace(0, 1, n)
    B, G, R = np.meshgrid(g, g, g, indexing='ij')              # .cube order: red changes fastest
    rgb = np.stack([R, G, B], axis=-1).reshape(-1, 3)
    out = grade(rgb, opt('--contrast', 1.12), opt('--vibrance', 0.32), opt('--warm', 0.012), opt('--skin', 0.4), opt('--pivot', 0.5))
    with open(sys.argv[1], 'w') as fh:
        fh.write(f'TITLE "walk grade"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for r, gg, bb in np.clip(out, 0, 1):
            fh.write(f'{r:.6f} {gg:.6f} {bb:.6f}\n')
    d = np.abs(out - rgb).max(axis=1)
    print(f'wrote {sys.argv[1]}: {n}^3 entries, largest change {d.max():.3f}, black -> {out[0].round(4)}, white -> {out[-1].round(4)}')
