"""The finished transcripts: the reader's words, with the reference text's spelling where the words match."""
import json

import pytest

from punchroll import said

REFERENCE = """# The Price of Sunlight

## How solar power became cheap

In 1958, the Navy launched Vanguard 1: a satellite powered by the sun.

For decades after that, solar power stayed expensive (and niche).

# The Next Piece

Not read.
"""


def heard_text(text):
    return {"duration": 75.0, "words": [{"text": w, "start": 1.0 + k * 0.4, "end": 1.3 + k * 0.4}
                                        for k, w in enumerate(text.split())]}


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "script.md").write_text(REFERENCE, encoding="utf-8")
    (tmp_path / "edited").mkdir()
    (tmp_path / "edited/piece 06.mp3").write_bytes(b"finished")
    (tmp_path / "book.toml").write_text(
        'script = "script.md"\nout = "edited"\nspeaker = "David"\n'
        '[[chapter]]\nname = "piece 06"\ntitle = "The Price of Sunlight"\nrecorded = "8 Oct 2026"\n'
        'audio = "piece 06.wav"\nfrom = "The Price of Sunlight"\nto = "The Next Piece"\n', encoding="utf-8")
    spoken = ("The price of sunlight. How solar power became cheap. In nineteen fifty eight, the Navy launched "
              "Vanguard one, a satellite that was powered by the sun. For decades after that, solar powered "
              "stayed expensive and niche.")
    monkeypatch.setattr(said, "cached_words", lambda path, cache: heard_text(spoken))
    return tmp_path


def test_plain_punctuation_for_what_was_said():
    assert said.plain("It was a goal: an entire industry — built on it; and more (a lot more).") == \
        "It was a goal, an entire industry, built on it. And more, a lot more."
    assert said.plain("He had a point. (He always did.) the end") == "He had a point. He always did. The end"


def test_draft_then_build(project, capsys):
    toml = project / "book.toml"
    assert said.draft([toml], log=lambda *a: None) > 0
    dec_path = project / "said/piece 06.decisions.json"
    dec = json.loads(dec_path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no decision yet"):
        said.build([toml], log=lambda *a: None)
    for key, d in dec.items():
        if d["use"] is None:
            # the reader added "that was"; the recognizer heard "powered" for "power"
            d["use"] = "w" if d["sig"].startswith("power") else "s"
    dec_path.write_text(json.dumps(dec), encoding="utf-8")
    said.build([toml], log=lambda *a: None)
    text = (project / "transcripts/piece 06.md").read_text(encoding="utf-8")
    assert text.startswith("# The Price of Sunlight\n\nWhat David said on the finished recording \"piece 06\" (1:15), recorded 8 Oct 2026.")
    assert "In 1958, the Navy launched Vanguard 1, a satellite that was powered by the sun." in text
    assert "solar power stayed expensive, and niche." in text and "Not read" not in text
    combined = (project / "transcripts/All recordings.md").read_text(encoding="utf-8")
    assert combined.startswith("# What David actually said") and "## The Price of Sunlight" in combined


def test_a_decision_follows_its_difference_when_the_numbers_move(project):
    toml = project / "book.toml"
    said.draft([toml], log=lambda *a: None)
    path = project / "said/piece 06.decisions.json"
    dec = json.loads(path.read_text(encoding="utf-8"))
    sig_to_use = {d["sig"]: "s" for d in dec.values() if d["use"] is None}
    renumbered = {str(100 + k): {"sig": s, "use": u} for k, (s, u) in enumerate(sig_to_use.items())}
    path.write_text(json.dumps(renumbered), encoding="utf-8")
    assert said.draft([toml], log=lambda *a: None) == 0


GIVEN = """# Two Pipes

## A worked example

So let's stress-test the household. Rent doesn't fall. The car payment doesn't fall. Groceries don't fall.

Their skill was real. So is yours. A typical home uses $1,200 a year.
"""

SAID = ("So let's stress-test that household. Rent doesn't fall, the car payment doesn't fall, and groceries "
        "don't fall.\n\nTheir skill was real, and so is yours. A typical home uses $1,200 a year.")


def test_changes_lists_each_sentence_he_changed_with_his_words_marked(tmp_path):
    (tmp_path / "given.md").write_text(GIVEN, encoding="utf-8")
    (tmp_path / "reference.md").write_text(GIVEN, encoding="utf-8")
    (tmp_path / "edited").mkdir()
    (tmp_path / "edited/piece 03.mp3").write_bytes(b"finished")
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts/piece 03.md").write_text(
        f"# Two Pipes\n\nWhat David said on the finished recording \"piece 03\" (0:30).\n\n{SAID}\n", encoding="utf-8")
    (tmp_path / "book.toml").write_text(
        'out = "edited"\n[[chapter]]\nname = "piece 03"\nscript = "reference.md"\nwritten = "given.md"\n'
        "heading = 'Piece 3, \"Two Pipes\" (8 Oct)'\n", encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n\n<!-- counts:start -->\nold\n<!-- counts:end -->\n\nWritten by hand.\n\n"
                     "<!-- log:start -->\nold log\n", encoding="utf-8")
    assert said.changes([tmp_path / "book.toml"], notes, log=lambda *a: None) == 3
    text = notes.read_text(encoding="utf-8")
    assert "| Piece 3, \"Two Pipes\" (8 Oct) | 7 | 3 | 43 % |" in text      # the unread headings aren't counted
    assert "Written by hand." in text and "old log" not in text and "\nold\n" not in text
    assert "1. W: So let's stress-test ~~the~~ household.\n   S: So let's stress-test **that** household." in text
    assert "S: Rent doesn't fall, the car payment doesn't fall, **and** groceries don't fall." in text
    assert "W: Their skill was real. So is yours.\n   S: Their skill was real, **and** so is yours." in text
    assert "1,200" not in text.split("<!-- log:start -->")[1]                 # read as written: not a change


def test_marks_keep_punctuation_outside():
    assert said.marked("I braced for an uphill fight.", "I braced for an uphill battle.") == \
        ("I braced for an uphill ~~fight~~.", "I braced for an uphill **battle**.")
    assert said.marked("lost their livelihoods to machines—master weavers, travel agents.",
                       "lost their livelihoods to machines, master weavers, and travel agents.")[1] == \
        "lost their livelihoods to machines, master weavers, **and** travel agents."
