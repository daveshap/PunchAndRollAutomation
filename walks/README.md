# Forest walks: a GoPro walk joined and mastered for YouTube

David films walks on a GoPro HERO11 (firmware H26.01 from 19 Oct 2026: 4K 59.94 fps HEVC Main 10, full range, BT.709). The camera splits each recording into chapters of 6:24 (`GX01nnnn.MP4`, `GX02nnnn.MP4`, ...), and with its raw-audio setting it writes a `.WAV` beside each chapter. The finished walk is one MP4 with the picture as shot and his voice mastered.

This folder is the version-controlled copy of the tools. The working copy, with the downloads they need, is `C:\Users\daves\voice-isolation` on his PC (work files in its `work\GX00nn\`). After a change there, copy it here and commit.

## His asks, in his words

- 29 Oct 2026: "concat the audio, I will upload to Adobe Podcast, we will use that, then you just concat the video, and spruce up the audio (EQ, sparkle, presence). Adobe Podcast handles the voice isolation so you just have to do the final engineering. no editing or color correction on the video (Cinematic setting on GoPro is good enough)."
- 19 Oct 2026, after hearing Adobe Podcast's isolation: "okay the adobe version is way better ... It maybe needs just a little EQ or light sparkle but it's definitely clear. there's no artifacts from the voice isolation. so I think we just need to use this as a default. and don't worry about the tone evening as I'm moving the camera around." Of the four samples (as is, EQ, sparkle, both) he picked both: "I think I is fine. it has some good clean punch".
- 13 Oct 2026, on the older chain: "this doesn't sound quite as crisp but it sounds smoother so that's what we want."
- A short clip shot after the walk goes on the end (29 Oct 2026: "the final clip is a conclusion with Mandy (my dog)").

## The default, step by step

Never touch his source chapters. Outputs go in the walk's folder, named `<GX00nn-...>_youtube_mastered.mp4`.

1. **The audio for Adobe Podcast.** `py -3.13 join_raw_audio.py "<walk folder>" <name> <WAVs in chapter order>`. It joins the WAVs bit for bit, writes the upload copy (`<name>_for_Adobe_Podcast.wav`: mono, scaled in float to a -1 dBFS peak, 24-bit) and a map note. David uploads it and puts Adobe's `-enhanced-v2.wav` in the same folder.
2. **Check Adobe's file:** the same number of samples as the upload, and in step with it (cross-correlation at a few points: 0 to 2 samples off on every walk so far).
3. **EQ, presence and sparkle:** `py -3.13 matcheq.py apply curves/adobe_curve_both.json <Adobe>.wav both.wav`. The curve was fitted on Adobe's output of walk 0038 against his three best studio reads (`curves/studio_top3.json`), capped at plus or minus 4 dB: +4 below 160 Hz, -3 at 285 and 508 Hz, +2 to +3 at 0.7 to 1 kHz, -2.6 at 2 kHz, +3 to +4 at 3 to 5 kHz (Adobe keeps the camera's dip at 4 to 4.6 kHz), and +4 above 7 kHz (the sparkle). `curves/adobe_curve_eq.json` and `adobe_curve_sparkle.json` are the two halves alone.
4. `ffmpeg -i both.wav -af highpass=f=70 -c:a pcm_f32le hp.wav`.
5. **Onto the video's timeline:** `py -3.13 pad_to_video.py "<walk folder>" hp.wav sync.wav <chapters in order>`. A WAV is not always as long as its chapter's video (29 Oct 2026: two of four were 8.5 and 13.5 ms short), and the MP4 concat starts each chapter at the video's length.
6. **The light compressor, when he is animated:** `acompressor=threshold=-22dB:ratio=2:attack=10:release=150:knee=4:detection=rms:makeup=1`. Decide with step 7's gain: render the voice with the gain alone and with the gain and limiter, then `check_walk.py limiter dry.wav limited.wav`. Walk 0038, which he approved with the limiter alone: 0.2 % of speech at 6 dB or more, at most 6.3 dB. When it runs well over that, compress first. Walk 0040: 2.8 % without, 0.05 % with. Walk 0044: 4.2 % (up to 14 dB) without, 0.4 % (8.8 dB) with.
7. **Loudness:** `bash set-loudness.sh comp.wav test.m4a` finds the gain for -14 LUFS through the limiter and prints the filter chain as its last line (walk 0044: `volume=16.81dB` plus the limiter, -14.0 LUFS, -1.0 dBTP, no trim). Render the voice with that chain to a float WAV.
8. **Mux:** a concat list of the MP4 chapters with absolute paths (`file 'C:/.../GX010044.MP4'`, one per line) as input 0 and the mastered WAV as input 1: `ffmpeg -f concat -safe 0 -i list.txt -i master.wav -map 0:v:0 -map 1:a:0 -c:v copy -tag:v hvc1 -c:a aac -b:a 192k -aac_tns 0 -ar 48000 -movflags +faststart <name>_youtube_mastered.mp4`. About 2 minutes for 28 GB.
9. **Checks:**
   - the video packets' MD5 equals the chapters' (`-map 0:v:0 -c copy -f md5 -` on the output and on the concat list);
   - `ebur128=peak=true` on the output's audio: -14.0 LUFS, peak at or under -1.0;
   - `check_walk.py sync list.txt <output>`: one constant offset everywhere, joins included (+5.5 ms against the camera's AAC on walk 0044);
   - `matcheq.py show curves/studio_top3.json <output>`: about 3 dB RMS from his studio voice (0040: 3.1; 0044: 2.9).

No grade: since walk 0040 he shoots "Cinematic" and wants the picture as it is. (`grade.py` made a 3D LUT for walk 0038, shot in "Natural".)

## Gotchas

- **`-aac_tns 0`, always.** On walk 0035 ffmpeg's AAC encoder with temporal noise shaping put one frame of ordinary speech at +2.8 dBTP, 4.3 dB over the limiter, and the loudness step's safety trim then dropped the whole walk to -18 LUFS. With TNS off the worst peak was -1.09 dBTP. `set-loudness.sh` uses it for its trial encode, and the real encode must too.
- **The raw WAVs run hot:** 32-bit float with peaks of +10 to +13 dBFS, over full scale much of the time. Scale in float before any fixed-point step.
- **Checking sync against the camera's AAC:** decode it with `aresample=async=1:min_hard_comp=0.001:first_pts=0`. The default threshold (0.1 s) leaves the few-millisecond gaps at the joins unfilled and fakes a shift of that size after them.
- A bright voice overshoots about 0.9 dB when AAC encodes it. `set-loudness.sh` turns the output down after the limiter until the encoded peak is at or under -1.0 dBTP, rather than limiting harder.

## Without Adobe Podcast: the older chain

For a walk with no Adobe file (walks 0033 and 0035, Oct 2026): mono WAV of the joined audio (`pan=mono|c0=0.5*c0+0.5*c1`); DeepFilterNet for the voice alone (`deep-filter-0.5.6-x86_64-pc-windows-msvc.exe -D -o <dir> mono.wav`, CPU, about 100 s for 20 minutes; its output is 1,440 samples shorter, aligned at the start); AP-BWE to rebuild the top the camera doesn't record above 8 kHz (`venv\Scripts\python.exe apbwe_run.py --repo ap-bwe\code --weights ap-bwe\weights\16kto48k\g_16kto48k.safetensors voice.wav top.wav`, on the GPU); `matcheq.py apply curves/gopro_voice_curve.json` and `highpass=f=70`; `mixbed.py voice_eq.wav mono.wav voice.wav mix.wav -17` (the forest back 17 dB down); then steps 7 to 9. `adaptmatch.py` (a time-varying EQ that evens the tone as he turns his head) and `deess.py` were tried on walk 0038 and are not in the default: he said not to worry about tone evening.

## What isn't in git

The downloads, in `C:\Users\daves\voice-isolation`: `deepfilter\deep-filter-0.5.6-x86_64-pc-windows-msvc.exe` (DeepFilterNet's release), `ap-bwe\code` (the AP-BWE repository) with `ap-bwe\weights\16kto48k\` (its 16 kHz to 48 kHz model and `config.json`), `models\` (a Mel-Band RoFormer vocals model tried on walk 0038), and `venv\` (Python with CUDA torch for AP-BWE). Downloading any of them again needs David's OK.

## Walks so far

| Walk | Date | Output | Chain |
|---|---|---|---|
| 0033 | 12 to 13 Oct 2026 | `GX0033_youtube_mastered.mp4` (no longer in `Videos`) | DeepFilterNet, AP-BWE, studio-match EQ, forest at -17 dB |
| 0035 | 14 Oct 2026 | `GX0035_youtube_mastered.mp4` (no longer in `Videos`) | the same; the `-aac_tns 0` fix |
| 0038 | 19 Oct 2026 | `Videos\GX0038_youtube_mastered.mp4` | the first with Adobe Podcast and `adobe_curve_both.json`; graded (shot "Natural") |
| 0040 and 0041 | 21 Oct 2026 | `Videos\2026-10-21 - hike\GX0040-0041_youtube_mastered.mp4` | Adobe, the curve, the compressor (new) |
| 0044 and 0045 | 29 Oct 2026 | `Videos\2026-10-29 hike\GX0044-0045_youtube_mastered.mp4` | Adobe, the curve, the compressor; padded onto the video's timeline; 0045 is the conclusion with Mandy |

## Thumbnail stills

When he asks for stills to build a thumbnail from (22 Oct 2026, walk 0040): decode only the keyframes (one a second on this HEVC) at 384 x 216, look at contact sheets of every 5th second, shortlist moments, take the sharpest frame within about 0.6 s of each (centre-weighted Laplacian variance; walking blurs most frames), check eyes and hands at 960 px, and deliver 4K PNGs plus JPEGs (quality 95) and a contact sheet in `<walk folder>\thumbnail stills\`, named by walk time and what's in them; eye contact first, then gestures, scenery, the dog.
