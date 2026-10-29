"""Join a walk's GoPro raw-audio WAVs for Adobe Podcast, and write the upload copy and a map note beside them.

usage: join_raw_audio.py <walk folder> <name> <WAV> [<WAV> ...]     (the WAVs in the order the chapters play)
   e.g. join_raw_audio.py "C:/Users/daves/Videos/2026-10-29 hike" GX0044-0045 GX010044.WAV GX020044.WAV GX030044.WAV GX010045.WAV

Writes, in the walk folder:
  <name>_raw_audio_joined.wav       the WAVs end to end, bit for bit (ffmpeg concat, -c copy; checked against the sources)
  <name>_for_Adobe_Podcast.wav      the file to upload: mono (0.5 L + 0.5 R), scaled in float so the loudest peak is
                                    -1.0 dBFS, then 24-bit PCM. The camera records 32-bit float hot (peaks of +10 to
                                    +13 dBFS), so any fixed-point step before scaling would clip the voice throughout.
  <name>_raw_audio_joined.map.txt   where each source starts, and how the upload copy was made.
Adobe's "-enhanced-v2.wav" comes back on the same timeline (0 to 2 samples off on the walks of Oct 2026)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

D, NAME, SRC = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
JOINED = D / f"{NAME}_raw_audio_joined.wav"
UP = D / f"{NAME}_for_Adobe_Podcast.wav"
for p in (JOINED, UP):
    if p.exists():
        sys.exit(f"{p} exists already; this never writes over a file")

with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
    for s in SRC:
        f.write(f"file '{(D / s).as_posix()}'\n")
subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", f.name, "-c", "copy", str(JOINED)], check=True)

starts, pos, parts = [], 0, []
for s in SRC:
    x, sr = sf.read(D / s, dtype="float32", always_2d=True)
    assert sr == 48000, f"{s}: {sr} Hz"
    starts.append((s, pos))
    parts.append(x)
    pos += len(x)
src = np.concatenate(parts)
j, sr = sf.read(JOINED, dtype="float32", always_2d=True)
assert j.shape == src.shape and np.array_equal(j, src), "the join is not bit-exact"
apart = 20 * np.log10(np.sqrt(np.mean((j[:, 0] - j[:, 1]) ** 2)) / np.sqrt(np.mean(j ** 2)) + 1e-12)
peak = float(np.abs(j).max())
mono = 0.5 * j[:, 0] + 0.5 * j[:, 1]
gain_db = -1.0 - 20 * np.log10(float(np.abs(mono).max()))
sf.write(UP, (mono * 10 ** (gain_db / 20)).astype(np.float32), sr, subtype="PCM_24")
sec = np.abs(j).max(axis=1)[: len(j) // sr * sr].reshape(-1, sr).max(axis=1)
lines = [f"{JOINED.name}: the GoPro raw-audio WAVs joined end to end, unchanged (48 kHz, stereo, 32-bit float).",
         "Made for Adobe Podcast by PunchAndRollAutomation/walks/join_raw_audio.py. Where each source starts (samples at 48 kHz, and seconds):"]
lines += [f"  {s:<14}{p:>10} samples  {p / sr:11.6f} s" for s, p in starts]
lines += [f"  {'(end)':<14}{len(j):>10} samples  {len(j) / sr:11.6f} s",
          "Check each WAV against its MP4 chapter's video length before muxing (pad_to_video.py does it).",
          "",
          f"{UP.name}: the file to upload. Mono (0.5 L + 0.5 R; the channels differ by about {apart:.0f} dB), turned down",
          f"{-gain_db:.3f} dB in floating point so its loudest peak is -1.0 dBFS, then 24-bit PCM. The raw audio peaks at",
          f"{20 * np.log10(peak):+.1f} dBFS and is over full scale in {int((sec > 1).sum()):,} of {len(sec):,} seconds.",
          f"Same length and timeline as the joined file ({len(j):,} samples)."]
(D / f"{NAME}_raw_audio_joined.map.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
