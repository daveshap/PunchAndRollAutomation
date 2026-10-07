import json
import os
import time

from punchroll.cli import _natural, main


def test_lines_command(tmp_path, capsys):
    script = tmp_path / "book.md"
    script.write_text("# Chapter 1\n\nOne. Two.\n\n# Chapter 2\n\nThree.\n", encoding="utf-8")
    assert main(["lines", "--script", str(script), "--from", "Chapter 1", "--to", "Chapter 2"]) == 0
    assert capsys.readouterr().out.splitlines() == ["   1  #  Chapter 1.", "   2     One.", "   3     Two."]


def test_natural_order():
    names = ["ch01-10.wav", "ch01-2.wav", "ch01-1.wav", "ch01-pickups.wav"]
    assert sorted(names, key=_natural) == ["ch01-1.wav", "ch01-2.wav", "ch01-10.wav", "ch01-pickups.wav"]


def test_batch_skips_finished_chapters(tmp_path, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    order = ["ch01-1.wav", "ch01-2.wav", "ch01-10.wav", "ch01-pickups.wav"]
    for f in order:
        (raw / f).write_bytes(b"not read when the chapter is skipped")
    (tmp_path / "book.md").write_text("# Chapter 1\n\nHello.\n\n# Chapter 2\n", encoding="utf-8")
    (tmp_path / "book.toml").write_text(
        'script = "book.md"\nout = "edited"\n\n[[chapter]]\nname = "ch01"\n'
        'audio = ["raw/ch01-*.wav", "raw/ch01-pickups.wav"]\nfrom = "Chapter 1"\nto = "Chapter 2"\n',
        encoding="utf-8")
    out = tmp_path / "edited"
    out.mkdir()
    report = {"script": "book.md from 'Chapter 1' to 'Chapter 2'",
              "takes": [{"file": str(raw / f)} for f in order],  # natural order, pickups last, once
              "summary": {"raw_minutes": 12.0, "edited_minutes": 10.0}, "pickups": [], "master": {"rms_db": -20.0}}
    (out / "ch01.report.json").write_text(json.dumps(report), encoding="utf-8")
    for ext in ("wav", "mp3"):
        (out / f"ch01.{ext}").write_bytes(b"edited")
    past = time.time() - 60
    for p in [*raw.iterdir(), tmp_path / "book.md"]:
        os.utime(p, (past, past))

    assert main(["batch", str(tmp_path / "book.toml")]) == 0
    printed = capsys.readouterr().out
    assert "up to date, skipped" in printed
    assert "12.0" in printed and "10.0" in printed
