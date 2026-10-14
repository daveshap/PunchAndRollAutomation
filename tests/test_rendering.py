"""Exact timing and source evidence for adversarial editorial choices."""
from types import SimpleNamespace

import numpy as np
import pytest

from punchroll.config import Settings
from punchroll.cut import cut
from punchroll.markup import read_markup, write_transcript
from punchroll.pieces import Piece
from punchroll.report import write_reports

SR = 1000


def render(pieces, text, *, head=0, tail=0, audio=True):
    n = round(max((p.b for p in pieces), default=0) * SR)
    x = np.linspace(0.1, 0.8, n, dtype=np.float32)
    room = SimpleNamespace(words=[], hop=5, db=np.full(n // 5, -60.0),
                           speech=np.zeros(n // 5, dtype=bool), floor=-60.0)
    result = cut(x, SR, room, pieces, read_markup(text, pieces),
                 Settings(head=head, tail=tail), render=audio, log=lambda *_: None)
    return x, result


def test_boundary_pauses_and_explicit_endpoint_quiet_have_exact_lengths():
    pieces = [Piece("quiet", 0, .1), Piece("word", .1, .3, "hello"), Piece("quiet", .3, .5)]
    _, result = render(pieces, "{0.010} hello {0.015} {0.007}", head=.02, tail=.03)
    assert len(result["audio"]) == 20 + 10 + 200 + 15 + 7 + 30
    assert result["kept"][0]["at"] == pytest.approx(.03)
    assert result["kept"][0]["end"] == pytest.approx(.23)
    assert sum(p["now_s"] for p in result["pauses"]) == pytest.approx(.032)
    _, struck = render(pieces, "~~{0.10}~~ hello ~~{0.20}~~")
    assert len(struck["audio"]) == 200
    assert struck["kept"][0]["at"] == 0


def test_insertions_before_first_and_after_last_piece_are_not_lost():
    pieces = [Piece("word", 0, .1, "hello")]
    _, result = render(pieces, "{0.003} hello {0.005}")
    assert len(result["audio"]) == 108
    assert result["kept"][0]["at"] == .003
    assert result["kept"][0]["end"] == .103
    assert [p["now_s"] for p in result["pauses"]] == pytest.approx([.003, .005])


def test_no_edge_floor_when_cutting_a_sound_and_both_surrounding_pauses():
    pieces = [Piece("word", 0, .1, "hello"), Piece("quiet", .1, .2),
              Piece("sound", .2, .3, level=-12), Piece("quiet", .3, .4),
              Piece("word", .4, .5, "world")]
    _, result = render(pieces, "hello ~~{0.10} {sound 0.10 -12} {0.10}~~ {0.001} world")
    assert len(result["audio"]) == 201
    assert result["kept"][1]["at"] - result["kept"][0]["end"] == pytest.approx(.001)
    assert result["pauses"][0]["asked_s"] == pytest.approx(.001)
    assert result["pauses"][0]["now_s"] == pytest.approx(.001)
    assert result["sounds"] == [{"piece": 2, "raw": .2, "raw_end": .3,
                                  "seconds": pytest.approx(.1), "level_db": -12,
                                  "kept": False, "at": None, "end": None}]


def test_a_one_sample_preserved_sound_survives_between_cuts():
    pieces = [Piece("word", 0, .1, "before"), Piece("sound", .1, .101, level=-20),
              Piece("word", .101, .2, "after")]
    x, result = render(pieces, "~~before~~ {sound 0.00 -20} ~~after~~")
    np.testing.assert_array_equal(result["audio"], x[100:101])
    assert result["sounds"][0]["at"] == 0
    assert result["sounds"][0]["end"] == .001
    assert [w["text"] for w in result["removed_words"]] == ["before", "after"]
    assert result["edl"] == [{"raw_in": .1, "raw_out": .101, "clean_in": 0, "clean_out": .001}]


def test_unedited_source_is_bit_identical_and_report_maps_source_samples():
    pieces = [Piece("word", 0, .1, "hello"), Piece("quiet", .1, .105),
              Piece("sound", .105, .11, level=-20), Piece("word", .11, .2, "world")]
    text = write_transcript(pieces, "sample.wav")
    x, result = render(pieces, text)
    np.testing.assert_array_equal(result["audio"], x)
    assert len(result["edl"]) == 1
    assert result["sounds"][0]["at"] == .105
    assert result["sounds"][0]["end"] == .11
    _, report_only = render(pieces, text, audio=False)
    assert report_only["audio"] is None
    assert {k: v for k, v in result.items() if k != "audio"} == {k: v for k, v in report_only.items() if k != "audio"}


def test_all_content_can_be_cut_and_only_chosen_room_tone_remains():
    pieces = [Piece("word", 0, .1, "hello")]
    _, result = render(pieces, "~~hello~~ {0.009}", head=.01, tail=.02)
    assert len(result["audio"]) == 39
    assert result["kept"] == []
    assert result["summary"]["words_cut"] == 1


@pytest.mark.parametrize("text", ["hello {", "hello ~", "hello {sound changed}"])
def test_corrupt_markup_is_not_silently_ignored(text):
    pieces = [Piece("word", 0, .1, "hello"), Piece("sound", .1, .2, level=-20)]
    with pytest.raises(ValueError):
        read_markup(text, pieces)


def test_long_room_tone_and_short_splices_do_not_share_fade_state():
    pieces = [Piece("word", 0, .1, "hello"), Piece("quiet", .1, .7), Piece("word", .7, .8, "world")]
    _, result = render(pieces, "{1.2} hello {2.0} world {1.3}")
    assert len(result["audio"]) == 1200 + 100 + 2000 + 100 + 1300
    assert np.isfinite(result["audio"]).all()


def test_quiet_only_cut_is_a_reported_pause_change(tmp_path):
    pieces = [Piece("word", 0, .25, "hello"), Piece("quiet", .25, .75),
              Piece("word", .75, 1, "world")]
    _, result = render(pieces, "hello ~~{0.50}~~ world")
    assert len(result["audio"]) == 500
    assert result["kept"][1]["at"] == result["kept"][0]["end"] == .25
    assert result["summary"]["pauses_changed"] == 1
    assert result["pauses"] == [{"raw": .25, "clean": .25, "was_s": .5,
                                  "asked_s": 0, "now_s": 0}]
    write_reports(tmp_path, "quiet-cut", result, "source.wav", "markup.md", None)
    report = (tmp_path / "quiet-cut.dry-run.report.md").read_text(encoding="utf-8")
    assert "pauses changed: 1" in report
    assert "## Pauses changed" in report
    assert "0.500 s | 0.000 s" in report


def test_cut_sound_retains_both_chosen_pauses_and_correct_source_mapping():
    pieces = [Piece("word", 0, .1, "hello"), Piece("quiet", .1, .2),
              Piece("sound", .2, .3, level=-12), Piece("quiet", .3, .45),
              Piece("word", .45, .55, "world")]
    x, result = render(pieces, "hello {0.10} ~~{sound 0.10 -12}~~ {0.15} world")
    assert len(result["audio"]) == 450
    assert result["kept"][1]["at"] == .35
    assert result["cuts"][0]["pause_s"] == pytest.approx(.25)
    assert result["pauses"][0]["now_s"] == pytest.approx(.25)
    assert result["summary"]["sounds_cut"] == 1
    assert result["summary"]["pauses_changed"] == 0
    assert result["edl"] == [
        {"raw_in": 0, "raw_out": .2, "clean_in": 0, "clean_out": .2},
        {"raw_in": .3, "raw_out": .55, "clean_in": .2, "clean_out": .45}]
    np.testing.assert_array_equal(result["audio"][110:190], x[110:190])
    np.testing.assert_array_equal(result["audio"][210:340], x[310:440])
