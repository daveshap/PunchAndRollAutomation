# How it works

Claude does the editing. The program does three things around that: it writes down what is in the recording, it carries out the mark-up exactly, and it masters the result. It makes no decision about the reading.

## 1. Transcribe

Silero VAD finds the stretches of speech. Neighboring stretches are grouped into chunks of up to 20 seconds, because a short phrase decoded on its own can come back empty while the same words decoded with their neighbors don't. Each chunk is transcribed by NVIDIA Parakeet TDT 0.6B v2 (int8 ONNX, through sherpa-onnx), which gives a timestamp for every token. Tokens are joined into words; punctuation is attached to a word without stretching its end time.

Two checks keep speech from going unheard:

- **Sound the detector left out.** The detector sometimes starts a stretch late, ends one early, or misses a short phrase or a muttered aside between two pauses. Any sound that stays within 25 dB of the voice's level for 0.15 seconds or more, and comes within 15 dB of it, is added to the detector's stretches.
- **A stretch that comes back empty.** The recognizer can drop a short stretch at the end of a long chunk. A stretch with no words is decoded again on its own.

Every finished chunk is written to the transcript cache immediately, so an interrupted run resumes where it stopped, and a finished transcript is reused whenever the same recording is opened again.

## 2. Lay the recording out as pieces

The recognizer's word times can swallow the silence after a word, so the edges are measured from the audio: 5 ms energy frames, the room's own level taken from the frames with no speech, and "quiet" defined as less than 12 dB above that.

From the first word to the last, the recording becomes one unbroken run of pieces (`pieces.py`):

- **Words.** Each runs from where the voice starts to where it stops.
- **Quiet.** The quiet stretches between words.
- **Sounds.** Anything between words that rises out of the quiet and is not a recognized word: a breath, a mouth click, a bump, a cut-off syllable. Each is given its length and its loudest moment in dB against the voice. A flicker shorter than 0.04 seconds and more than 30 dB under the voice is the room's own noise and stays part of the quiet.

A sound at the voice's own level that the recognizer gave no word for (it smooths "Th— The easy things" into the sentence alone, and has no word for a cough) is found the same way and listed as a sound.

## 3. The transcript and the mark-up

`punchroll transcript` writes the pieces out as text (`markup.py`), one run of speech to a line, each line starting with its time in the recording:

```
3:11.7  Learning by trial and error. {0.75}

3:14.1  Instead of being shown the right answer, {0.27} the system tries actions and receives R D. {1.76}

3:21.5  Instead of being shown the right answer, {0.26} the system tries actions, {0.24} receives a reward or penalty, and gradually adjusts towards whatever earns more reward. {0.25} {sound 0.11 -24} {0.10} {sound 0.18 -36} {0.21}
```

`{0.75}` is a pause of 0.75 seconds. `{sound 0.11 -24}` is a sound of 0.11 seconds, 24 dB under the voice. A gap shorter than 0.15 seconds with no sound in it is not listed; it goes with the word after it.

Claude reads the whole transcript and saves a marked copy:

| Mark | Meaning |
|---|---|
| `~~struck through~~` | Cut. Words, pauses and sounds are struck the same way. |
| `{0.75}` changed to `{0.40}` | Make this pause 0.40 seconds. |
| `{0.60}` written where there was no pause | Put one in. |

What is not struck is what the finished file holds. In the example the second line is an abandoned take, so it is struck whole, pause included, and the 0.75-second pause before it becomes the pause before the retake.

The words themselves must stay in the file as written, struck or not. `punchroll cut` checks the marked file against the recording word for word and stops if they differ, naming the line, so a slip in the mark-up cannot move a cut.

## 4. Cut

`cut.py` carries the mark-up out:

- **Nothing struck and no number changed between two words:** the audio is left exactly as recorded, breaths included.
- **A pause made shorter:** quiet is taken out of its middle. **Made longer:** room tone is let into its middle.
- **Something struck:** the audio leaves the recording after the last kept word and comes back at the next one. The pause between them is the sum of the pauses left unstruck between the two. It is built from the recording's own quiet beside each word, with room tone added only if more was asked for than the recording has there.
- **Even where every pause at a cut was struck,** 0.05 seconds of the room is kept after the earlier word and 0.03 before the later one, so no word is clipped.

