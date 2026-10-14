# PunchAndRollAutomation

Tools and techniques for Claude Code to automate audiobook editing.

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
2. **Read and mark the whole transcript.** Claude saves the edit as `markup/ch01.md`. It selects takes in context, preserves intended wording and delivery, removes unwanted material, and sets pauses to suit the passage.
3. **Render and master.** Run the command below to write the WAV, MP3, Markdown report and JSON edit map.
4. **Check the finished audio.** Transcribe it into a separate folder, review the wording and sounds, inspect the joins and quality measurements, and revise the edit where needed.

```bash
python -m punchroll cut raw/ch01.wav --markup markup/ch01.md --config examples/settings.toml
python -m punchroll transcript edited/ch01.wav -o review
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
python -m punchroll scorecard project.toml --listener
```

For entries awaiting an edit, `batch` gives Claude the transcript and expected markup path. After Claude saves each markup, rerun it to render and master. Complete outputs are reused until their inputs change. `--only` selects recordings; `--force` rebuilds them.

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
| `scorecard project.toml --listener` | The finished files side by side: clicks, noise floor, tone, pitch, pace and trained-listener estimates. |
| `picture FILE --at 3:08` | Spectrogram of a passage; `--with RAW --with-at 3:14.5` compares source and result. |

Add `--script book.md --from "Chapter 1" --to "Chapter 2"` to `cut` or `verify` to compare a manuscript section. Markdown, plain text and Word files are supported. Manuscript comparisons provide evidence for Claude's editorial judgment; the marked transcript controls the edit.

See [editing and mastering](docs/how-it-works.md) and [quality analysis](docs/checking.md) for the techniques and measurements.
