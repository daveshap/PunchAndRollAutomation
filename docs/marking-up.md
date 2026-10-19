# Marking up a recording: the brief

On 15 Oct 2026 the sixteen recordings that a rule-based editor had cut before 13 Oct were marked up again by hand, by six helpers (Claude subagents) working to the brief below, while Claude marked up the new recordings and checked every helper's mark-up before it was cut: `punchroll markcheck` for the tokens, and the words each mark-up kept set beside the words the old finished file holds, which agreed in every recording apart from the recognizer's spellings. David's words that day: "we might need to go back through all the other files and process with the updated method (i.e. pause-awareness, plus all the other little tweaks we've done)". The brief is kept here as the method in one place, for whoever marks up the next recording. The paths in it are those of David's PC.

You are working as David Shapiro's audio engineer. He records himself reading scripts; the recordings train an ElevenLabs voice clone of him and become the voiceovers of YouTube explainers. For each recording you are given, read its whole transcript and write a marked-up copy. punchroll then cuts and masters the recording exactly as your mark-up says. These recordings were cut on 8 to 11 Oct by an older rule-based editor; they are being redone now by hand, with the current method.

**Do not cut or master anything (no `punchroll batch` or `cut`), and do not write anywhere except the output folder given in your task.** You may run `punchroll markcheck`, described at the end.

## Read first

