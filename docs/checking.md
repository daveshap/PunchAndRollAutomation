# Checking finished recordings

`verify` checks a finished file against its script. The three commands here check it against the published standards, against the other recordings in the set, and by eye. None of them changes any audio.

```bash
punchroll standards edited/*.mp3            # ACX and ElevenLabs, no transcription, a few seconds a file
punchroll scorecard book.toml               # every finished chapter side by side
punchroll picture edited/ch01.wav --at 3:08 --with ch01.wav --with-at 3:14.5
```

## 1. Standards

`punchroll standards` measures each file and judges it against two published sets of figures. Both pages were read on 11 October 2026. Publishers change them, so follow the links before relying on a number.

**ACX**, from its [audio submission requirements](https://help.acx.com/s/article/acx-audio-submission-requirements):

| What | Figure |
|---|---|
| Loudness | −23 to −18 dB RMS |
| Peaks | no higher than −3 dB |
| Noise floor | no higher than −60 dB RMS |
| Room tone | 1 to 5 seconds at the head and at the tail (recommended) |
| Gaps | "Room tone spacing must not exceed 5 seconds" |
| Format | 192 kbps or higher, constant bit rate, 44.1 kHz MP3; all files mono or all stereo |
| Length | no file longer than 120 minutes |
| Clean | free of "plosives, microphone pops, mouse clicks, excessive mouth noise" and outtakes |
| Narration | by a human, unless ACX has authorized otherwise |

**ElevenLabs**, from its [guide to Professional Voice Cloning](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/professional-voice-cloning), for audio that will train a voice clone:

| What | Figure |
|---|---|
| Loudness | "between -23dB and -18dB RMS with a true peak of -3dB": the same numbers as ACX |
| Format | "We strongly recommend MP3 at 192kbps or above"; uncompressed WAV "usually do not improve clone quality" |
| How much | 30 minutes at the least, two to three hours for the best clone |
| Pauses | avoid "long gaps of silence"; the clone copies long pauses and filler words |
| Sameness | one voice, one speaking style, consistent quality and tone across the files |
| Clean | no background noise or echo: "the AI will clone everything about the audio" |

Where a publisher gives no number, the limit in the report is ours and says so: a pause over 3 seconds for ElevenLabs' "long gaps", and a file whose tone sits more than 2 dB from the rest of the set for "consistent".

The check doesn't judge three things:

- **Mouth clicks.** It counts them (see below) but neither publisher gives a figure.
- **Breaths.** Neither publisher gives a rule. Audiobook practice is to leave breaths in, lower only the loud or gasping ones, and never leave one half cut: [Narrators Roadmap](https://www.narratorsroadmap.com/should-i-remove-breaths-from-my-audiobook/) calls leaving them in "the audiobook industry standard approach", and [Sound on Sound](https://www.soundonsound.com/techniques/podcast-dialogue-editing-cubase) lowers them by about 6 dB because removing them "often sounds unnatural".
- **How it sounds.**

## 2. Scorecard

`punchroll scorecard book.toml` scores every chapter that has a finished WAV, and writes `scorecard.md` to the project's output folder. It is for choosing among recordings that all pass: which to put in a voice-clone training set, which chapter to re-record first. The edit is rebuilt from each recording to line it up with its finished file, so the recordings and their transcripts must still be where the project file says.

| Column | What it measures |
|---|---|
| Clicks/min | Mouth clicks standing alone in pauses: a spike of 25 ms or less in 1 to 10 kHz, at least 60 ms clear of the words either side, counted when it comes within 30 dB of the file's level. |
| Room dB | How far the quietest moments of the recording sit under the voice, 300 to 4000 Hz. Bigger is quieter. |
| Retakes % | Lines that took two or more takes, per 100 lines. |
| Cuts/min | Places where the edit removed something. |
| Tone dB | How far the file's balance by octave (125 Hz to 8 kHz, while speaking) is from the middle of the set. |
| Pitch Hz | Median pitch of the voice over the middle 100 seconds. |
| Words/min | Pace. |
| Breaths (whole) | Breaths found in pauses the edit kept whole, and how many of them reach the finished file whole. |
| Order | The average of the file's rank on clicks, tone, retakes and, with `--listener`, the listener. 1 is best. |

Read it with these in mind:

- **The order is a starting point.** The measures aren't equally important, and none of them hears the performance.
- **Noise reduction thins breaths when the room is noisy.** A quiet breath close to the level of the room's hiss is treated as room: turned down, or cut off at its start. With a quieter room the same breath passes whole. On sixteen recordings, 55 of 180 breaths came through whole in the ten made with a hissier chain and 103 of 108 in the six made after it was fixed.
- **Don't compare clicks across different amounts of noise reduction.** The same thing happens to faint clicks, so a noisier recording's count is flattered.
- **A click count is a count, not a verdict.** About five a minute is what a close microphone and a clean pause showed on a careful reader.

### The trained listener

`--listener` adds an estimate from a model trained on people's ratings: torchaudio's SQUIM objective model, which estimates PESQ (1 to 4.5) from the audio alone. Install it with `pip install -e ".[listen]"` (PyTorch and torchaudio); the first run downloads about 28 MB.

It was tried on sixteen finished narration files and on copies of one passage spoiled on purpose:

| Passage | Estimate |
|---|---|
| Finished | 4.05 |
| As recorded | 4.13 |
| Hiss added 40 dB under the voice | 3.56 |
| Hiss added 30 dB under the voice | 2.42 |
| Thirty loud clicks added | 2.90 |
| A small room's echo added, 10 dB under the voice | 4.05 |
| Clipped at a third of its peak | 3.96 |

So it hears hiss and clicks and does not hear echo or clipping. It works at 16 kHz, so nothing above 8 kHz is judged. The sixteen files all scored between 3.86 and 4.12, and the lowest-scoring ten seconds among them looked like ordinary clean speech. It will catch a bad session. It will not pick the best of several good ones.

SQUIM's other model, which estimates an opinion score out of 5, is not used. It gave 4.99 to all sixteen files and to every spoiled copy in the table above, and fell only once the hiss was 20 dB under the voice. Its weights are also licensed for non-commercial use only.

## 3. Pictures

`punchroll picture` draws a spectrogram of a passage: time across, pitch up, brightness for level. `--with` puts a second file underneath, brought to the same loudness, which is how to see what the edit and the mastering did. Give each file its own start time, since the same words sit at different times in the recording and the finished file. Needs `pip install -e ".[pictures]"` (matplotlib).

What to look for:

- **The voice** is a stack of evenly spaced bright lines (the pitch and its overtones) with brighter bands where the mouth shapes them.
- **The room** is the haze between words. In a finished file with noise reduction it is black.
- **A hum** is a thin level line that carries on through the pauses, most often under 500 Hz. Use `--top 700` to look there.
- **A mouth click** is a thin bright vertical line standing alone in a pause, often just before a breath.
- **A breath** is a soft haze with a few broad bands, mostly under 5 kHz. One that noise reduction has thinned starts abruptly and has holes in it.
- **Echo** is smear to the right of a word's end. A dry room leaves a sharp edge.
- **Clipping** is a bright column from bottom to top on a loud syllable.

## 4. What the edit cut and never heard again

Every edit report now has a section, "Cut and not said again". A retake says the abandoned words again, so they turn up in what the edit keeps straight after the cut. Words that don't are shown in capitals. Most are chatter, slips and cut-off words. Some are things the reader meant to keep:

- three or more words added in a row, which are cut as an aside by design ("...can be useless OR EVEN DANGEROUS.");
- a word added beside a take you abandoned, if you said it in the same breath as that take or in front of a retake that picks up partway through a line ("It's the bedrock..." read again as "IT IS the bedrock..."); set apart by a pause, at the start or end of a line, it is kept;
- a sentence reworded on the retake, when the first take matched the script better.

The check does not use the script, so it sees what the alignment can't. If your own wording is what counts, give punchroll a script that holds what you said (your last take of every line), and this section will hold nothing but chatter.
