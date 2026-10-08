# Recording for punchroll

## The one habit

When you slip, keep recording. Pause for a breath, then start the sentence again from its beginning.

- A clean pause before the restart (half a second or more) gives the cleanest splice.
- Restarting at the start of a clause works too, but the start of the sentence is safest.
- No need to say "sorry" or "again". Fillers and asides are cut, but silence cuts cleaner.
- If a whole paragraph went wrong, just read the paragraph again. The last complete reading of every line wins.

## Before each session

- Same microphone, distance, room, interface gain, and processing every time. Lines recorded on different days get spliced together, so consistency matters more than any one setting.
- Record WAV, 24-bit, 44.1 or 48 kHz, mono.
- Aim for peaks around −12 to −6 dBFS. Don't limit or compress on the way in; mastering handles loudness.
- Start each file with about five seconds of silence. punchroll finds room tone in your pauses anyway, but a clean stretch at the start helps.

## What goes in one file

- One chapter per file is simplest. If a chapter takes several sittings, record several files and list them in the order you made them.
- Read headings exactly as they're written in the script.
- Stay on script. If you change wording on purpose, change the script too; otherwise the change shows up as a pickup. If you reword often, run with `--no-comps` so an earlier take is never spliced over your rewording.

## Pickups

1. Open the **Pickups** table in the chapter's report. Each row gives the line, where it is in the edited file, and what differs. The recognizer can mishear too, so listen before you re-record.
2. Record the lines you want to fix into one new file, in any order, with the same setup. Read each as a full sentence and leave a pause between them.
3. Run `punchroll clean` again with the original recording(s) and the pickups file last. The pickups replace the old readings, with their level matched to the first file.

## The script

- Make a narration version of the manuscript that says exactly what you'll say: spoken headings ("Chapter One", "Part One"), and nothing you'll skip. Footnotes, tables, images, and links are removed automatically.
- Export it to Markdown, for example `pandoc manuscript.docx -t markdown --wrap=none -o narration.md`, or use the .docx directly after `pip install python-docx`.
- Run `punchroll lines --script narration.md --from "Chapter 3" --to "Chapter 4"` to see exactly what a chapter will be matched against.
