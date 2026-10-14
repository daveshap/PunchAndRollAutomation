"""The manuscript comparison: every difference listed in full, with its line and its time."""
from punchroll.proof import compare, manuscript_markdown
from punchroll.text import build_lines

BOOK = build_lines([("heading", "Chapter 1"),
                    ("body", "The woman opened the door. She saw 2 dogs in the yard. Nobody spoke for a while."),
                    ("body", "Then the rain began. It did not stop until morning.")])


def heard(text, start=1.0, step=0.4, raw_offset=None):
    """Words 0.4 s apart and 0.3 s long; with raw_offset, each also has its time in a recording."""
    out = []
    for i, w in enumerate(text.split()):
        at = start + i * step
        word = {"text": w, "at": at, "end": at + 0.3}
        if raw_offset is not None:
            word |= {"raw": at + raw_offset, "raw_end": at + 0.3 + raw_offset}
        out.append(word)
    return out


EXACT = "Chapter one. The woman opened the door. She saw two dogs in the yard. Nobody spoke for a while. Then the rain began. It did not stop until morning."


def test_a_reading_that_matches_has_nothing_to_report():
    c = compare(BOOK, heard(EXACT))
    assert c["lines"] == 6 and c["lines_found"] == 6
    assert not c["pickups"] and not c["small"] and not c["not_found"] and not c["extra"]      # "2" and "two" are the same word


def test_a_small_difference_is_listed_with_its_sentence_and_its_time_like_any_other():
    said = EXACT.replace("The woman", "The women").replace("saw two dogs in the yard", "saw two dog in a yard").replace("did not stop", "never stopped")
    c = compare(BOOK, heard(said))
    assert [(r["line"], r["problem"], r["text"]) for r in c["pickups"]] == [
        (6, "read 'never stopped' for 'did not stop'", "It did not stop until morning.")]
    small = {r["line"]: r for r in c["small"]}
    assert small[2]["problem"] == "read 'women' for 'woman'" and small[2]["text"] == "The woman opened the door."
    assert abs(small[2]["at"] - (1.0 + 3 * 0.4)) < 1e-6                         # the time of the word itself, not of the line's start
    assert "read 'dog' for 'dogs'" in small[3]["problem"] and "read 'a' for 'the'" in small[3]["problem"]
    assert len(small[3]["differences"]) == 2 and small[3]["differences"][1]["at"] > small[3]["differences"][0]["at"]
    md = "\n".join(manuscript_markdown(c))
    assert "| 2 | 0:02.2 | read 'women' for 'woman' | The woman opened the door. |" in md


def test_every_small_difference_is_listed_however_many_there_are():
    book = build_lines([("body", " ".join(f"The dog number{i} ran." for i in range(60)))])
    c = compare(book, heard(" ".join(f"A dog number{i} ran." for i in range(60))))
    assert len(c["small"]) == 60 and "| 60 |" in "\n".join(manuscript_markdown(c))


def test_a_line_that_was_not_read_says_where_it_was_expected():
    said = EXACT.replace(" Nobody spoke for a while.", "")
    words = heard(said)
    c = compare(BOOK, words)
    assert [(r["line"], r["text"]) for r in c["not_found"]] == [(4, "Nobody spoke for a while.")] and c["lines_found"] == 5
    yard = next(w for w in words if w["text"] == "yard.")
    assert c["not_found"][0]["at"] == yard["end"]                              # straight after the last line that was read
    assert "Expected at" in "\n".join(manuscript_markdown(c))


def test_audio_the_manuscript_has_nothing_for_gets_its_own_row():
    said = EXACT.replace("Then the rain", "Sorry let me take that one more time please Then the rain")
    c = compare(BOOK, heard(said))
    assert [(r["count"], r["words"]) for r in c["extra"]] == [(9, "Sorry let me take that one more time please")]
    assert not c["pickups"] and not c["not_found"]


def test_an_edit_of_a_recording_reports_both_clocks():
    c = compare(BOOK, heard(EXACT.replace("door", "window"), raw_offset=30.0))
    r = c["pickups"][0]
    assert r["problem"] == "read 'window' for 'door'" and abs(r["raw"] - r["at"] - 30.0) < 1e-6
    md = "\n".join(manuscript_markdown(c))
    assert "| Line | Edited at | Recorded at | What differs | Manuscript |" in md and "| 2 | 0:03.4 | 0:33.4 |" in md


def test_short_additions_before_between_and_after_lines_are_all_reported():
    book = build_lines([("body", "Birds fly. Fish swim.")])
    c = compare(book, heard("Ready Birds fly. Sorry Fish swim. Done", raw_offset=20))
    assert [r["words"] for r in c["extra"]] == ["Ready", "Sorry", "Done"]
    assert all(r["count"] == 1 and r["raw"] == r["at"] + 20 for r in c["extra"])
    assert not c["pickups"] and not c["small"] and not c["not_found"]
    md = "\n".join(manuscript_markdown(c))
    assert "Ready" in md and "Sorry" in md and "Done" in md


def test_an_empty_manuscript_still_reports_every_heard_word():
    c = compare([], heard("Just testing"))
    assert c["extra"] == [{"at": 1.0, "raw": None, "count": 2, "words": "Just testing"}]


def test_long_manuscript_and_difference_text_are_not_truncated():
    line = " ".join(f"word{i}" for i in range(100)) + " LASTWORD"
    c = compare(build_lines([("body", line)]), [])
    md = "\n".join(manuscript_markdown(c))
    assert line in md
    c = compare([], heard(line))
    assert line in "\n".join(manuscript_markdown(c))
