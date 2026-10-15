"""Clicks struck by the method, and the check of a mark-up against its transcript."""
from types import SimpleNamespace

import pytest

from punchroll import markfix

HEAD = "# take.wav\n\n<!--\nMark-up: what is not struck is what the finished file holds.\n-->\n\n"
TRANSCRIPT = HEAD + (
    "0:01.0  The system receives a reward. {0.40} {sound 0.02 -29} {0.20} {sound 0.30 -35} {0.10}\n\n"
    "0:04.0  It learns {0.16} from light. {0.50}\n\n"
    "0:06.0  Then it acts. {1.90}\n\n"
    "0:09.0  Done.\n"
)


def fixed(markup, rows=None, pieces=None):
    m = markfix.MarkedUp(markup, TRANSCRIPT)
    changes = markfix.strike_short_sounds(m)
    if rows is not None:
        changes += markfix.strike_traced(m, rows, pieces)
    return m.render(), changes


def line(text, stamp):
    return next(l for l in text.splitlines() if l.startswith(stamp))


def test_a_click_left_in_is_struck_with_its_pauses_and_the_gap_kept():
    out, changes = fixed(TRANSCRIPT)
    assert line(out, "0:01.0") == ("0:01.0  The system receives a reward. ~~{0.40} {sound 0.02 -29} {0.20}~~ {0.62} "
                                   "{sound 0.30 -35} {0.10}")
    assert len(changes) == 1


def test_a_click_struck_alone_gets_its_pauses_struck_too():
    markup = TRANSCRIPT.replace("{0.40} {sound 0.02 -29} {0.20}", "{0.40} ~~{sound 0.02 -29}~~ {0.20}")
    out, _ = fixed(markup)
    assert "~~{0.40} {sound 0.02 -29} {0.20}~~ {0.60} {sound 0.30 -35}" in out


def test_declick_changes_nothing_the_second_time_and_leaves_hand_written_pauses_alone():
    once, _ = fixed(TRANSCRIPT)
    twice, changes = fixed(once)
    assert twice == once and changes == []
    by_hand = TRANSCRIPT.replace("{0.40} {sound 0.02 -29} {0.20}", "~~{0.40} {sound 0.02 -29} {0.20}~~ {0.50}")
    out, changes = fixed(by_hand)
    assert out == by_hand and changes == []


def pieces_for(transcript):
    """One piece per transcript token, with a hidden quiet after the first word, as a recording would have."""
    out = []
    m = markfix.MarkedUp(transcript, transcript)
    for k, tok in enumerate(m.source):
        kind = "quiet" if markfix.PAUSE.match(tok) else ("sound" if tok.startswith("{sound") else "word")
        out.append(SimpleNamespace(kind=kind, shown=True, text=tok))
        if k == 0:
            out.append(SimpleNamespace(kind="quiet", shown=False, text=""))
    return out


def test_a_traced_click_in_a_pause_strikes_that_pause_and_writes_it_again():
    pieces = pieces_for(TRANSCRIPT)
    k = next(i for i, p in enumerate(pieces) if p.text == "{0.16}")
    out, changes = fixed(TRANSCRIPT, [{"piece": k, "where": "inside a pause", "context": "learns *{0.16}* from"}], pieces)
    assert line(out, "0:04.0") == "0:04.0  It learns ~~{0.16}~~ {0.16} from light. {0.50}"


def test_a_traced_click_in_a_breath_takes_the_breath_and_its_pauses():
    markup = TRANSCRIPT.replace("{0.40} {sound 0.02 -29} {0.20}", "~~{0.40} {sound 0.02 -29} {0.20}~~ {0.62}")
    pieces = pieces_for(TRANSCRIPT)
    k = next(i for i, p in enumerate(pieces) if p.text == "{sound 0.30 -35}")
    out, _ = fixed(markup, [{"piece": k, "where": "inside a sound", "context": "*{sound 0.30 -35}*"}], pieces)
    assert line(out, "0:01.0").endswith("~~{0.40} {sound 0.02 -29} {0.20}~~ {0.62} ~~{sound 0.30 -35} {0.10}~~ {0.40}")


def test_a_click_inside_a_word_is_left():
    pieces = pieces_for(TRANSCRIPT)
    k = next(i for i, p in enumerate(pieces) if p.text == "learns")
    out, changes = fixed(TRANSCRIPT, [{"piece": k, "where": "inside a word", "context": "*learns*"}], pieces)
    assert line(out, "0:04.0") == line(TRANSCRIPT, "0:04.0")


def test_check_lists_hesitations_long_gaps_and_short_sounds():
    result = markfix.check(markfix.MarkedUp(TRANSCRIPT, TRANSCRIPT))
    assert result["clicks"] == ["0:01.0  {sound 0.02 -29}"]
    assert result["inside"] == ["0:04.0  learns {0.16} from"]
    assert result["long"] == ["0:06.0  acts. ... 1.90 s ... Done."]


def test_a_changed_word_is_refused():
    with pytest.raises(ValueError, match="only ~~ marks and pause lengths may differ"):
        markfix.MarkedUp(TRANSCRIPT.replace("learns", "learned"), TRANSCRIPT)
