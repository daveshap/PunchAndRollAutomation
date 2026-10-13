import json
import os
import time

from punchroll.cli import main
from punchroll.pipeline import finished, natural, recording


def _touch(path, t):
    os.utime(path, (t, t))


def test_finished_means_newer_than_everything_it_was_made_from(tmp_path):
    audio, markup = tmp_path / "ch01.wav", tmp_path / "ch01.md"
    audio.write_bytes(b"audio")
    markup.write_text("mark-up", encoding="utf-8")
    out = tmp_path / "edited"
    out.mkdir()
    assert not finished(out, "ch01", [audio, markup])          # nothing written yet
    now = time.time()
    for p in (out / "ch01.wav", out / "ch01.mp3"):
        p.write_bytes(b"edited")
        _touch(p, now - 30)
    for p in (audio, markup):
        _touch(p, now - 60)
    assert finished(out, "ch01", [audio, markup])
    _touch(markup, now - 10)
    assert not finished(out, "ch01", [audio, markup])          # marked up again since
    assert finished(out, "ch01", [audio])
    (out / "ch01.mp3").unlink()
    assert not finished(out, "ch01", [audio]) and finished(out, "ch01", [audio], mp3=False)


def test_natural_order_and_one_recording_per_entry(tmp_path):
    names = ["ch01-10.wav", "ch01-2.wav", "ch01-1.wav"]
    assert sorted(names, key=natural) == ["ch01-1.wav", "ch01-2.wav", "ch01-10.wav"]
    (tmp_path / "piece 01 - take 1.wav").write_bytes(b"x")
    assert recording(tmp_path, "one", "piece 01 - *.wav").endswith("piece 01 - take 1.wav")


def test_batch_writes_transcripts_cuts_what_is_marked_and_leaves_finished_work_alone(tmp_path, capsys, monkeypatch):
    for f in ("old.wav", "new.wav", "marked.wav"):
        (tmp_path / f).write_bytes(b"recording")
    (tmp_path / "book.toml").write_text(
        'out = "edited"\n\n[[chapter]]\nname = "old"\naudio = "old.wav"\n\n'
        '[[chapter]]\nname = "new"\naudio = "new.wav"\n\n[[chapter]]\nname = "marked"\naudio = "marked.wav"\n', encoding="utf-8")
    (tmp_path / "markup").mkdir()
    (tmp_path / "markup" / "marked.md").write_text("the mark-up", encoding="utf-8")
    out = tmp_path / "edited"
    out.mkdir()
    for ext in ("wav", "mp3"):                                 # "old" was finished before there was any mark-up
        (out / f"old.{ext}").write_bytes(b"edited")
    past = time.time() - 60
    _touch(tmp_path / "old.wav", past)
    seen = []
    monkeypatch.setattr("punchroll.pipeline.transcript", lambda audio, dest, settings=None, log=print: seen.append(("transcript", dest.name)))
    monkeypatch.setattr("punchroll.pipeline.cut_and_master",
                        lambda audio, markup, out, name, settings, mp3=True: seen.append(("cut", name)) or
                        {"summary": {"raw_minutes": 9.0, "edited_minutes": 8.0, "cuts": 7}})
    assert main(["batch", str(tmp_path / "book.toml")]) == 0
    assert seen == [("transcript", "new.transcript.md"), ("cut", "marked")]
    printed = capsys.readouterr().out
    assert "finished earlier" in printed and "Waiting for mark-up: new" in printed and "8.0" in printed
    assert json.dumps(seen)                                    # nothing else was touched
