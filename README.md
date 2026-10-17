# PunchAndRollAutomation

Tools and techniques for Claude Code to automate audiobook editing.

David, 14 Oct 2026: "you're not building a software product, you're building a library of tools, techniques, and methods for YOU to use as my audio engineer."

Claude reads the entire transcript, uses the recording and manuscript as context, decides what to keep, cut, repair and retime, then produces finished audio and a comprehensive report. The tools provide transcription, editing, mastering and quality analysis.

## Install

```bash
python -m pip install -e ".[all,pictures,listen]"
python -m punchroll models
```

On Windows with multiple Python versions, use `py -3.13` in place of `python`. Speech models are cached after downloading. `PUNCHROLL_MODELS` and `PUNCHROLL_CACHE` set the model and transcript cache folders.

With an NVIDIA card, a CUDA build of PyTorch runs the heaviest number-crunching on the card: the trained listener, the 4x oversampling behind true peak and the limiter, and the scorecard's pitch tracker. The results are the same as on the CPU. `PUNCHROLL_DEVICE=cpu` keeps everything on the CPU.

```bash
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

## Edit a recording

1. **Transcribe.** `python -m punchroll transcript raw/ch01.wav` writes `markup/ch01.transcript.md` with words, timestamps, pauses and nonword sounds.
2. **Read and mark the whole transcript.** Claude saves the edit as `markup/ch01.md`. It selects takes in context, preserves intended wording and delivery, removes unwanted material, and sets pauses to suit the passage. Every pause is read, and a hesitation inside a sentence is closed ([docs/how-it-works.md](docs/how-it-works.md), "Pauses").
3. **Render and master.** Run the command below to write the WAV, MP3, Markdown report and JSON edit map.
4. **Check the finished audio.** Read it back against the mark-up, trace the clicks it still has, look for anything cut that was never said again, inspect the joins and quality measurements, and revise the edit where needed.

```bash
python -m punchroll cut raw/ch01.wav --markup markup/ch01.md --config examples/settings.toml
python -m punchroll readback edited/ch01.mp3 --markup markup/ch01.md
python -m punchroll clicks raw/ch01.wav edited/ch01.wav --config examples/settings.toml
python -m punchroll lost raw/ch01.wav edited/ch01.mp3
python -m punchroll standards "edited/*.mp3" -o edited/standards.md
```

### Markup

| Mark | Action |
|---|---|
| `~~words~~` | Cut the marked words. |
| `~~{sound 0.11 -24}~~` | Cut the marked nonword sound. |
| `{0.75}` changed to `{0.40}` | Set that pause to 0.40 seconds. |
| `{0.60}` inserted between words | Insert a 0.60-second pause. |

Keep the transcript's words and sound tokens in order; use strikes for deletions. Blockquotes or HTML comments can hold editorial notes. The reader validates the markup against the source before rendering.

```text
0:12.0  ~~The system receives R D. {1.76}~~
0:16.0  The system receives a reward or penalty. {0.75}
```

`cut --report-only` writes a preview report without rendering. Settings for room tone, filtering, noise reduction, compression, loudness and output format are in [examples/settings.toml](examples/settings.toml).

## Work on a project

List recordings in [a project TOML](examples/project.toml), then run:

```bash
python -m punchroll batch project.toml
python -m punchroll scorecard project.toml other.toml --listener
```

For entries awaiting an edit, `batch` gives Claude the transcript and expected markup path. After Claude saves each markup, rerun it to render and master. Complete outputs are reused until their inputs change. `--only` selects recordings; `--force` rebuilds them. An entry can name its own settings file with `config`, for example a recording made with the microphone's high-pass filter off (`mic_filter_hz`).

Score the finished product, never the raw recording. David, 14 Oct 2026: "you should not be scoring the raw file" and "you should be scoring the final product". The scorecard reads only the finished files; how a take went in the room doesn't count.

The scorecard ranks the recordings by **fire**: the lift, movement, range and brightness of the delivery, on a fixed scale where 50 is the reader's average. David, 17 Oct 2026: "now that we've solved the basic production quality, [fire] will be the prime determinant of the files that get used for the PVC". The first run with `--calibrate-fire` sets the scale from the recordings so far (`fire-reference.json` beside the first project file); later runs read it, so new recordings land on the same scale. See [the fire score](docs/checking.md#fire).

## What was said

The finished transcripts: what the reader actually said on each finished recording, written out cleanly. Their wording is the gold standard for the manuscript.

```bash
python -m punchroll said draft project.toml     # where the finished audio differs from the reference text
python -m punchroll said build project.toml     # once every difference has a decision
python -m punchroll said changes project.toml --into notes.md   # every sentence the reader changed
```

`draft` lists each place where the recognizer's words for the finished file differ from the entry's reference text (`script` with `from`/`to`), and decides the ones that are only spelling. Claude decides the rest by reading: the reader's own wording, or a recognizer mishearing. `build` writes one transcript per recording and one with all of them. `changes` sets each sentence of the text the reader was given beside his finished transcript and lists every one he changed, with his own words marked: the evidence for writing the next script the way he speaks. See [quality analysis](docs/checking.md#finished-transcripts).

## Pickups and alternate recordings

Claude can select passages across recordings with an [assembly plan](examples/assembly.json): source files, time ranges, order, crossfades and optional level matching.

```bash
python -m punchroll assemble examples/assembly.json -o assembled/ch01.wav
```

This writes a float WAV and a source/output map. Use the assembled recording in the transcript, markup and mastering workflow above.

## Reports and inspection

| Tool | Output |
|---|---|
| `cut` | Full cut and pause report, sound inventory, removed-word audit, mastering measurements and source/output edit map. |
| `verify FILE --script book.docx` | Manuscript differences, pickups, small differences, missing lines, added material and ACX measurements. |
| `batch project.toml --proof` | Manuscript proof reports for finished project audio. |
| `standards FILES` | ACX and ElevenLabs measurements, format, pauses, mouth-click rate, tonal consistency and total duration. |
| `scorecard P.toml... --listener --enunciation` | The finished files side by side, best first by fire (lift, movement, range, brightness, hottest minutes), with enunciation (the everyday words a speech recognizer doubts), clicks, noise floor, tone, pitch, pace and trained-listener estimates; as Markdown and as a CSV beside it. |
| `readback EDITED --markup M` | Every word the mark-up kept, checked against the finished file: missing, doubled or returned words, with the nearest join. |
| `clicks RAW EDITED` | Each click counted in the finished file, traced to the recording and its place in the mark-up. |
| `lost RAW EDITED` | Stretches cut from the recording that are never said again: asides, slips, or something lost. |
| `declick MARKUP [--raw RAW --finished EDITED] [--write]` | Clicks struck in the mark-up as docs/checking.md says: a click left in or struck alone, and with the recording and the finished file, each click traced to a kept pause or breath. |
| `markcheck MARKUP` | The mark-up checked against its transcript, and what is left to judge: short sounds, pauses inside a sentence, long gaps. |
| `said draft/build P.toml` | The finished transcripts. |
| `said changes P.toml` | Every sentence the reader changed from the text he was given, with a count per recording. |
| `picture FILE --at 3:08` | Spectrogram of a passage; `--with RAW --with-at 3:14.5` compares source and result. |

Add `--script book.md --from "Chapter 1" --to "Chapter 2"` to `cut` or `verify` to compare a manuscript section. Markdown, plain text and Word files are supported. Manuscript comparisons provide evidence for Claude's editorial judgment; the marked transcript controls the edit.

See [editing and mastering](docs/how-it-works.md) and [quality analysis](docs/checking.md) for the techniques and measurements.
