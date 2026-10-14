import json

from punchroll.report import removed_words_not_retained, write_reports


def result():
    return {
        "summary": {"raw_minutes": 2, "edited_minutes": 1, "cuts": 1, "words_cut": 2,
                    "words_heard": 4, "sounds_cut": 1, "pauses_changed": 0},
        "cuts": [{"raw": 1.0, "clean": 1.0, "seconds": 1.0, "pause_s": None,
                  "words": "many words " * 60 + "FINAL | <sound>"}],
        "pauses": [], "edl": [], "render_version": "test-renderer",
        "kept": [{"text": "two", "at": 1.0, "end": 1.2, "raw": 3.0, "raw_end": 3.2}],
        "removed_words": [{"text": "2", "raw": 1.0, "raw_end": 1.2},
                          {"text": "unique", "raw": 1.3, "raw_end": 1.5}],
        "sounds": [{"piece": 1, "raw": 1.5, "raw_end": 1.51, "seconds": .01,
                    "level_db": -20.0, "kept": False, "at": None, "end": None},
                   {"piece": 4, "raw": 3.5, "raw_end": 3.7, "seconds": .2,
                    "level_db": -30.0, "kept": True, "at": 1.5, "end": 1.7}],
    }


def test_report_preserves_full_cut_text_and_all_sound_evidence(tmp_path):
    res = result()
    data = write_reports(tmp_path, "chapter", res, "audio.wav", "markup.md", None)
    md = (tmp_path / "chapter.dry-run.report.md").read_text(encoding="utf-8")
    assert "many words " * 60 + "FINAL &#124; &lt;sound&gt;" in md
    assert "| 1 | cut |" in md and "| 4 | kept |" in md
    assert "| 0.010 | -20.0 |" in md and "| 0.200 | -30.0 |" in md
    assert "0:01.500 | 0:01.510" in md
    assert data["sounds"] == res["sounds"] and data["removed_words"] == res["removed_words"]
    assert [w["text"] for w in data["removed_words_not_retained"]] == ["unique"]


def test_edit_json_preserves_transcripts_and_sound_decisions(tmp_path):
    res = result()
    metrics = {"rms_db": -20, "true_peak_db": -3, "sample_peak_db": -3,
               "noise_floor_db": -70, "rms_ok": True, "peak_ok": True, "noise_ok": True}
    write_reports(tmp_path, "chapter", res, "audio.wav", "markup.md", metrics)
    data = json.loads((tmp_path / "chapter.edit.json").read_text(encoding="utf-8"))
    for key in ("sounds", "removed_words", "kept", "cuts", "render_version"):
        assert data[key] == res[key]
    assert data["removed_words_not_retained"][0]["unmatched_tokens"] == ["unique"]


def test_removed_word_audit_preserves_occurrences_and_reports_partial_normalization():
    removed = [{"text": "chat-gpt", "raw": 0, "raw_end": 1},
               {"text": "lost", "raw": 2, "raw_end": 3},
               {"text": "lost", "raw": 4, "raw_end": 5}]
    rows = removed_words_not_retained(removed, [{"text": "chat"}])
    assert [r["unmatched_tokens"] for r in rows] == [["gpt"], ["lost"], ["lost"]]
    assert [r["raw"] for r in rows] == [0, 2, 4]