Room tone is taken from the recording itself: half-second stretches with no speech, near the 30th percentile of their levels (typical, not the quietest), with the fewest clicks, crossfaded together. Every join is an 8 ms crossfade. The file starts with `head` seconds of room tone and ends with `tail` seconds (1.5 and 3.0 unless the settings say otherwise).

## 5. Master

1. Normalize to −22 dB RMS.
2. Noise reduction, if `noise_reduction` is `"on"`, or if it is `"auto"` (the default) and the noise floor (quietest half second) would otherwise end above −62 dB. See below.
3. Second-order high-pass at 70 Hz.
4. Compressor: RMS detector on 10 ms windows, −26 dB threshold, 2:1, 10 ms attack, 150 ms release.
5. Look-ahead limiter (6 ms) with a true-peak ceiling of −3.5 dB, and the gain searched so the result lands at −20 dB RMS. The limiter works from the waveform's level between samples (4x oversampled), not from the samples alone: on a bright or sibilant voice the two differ by 2 dB or more, and a limiter that only watches samples lets the true peak through. ACX's limit is −3 dB; the half decibel is room for their meter to read a little higher than this one.

**Noise reduction** follows the method of Audacity's Noise Reduction effect, and its three settings mean what Audacity's three sliders mean. The difference is that nobody selects a noise sample: it is found in the pauses.

- The recording is cut into overlapping windows of 46 ms, and each window into about a thousand frequency bands.
- *The noise sample* is the average level of each band over the quieter half of the pauses. A pause here is a stretch where the level between 200 and 4000 Hz stays within 25 dB of the quietest twentieth of the recording, from a quarter second after the last louder sound to a quarter second before the next. The sample comes from the pauses as a whole and not from their one quietest moment, because a pause holds more than the room: faint mouth sounds, the low end of a breath. With only the room's hiss in the sample, those are left standing in a pause that is otherwise much quieter, and the leftover crackles.
- A band holds only noise at a given moment unless it rises well above the sample: at `noise_sensitivity = 6`, about 11 dB above it in two of five neighbouring windows. Bands holding only noise are turned down by `noise_reduction_db`. Everything else passes as it is, so a breath that stands clear of the pause keeps its top and loses some of its low end.
- The turning down fades in over 0.1 seconds after a sound and lifts 0.02 seconds ahead of one. Each band's gain is then averaged with `noise_smoothing` bands on either side, so no band is left open or shut alone.
- The same rule runs from the first sample to the last, ahead of the compressor. A hum pitched inside the voice's range is not removed under speech: its bands are open while the voice is sounding in them, and the voice covers it. It fades within a tenth of a second of the voice stopping and is down by the full amount through every pause, along with everything else in the sample.

One thing is done differently from Audacity. The bands under the high-pass frequency take no part in the smoothing. They hold rumble and none of the voice, they are shut nearly all the time, and averaging them with the bands just above turned the lowest note of a low voice down with them: 3 dB at 100 to 140 Hz on a voice pitched near 125 Hz, at smoothing 6.

If the recording has no pauses to sample (under half a second of them, or quiet that isn't 20 dB below the voice), noise reduction is skipped and the log says so.

The WAV master is written at the bit depth the recording came in at (16 bits at least, 24 at most; 16-bit output is dithered). The MP3 is resampled to 44.1 kHz if needed and encoded, then decoded again and measured: if resampling or the encoder pushed its true peak over the ceiling, it is encoded again slightly lower.

RMS, true peak (of the WAV and of the MP3), and noise floor are reported against ACX's limits. The peak passes on the true peak, not on the highest sample.

## 6. Report

`punchroll cut` writes two files beside the audio:

- `name.report.md`: the ACX measures, every cut in order with the words that went and the pause now standing there, and every pause whose length was changed.
- `name.edit.json`: the same, plus the edit list (which stretch of the recording sits where in the finished file). The scorecard reads it.

To read a finished file back, run `punchroll transcript` on it: the result is the same kind of transcript, and anything still wrong in it shows the way it did in the recording.
