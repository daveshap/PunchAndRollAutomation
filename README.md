# PunchAndRollAutomation

Claude Code as David Shapiro's audio engineer for narration.

David records straight through. When he slips, he pauses and says it again. Claude transcribes the recording, reads the whole transcript, and marks it up: what is cut, what stays, and how long each pause is. `punchroll` cuts exactly what was marked, masters the result to ACX's numbers, and measures it.

The program makes no editing decisions. It has no script to match against and no rule for what counts as a retake, a filler, or a pause that is too long. Those calls are made by reading, the way an editor makes them. What this replaced, and why, is in the [field log](#field-log).

## Editing a recording

**1. Transcript.**

```bash
py -3.13 -m punchroll transcript "piece 12.wav"
```

This writes `markup/piece 12.transcript.md`: every word in order, the time each line starts, the length of every pause, and every sound in a pause that is not a word (a breath, a click, a cut-off syllable), with its length and its level against the voice.

```
3:11.7  Learning by trial and error. {0.75}

3:14.1  Instead of being shown the right answer, {0.27} the system tries actions and receives R D. {1.76}

3:21.5  Instead of being shown the right answer, {0.26} the system tries actions, {0.24} receives a reward or penalty, and gradually adjusts towards whatever earns more reward. {0.25} {sound 0.11 -24} {0.10} {sound 0.18 -36} {0.21}
```

**2. Mark-up.** Claude reads it and saves a marked copy as `markup/piece 12.md`:

- `~~struck through~~` is cut. Words, pauses and sounds are struck the same way.
- `{0.75}` is a pause in seconds. Changing the number changes the pause.
- `{0.60}` written where there was no pause puts one in.

What is not struck is what the finished file holds. Above, the second line is an abandoned take, so it is struck whole:

```
3:14.1  ~~Instead of being shown the right answer, {0.27} the system tries actions and receives R D. {1.76}~~
```

**3. Cut and master.**

```bash
py -3.13 -m punchroll cut "piece 12.wav" --markup "markup/piece 12.md" --config settings.toml
```

This cuts as marked, joins with short crossfades, masters, and writes `edited/piece 12.wav`, `.mp3`, `.report.md` (every cut and the pause left at it) and `.edit.json`. It first checks the marked file against the recording word for word and stops if they differ, so a slip in the mark-up can't move a cut. `--report-only` lists what the mark-up does and renders nothing.

**4. Read it back.** `punchroll transcript "edited/piece 12.wav"` gives the transcript of the finished file, to check that it says what was meant.

**A set of recordings.** A project file names them (see [examples/project.toml](examples/project.toml)):

```bash
py -3.13 -m punchroll batch voice-clone.toml
```

For each recording it writes the transcript if there is no mark-up yet, cuts and masters if there is, and leaves a finished one alone unless its recording, mark-up or settings changed since.

How each step works is in [docs/how-it-works.md](docs/how-it-works.md).

## Against a manuscript

When the audio has to follow a script word for word, punchroll sets the two side by side and lists every difference. This is a report. It never decides a cut.

```bash
py -3.13 -m punchroll verify "edited/ch01.mp3" --script book.md --from "Chapter 1" --to "Chapter 2"
py -3.13 -m punchroll batch book.toml --proof
py -3.13 -m punchroll cut "ch01.wav" --markup "markup/ch01.md" --script book.md --from "Chapter 1" --to "Chapter 2"
```

- **`verify`** proofs a finished file, whoever made it: it transcribes the file, compares it with the manuscript section, and measures it against ACX. It writes `name.verify.md` and `.json`, and no audio.
- **`batch --proof`** does that for every finished file a project lists. `--report-only` is accepted with it.
- **`cut --script`** adds the same comparison to the cut's own report, for the words the mark-up kept, with each time given twice: in the edited file and in the recording. In a project file, an entry that names its part of the manuscript (`from`, `to`, `lines`, or a `script` of its own) gets this automatically, and `batch --report-only` writes the reports without rendering audio.

The report is the same in all three:

| Section | What it lists |
|---|---|
| Pickups | Each line where what was read differs from the manuscript: the line number, the time of the word itself, what differs, and the manuscript's full sentence. |
| Small differences | Differences of an article, a plural, or a spelling the recognizer varies on. Listed in full in the same form, with nothing left out, because some of them are real misreads. |
| Not found | Manuscript lines with nothing read for them, each with the time where it was expected. |
| In the audio and not in the manuscript | Six or more words in a row that the manuscript has nothing for: a retake left in, an aside, an added sentence. |

The manuscript can be Markdown, plain text, or a Word file. Numbers are compared the way they are spoken ("1810s" and "eighteen tens", "$52,000" and "fifty-two thousand dollars", "World War II" and "World War two").

For David's own recordings none of this is used: his spoken words are the standard.

## What Claude goes by

David's instructions for the reading:

- His spoken words are the standard. The last take of each sentence stands, with whatever he added or reworded. A script, where there is one, is read beside the transcript; nothing is cut to make the audio match it. A job that has to follow a script word for word is a different instruction, given for that job.
- Cut the bad stuff: abandoned takes, false starts, chatter between takes, noises.
- "We need the longer pauses preserved for things like titles, subtitles, scene breaks."
- "Measure twice, cut once. It's easier to cut out a pause later." When it isn't clear, it stays, and Claude says so.
- A slip in what was said, one word for another, is reported, not patched.

## Mastering

−20 dB RMS, true peak at −3.5 dB or lower (ACX's limit is −3), high-pass at 70 Hz, 2:1 compression, 1.5 seconds of room tone at the head and 3 at the tail. Noise reduction follows Audacity's Noise Reduction effect and takes its three numbers; David's recordings run it at 20 dB, sensitivity 6, frequency smoothing 6, with the noise sample taken from the pauses. Output is a WAV at the recording's bit depth and a 44.1 kHz mono 192 kbps constant-bit-rate MP3, whose own peak is measured after encoding.

Every setting is listed in [examples/settings.toml](examples/settings.toml).

## Checking finished files

```bash
py -3.13 -m punchroll standards "edited/*.mp3"
py -3.13 -m punchroll scorecard voice-clone.toml
py -3.13 -m punchroll picture "edited/piece 12.wav" --at 3:08 --with "piece 12.wav" --with-at 3:14.5
```

- **`standards`** measures loudness, true peak, noise floor, room tone at each end, the longest pause, the format, and how far each file's tone sits from the rest, against ACX's requirements and ElevenLabs' guidance for voice-clone training audio. It also adds up the set: ElevenLabs asks for 30 minutes at the least and two to three hours for the best clone.
- **`scorecard`** is for choosing among recordings that all pass. Per recording: mouth clicks per minute, how quiet the room was, how much was cut, how far the tone is from the set's, pitch, pace, and how many breaths came through whole. `--listener` adds a trained model's estimate of how clean each file sounds.
- **`picture`** draws a spectrogram of a passage, with a second file underneath: the recording above the finished file shows what the edit and the mastering did.

What each measures, and what it can't tell you, is in [docs/checking.md](docs/checking.md).

## Set-up

```bash
pip install -e ".[all]"
py -3.13 -m punchroll models
```

On David's PC the package is installed into Python 3.13, so it runs as `py -3.13 -m punchroll`. The speech models (about 480 MB) go to `%LOCALAPPDATA%\punchroll`. `pip install -e ".[pictures]"` adds matplotlib for `picture`, and `".[listen]"` adds PyTorch for the scorecard's listener.

## Field log

Notes from real sessions: what was run, what it showed, and what changed in the code because of it. Newest first.

Every entry below the first describes the rule-based editor (`clean`, `verify`, the alignment, comps, pause ranges) that the first entry removed. They are kept as the record of what that approach got right and wrong. The transcription, the mastering, and the measuring commands they describe are still in use.

### 2026-10-13, third entry: the manuscript reports, put back and finished

**What happened.** The entry below removed the rule-based editor. It also removed, by mistake, everything that compared audio with a manuscript: `verify`, `batch --proof`, and the Pickups and Small differences reports. David had asked for the rules that decide cuts to go. He had not asked for the reports to go, and he had approved the engineer's four requests about them the same morning. They were neither kept nor built.

**What changed.**

- The comparison is back as a report only (`proof.py`): it sets the words in the audio beside the manuscript's lines and lists what differs. It decides nothing about a cut.
- *Small differences are listed in full.* Each has its line number, the time of the word, what differs, and the manuscript's sentence, exactly like a pickup. The list is no longer one run-on line, and no longer stops at forty.
- *Times are the word's own,* not the start of its line. A line with several differences gives each its time.
- *"Not found" lines say where they were expected:* the end of the last line read before them.
- *The proof report and the cut report are the same report.* Both show the manuscript's line. `verify` and `batch --proof` proof finished files; `cut --script` adds the sections to a cut's report with both clocks, edited and recorded. `batch` accepts `--report-only`.
- Roman numerals in a manuscript ("World War II") are compared as the numbers they are read as.

**Run on real files.** Recordings 12 and 13, the first two finished from a marked-up transcript, were proofed against the script pieces they were read from. Recording 13: 78 of 80 lines found (the title and subtitle are not read aloud), 7 pickups and 5 small differences, each a rewording made on purpose or a spelling ("line" for "row", "it is" for "it's", "Agemalu" for "Acemoglu"). 52 tests.

**Still open.** The comparison is a plain word-for-word diff. A retake left in a finished file shows as words the manuscript has nothing for, not as a "restart".

### 2026-10-13, second entry: the rules come out

**What happened.** An audiobook engineer ran the code as it then stood over other narrators' books and sent seven points. Four were about the reports. Three were audio the editor should have left alone:

1. *An unscripted "uh" inside a character's dialogue was cut,* because fillers were always cut.
2. *A scene break's three-second pause came out at 1.1 seconds,* because the pause ranges knew sentences, paragraphs and headings and nothing else.
3. *"High above" from one sentence was set into another sentence read nine minutes earlier,* because a repeated phrase was taken for a retake however far back it reached. The same thing was reproduced on a made-up chapter.

Two days before, David's own recordings had gone the same way: three or more words he added were cut as an aside, and a sentence he reworded on the retake lost to the first take because the first take matched the script.

Each was a fixed rule meeting a case it didn't fit. Claude's first answer was more rules: a dearer price for a retake found far back, a pattern for scene-break marks, a switch for fillers. David's answer was to stop. Claude reads the whole transcript and decides every cut and every pause, and the program only carries that out.

**What changed.**

- Removed: the alignment and its costs (`align.py`), the last-take and ad-lib rules, comps and pause ranges (`edit.py`), script parsing (`text.py`), and the script comparison (`verify.py`), with the commands `clean`, `verify`, `lines` and `transcribe`. (The script parsing and the comparison should not have gone; the entry above puts them back.)
- Added: `pieces.py` lays the recording out as words, quiet, and the sounds between words. `markup.py` writes that as a transcript and reads the marked-up copy back. `cut.py` applies it. The commands are `transcript` and `cut`, and `batch` does both across a project.
- The scorecard reads an edit list saved beside each finished file (`name.edit.json`) instead of rebuilding the edit. The sixteen recordings finished before this each had theirs saved from the old editor, and each matched its finished file to within 0.01 seconds.
- `standards`, `scorecard`, `picture`, the transcription and the mastering are as they were. 37 tests.

**The first recording done this way.** Recording 11: 8.2 minutes, a glossary read with six abandoned takes. Reading the transcript found the six, among them one called off with "No, I don't like that" and one that trailed into "Uh uh", and two loud clicks in pauses (5 and 10 dB under the voice). Marked, cut and mastered, it is 7.4 minutes and passes ACX's figures. Its finished file transcribes to the same 998 words as the master the old editor had made from a hand-written text of what was said. The difference between the two is the pauses: here they are his own, and there they were trimmed to ranges.

**Still open.** Claude can't hear. A sound in a pause is judged by its length, its level and where it sits, so a breath kept or a click cut is a judgement worth a listen. A pickup recorded in a second file can't be moved into place by the mark-up, which keeps the recording's order.

### 2026-10-13: a word added where a retake begins

**The job.** The item left open on 11 October. A general-purpose technology, says the script, "has three features. It's pervasive, spreading across many sectors. It keeps improving over time." The reader said: "...three features. First, it's pervasive, spreading across many sectors. Second, it keeps spawning, no, sorry. Second, it keeps improving over time." The edit kept "First," and cut the last "Second,", so the finished audio counted "First, ... And third, ...".

**What it showed.**

1. *The rule for added words looked only between two kept lines.* "First," sat between two lines that were both kept. The last "Second," had a cut word before it, which classed it as part of a re-read whatever the pauses around it.
2. *The same thing happens at the end of a sentence.* Another recording of that day has "And AI hasn't even entered its golden age yet." and "a national fund that pays every citizen dividends." Each added word ran straight on from its sentence. The next sentence was then started, abandoned, and read again, and the added word went out with the abandoned take.
3. *The pauses tell an added word from the end of an abandoned take.* In the sixteen recordings the edit picks up after a cut 128 times. By the recognizer's word times, 121 of those come a second or more after the last cut word and 125 half a second or more. Of the three that come sooner, one is a stumble with no pause ("with c, the, with the coalitions") and two follow a stray sound. So an unscripted word that runs on from the cut take belongs to it, and one that follows a pause and runs into the retake opens the retake. A filler between two words is not a pause: "no, sorry, that's wrong" is all chatter.
4. *This reader calls a take off with "no".* Ten times in the sixteen recordings ("No, sorry.", "No, that's wrong.", "No, hang on."). Once it ran straight into the next attempt ("...isn't immune. No, even our..."), which is where an added word would be.
5. *A retake that rewords its first word is taken to start at its second.* "It's the bedrock arrangement of civilization" was read again as "It is the bedrock arrangement of civilization". The alignment explains "It is" as two unscripted words in front of a retake that starts at "the", which costs a little less than a misread, so the first take's "It's" stays as the last reading of that word. Keeping "It is" as an added word there would have put "It's It is" in the finished audio.
6. *The case that started this only just passes.* The pause between the last "Second," and "it" is 0.244 seconds, against a limit of 0.25.

**What changed.**

- `edit.py`: the rule for ad-libs at the edge of a line also looks at unscripted words beside a take that was cut. One or two of them are kept when they run straight on from, or into, a kept word (the same 0.25 seconds and the same two-word limit), provided they stand clear of the cut take: walking from them toward it, a pause of 0.25 seconds or more comes before any cut word, fillers and stray sounds aside. They must begin or end their line, so a retake that picks up partway through a line is left as it was. "No" is never kept this way.
- Nor is a word that says the line's own first or last words again. That is a false start ("The— The end comes."), and at the first and last lines of a script the alignment takes one for chatter instead of a restart. None of the sixteen recordings has one there. It turned up when random readings were run through the old and the new code side by side.
- The sixteen recordings were rebuilt. As they were edited, twelve against the written script and four against the reader's own wording, 111 runs of unscripted words sit beside a cut take, 75 of them one or two words long, and no edit list changed. Set against the written script instead, the four loose recordings now keep "Second,", "yet." and "dividends.", and nothing else differs. With comps on the result is the same. 62 tests.

**Still open.** The retake that rewords its first word (item 5) is edited as before: the earlier take's first word is kept and the retake's own opening is cut. A stray word that follows a pause and runs straight into a retake is kept as an added word, unless it is "no". A word added in the same breath as the take being abandoned is cut with it. And a reader who leaves a beat after "Second," loses it: `adlib` is the setting to raise.

### 2026-10-11: four recordings read loosely, two of them in the rain

**The job.** Four new recordings of 7 to 10 minutes. The reader now departs from the script on purpose: added words, added sentences, sentences reworded between takes. Two were recorded while it rained. Comps off, noise reduction on. With these the set is sixteen recordings, 2 h 21 min, meant as training audio for a voice clone, so the questions were whether his wording survived, whether the rain did, and how the set stands against what ACX and ElevenLabs ask for.

**What it showed.**

1. *Added wording was cut in three ways, and the report showed none of them as a loss.* Three or more added words are an aside by design ("can be useless or even dangerous"). A word added at the start of a retaken sentence ("Second, it keeps improving") went out with the abandoned take before it, because its neighbour was a cut word. And a sentence reworded on the retake lost to the first take, which matched the script: "We haven't seen what the robots will do" was kept as written, and the retake's new words ("even begun to", "be capable of") were cut out of it as asides. The cuts list called all of these asides or re-reads.
2. *A check that doesn't use the script finds them.* A retake says the abandoned words again, so they turn up in what the edit keeps straight after the cut. Words that don't are either chatter or something lost. Run over all sixteen recordings, it showed the four new ones losing wording and the twelve earlier ones losing none: all 105 of their cut stretches were retakes, false starts, or chatter.
3. *What fixed the four* was giving punchroll the reader's own wording to follow: a text file per recording holding his last take of every line. Every line was then found, the cuts were retakes and chatter only, and `verify` found nothing but the recognizer's spellings.
4. *The rain reached the microphone and one number hid it.* The room in the pauses was 9 to 10 dB up from 140 Hz to 4 kHz, while the noise floor, the quietest half second, still read as a quiet room. Minute by minute the room's level rose and fell with the weather. After noise reduction the pauses sat near −85 dBFS and the reader could hear the rain only because he knew it was there.
5. *Noise reduction decides what happens to breaths.* Where the room's hiss was close to the level of a quiet breath, the breath was thinned or cut off at its start: 55 of 180 came through whole in the ten recordings made with a hissier chain. In the six made since, 103 of 108 did, at about 32 dB under the voice. Audiobook practice is to leave breaths in and never half cut one.
6. *Clean pauses show mouth clicks.* About five a minute stood alone in the pauses within 30 dB of the file's level, usually just before the breath that leads into a sentence. Noise reduction leaves them and takes away what used to cover them.
7. *Two trained listener models were tried and neither can rank good narration.* torchaudio's SQUIM opinion-score model gave 4.99 out of 5 to all sixteen files, and to copies spoiled with audible hiss, echo, clipping and clicks. Its objective model reacted to hiss and clicks, not to echo or clipping, and put all sixteen between 3.86 and 4.12 on a 4.5 scale.
8. *ElevenLabs asks for ACX's numbers.* Its guide to Professional Voice Cloning gives −23 to −18 dB RMS with a true peak of −3 dB, recommends MP3 at 192 kbps, and wants two to three hours. All sixteen files pass both.

**What changed.**

- Every cut now carries the words in it that are not said again (`edit.not_said_again`, `unsaid` in the JSON report), and the Markdown report lists them under "Cut and not said again", in capitals.
- `punchroll standards` checks finished files against ACX and ElevenLabs without transcribing them (`standards.py`).
- `punchroll scorecard` scores a project's finished chapters side by side (`scorecard.py`), with the measures in `measure.py`: mouth clicks, pauses, the room and the room minute by minute, tone by octave, pitch, and what became of each breath. `--listener` adds the SQUIM objective estimate (`listen.py`).
- `punchroll picture` draws a spectrogram of a passage, with a second file underneath (`picture.py`).
- [docs/checking.md](docs/checking.md) says what each measures and what it can't tell you. 57 tests.

**Still open.** A word or two added at the start of a retaken sentence is still cut. It now shows in the new section. Nothing removes mouth clicks. The scorecard's order weighs its measures equally, which they aren't.

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
