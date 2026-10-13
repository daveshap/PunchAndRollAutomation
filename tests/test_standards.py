"""The standards check on made-up finished files, and the scorecard's ranking."""
import numpy as np
import soundfile as sf

from punchroll.cli import _seconds, main
from punchroll.scorecard import kept_pauses, rank_rows, scorecard_markdown
from punchroll.standards import acx_problems, check_files, measure_file, pvc_problems, standards_markdown

SR = 44100


def finished(path, pause_s=1.0, level=0.1, head_s=1.5, tail_s=3.0):
    """A file shaped like a master: room tone, 'speech' (a buzz), a pause, speech, room tone."""
    rng = np.random.default_rng(0)
    t = np.arange(4 * SR) / SR
    buzz = sum(np.sin(2 * np.pi * 130 * k * t + k) / k for k in range(1, 40))
    buzz = (level * buzz / np.sqrt(np.mean(buzz ** 2))).astype(np.float32)
    x = np.concatenate([np.zeros(int(head_s * SR), np.float32), buzz, np.zeros(int(pause_s * SR), np.float32), buzz,
                        np.zeros(int(tail_s * SR), np.float32)])
    x += rng.normal(0, 10 ** (-80 / 20), len(x)).astype(np.float32)
    sf.write(str(path), x, SR, subtype="PCM_16")
    return path


def test_a_file_at_level_passes_everything_but_the_format(tmp_path):
    f = measure_file(finished(tmp_path / "ch01.wav", level=0.115))
    assert -23 <= f["rms_db"] <= -18 and f["true_peak_db"] <= -3 and f["noise_floor_db"] < -60
    assert abs(f["head_s"] - 1.5) < 0.1 and abs(f["tail_s"] - 3.0) < 0.1 and abs(f["longest_pause_s"] - 1.0) < 0.1
    assert [p for p in acx_problems(f) if "MP3" not in p] == []
    assert len(pvc_problems(f)) == 1 and "MP3 at 192 kbps" in pvc_problems(f)[0]


def test_what_is_wrong_is_named(tmp_path):
    f = measure_file(finished(tmp_path / "loud.wav", level=0.3, pause_s=6.0, head_s=0.3))
    acx = " | ".join(acx_problems(f))
    assert "RMS" in acx and "room tone at the head" in acx and "over 5 s" in acx
    assert any("long pauses" in p for p in pvc_problems(f))


def test_the_set_is_judged_on_length_and_the_report_reads(tmp_path):
    res = check_files([finished(tmp_path / "a.wav"), finished(tmp_path / "b.wav")])
    assert len(res["files"]) == 2 and res["total_minutes"] < 1
    assert any("under the 30-minute minimum" in n for n in res["notes"])
    md = standards_markdown(res)
    assert "| a.wav |" in md and "## The set" in md and "help.acx.com" in md and "elevenlabs.io" in md


def test_standards_command_prints_and_writes(tmp_path, capsys):
    finished(tmp_path / "ch01.wav")
    out = tmp_path / "check.md"
    assert main(["standards", str(tmp_path / "*.wav"), "-o", str(out)]) == 0
    assert "# Standards check" in capsys.readouterr().out
    assert "ch01.wav" in out.read_text(encoding="utf-8")


def test_seconds_from_a_clock_time():
    assert _seconds("3:08.5") == 188.5 and _seconds("42") == 42.0 and _seconds("1:02:03") == 3723.0


def test_rank_rows_orders_by_the_average_rank():
    def row(name, clicks, cut, tone_bands, pesq=None):
        return {"name": name, "minutes": 5.0, "clicks": clicks, "room": 60.0, "cut": cut, "cuts": 1.0,
                "tone_bands": np.array(tone_bands, dtype=float), "pitch": 120.0, "pace": 140.0, "breaths": 3, "breaths_whole": 3,
                "pesq": pesq, "pesq_low": pesq, "lowest": []}
    rows = [row("clean", 1.0, 2.0, [0, 0, 0]), row("clicky", 9.0, 5.0, [0, 0, 0.3]), row("odd one out", 4.0, 9.0, [6, -6, 6])]
    rank_rows(rows)
    assert [r["name"] for r in sorted(rows, key=lambda r: r["order"])] == ["clean", "clicky", "odd one out"]
    assert rows[2]["tone"] > rows[0]["tone"]
    md = scorecard_markdown(rows)
    assert md.index("| clean |") < md.index("| clicky |") < md.index("| odd one out |") and "Listener" not in md.split("\n")[4]


def test_kept_pauses_leaves_out_a_pause_the_edit_touched():
    words = [{"text": w, "start": s, "end": s + 0.3} for w, s in (("one", 1.0), ("two", 2.0), ("three", 5.0), ("four", 6.0))]
    edl = [{"raw_in": 0.8, "raw_out": 2.5, "clean_in": 1.5, "clean_out": 3.2}, {"raw_in": 4.8, "raw_out": 6.5, "clean_in": 3.9, "clean_out": 5.6}]
    spans, gaps = kept_pauses(words, edl)
    assert len(spans) == 4
    assert [(round(a, 2), round(b, 2), round(c, 2)) for a, b, c in gaps] == [(1.3, 2.0, 2.0), (5.3, 6.0, 4.4)]   # not the pause across the cut
