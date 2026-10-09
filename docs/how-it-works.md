# How it works

`punchroll clean` runs six stages. Everything but the speech model is plain numpy and scipy.

## 1. Transcribe

Silero VAD finds the stretches of speech. Neighboring stretches are grouped into chunks of up to 20 seconds, because a short phrase decoded on its own can come back empty while the same words decoded with their neighbors don't. Each chunk is transcribed by NVIDIA Parakeet TDT 0.6B v2 (int8 ONNX, through sherpa-onnx), which gives a timestamp for every token. Tokens are joined into words; punctuation is attached to a word without stretching its end time.

The editor treats whatever lies between two recognized words as a pause and keeps it, so speech that goes unheard would stay in the edit. Two checks guard against that:

- **Sound the detector left out.** The detector sometimes starts a stretch late, ends one early, or misses a short phrase or a muttered aside between two pauses. Any sound that stays within 25 dB of the voice's level for 0.15 seconds or more, and comes within 15 dB of it, is added to the detector's stretches. Breaths and clicks fall short of that. In a room too noisy to tell the voice from the background by level, the detector's stretches are used as they are.
- **A stretch that comes back empty.** The recognizer can drop a short stretch at the end of a long chunk. A stretch with no words is decoded again on its own.

Every finished chunk is written to the transcript cache immediately, so an interrupted run resumes where it stopped, and a finished transcript is reused whenever the same recording is edited again.

## 2. Align, allowing restarts