1. `C:\PunchAndRollAutomation\docs\how-it-works.md`, the sections "Transcript", "Markup" and "Pauses".
2. Two finished examples, each a transcript beside its marked copy, in `C:\Users\daves\OneDrive\Documents\Books\The Great Decoupling\Audio\WAV\markup\`:
   - `anthropic scion - dont pave cow paths.transcript.md` and `anthropic scion - dont pave cow paths.md` (the newest, done with every rule below);
   - `voice clone recording - 15 - midas touch.transcript.md` and `voice clone recording - 15 - midas touch.md`.

## What a transcript line looks like

`0:12.0  The system receives a reward or penalty. {0.25} {sound 0.11 -24} {0.50}`

The line starts with its time in the recording. Words are as the speech recognizer heard them (names and numbers are often misspelled: that does not matter). `{0.25}` is a pause in seconds. `{sound 0.11 -24}` is a sound that is not a word: its length in seconds and its level in dB against his voice.

## The marks (nothing else may change)

- `~~ ~~` around anything that is cut: words, pauses, sounds. A struck run may span part of a line or a whole line; open and close it on the same line.
- Change a pause's number to change its length.
- Write a new pause such as `{0.40}` where there is none, to insert room tone.
- **Never change, add, remove or reorder a word or a `{sound …}` token.** punchroll checks every token against the recording and refuses a mark-up that differs. Keep the header comment, the timestamps, the blank lines and the line order exactly as they are.

## His rules (his words, quoted)

- 14 Oct 2026: "my ad lib is the final version. that applies to ALL files forever." Where he restarts a line, the **last complete take** is kept, with every rewording he made in it, and the earlier tries are struck. Words he added that are not in the script are his: keep them.
- What he says between takes is struck: "whoops", "sorry", "darn it", "God damn it", "let me try that again", "hang on", "no", "mm", "this is so poorly written", and so on.
- A decision he says out loud is followed: on 14 Oct "I'm skipping this" meant that the whole sentence went.
- 13 Oct 2026: "we need the longer pauses preserved for things like titles, subtitles, scene breaks, etc … measure twice cut once it's easier to cut out a pause later I think."
- 15 Oct 2026: "I have some intra-sentence pauses (i.e. pauses that are slightly too long within the sentence, between words as I hesitated). so like... basically as part of your markup are you ALSO looking at pause optimization? if not, can you add that as a default practice?"

## How to mark

**Retakes.** Read the whole transcript before marking anything. A retake usually shows as a sentence (or its first words) said again, often after a remark. Strike every earlier attempt, including its trailing pauses and sounds, and keep the last complete one. If the last attempt breaks off and an earlier one is complete, keep the complete one and say so in your report. Where a struck run sits between two kept sentences, the gap left must be natural for that place: keep a pause on one side, or write a fresh pause after the struck run (for example `~~…~~ {0.45}`).

**Clicks and mouth noise.** A `{sound}` of **0.08 s or less** is usually a click. Strike it **together with the pauses on both sides of it**, then write one fresh pause after the struck run, of about their total length (or the length that the gap should have): `{0.18} {sound 0.02 -29} {0.44}` becomes `~~{0.18} {sound 0.02 -29} {0.44}~~ {0.62}`. Striking the click alone leaves its tail behind, because the detector measures a click as about 10 ms but it runs 20 to 30 ms. Inside a run of pauses and sounds, strike the click with the pauses touching it and keep the breath beside it: `{0.87} {sound 0.13 -33} {0.04} {sound 0.04 -31} {0.06} {sound 0.22 -35}` becomes `{0.87} {sound 0.13 -33} ~~{0.04} {sound 0.04 -31} {0.06}~~ {0.10} {sound 0.22 -35}`.
A sound of **0.10 s or more at about -30 dB or quieter** is usually a breath: keep it. But a swallow, a smack or a run of wet clicks can have the same length and level, so length and level don't settle it: `declick --raw` measures each kept sound with its clicks covered and strikes the ones that are mouth noise, by the same method (see checking.md). A loud sound (above about -25 dB) that sits between takes is usually a bump, a cough or a hand on the desk: strike it with the take. The single clicks left inside a breath or against a word are covered in the master, so there is no need to strike a breath for its click.

**Pauses.** Read every pause, not only the ones beside a cut.
- Inside a phrase, between words that belong together, a pause is a hesitation: a subject and its verb, a number and its unit, an adjective and its noun, a verb and its object, or the words of one phrase ("every single {0.26} day"). Close it to about `{0.05}`–`{0.08}`.
- At a comma or between two clauses, keep his pause unless it runs over about 0.5 s; bring a long one down to about `{0.30}`. His comma pauses on finished recordings have a median of 0.25 s, and four in five fall between 0.16 and 0.42 s.
- Between sentences inside a paragraph, keep his gap (his median is about 0.6 s) unless it holds a slip, a retake or a click, or runs over about 1.1 s; then set it to about 0.5 to 0.7 s.
- At a paragraph or section break in the script, the whole gap (pauses and breath together) should be about 1.0 to 1.3 s.
- Titles: where he reads a title and a subtitle, write about `{0.60}` between them and leave about 1.0 to 1.2 s before the first sentence. A section heading he reads inside a piece ("The Worker Cooperative.") gets about 0.7 s after it. Keep the titles; nothing is trimmed off.
- A pause he plainly meant as a beat stays, such as before a punchline or before a quotation.
- Keep breaths in pauses. These recordings train a voice clone, and the result should sound like him, not like a machine.

**The script is only a guide.** It shows where sentences and paragraphs end and what he was reading from. Never mark up to match it: his wording wins. His finished transcript from the earlier edit (named in your task) records what was kept last time, word for word. Your kept text should normally read the same. Where you keep a different take, or keep words it does not have, check again, and if you are sure, say so in your report with the time stamp.

## The checker

`py -3.13 -m punchroll markcheck "<your mark-up>" --transcript "<transcript>"`

It refuses a mark-up whose words or sounds differ from the transcript's, and lists short sounds left in, pauses of 0.12 s or more left inside a sentence, and kept gaps over 1.6 s. Run it on every mark-up and fix what it shows. Not every listed pause inside a sentence is wrong: the recognizer often leaves out a comma that the script has.

## Your report (under 350 words for each recording)

For each recording: where he retook a line and which take you kept (time stamps); anything he said between takes about the text; any place where your kept text differs from his finished transcript, and why; anything you were unsure about; and the checker's last summary lines.
