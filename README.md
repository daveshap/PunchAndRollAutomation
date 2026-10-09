# PunchAndRollAutomation

Automatic punch-and-roll editing for audiobook narration.

Record straight through. When you slip, pause and start the sentence again. `punchroll` finds every restart, keeps your last good take of each line, rebuilds the pauses, and masters each chapter to ACX specs. Everything runs on your own computer: no uploads, no API keys, no subscriptions.

On a real 18.6-minute chapter read with 21 restarts, it found all 121 lines of the script, removed 274 words of false starts and asides, and produced 15.4 minutes of finished audio in 2.8 minutes of processing on two CPU cores. Re-transcribing the result found no restarts left.

What running it on real recordings has turned up, and what changed in the code because of it, is in the [field log](#field-log).

## What it does

1. **Transcribes** each recording with word timings, offline, using NVIDIA Parakeet TDT 0.6B v2 through sherpa-onnx. Sound at the voice's level that the voice detector skips (a clipped sentence start, a muttered aside) is transcribed too, so it can't sit unheard in a pause, and sound the recognizer has no word for (a cut-off syllable, a bump) is cut the way a filler is.
2. **Aligns** the transcript to your narration script. Restarts, skipped text, fillers ("um", "sorry"), and asides are explicit moves in the alignment, so a repeated phrase, a retaken sentence, and a re-read paragraph are all recognized the same way. For every word of the script, the last reading wins. A word your retake leaves out stays out, so nothing from the abandoned take is set into the middle of it. A word or two you add at the edge of a line is kept when it runs straight on from the line.
3. **Comps** where it helps: if the last take of a line has a slip that an earlier take read correctly, the two are spliced at a natural pause. If you reword lines on purpose as you read, `--no-comps` keeps your last take of every line whole.
4. **Rebuilds the pauses.** Your own pauses and breaths are kept wherever nothing was cut and the pause is in range. Where a take was cut, or a pause is too long or too short, the gap is rebuilt from your room's own tone. Every join gets a short crossfade.
5. **Masters to ACX**: −20 dB RMS, true peak at −3.5 dB or lower (ACX's limit is −3), noise floor below −60 dB (with noise reduction if the room needs it, or whenever you ask for it), 1.5 s of room tone at the head and 3 s at the tail. Writes a WAV at your recording's bit depth and a 44.1 kHz mono 192 kbps constant-bit-rate MP3, and measures the MP3's own peak after encoding it.
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

**If `punchroll` isn't found after installing** (common on Windows with more than one Python): pip installed it into a Python whose `Scripts` folder isn't on your PATH, and `py` may be starting a different Python than the one pip used. pip's output names the Python it installed into. Run punchroll through that one:

```bash
py -3.13 -m punchroll models
```

Every `punchroll ...` command below works the same way as `py -3.13 -m punchroll ...`.

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

**Audio that is already edited and mastered.** `verify` works on any finished file, whoever made it: it recognizes the speech, matches it to the script, lists what differs, and measures the ACX specs, and it writes no audio. For a whole book, point a project file at the finished files and add `--proof`:

```bash
punchroll batch book.toml --proof
```

To see what `clean` would cut from a raw recording without rendering anything, add `--report-only` to it.

**Not sure which chapter a recording is?** Transcribe it and read the first few words:

```bash
punchroll transcribe take-07.wav
```

That writes the words and their times to `edited/take-07.words.json`. The transcript is cached, so `clean` won't transcribe the file again.

## The script

- Markdown, plain text, or Word (`.docx`, using heading styles for headings).
- It should contain exactly what you say aloud, headings included: "Chapter One", "Part One", the chapter title. Words you say that aren't in the script are treated as asides and cut, and script lines you didn't read are reported.
- Footnote markers and footnote text, tables, images, code blocks, links, and `<!-- comments -->` are cleaned out automatically. Numbers are compared the way they're spoken ("1810s" matches "eighteen tens", "$52,000" matches "fifty-two thousand dollars", "8:00 a.m." matches "eight a.m.").
- Select a chapter with `--from` and `--to` (text from its headings) or `--lines 115-143`.

A Word manuscript works as it is. If you'd rather mark up a Markdown copy, [Pandoc](https://pandoc.org) makes one: `pandoc manuscript.docx -t markdown --wrap=none -o narration.md`. Pandoc is a separate program that pip does not install, and punchroll doesn't need it.

## Recording for it

The short version: when you slip, keep recording, pause for a breath, and restart the sentence from its beginning. Details, including pickups and session setup, are in [docs/recording.md](docs/recording.md).

## Speed and memory

- Transcription runs at 7 to 8 times real time on 2 CPU cores, and faster with more (`--threads`).
- Transcripts are cached per recording (in `~/.cache/punchroll/transcripts`, or `PUNCHROLL_CACHE`), so changing settings or adding pickups only transcribes what's new.
- Measured on 2 CPU cores: an 18.6-minute chapter (44.1 kHz MP3) took 2.8 minutes the first time and 0.5 minutes on re-runs, peaking at 0.7 GB of memory on re-runs. A 56-minute chapter (48 kHz, 24-bit WAV, 480 MB) took 8.3 minutes the first time and 1.7 minutes on re-runs, peaking at 2.3 GB while transcribing and 1.7 GB after.
- Measured on 8 CPU cores (8 threads): transcription ran at 16 to 17 times real time. A 9-minute recording took about half a minute to transcribe and another 20 seconds to edit and master.
- For chapters much longer than 90 minutes, record and edit in sections.
- `--max-minutes N` stops transcription after N minutes and exits with code 3; running the same command again resumes where it stopped. Useful in shells with a time limit; leave a couple of minutes of headroom for editing and mastering.

## Settings

Pause rules, loudness targets, and alignment costs can be changed with `--config settings.toml`. Every setting and its default is listed in [examples/settings.toml](examples/settings.toml), and the reasoning is in [docs/how-it-works.md](docs/how-it-works.md).

For mastering, `limiter_ceiling_db` is the true-peak ceiling (−3.5 dB, half a decibel under ACX's limit) and `wav_bits` sets the WAV master's bit depth (your recording's own by default).

Noise reduction is automatic unless you say otherwise: it runs only when the noise floor would end above −62 dB, and turns the room's noise down by 12 dB. `noise_reduction = "on"` runs it on every chapter and `"off"` on none. `noise_reduction_db`, `noise_sensitivity`, and `noise_smoothing` are the three numbers Audacity's Noise Reduction effect asks for and mean the same here, so settings you already trust carry over. There is no noise sample to select: it is taken from the pauses. A hum at the pitch of your voice still passes while you are speaking, where your voice covers it, and is down by the full amount in every pause. More in [docs/how-it-works.md](docs/how-it-works.md#5-master).

Two settings decide how much of your own wording survives when you depart from the script. `comps = false` (or `--no-comps` on the command line) keeps the last take of every line whole instead of splicing in part of an earlier one. That includes its end: if your retake drops the last few words of a sentence and reads on, they stay dropped. `adlib` under `[pauses]` is how closely an unscripted word must follow or lead into a line to count as part of it (0.25 seconds by default).

## Running it with an AI agent (optional)

Nothing in the pipeline calls an AI service. If you'd like Claude to run it for you:

- **Claude Code** (in a terminal, or the Code tab of the Claude desktop app) works directly on your computer: it can install this, run chapters, read the reports, and fix problems, with no time limit per command.
- **Claude in Cowork mode**, with your computer linked and the recordings folder connected, can run it inside that folder. Use `--max-minutes` so long transcriptions finish across several calls.

## Limits

- The recognizer sometimes mishears names, numbers, and short words, so pickups are places to listen, not verdicts. It formats numbers by context: "$450" has come back as "$450,000" right after a larger figure was read.
- A sound at the voice's level with no recognizable words in it (a cut-off syllable, a cough, a bump) is cut and listed in the report as a stray sound, provided it stands clear of the words around it. One that runs into a word, or sits more than 25 dB under the voice, is not caught. One that stands where the script has a word nothing else was heard for is kept as that word, and the report says so.
- Cuts are placed in quiet where there is any. When you stumble and start again without a pause, the cut goes just ahead of the re-read's first word, in whatever sound is there, and the report doesn't mark that join.
- English only (Parakeet v2 is an English model).
- If the script repeats a sentence word for word, a retake of it can occasionally be matched to the wrong instance.
- No music beds or sound effects; this is for narration.

## Field log

Notes from real sessions: what was run, what it showed, and what changed in the code because of it. Newest first.

### 2026-10-09, third entry: two more recordings, and two things left in the edit

**The job.** Two new recordings of 8 to 9 minutes, read with the titles left off, comps off, noise reduction on. Both mastered at −20 dB RMS with noise floors of −83 dB.

**What it showed.**

1. *An ending the reader said he was cutting came back.* He read a sentence to its end, said "that doesn't make any sense, I'm going to cut that out", re-read it without its last five words, and went on to the next sentence. The edit kept the retake and then set the five words in after it from the abandoned take. A word left out of the middle of a retake already stayed out. One left off the end stayed out only when the dropped words were few: the alignment counts three or four as words not read and more than that as a jump ahead, and a jump ahead that reached the end of the sentence was taken to mean the take had stopped there.
2. *A cut-off syllable sat in a pause.* `verify` found a restart in the finished file: "The th— The easy things were always the hard part." The recognizer had heard the syllable in the finished file and not in the recording, where the same stretch came back as the sentence alone. Nothing marked the syllable as speech, so it was kept as part of the pause before the sentence.
3. *It was not the only one.* A search of all twelve recordings for sound at the voice's level that no recognized word covers found three inside the finished edits: that syllable, another cut-off syllable before a sentence in a recording delivered two days earlier, and a low bump with a click before a sentence in a third. `verify` had passed the last two, because the recognizer has no word for them in any decoding. Every other sound the search found was already being cut with the take around it.

**What changed.**

- With comps off, a take that stops partway through a sentence and reads on has dropped the rest, whatever its length, and the earlier take's ending is not put back (`last_take(..., whole=True)`). With comps on, nothing changes.
- When the edit is built, sound at the voice's level that touches no recognized word is entered in the transcript as `[sound]` and cut as a filler is, unless it stands where the script has a word that nothing else was heard for (`edit.stray_sounds`). The report counts and lists stray sounds.
- The three recordings were edited again. In each, the edit list changed only at the sound in question, the nine other recordings' edit lists did not change, and `verify` finds no restarts left in any of the twelve. 40 tests.

**Still open.** A stray sound that runs into a word, with no dip between them, is not separated from it. A cut-off syllable followed straight away by the word it was reaching for is the likely case.

### 2026-10-09, second entry: noise reduction that doesn't come and go

**What it showed.** The narrator of the ten recordings below listened to the masters and heard a low hum cutting in and out, a choppiness behind his voice. The recordings carry a steady 120 Hz tone near −69 dB. The noise reduction then in place set its threshold at the room tone's own level and took 8 dB off whatever fell under it, after the compressor. Noise sits at its own level, so bands of it opened and shut at random, and 8 dB down is still audible: both states could be heard, and so could the movement between them. He ran Audacity's Noise Reduction over a recording by hand (20 dB, sensitivity 6, frequency smoothing 6) and preferred it at once.

**What was tried on the way.**

1. *A notch at 120 Hz, switched out whenever his voice was on that frequency.* It measured well (−67 dB to −93 dB in the pauses), and he heard the tone coming and going.
2. *Audacity's method with an automatic noise sample.* Set beside his own Audacity pass on the same 19-second recording, the two left the same silence to within 0.3 dB below 200 Hz and within 2 dB up to 1 kHz.
3. *What that method costs the voice.* Both passes took about 2 to 3 dB off his voice between 70 and 200 Hz and nothing above 300 Hz. The cause is the frequency smoothing: each band's gain is averaged with six neighbours on either side, the bands below 70 Hz hold rumble and are shut nearly all the time, and the lowest note of a voice pitched near 125 Hz sits within six bands of them. With those bands left out of the averaging the loss at 70 to 140 Hz is 0.0 dB and the pauses are as quiet as before.
4. *Where the sample is taken.* With the sample drawn only from the quietest moments, the room's hiss came down 20 dB and everything else in a pause was left standing: in an 8-minute piece, 9 to 13 % of the quietest windows had a band jumping 6 dB or more above the rest, against 0 to 1.5 % before any noise reduction. Drawn from the quieter half of all the pauses, that share is 0.4 to 1.3 %, and breaths between sentences lose 8 dB below 1 kHz and 2.6 dB from 1 to 4 kHz. That average hides a split: a quiet breath goes almost entirely (16 to 19 dB in one looked at closely) and a full one passes. Soft speech sounds and weak consonants changed by 0.3 dB or less under either rule.
5. *Under speech, and at the edges of words.* The tone is at the pitch of his voice, so its bands are open while he speaks. In the re-mastered recordings the 100 to 140 Hz band stays at −63 to −71 dB through speech and sits at −76 to −82 dB in the pauses, a bigger step than the old masters had. Listening, the narrator called the result clean: under speech the voice is 30 dB or more above the tone on the same frequency, and the pauses are quiet. Across 117 places in one piece where the voice starts after a pause, the change from the moment it passes −50 dB was nil (−0.1 dB for the worst tenth), and the 30 ms before that lost 1 dB typically and 4 dB for the worst tenth. Tails dying away below −50 dB fade faster than they did: 2 dB down at −54 dB, 7 dB down at −63 dB.

**What changed.** The between-words noise reduction is gone. In its place is the method above, run over the whole edit ahead of the compressor, with settings on Audacity's scales: `noise_reduction` (`"auto"`, `"on"`, `"off"`), `noise_reduction_db`, `noise_sensitivity`, `noise_smoothing`. On automatic it still runs only where the floor would end above −62 dB, now by 12 dB. The first of the ten recordings mastered at a floor of −58.9 dB with it off, −70.7 dB on automatic, and −78.7 dB at 20 dB. It adds about a second per minute of audio. 37 tests.

All ten recordings were then mastered again at 20 dB, sensitivity 6, smoothing 6. The edit lists came out identical, the noise floors are −76 to −80 dB where they had been −64 to −68, and a fresh proofing pass found no restarts left in any of them. The proofing lists differ from the earlier ones in how the recognizer wrote numbers and names, and in one word ("who", now heard as "which") whose audio is unchanged from 50 ms after its start; the quiet breath in front of it is gone.

**Still open.** How far the result holds for a room with louder or less steady noise than this one, and for a higher voice, where the lowest note has empty bands below it that the 70 Hz line does not cover. Lower `noise_smoothing` is the remedy there (at 3, before the 70 Hz line, the loss at this voice's lowest note was under half of what it was at 6).

### 2026-10-09: the true-peak meter at block edges

**What it showed.** The change below made the limiter and the MP3 check act on the true-peak reading, and that reading had a flaw of its own, there since the first release. The meter resamples the file in blocks of about 24 seconds, each with a little of its neighbours for context, and it took its maximum over the context as well. The resampler rings where its input is cut off, so when a block edge fell on a loud moment the ringing read as a peak up to 1 dB over the real one. While the figure was only printed, the cost was an occasional pessimistic number. Once it steered the level, one master came out at −20.7 dB RMS instead of −20.0, and its MP3 0.9 dB lower than it had to be.

**How it was found.** By mastering the same recording a second time for another experiment and getting a different loudness. No test had caught it because none of their signals was longer than one block.

**What changed.** The meter keeps only each block's own part. Two tests cover it: the reading must not depend on where the blocks fall, and a recording with a loud syllable cresting exactly where a block begins must still master to −20 dB RMS. Both fail with the previous meter. 32 tests.

### 2026-10-08, third entry: an engineer's test on other narrators' audio

**The job.** An audiobook engineer who masters for ACX every day ran the tool on his own material: an 800-page manuscript marked up as Markdown, chapters picked out with `--from "Chapter 99" --to "Chapter 100"`, and a batch on a laptop at 13.7 times real time. It found the one pickup he already knew was in a chapter, and he put its false positives (names, the odd misheard word) level with a paid proofing service's.

**What it showed.**

1. *The masters came out hot on his meter: a true peak of −2.3 dB.* The limiter held the samples at −3.6 dB and left the true peak to land where it would. On the ten recordings below that was −3.4 dB. On a brighter voice it isn't: the same mastering, run on one of those recordings with everything above 3 kHz raised 12 dB, put the true peak at about −1 dB with every sample still at −3.6. The report printed the true peak in brackets and passed the file on the sample peak.
2. *16-bit recordings came back as 24-bit masters,* half as large again and no better.
3. *He asked for a way to run only the recognition, matching, and reporting on files that are already mastered.* `verify` did that for one file, but nothing said it works on audio the tool didn't make, and there was no way to run it over a book.
4. *Pandoc looked like a dependency.* The README gave a `pandoc` command for turning a Word manuscript into Markdown without saying that Pandoc is a separate program, or that a .docx can be used as it is.
5. *He keeps true peaks at −3.5 dB,* because ACX's own meter has objected to files that read −3 on his.

**What changed.**

- `master.py`, `audio.py`: the limiter works from the level between samples (4x oversampled), so its ceiling is a true-peak ceiling, now −3.5 dB, and the peak passes or fails on the true peak. The brightened recording masters to −3.5 dB.
- The MP3 is decoded after encoding and measured. If resampling or the encoder pushed its true peak over the ceiling, it is encoded again slightly lower, and the report gives the MP3's figure beside the WAV's. On the ten recordings the MP3s read −3.6 to −3.7 dB.
- The WAV master is written at the recording's own bit depth, 16 at least and 24 at most (`wav_bits` in the settings overrides it). 16-bit output is dithered.
- `batch --proof` runs `verify` over every chapter of a project file and writes reports only. The Quick start now says what `verify` and `--report-only` are for.
- The README and the recording guide say that a Word file works as it is and that Pandoc is optional.
- Tests went from 27 to 30.

**Still open.** His meter and this tool's were not compared on the same file. punchroll reads true peak 4x oversampled, and a stricter reading (32x) came out up to 0.2 dB higher on the brightened test. The half decibel under ACX's limit is there to cover that.

### 2026-10-08, second run: four book chapters, 58 minutes

**The job.** Four recordings of 8 to 21 minutes made over the previous week, each one section of a book: the preface, the introduction, and the first two parts of chapter 1. The script was the whole manuscript, 172,000 words under 90 headings.

| Recording | Recorded | Edited | Restarts cut | Words removed | Speech the voice detector missed |
|---|---|---|---|---|---|
| Preface | 8.3 min | 7.9 min | 6 | 44 | 1.9 s |
| Introduction | 9.7 min | 9.0 min | 8 | 51 | 1.6 s |
| Chapter 1, part 1 | 18.6 min | 15.4 min | 21 | 277 | 3.9 s |
| Chapter 1, part 2 | 21.1 min | 17.4 min | 26 | 308 | 16.8 s |

After the fix below: 410 of 412 script lines found (the other two are section titles that were never read aloud), no restarts left on `verify` in any of the four, and masters at −20 dB RMS with noise floors of −64 to −68 dB.

**How it was run.**

- The manuscript is a Word file, and earlier in the day another Word file could not be read while it was open in Word. So its text, from the title page through the appendix, was written out once as Markdown with the headings kept, and checked to give the same words as the .docx, block for block. `batch` ran against that, with `from` and `to` set to section headings.
- The reader says a part label the manuscript doesn't have ("Part one. The Rise of Automation."). As words between two headings it would have been cut as an aside, so the label was added to that heading in the script ("Part One: The Rise of Automation"). `from` and `to` still found it, because they look for text inside a heading.
- Same settings as the first run (`comps = false`), and `verify` on every finished file.

**What it showed.**

1. *One word of an abandoned take ended up inside the final take.* The first take read "A radiologist and a truck driver occupy indire" and stopped. The retake read "A radiologist and truck driver occupy...", without the second "a". "Last reading wins" was applied word by word, so the only reading of that "a", the first take's, was kept: 0.2 seconds of the first take set between "and" and "truck" of the retake, with the cuts inside the voice (−24 to −34 dB in a room at −62 dB).
2. *`verify` could not see it.* The words of the finished file matched the script. It was found by measuring the level at every cut point of all ten edits from the day, which the tool does not do. The other nine were clean.
3. *The same thing happens when the recognizer misses a short word in the retake.* The retake's own "a" would then still be in the audio, and the first take's would be added to it.
4. *A second decoding settles most single-word doubts.* The reports flagged 29 lines. Two were the unread titles. Nearly all the rest were rewording, tense, and names. Three differences in the raw transcripts ("understand" for "understanding", "lifetime" for "lifting", "cleaner" for "clearer") came back as the script's word when the finished file was transcribed. One came back the same both times ("nearly possible" for "nearly impossible") and went on the list to hear.
5. *The recognizer writes `<unk>` for a sound it can't spell.* "C++" came back as `C<unk>` and was listed as an added word, "unk".
6. *Missed speech follows the muttering.* The detector missed 16.8 seconds in part 2, which has spoken asides between takes, and under 4 seconds in each of the others. Every sound at voice level that produced no words was inside a stretch that was cut.
7. *Joins.* Of 101 joins in the four final edits, 99 are within 15 dB of the room. One is a retimed pause in a soft breath. The other follows a stumble with no pause before the re-read ("with c, the, with the coalitions"): the cut goes just ahead of the re-read's first word and comes back in 18 dB above the room.

**What changed.**

- `align.py`: a word or phrase that a later take read straight past is cut with the rest of the earlier take. The retake stays in one piece, and the line is reported as missing that word. With comps on, an earlier take can still supply it, spliced at a pause. A take that stops partway and moves on still replaces only what it re-read.
- `text.py`: the recognizer's `<unk>` is dropped.
- Tests went from 25 to 27. All ten edit lists from the day were rebuilt with the change: nine came out identical, and part 2 differs only at that sentence, which is now one continuous stretch of the retake.

**Still open.** The level check that found the misplaced word is not part of the tool, so a join that lands in the voice is not reported (see Limits).

### 2026-10-08: six standalone recordings, 53 minutes

**The job.** Six mono 44.1 kHz WAV exports of 8 to 9.5 minutes, each one piece of a 24-piece script (about 1,000 to 1,150 words a piece), read with restarts, spoken asides, and deliberate rewording. Windows 10, 8 cores, Python 3.13 with 3.14 also installed.

| Recording | Recorded | Edited | Restarts cut | Words removed | Speech the voice detector missed |
|---|---|---|---|---|---|
| 1 | 9.4 min | 8.3 min | 6 | 93 | 2.1 s |
| 2 | 8.1 min | 7.5 min | 3 | 43 | 2.0 s |
| 3 | 8.6 min | 8.0 min | 4 | 48 | 2.5 s |
| 4 | 9.3 min | 8.0 min | 6 | 76 | 8.2 s |
| 5 | 8.8 min | 7.7 min | 5 | 92 | 5.3 s |
| 6 | 8.7 min | 7.6 min | 9 | 111 | 5.5 s |

After the fixes below: all 500 script lines found, `verify` reports no restarts left in any of the six, and every master is at −20 dB RMS with true peaks at −3.4 dB and a noise floor between −65 and −68 dB.

**How it was run.**

```bash
py -3.13 -m punchroll transcribe take-01.wav
py -3.13 -m punchroll clean take-01.wav --script script.md --from "Title of this piece" --to "Title of the next piece" --no-comps --name take-01
py -3.13 -m punchroll verify edited/take-01.mp3 --script script.md --from "Title of this piece" --to "Title of the next piece"
```

- `pip install -e ".[all]"` installed into Python 3.13, but `py` started 3.14 and the `Scripts` folder wasn't on the PATH, so neither `punchroll` nor `py -m punchroll` worked until the version was named. The Install section now covers this.
- Each recording was one piece, so `transcribe` came first to read its opening words, and `--from` and `--to` were the title of that piece and of the one after it.
- Once the settings were right, the six became a project file run with `batch`, with `comps = false` in its settings file and one `[[chapter]]` per recording. A wildcard in `audio` picks up a second take or a pickups file later.
- `verify` ran on every finished file. It is the step that showed the first pass was wrong.

**What it showed.**

1. *A clean report is not proof.* The first pass reported every line found and every spec passed, and `verify` still found a false start in recording 1. The recognizer had returned no words for a 0.8-second stretch at the end of an 18.5-second chunk, after a one-second pause. Decoded on its own, or with the chunk ending 0.3 seconds later, the words came back.
2. *The voice detector misses speech at full level.* The recordings had a voice level around −17 dB and a noise floor near −60 dB, and the speech it missed peaked at −14 to −16 dB. Most misses were sentence starts caught 0.1 to 0.3 seconds late. The rest were the first two words of a sentence after a pause, the last word of a sentence, a two-word sentence between two pauses, an aborted word before a sentence, and, in two recordings, muttered asides of about 2 seconds between takes that it did not mark at all.
3. *What a miss costs depends on where it falls.* The editor keeps whatever lies between two recognized words as a pause. Between a cut take and its re-read, an unheard sound is removed with the rest. Between two kept sentences it stays. The first pass left one false start and two sub-second blips in the audio that way, and reported two words and a whole line as missing that were there.
4. *Rewording on purpose runs into two rules.* The reader changed about 30 small things ("technician" to "tech", an added "actually"). Listing those as pickups is right. But a word added at the edge of a sentence ("...until they were cheap enough.", "And groceries don't fall.") was classed as an aside between lines and cut, with no pause to cut at. Both cuts landed inside continuous speech, and the re-check still heard the words. And one comp put the second half of an earlier take over a sentence the reader had re-read.
5. *Three token mismatches made false differences.* The recognizer attaches an amount to the word before it ("is$450"). An em dash without spaces joined two script words into one. "per cent" and "percent" both appeared in a single transcript.
6. *A difference that survives several decodings is worth a listen; one that flips is the recognizer.* "$450" came back as "$450,000" when the same chunk held "$52,000", and as "$450" in five of six decodings with other boundaries. One word decoded six ways came back as the script's "competence" twice and as "confidence" four times. Names came back in a different spelling on each pass.
7. *Mastering.* After leveling, the noise floor was between −57.5 and −59.8 dB in every recording, so all six got the gentle noise reduction.
8. *Joins.* Of 101 joins in the six final edits, 99 leave and re-enter the recording within 15 dB of the noise floor. The other two are retimed pauses that sit in a soft breath at about −45 dB.

**What changed.**

- `asr.py`: sound within 25 dB of the voice's level for 0.15 seconds or more, peaking within 15 dB of it, is added to the detector's stretches (`add_missed_speech`). A stretch that comes back without words from its chunk is decoded again on its own. The transcript cache key carries a version, so transcripts made before a change like this are not reused.
- `edit.py`: an unscripted word or two at the edge of a line is kept when it follows or leads into the kept word beside it within 0.25 seconds (`adlib` under `[pauses]`). An aside or a stray sound that stands apart is still cut. Comps can be turned off (`comps = false`, `--no-comps`).
- `text.py`: currency amounts are set off from the word before them, dashes and other non-ASCII punctuation separate words instead of joining them, and "percent" is always two tokens. From the same day's run of the whole script through the parser: clock times are read the way they're said ("8:00 a.m." is "eight a.m."), letters that Unicode normalization drops (Þ, ø, ß and others) are transliterated, and Markdown comments that span several lines are skipped.
- Tests went from 16 to 25, none needing the speech models. The six edits came out identical before and after the parser changes were merged in.

**Still open.** A cough or throat-clear between two kept sentences would stay in the edit unreported (see Limits). None of the six had one: every voice-level sound without words was before the first line, after the last, or between a cut take and its re-read.

### 2026-10-07: first release

An 18.6-minute chapter read (44.1 kHz MP3, 21 restarts): 121 of 121 lines found, 274 words of false starts and asides removed, one two-take splice, 15.4 minutes out, and no restarts left on `verify`. A test pickups file replaced two of the six flagged lines. A 56-minute 48 kHz WAV ran in 8.3 minutes on two cores. Timings for both are under Speed and memory.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests cover script parsing, the alignment rules (restarts, fillers, asides, pickups, words a retake leaves out), the check for speech the voice detector missed, a full edit-and-master pass on synthetic audio (including ad-libs at the edge of a line and the comps switch), the true-peak ceiling on a bright signal and in the MP3, the WAV's bit depth, and the command line, including which chapters `batch` skips and what `--proof` writes. They don't need the speech models.

## Credits

- Speech recognition: [NVIDIA Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0), run with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0)
- Voice activity detection: [Silero VAD](https://github.com/snakers4/silero-vad) (MIT)
- MP3 encoding: LAME through [lameenc](https://github.com/chrisstaite/lameenc) (LGPL)
- Number words: [num2words](https://github.com/savoirfairelinux/num2words) (LGPL)
- ACX audio requirements: [ACX Audio Submission Requirements](https://help.acx.com/s/article/acx-audio-submission-requirements)