Script and transcript are reduced to the same tokens: lowercase, accents removed, dashes and other punctuation treated as spaces, numbers spelled out the way they're read (years, decades, ordinals, percentages, money, clock times), and the recognizer's `<unk>` (a sound it can't spell) dropped. Compounds are reconciled in both directions ("ChatGPT" vs "chat GPT", "cow paths" vs "cowpaths").

The transcript is then consumed in order while a pointer moves through the script. Each move has a cost, in tenths:

| Move | Meaning | Cost |
|---|---|---|
| match | the spoken word is the script word | 0 |
| near match | toward / towards, assistant / assistants | 3 |
| substitution | a different word in its place | 11 |
| insertion | a word not in the script | 10 |
| filler | um, uh, sorry, okay | 4 |
| edge insertion | chatter before the first or after the last word | 6 |
| deletion | a script word that wasn't read | 10 |
| restart | the pointer jumps back to any earlier word | 9 |
| skip | the pointer jumps forward | 40 |

The cheapest path through all of the spoken words is found exactly by dynamic programming (integer costs, one int32 per spoken-token-by-script-token cell). Two choices in the table do most of the work:

- A restart costs less than one inserted word, so a repeated word, phrase, sentence, or paragraph is explained as a restart rather than as extra words.
- A substitution costs a little more than an insertion, so the stray word in front of a restart ("the office workers of the eighteen— the office workers of the 1980s") is explained as an aside and cut, not passed off as a misread of the next word.

Where a new recording starts (a pickup file, the next session), the pointer may jump anywhere at no cost, and after the last recording it may jump to the end. That's what lets a pickup recorded after the chapter replace the line it re-reads.

## 3. Keep the last take

For every script word, the last spoken word aligned to it wins. Tokens it replaces are cut ("re-read later"). Then:

- A word that a later take read straight past is cut with the rest of the earlier take. If the first take had "and a truck driver" and the retake has "and truck driver", the first take's "a" is not set into the middle of the retake; the report lists the line as missing that word. The same holds when the recognizer misses a short word in the retake: the retake stays in one piece. A take that stops partway and moves on still replaces only the words it re-read.
- A misread word just before a mid-line restart, which the restart didn't re-read, is dropped: it's what the reader stopped to fix.
- Inserted words are kept only as short ad-libs (one or two words): inside a kept stretch of a single line, or at the edge of a line when they run straight on from the kept word beside them, with less than 0.25 seconds between ("until they were cheap enough.", "And groceries don't fall."). Cutting those would mean cutting where there is no pause. Fillers, asides that stand apart between lines, and anything outside the text are cut.

**Comps.** If the last take of a line still differs from the script and an earlier take read that part correctly, the line is assembled from the two, split at a word boundary where both takes had a natural pause of at least 0.12 seconds. It's used only when it reduces the number of real differences. If you reword lines on purpose as you read, turn comps off (`--no-comps`, or `comps = false` in the settings): the last take of every line is then kept whole, and the rewording is only listed in the report.

## 4. Rebuild the pauses

Recognizer word times can swallow the silence after a word, so pauses are measured from the audio: 10 ms energy frames, a noise floor estimated from non-speech frames, and "quiet" defined as less than 12 dB above that floor.

Kept words are grouped into pieces: runs of consecutive recorded words within one line. Between pieces:

- **Nothing was cut, and the pause is in range:** left exactly as recorded, breaths included.
- **Nothing was cut, but the pause is out of range:** quiet is removed from the middle of the longest quiet stretch (mouth clicks under 60 ms are bridged), or room tone is added in its middle.
- **A take was cut:** the end of the earlier piece and the start of the later one are trimmed to their quiet edges, and the gap is rebuilt with room tone to a target length.

Default ranges, in seconds (min, max, target when rebuilt):

| Between | Range | Rebuilt |
|---|---|---|
| sentences in a paragraph | 0.30 to 1.10 | 0.55 to 0.90, from the original pause |
| paragraphs | 0.80 to 1.70 | 1.20 |
| "Chapter One." and what follows | 0.80 to 1.50 | 1.00 |
| a heading and body text | 1.50 to 2.50 | 2.00 |
| two headings | 1.00 to 2.00 | 1.50 |
| body text and the next heading | 1.80 to 3.00 | 2.20 |
| pieces of one sentence | | 0.12 to 0.45, from the original pause |
| head and tail of the file | | 1.5 and 3.0 |

Room tone is taken from the recording itself: half-second stretches with no speech, near the 30th percentile of their levels (typical, not the quietest), with the fewest clicks, crossfaded together. Every join in the output is an 8 ms equal-gain crossfade.

## 5. Master

1. Normalize to −22 dB RMS.
2. Second-order high-pass at 70 Hz.
3. Compressor: RMS detector on 10 ms windows, −26 dB threshold, 2:1, 10 ms attack, 150 ms release.
4. Look-ahead limiter (6 ms) with a true-peak ceiling of −3.5 dB, and the gain searched so the result lands at −20 dB RMS. The limiter works from the waveform's level between samples (4x oversampled), not from the samples alone: on a bright or sibilant voice the two differ by 2 dB or more, and a limiter that only watches samples lets the true peak through. ACX's limit is −3 dB; the half decibel is room for their meter to read a little higher than this one.
5. If the noise floor (quietest half second) is still above −62 dB, gentle stationary noise reduction using the room tone as the noise profile, then re-level.

The WAV master is written at the bit depth the recording came in at (16 bits at least, 24 at most; 16-bit output is dithered). The MP3 is resampled to 44.1 kHz if needed and encoded, then decoded again and measured: if resampling or the encoder pushed its true peak over the ceiling, it is encoded again slightly lower.

RMS, true peak (of the WAV and of the MP3), and noise floor are reported against ACX's limits. The peak passes on the true peak, not on the highest sample.

## 6. Report and verify

The report lists:

- **Pickups:** lines whose kept reading still differs from the script, beyond articles, plurals, and spellings the recognizer varies on (those are listed separately as small differences).
- **Cuts:** every removed stretch, with the words and the reason.
- **Pause edits** and the **edit decision list:** for each kept stretch, the source file and times and where it landed in the edited file.

`punchroll verify` re-transcribes the finished file from scratch and runs the same alignment. On a clean edit it finds no restarts, and every remaining difference is either a known pickup or the recognizer mishearing.
