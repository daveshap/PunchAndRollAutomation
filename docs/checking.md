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

`declick` makes these strikes in the mark-up: `punchroll declick markup/ch01.md --raw raw/ch01.wav --finished edited/ch01.wav --write`. Without `--raw` and `--finished` it rewrites only what the mark-up itself shows: a click left in, or a click struck alone with its pauses kept. Pauses written in by hand are never struck. Then cut again and run `clicks` again: taking out one click can let the detector count another that was below its threshold beside it. Repeat until no click is left in a pause or a sound, which took one to three rounds on the recordings of 15 Oct 2026, and read the whole list each time, not only its end.

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

`scorecard` reads each finished WAV and nothing from the source recording. Give it every project file whose recordings belong in one comparison (`scorecard labor-zero.toml voice-clone.toml`). It sorts the recordings by fire, highest first, and writes the table twice: as Markdown, and as a CSV of the same name for a spreadsheet.

| Column | Measurement |
|---|---|
| Recorded | The date in the chapter's entry in the project file. |
| Fire | Lift, movement, range and brightness on one scale: 50 is the reference set's average, every 10 a standard deviation. |
| Lift st | Median pitch over the whole file, in semitones above the reference set's average. |
| Movement st/s | How fast the pitch moves along each voiced stretch, in semitones per second. |
| Range st | How far the pitch swings: from its 10th to its 90th percentile while voiced, in semitones. |
| Brightness Hz | Centre of mass of the voice's spectrum up to 8 kHz, on the louder half of the voiced frames. |
| Hottest minutes | The three minutes of the file with the most fire: where each starts, and its fire. |
| Clarity | With `--clarity`: enunciation, landing and reset on one scale. As with fire, 50 is the reference set's average and every 10 a standard deviation. |
| Enunciation /100 | Everyday words per hundred that the speech recognizer doubts. Fewer is clearer. |
| Landing | How far a statement's pitch falls at its end, in the file's own pitch ranges (median). |
| Reset | How far the next sentence starts up again, in the same units (median). |
| Order | Average rank on clicks, tonal distance and available listener scores (production quality). |
| Clicks/min | Isolated short spikes in pauses, in the 1–10 kHz band. |
| Noise floor dB | The finished file's noise floor, as ACX measures it. |
| Tone dB | Octave-band distance from the set's median balance. |
| Pitch Hz | Median voice pitch over the whole file. |
| Words/min | Words in the finished file's transcript per minute, when it has been transcribed. |

Compare recordings made and processed under similar conditions. Use the individual measurements to select a coherent set and identify passages to improve.

### Fire

David, 17 Oct 2026: "I want to add this brightness/fire as a standard measurement to all files as this, I think, now that we've solved the basic production quality, will be the prime determinant of the files that get used for the PVC" and "put a number on it, and include it in the standard report". He had heard it before it was measured. Three recordings made back to back on 15 Oct 2026 (the Scion, essential demand and communism scripts) have "the pop and fire that we want to focus on". He also asked for the parts to be shown beside the score, "so I can see my progress". Range was added the same day, after research into what listeners hear as charisma; his words: "if that is something we can measure and quantify, absolutely. Let's science the shit out of making the perfect PVC".

