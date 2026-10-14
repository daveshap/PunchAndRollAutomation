# Quality analysis

Use the finished transcript, edit report, signal measurements and visual inspection together to assess the recording.

```bash
python -m punchroll transcript edited/ch01.wav -o review
python -m punchroll standards "edited/*.mp3" -o edited/standards.md
python -m punchroll scorecard project.toml --listener
python -m punchroll picture edited/ch01.wav --at 3:08 --with raw/ch01.wav --with-at 3:14.5
```

## Finished-file review

Read the entire output transcript against the intended reading. Inspect cuts for clipped syllables, repeated material, missing words and unintended pauses. The cut report includes source and output locations, retained and removed sounds, changed pauses and removed words absent from the retained transcript. Use the source recording to resolve recognition errors and inspect the relevant passage with `picture`.

When a manuscript is available, `verify` lists the full sentence and location of each difference. Decide whether the difference is an intended ad-lib, a recognition error or a reading that needs repair.

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

`scorecard` reads each finished WAV, its source recording and its `.edit.json` map.

| Column | Measurement |
|---|---|
| Clicks/min | Isolated short spikes in pauses, in the 1–10 kHz band. |
| Room dB | Separation between source room noise and voice, in the 300–4000 Hz band. |
| Cut % | Percentage of recognized source words removed. |
| Cuts/min | Number of cuts per finished minute. |
| Tone dB | Octave-band distance from the set's median balance. |
| Pitch Hz | Median voice pitch over the middle 100 seconds. |
| Words/min | Retained words per minute. |
| Breaths (whole) | Detected breaths in untouched pauses and how many survive mastering whole. |
| Order | Average rank on clicks, tonal distance, cut percentage and available listener scores. |

Compare recordings made and processed under similar conditions. Use the individual measurements to select a coherent set and identify passages to improve.

### Trained listener

`--listener` uses [torchaudio SQUIM Objective](https://docs.pytorch.org/audio/main/pipelines.html#squim-objective) to estimate PESQ in ten-second windows. It reports the mean, lower tenth and locations of the lowest-scoring windows. The model evaluates audio resampled to 16 kHz.

Use low-scoring windows as inspection points alongside spectral and peak measurements. The model's score estimates signal quality; Claude assesses the wording, performance and edit.

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
