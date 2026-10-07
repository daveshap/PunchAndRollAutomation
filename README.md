# PunchAndRollAutomation

Automatic punch-and-roll editing for audiobook narration.

Record straight through. When you slip, pause and start the sentence again. `punchroll` finds every restart, keeps your last good take of each line, rebuilds the pauses, and masters each chapter to ACX specs. Everything runs on your own computer: no uploads, no API keys, no subscriptions.

On a real 18.6-minute chapter read with 21 restarts, it found all 121 lines of the script, removed 274 words of false starts and asides, and produced 15.4 minutes of finished audio in 2.8 minutes of processing on two CPU cores. Re-transcribing the result found no restarts left.

## What it does

1. **Transcribes** each recording with word timings, offline, using NVIDIA Parakeet TDT 0.6B v2 through sherpa-onnx.
2. **Aligns** the transcript to your narration script. Restarts, skipped text, fillers ("um", "sorry"), and asides are explicit moves in the alignment, so a repeated phrase, a retaken sentence, and a re-read paragraph are all recognized the same way. For every word of the script, the last reading wins.
3. **Comps** where it helps: if the last take of a line has a slip that an earlier take read correctly, the two are spliced at a natural pause.
4. **Rebuilds the pauses.** Your own pauses and breaths are kept wherever nothing was cut and the pause is in range. Where a take was cut, or a pause is too long or too short, the gap is rebuilt from your room's own tone. Every join gets a short crossfade.
5. **Masters to ACX**: −20 dB RMS, peaks below −3 dB, noise floor below −60 dB, 1.5 s of room tone at the head and 3 s at the tail. Writes a 24-bit WAV and a 44.1 kHz mono 192 kbps constant-bit-rate MP3.
6. **Reports** what to re-record (pickups), every cut and why, every pause it changed, and an edit decision list.

## Install

Python 3.10 or newer on macOS, Windows, or Linux.

```bash
git clone https://github.com/daveshap/PunchAndRollAutomation
cd PunchAndRollAutomation
pip install -e ".[all]"
punchroll models          # downloads about 480 MB of speech models, once
```

Models go to your user cache folder (`~/.cache/punchroll`, `~/Library/Caches/punchroll`, or `%LOCALAPPDATA%\punchroll`). Set `PUNCHROLL_MODELS` to put them elsewhere.

## Quick start

Check what a chapter will be matched against:

```bash
punchroll lines --script narration.md --from "Chapter 1" --to "Chapter 2"
```

Edit and master it:

```bash
punchroll clean ch01.wav --script narration.md --from "Chapter 1" --to "Chapter 2" --name ch01
```

Results land in `./edited`: `ch01.wav`, `ch01.mp3`, `ch01.report.md`, `ch01.edl.csv`, and `ch01.report.json`.

**Pickups.** Record the lines the report lists into a new file, in any order, then run the same command with both files, pickups last. Later recordings win, and their level is matched to the first file:

```bash
punchroll clean ch01.wav ch01-pickups.wav --script narration.md --from "Chapter 1" --to "Chapter 2" --name ch01
```

**Check the result** the way a proofer would. This re-transcribes the finished file, reports anything that still differs from the script, and measures the ACX specs on the file itself:

```bash
punchroll verify edited/ch01.mp3 --script narration.md --from "Chapter 1" --to "Chapter 2"
```

**A whole book.** List the chapters in a project file (see [examples/project.toml](examples/project.toml)) and run them all:

```bash
punchroll batch book.toml
```

Run it again after every recording session. Chapters that are already edited are skipped unless their recordings, script section, or settings changed (`--force` redoes them anyway; `--only ch07` picks one).

## The script

- Markdown, plain text, or Word (`.docx`, using heading styles for headings).
- It should contain exactly what you say aloud, headings included: "Chapter One", "Part One", the chapter title. Words you say that aren't in the script are treated as asides and cut, and script lines you didn't read are reported.
- Footnote markers and footnote text, tables, images, code blocks, and links are cleaned out automatically. Numbers are compared the way they're spoken ("1810s" matches "eighteen tens", "$52,000" matches "fifty-two thousand dollars").
- Select a chapter with `--from` and `--to` (text from its headings) or `--lines 115-143`.

To make a narration script from a Word manuscript: `pandoc manuscript.docx -t markdown --wrap=none -o narration.md`, then edit it to match what you'll say.

## Recording for it

The short version: when you slip, keep recording, pause for a breath, and restart the sentence from its beginning. Details, including pickups and session setup, are in [docs/recording.md](docs/recording.md).

## Speed and memory

- Transcription runs at 7 to 8 times real time on 2 CPU cores, and faster with more (`--threads`).
- Transcripts are cached per recording (in `~/.cache/punchroll/transcripts`, or `PUNCHROLL_CACHE`), so changing settings or adding pickups only transcribes what's new.
- Measured on 2 CPU cores: an 18.6-minute chapter (44.1 kHz MP3) took 2.8 minutes the first time and 0.5 minutes on re-runs, peaking at 0.7 GB of memory on re-runs. A 56-minute chapter (48 kHz, 24-bit WAV, 480 MB) took 8.3 minutes the first time and 1.7 minutes on re-runs, peaking at 2.3 GB while transcribing and 1.7 GB after.
- For chapters much longer than 90 minutes, record and edit in sections.
- `--max-minutes N` stops transcription after N minutes and exits with code 3; running the same command again resumes where it stopped. Useful in shells with a time limit; leave a couple of minutes of headroom for editing and mastering.

## Settings

Pause rules, loudness targets, and alignment costs can be changed with `--config settings.toml`. Every setting and its default is listed in [examples/settings.toml](examples/settings.toml), and the reasoning is in [docs/how-it-works.md](docs/how-it-works.md).

## Running it with an AI agent (optional)

Nothing in the pipeline calls an AI service. If you'd like Claude to run it for you:

- **Claude Code** (in a terminal, or the Code tab of the Claude desktop app) works directly on your computer: it can install this, run chapters, read the reports, and fix problems, with no time limit per command.
- **Claude in Cowork mode**, with your computer linked and the recordings folder connected, can run it inside that folder. Use `--max-minutes` so long transcriptions finish across several calls.

## Limits

- The recognizer sometimes mishears names, numbers, and short words, so pickups are places to listen, not verdicts.
- English only (Parakeet v2 is an English model).
- If the script repeats a sentence word for word, a retake of it can occasionally be matched to the wrong instance.
- No music beds or sound effects; this is for narration.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests cover script parsing, the alignment rules (restarts, fillers, asides, pickups), a full edit-and-master pass on synthetic audio, and the command line, including which chapters `batch` skips. They don't need the speech models.

## Credits

- Speech recognition: [NVIDIA Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0), run with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0)
- Voice activity detection: [Silero VAD](https://github.com/snakers4/silero-vad) (MIT)
- MP3 encoding: LAME through [lameenc](https://github.com/chrisstaite/lameenc) (LGPL)
- Number words: [num2words](https://github.com/savoirfairelinux/num2words) (LGPL)
- ACX audio requirements: [ACX Audio Submission Requirements](https://help.acx.com/s/article/acx-audio-submission-requirements)