How it was found, on the 28 finished recordings of 2 to 16 Oct 2026 (Claude's account). Each candidate was compared minute by minute: the three fire recordings against the rest, against the session closest to them in setup (16 Oct, the next morning), and against the other late-morning sessions.

- **Timing and phrasing don't separate them:** words per phrase, articulation rate, pauses, pitch resets and declination.
- **Voice-source measures don't either:** glottal flow by inverse filtering (NAQ, QOQ), H1–H2, cepstral peak prominence and harmonics-to-noise ratio. They track the low, slightly creaky morning voice instead.
- **Pitch height and pitch movement** track how warmed up the voice is, for which David's own guess was the time of day ("after I've had my coffee, biscuit, and some social engagement"). They were lowest in the 7 a.m. sessions of 14 and 16 Oct, and as high in the late-morning sessions as on 15 Oct. The 7 a.m. session of 8 Oct was nearly as animated, so the clock alone is not the cause.
- **Brightness** was the one measure on which 15 Oct stood above every other session, the next morning's included.

**Range** is the best-evidenced voice measure of charisma. Across 51 speakers, the distance from the 10th to the 90th percentile of pitch correlated .52 with rated charisma (.62 for men), where the plain lowest-to-highest range gave .04 (Niebuhr and Skarnitzl, ICPhS 2019). In resynthesis, widening a voice's range raised its ratings while moving its pitch up or down by 2 semitones did not (Berger et al., DAGA 2017). Range doesn't depend on the microphone. Adding it kept 9 of the top 10 recordings the same.

Fire combines the four parts with equal weight, so it rewards a warmed-up, animated, wide-ranging, projected read. It was not fitted to the three recordings. Two cautions:

- **Brightness moves with microphone placement as well as with the voice.** Compare sessions recorded with the microphone in its usual place, and read the parts, not only the total. Without brightness, two of the three 15 Oct recordings fall to the middle of the ranking, so that session's lead rests partly on it.
- **Any recording can be scored on the same scale** with `punchroll fire FILES` (run it in the folder that holds `fire-reference.json`, or name the file with `--reference`). The warm-up experiment uses it on a one-minute probe read three times a session: cold, after the warm-up, and after the last piece. The text is the same each time, so only the reader's state changes.
- **The scale is the speaker's own.** `--calibrate-fire` sets it from the recordings given (`fire-reference.json`, beside the first project file). Without the file, the score is relative to whatever set is scored and moves as recordings are added. Recalibrate only on purpose: every number in the earlier reports is on the old scale.

### Clarity

Fire rewards energy. Clarity rewards control: every word clearly said, every statement landed, and every new sentence started afresh. David, 17 Oct 2026, of the narration of "How Jobs Actually Disappear", which had scored an average 50 on fire: "a sober, self-possessed clarity with still really good prosody", and "exactly the kind of cadence/prosody for my audiobook too".

`--clarity` puts three parts on one scale, each a z-score against the reference set, averaged and scaled like fire's. The scale and its everyday words are in `clarity-reference.json` beside the first project file. The first run with `--clarity` sets it from the recordings given, and `--calibrate-clarity` sets it again.

- **Enunciation:** below.
- **Landing:** for each statement, which is a sentence of the finished transcript that ends in a full stop, its median pitch minus the low end of its last word (the median of the lower half of that word's voiced frames), divided by the file's pitch range from the 10th to the 90th percentile. The median over the file counts. Skilled readers end statements with large falls, and listeners hear a falling end as confident.
- **Reset:** the top of the pitch (90th percentile) over the first two words of the next sentence, minus the low end of the sentence before, in the same units. The new sentence starts afresh.

Dividing by the file's own range measures where the pitch moves, not how much it moves, which is fire's business. Pauses are left out on purpose: punchroll sets them in the edit, so they would score the editor and not the reader. Sentence ends come from the punctuation of the finished transcript (`punchroll said build`), matched to the recognizer's word timings for the finished file. A file with no finished transcript gets enunciation only. Landing and reset are measured on the same file as the word timings. Here the MP3s run 25 ms behind their WAVs, and pairing one file's timings with the other's audio moved landings by up to 0.1, because a statement's fall is in its last tens of milliseconds.

What the research says (Claude's reading, 17 Oct 2026):

- **The best-evidenced cues to clear, confident narration that a finished file keeps** are articulation (vowel space), a decisive fall at the end of statements (Vaughan-Johnston et al. 2024; Goupil et al. 2021; skilled readers in Schwanenflugel's reading-prosody work), and marking sentence boundaries with a pitch reset and final lengthening (Yang et al. 2014).
- **Measures not used.** The classic clear-speech cues of energy at 1 to 3 kHz and envelope modulation depth move with the microphone, the noise reduction and the compressor. Pause measures score the edit. Vowel formants are left for later; they need a pronouncing dictionary and LPC tracking.

On the 28 recordings of 2 to 16 Oct 2026:

- **The narration he singled out ("labor attrition") was second of 28 on clarity:** third for enunciation, fourth for landing and third for reset, against twelfth on fire. Only 11 percent of its statements failed to fall, the second fewest.
- **Clarity and fire are nearly independent** (correlation −0.23). The Scion read, his benchmark, is the only one near the top of both: third on fire and fourth on clarity.
- **The fieriest reads landed least.** Piece 8 left 41 percent of its statements up in the air, and piece 4 was lowest.

#### Enunciation

David, 17 Oct 2026, on the narration of "How Jobs Actually Disappear": "what people are noticing is just how entirely clear the enunciation is. But the thing is, for most listeners, particularly for audiobooks, that is the entire job. it's not just the words being spoken, it's HOW they are spoken (clarity, emphasis) so yeah if you can find a way to also measure prosody and enunciation that would be a good measure." That recording had scored an average 50 on fire, and he heard "a sober, self-possessed clarity with still really good prosody".

Enunciation asks a machine listener: the recognizer that transcribes the recordings, which reports a log-probability for every token that it hears. A word's probability is the product of its tokens'.

- **Only everyday words count.** These are the words found in at least a third of the reference recordings, 293 words for the 28 recordings of 2 to 16 Oct 2026, so names and jargon, which a recognizer doubts whoever says them, drop out. Each recording has about 600 to 1,300 of them.
- **A word is doubted** when the recognizer gives it a probability under 0.9. The score is the number of doubted words per hundred everyday words.
- **The word list is fixed** with the clarity scale in `clarity-reference.json`, so that later recordings are counted on the same words.
- **The recognizer's word confidences are cached** with the transcripts, so only new files take the extra 30 seconds or so.

On those 28 recordings it ran from 4.3 to 7.9 doubted words per hundred.

- **Recording 13, the narration that he and his viewers singled out, was third clearest.** The others in the top five were pieces 15, 9 and 12 and part 2 of chapter 1.
- **The least clear** were pieces 6, 3 and 19 (the charts piece). Piece 19 is the one most full of numbers.
- **It doesn't depend on fire** (correlation 0.07): recording 13 sat in the middle on fire, and the rats piece, top on fire, sat in the middle on enunciation.

Cautions:

- **Each count is a sample of a few hundred words**, so differences under about one word per hundred are within noise.
- **The recognizer also doubts fast or run-together speech and unusual phrasing**, so the material still counts for something. Compare recordings of like material where you can.

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

### What the reader changed

`said changes` sets each sentence of the text the reader was given beside his finished transcript and lists every sentence he changed: the written one with the words he didn't say struck, the said one with his own words in bold, and a count per recording. With `--into NOTES.md` it rewrites only what lies between the file's `<!-- counts:start -->` and `<!-- counts:end -->` markers and after `<!-- log:start -->`. An entry's `written` (with `written_from` and `written_to`) names the text he was given when the reference is a copy made from his reading, and `heading` is its heading in the log. Because what was said is the finished transcript, a misspelled name or a spelled-out number is never a change; a slip of the tongue is, so read each one.

This is the evidence for writing a script he won't have to fix. With it, read:

- the mark-ups of the raw recordings, for the sentences that took several tries and what he said about the text between takes;
- his own edits in the script he read from, found by setting that file beside the text he was given: they are his writing, and they outrank everything else;
- for a rewrite of a script, the old text, the rewrite and the finished transcript side by side: count the rewrite's edits that he read as written, put back, or changed further. That tests the rules the rewrite followed. The surface rules can all pass while the writing still fails him underneath them.

Sort every change into a pattern, with all its examples, and write the rules from them. The reader's own words, quoted with their date, outrank the patterns.

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
