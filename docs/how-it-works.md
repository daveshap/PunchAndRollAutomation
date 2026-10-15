# Editing and mastering

## Transcript

`transcript` uses Silero voice activity detection and Parakeet word recognition to produce timed words. Recognition runs in chunks and caches completed work. Additional decoding covers energetic sounds missed by the detector and speech stretches that returned no words.

`pieces.py` measures word boundaries, quiet and nonword sounds. Each sound has a duration and level relative to the voice. `markup.py` writes the sequence as readable text:

```text
0:12.0  The system receives R D. {1.76}
0:16.0  The system receives a reward or penalty. {0.25} {sound 0.11 -24} {0.50}
```

Claude reads the entire sequence and chooses the intended reading. Use surrounding sentences and the actual recording to distinguish retakes, deliberate repetition, ad-libs, breaths and unwanted sounds. A manuscript supplies context and comparison. The edit follows the intended spoken delivery.

Save the marked copy separately from the generated transcript. Repeated transcription preserves existing files and writes a numbered copy. The whole method in one place, as it was given to helpers marking up recordings, is [marking-up.md](marking-up.md).

## Markup

| Syntax | Meaning |
|---|---|
| `~~text~~` | Cut the marked words, sounds or pauses. |
| `{0.40}` replacing an existing pause | Set its duration in seconds. |
| `{0.60}` inserted between pieces | Insert room tone for that duration. |
| `{sound 0.11 -24}` | Measured nonword sound: 0.11 seconds, 24 dB below the voice. |
| Blockquote or HTML comment | Editorial note, ignored by the renderer. |

Leave the original word and sound tokens in order. The parser verifies their correspondence with the source. Striking a sound removes it; leaving it unstruck preserves it. Claude sets pause timing for the sentence, title, transition or scene.

### Pauses

Claude reads every pause in the transcript and sets it, including the pauses inside a sentence, and not only the ones beside a cut. The reader's words:

- 13 Oct 2026: "we need the longer pauses preserved for things like titles, subtitles, scene breaks, etc (I know there is some variance in this, I've heard audiobooks where there is zero pause, and some where there is pretty significant pause) but as they say measure twice cut once it's easier to cut out a pause later I think."
- 15 Oct 2026: "I have some intra-sentence pauses (i.e. pauses that are slightly too long within the sentence, between words as I hesitated). so like... basically as part of your markup are you ALSO looking at pause optimization? if not, can you add that as a default practice?"

How Claude reads them (the lengths come from his finished recordings, pieces 12 to 16 of the voice-clone script; they guide the reading, and nothing in the code applies them):

- **A pause between words that belong together is a hesitation.** Examples are a subject and its verb ("Every company {0.15} is going"), a number and its unit ("more than 30,000 {0.16} per day"), and the words inside one phrase ("every single {0.26} day"). Close it to about 0.05 s so the words join as they do in his fluent reading. A shortened pause keeps the quiet at both of its ends, so no sound is clipped.
- **A pause at a comma or between two clauses stays as he made it, unless it runs long.** His comma pauses have a median of 0.25 s, and four in five fall between 0.16 and 0.42 s. Bring a longer one down to about 0.3 s.
- **A pause between sentences stays, unless it holds a slip, a retake or a click.** His median is 0.62 s, and four in five fall between 0.30 and 1.43 s, with scene breaks included in that count.
- **Titles, subtitles and scene breaks keep a longer pause.** Write a pause in after a title, and between a title and its subtitle when he ran them together. Give a scene or paragraph break about a second.
- **A pause that he plainly meant as a beat stays,** such as one before a punchline or before a number he is landing.

`punchroll markcheck markup/ch01.md` sets a mark-up beside its transcript and lists what is left to judge: short sounds still in, pauses of 0.12 s or more inside a sentence, and kept gaps over 1.6 s. A pause it lists is not always wrong, because the recognizer often leaves out a comma that the script has.

## Rendering

`cut.py` builds a timeline from retained source spans and selected pauses. Unchanged adjacent source spans are joined into one continuous span. Every positive sample range is retained, including short sounds.

A shortened pause keeps quiet from its two ends. A lengthened pause adds room tone in the middle. Inserted pauses use room tone from the recording. Splice fades suppress clicks without changing the selected timeline length. The edit map records the exact source and output positions.

Room tone is built from quiet source passages. `head` and `tail` add room tone at the output boundaries. Standard transcripts cover the first through last measured word or sound; short exterior source handles preserve the onset and decay at those boundaries.

## Pickups and alternate sources

`assemble` consumes a JSON plan with `sample_rate`, named `sources` and ordered `clips`. Paths are relative to the plan. Each clip selects `source`, `start` and `end` in seconds.

Optional `crossfade` overlaps the preceding clip by the stated duration. `gain_db` applies a chosen gain. `match_level_to` measures an explicitly selected reference range; `level_sample` selects comparable speech from the pickup for RMS matching. `note` records the reason for the selection. See [examples/assembly.json](../examples/assembly.json).

The command writes a float WAV and `.assembly.json` containing source paths, exact sample mappings, applied gains and peak measurements. Feed the assembled recording through the standard transcription, edit and mastering workflow. Preserve the assembly map with the final deliverables to trace pickups back to their recordings.

## Mastering

The default chain is:

1. Normalize the working signal to -22 dB RMS.
2. Apply profile-based noise reduction when selected.
3. High-pass at 70 Hz.
4. Compress at 2:1 with a -26 dB threshold.
5. Limit to -3.5 dB true peak while targeting -20 dB RMS.
6. Export WAV and 44.1 kHz mono 192 kbps CBR MP3; decode and measure the encoded MP3.

The noise profile comes from quiet passages. Reduction operates across the recording, with attack, release and frequency smoothing to maintain continuous room sound. The three controls correspond to Audacity's noise reduction amount, sensitivity and smoothing. The low-frequency bands removed by the high-pass filter are excluded from smoothing into the voice.

Select `noise_reduction = "on"`, `"off"` or `"auto"` and adjust the amount for the recording. Automatic mode uses the configured projected noise floor. For a recording made with the microphone's own high-pass filter switched off, `mic_filter_hz` adds a second-order high-pass ahead of everything else so its low end matches the rest; give that recording its own settings file with `config` in its project entry. The WAV uses the source bit depth by default, with dither for 16-bit export. All settings are in [examples/settings.toml](../examples/settings.toml).

## Reports

A rendered recording produces:

- `name.wav` and `name.mp3`: finished audio.
- `name.report.md`: cuts, pause changes, sound decisions, removed-word audit, manuscript comparison when supplied, and mastering measurements.
- `name.edit.json`: the report data, retained words and source/output edit map.

`--report-only` writes `name.dry-run.report.md`. It leaves finished outputs intact.

The manuscript comparison normalizes written and spoken number forms, then lists differences with source and output times where available. It includes full sentences, small differences, missing lines and additional material.

After rendering, transcribe the finished audio into a separate review folder. Read it against the intended transcript and inspect the reported passages. Use [quality analysis](checking.md) to evaluate signal quality, delivery and consistency, then revise and render again as needed.

## Batch

A project file names source recordings, markup paths, settings and optional manuscript sections. `batch` prepares transcripts for Claude, renders completed markups and reports the files awaiting edits. It checks both audio and report artifacts against the source, markup, project, settings, manuscript and renderer version before reusing a result.

`batch --proof` selects a named finished output when present, or the entry's supplied audio for a project of externally mastered files. It prints the exact file being proofed. `--report-only` renders no audio.
