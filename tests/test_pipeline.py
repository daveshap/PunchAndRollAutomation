import json
import os
import time

from punchroll.pipeline import describe, finished_report


def _touch(path, t):
    os.utime(path, (t, t))


def test_finished_report_tracks_inputs(tmp_path):
    audio, script, config = tmp_path / "ch01.wav", tmp_path / "book.md", tmp_path / "settings.toml"
    audio.write_bytes(b"audio")
    script.write_text("# Chapter 1\n", encoding="utf-8")
    config.write_text("", encoding="utf-8")
    out = tmp_path / "edited"
    out.mkdir()
    desc = describe(script, "Chapter 1", "Chapter 2")
    assert desc == "book.md from 'Chapter 1' to 'Chapter 2'"

    def done(paths=(str(audio),), section=desc, mp3=True, extra=()):
        return finished_report(out, "ch01", list(paths), script, section, mp3, extra) is not None

    assert not done()  # nothing written yet

    now = time.time()
    outputs = [out / "ch01.wav", out / "ch01.mp3", out / "ch01.report.json"]
    for p in outputs[:2]:
        p.write_bytes(b"edited")
    report = {"script": desc, "takes": [{"file": str(audio)}], "master": None}
    outputs[2].write_text(json.dumps(report), encoding="utf-8")
    for p in (audio, script, config):
        _touch(p, now - 60)
    for p in outputs:
        _touch(p, now - 30)
    assert not done()  # a --report-only run wrote no audio

    outputs[2].write_text(json.dumps(dict(report, master={"rms_db": -20.0})), encoding="utf-8")
    _touch(outputs[2], now - 30)
    assert done(extra=[config])
    assert not done(section=describe(script, "Chapter 1"))  # a different script section
    assert not done(paths=[str(audio), str(audio)])  # different recordings
    _touch(config, now - 10)
    assert not done(extra=[config])  # settings changed since
    _touch(script, now - 10)
    assert not done()  # script changed since
    _touch(script, now - 60)
    (out / "ch01.mp3").unlink()
    assert not done()  # MP3 missing
    assert done(mp3=False)
