# Quality analysis

Use the finished transcript, edit report, signal measurements and visual inspection together to assess the recording.

```bash
python -m punchroll readback edited/ch01.mp3 --markup markup/ch01.md
python -m punchroll clicks raw/ch01.wav edited/ch01.wav --config settings.toml
python -m punchroll lost raw/ch01.wav edited/ch01.mp3
python -m punchroll standards "edited/*.mp3" -o edited/standards.md
python -m punchroll scorecard project.toml --listener
python -m punchroll picture edited/ch01.wav --at 3:08 --with raw/ch01.wav --with-at 3:14.5
```

## Finished-file review

Read the entire output transcript against the intended reading. Inspect cuts for clipped syllables, repeated material, missing words and unintended pauses. The cut report includes source and output locations, retained and removed sounds, changed pauses and removed words absent from the retained transcript. Use the source recording to resolve recognition errors and inspect the relevant passage with `picture`.

When a manuscript is available, `verify` lists the full sentence and location of each difference. Decide whether the difference is an intended ad-lib, a recognition error or a reading that needs repair.

### Read-back

`readback` sets the words the mark-up kept beside the recognizer's words for the finished file. Each word kept should be there once, in order, and nothing struck should be back. A difference marked "spelling only" is the recognizer writing the same word two ways ("EU V" and "EUV"); a different word heard in the same place is usually the recognizer too, and is worth a listen when it falls near a join. A word missing at a join means the cut clipped it.

### Clicks left in a finished file

`clicks` lists every click the scorecard counts and traces each one to the recording and to its place in the mark-up: inside a pause, inside a sound, or inside a word.

- The click detector times a click at about 10 ms, but the click itself runs 20 to 30 ms. Striking only the `{sound ...}` leaves the click's tail at the join, where it starts abruptly and stands out more than the click did.
- For a click in a pause, strike the pause around it as well and write a fresh pause of the same length after the struck run (`~~{0.14} {sound 0.01 -24} {0.18}~~ {0.32}`), which is filled with room tone. Or lengthen a clean pause beside it and strike the rest.
- A click inside a kept breath goes with the breath.
- A click inside a word's span (a lip smack at the end of "them") can't be cut without cutting into the word.

### Lost words

`lost` sets the recognizer's words for the recording beside those for the finished file. A retake repeats what it replaces, so the cut words come back just after the cut. Cut words that never come back are an aside, a slip or a false start, or something the reader said that the edit lost. Read each one; the reader's last take and every rewording are the text.

## Standards

The numeric targets below come from [ACX audio submission requirements](https://help.acx.com/s/article/acx-audio-submission-requirements) and [ElevenLabs Professional Voice Cloning guidance](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/professional-voice-cloning), checked 13 October 2026.

| Measurement | ACX | ElevenLabs voice-clone training |
|---|---|---|
| Loudness | -23 to -18 dB RMS | -23 to -18 dB RMS |
| Peak | At most -3 dB | -3 dB true peak target |
| Noise floor | At most -60 dB RMS | Clean recording without background noise |
| Room tone | 1–5 seconds recommended at the head and tail; spacing at most 5 seconds | Timing appropriate to the delivery being cloned |
| Encoding | MP3, 192 kbps or higher CBR, 44.1 kHz | MP3, 192 kbps or higher recommended |
| Duration | At most 120 minutes per file | At least 30 minutes; about 2–3 hours recommended |

The `standards` report also gives the longest pause, click rate, tonal distance and loudness spread. Claude evaluates those measurements in context. Numeric compliance checks do not change the edit.

## Scorecard

Score the finished product, never the raw recording. David, 14 Oct 2026: "you should not be scoring the raw file" and "you should be scoring the final product". How a take went in the room (how much was cut, how noisy the raw recording was, what processing did to it) doesn't count; what the finished file is like does.

`scorecard` reads each finished WAV and nothing from the source recording.

| Column | Measurement |
|---|---|
| Clicks/min | Isolated short spikes in pauses, in the 1–10 kHz band. |
| Noise floor dB | The finished file's noise floor, as ACX measures it. |
| Tone dB | Octave-band distance from the set's median balance. |
| Pitch Hz | Median voice pitch over the middle 100 seconds. |
| Words/min | Words in the finished file's transcript per minute, when it has been transcribed. |
| Order | Average rank on clicks, tonal distance and available listener scores. |

Compare recordings made and processed under similar conditions. Use the individual measurements to select a coherent set and identify passages to improve.

### Trained listener

`--listener` uses [torchaudio SQUIM Objective](https://docs.pytorch.org/audio/main/pipelines.html#squim-objective) to estimate PESQ in ten-second windows. It reports the mean, lower tenth and locations of the lowest-scoring windows. The model evaluates audio resampled to 16 kHz.

Use low-scoring windows as inspection points alongside spectral and peak measurements. The model's score estimates signal quality; Claude assesses the wording, performance and edit.

## Finished transcripts

What the reader actually said on each finished recording, written out cleanly: the gold standard for the reader's wording. `said draft` aligns the recognizer's words for the finished file with the entry's reference text and lists every difference with the words around it; differences that are only spelling are decided straight away. Decide the rest by reading, in `said/NAME.decisions.json`:

| Decision | Writes |
|---|---|
| `"s"` | What the recognizer heard: the reader's own wording. |
| `"w"` | The reference's words: a name, a homophone, a number the recognizer spelled out. |
| any other text | Exactly that; a leading `<` takes the comma or full stop off the word before. |

To tell a mishearing from a rewording: names and homophones are the recognizer's; a changed word that the recognizer hears the same way in the raw recording and in the finished file is the reader's. `_fixes` in the same file mends capitals and commas where the reader's wording joins the written text. Punctuation is plain: a colon, semicolon, dash or bracket that the reader read through becomes a comma or a full stop.

## Breaths, pauses and noise

Preserve natural breathing and intentional delivery. Reduce or remove distracting gasps, clicks and other noises as the passage requires, keeping whole breaths and natural transitions. [Narrators Roadmap](https://www.narratorsroadmap.com/should-i-remove-breaths-from-my-audiobook/) describes preserving ordinary breaths as standard audiobook practice.

Inspect title, subtitle, paragraph and scene transitions in context. Set their timing in the markup. Use continuous noise reduction when needed and compare the processed passage with the source for changes to the voice, breath texture and room sound.

## Spectrograms

`picture` plots time horizontally, frequency vertically and energy as brightness. Use `--top 700` to inspect low-frequency hum; give each file its own start time when comparing source and output.

| Feature | Appearance |
|---|---|
| Voice | Harmonic lines and broader resonance bands. |
| Room noise | Diffuse energy between words. |
| Hum | Persistent horizontal line. |
| Mouth click | Short vertical spike. |
| Breath | Diffuse energy between voiced passages. |
| Reverberation | Energy extending beyond a word's end. |

Inspect joins and noise-reduction changes at the corresponding source and output times.
