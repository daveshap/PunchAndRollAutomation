import json
import os
import time
from pathlib import Path

import pytest

from punchroll.cli import main
from punchroll.cut import RENDER_VERSION
from punchroll.pipeline import finished, latest_transcript, natural, recording, transcript


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
    for p in (out / f"ch01.{ext}" for ext in ("wav", "mp3", "report.md", "edit.json")):
        p.write_text(json.dumps({"render_version": RENDER_VERSION}) if p.suffix == ".json" else "edited", encoding="utf-8")
        _touch(p, now - 30)
    for p in (audio, markup):
        _touch(p, now - 60)
    assert finished(out, "ch01", [audio, markup])
    _touch(markup, now - 10)
    assert not finished(out, "ch01", [audio, markup])          # marked up again since
    assert finished(out, "ch01", [audio])
    (out / "ch01.mp3").unlink()
    assert not finished(out, "ch01", [audio]) and finished(out, "ch01", [audio], mp3=False)
    (out / "ch01.report.md").unlink()
    assert not finished(out, "ch01", [audio], mp3=False)


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
    for ext in ("wav", "mp3", "report.md", "edit.json"):       # "old" was finished before there was any mark-up
        (out / f"old.{ext}").write_text(json.dumps({"render_version": RENDER_VERSION}) if ext == "edit.json" else "edited", encoding="utf-8")
    past = time.time() - 60
    _touch(tmp_path / "old.wav", past)
    _touch(tmp_path / "book.toml", past)
    seen = []
    monkeypatch.setattr("punchroll.pipeline.transcript", lambda audio, dest, settings=None, log=print: seen.append(("transcript", dest.name)) or dest)
    monkeypatch.setattr("punchroll.pipeline.cut_and_master",
                        lambda audio, markup, out, name, settings, mp3=True, lines=None, script="": seen.append(("cut", name)) or
                        {"summary": {"raw_minutes": 9.0, "edited_minutes": 8.0, "cuts": 7}})
    assert main(["batch", str(tmp_path / "book.toml")]) == 0
    assert seen == [("transcript", "new.transcript.md"), ("cut", "marked")]
    printed = capsys.readouterr().out
    assert "finished earlier" in printed and "Waiting for mark-up: new" in printed and "8.0" in printed
    assert json.dumps(seen)                                    # nothing else was touched


def test_transcripts_never_overwrite_existing_marked_copies(tmp_path, monkeypatch):
    monkeypatch.setattr("punchroll.pipeline.measure", lambda *args: (None, None, None, []))
    monkeypatch.setattr("punchroll.pipeline.write_transcript", lambda *args: "new transcript")
    dest = tmp_path / "chapter.transcript.md"
    dest.write_text("~~editor's decisions~~", encoding="utf-8")
    _touch(dest, time.time() - 60)
    second = transcript("chapter.wav", dest)
    assert second.name == "chapter.transcript.2.md"
    assert dest.read_text(encoding="utf-8") == "~~editor's decisions~~"
    assert second.read_text(encoding="utf-8") == "new transcript"
    assert latest_transcript(dest) == second
    third = transcript("edited/chapter.wav", dest)
    assert third.name == "chapter.transcript.3.md"
    assert second.read_text(encoding="utf-8") == "new transcript"


@pytest.mark.parametrize("changed", ["book.toml", "settings.toml", "book.md", "markup/chapter.md"])
def test_batch_rebuilds_when_project_settings_manuscript_or_markup_change(tmp_path, monkeypatch, changed):
    (tmp_path / "chapter.wav").write_bytes(b"audio")
    (tmp_path / "settings.toml").write_text("tail = 2.0\n", encoding="utf-8")
    (tmp_path / "book.md").write_text("This is the manuscript.\n", encoding="utf-8")
    (tmp_path / "markup").mkdir()
    (tmp_path / "markup/chapter.md").write_text("marked", encoding="utf-8")
    project = tmp_path / "book.toml"
    project.write_text('config = "settings.toml"\n[[chapter]]\nname = "chapter"\naudio = "chapter.wav"\nscript = "book.md"\n', encoding="utf-8")
    now = time.time()
    for f in tmp_path.rglob("*"):
        if f.is_file():
            _touch(f, now - 60)
    out = tmp_path / "edited"
    out.mkdir()
    for ext in ("wav", "mp3", "report.md", "edit.json"):
        path = out / f"chapter.{ext}"
        path.write_text(json.dumps({"render_version": RENDER_VERSION}) if ext == "edit.json" else "finished", encoding="utf-8")
        _touch(path, now - 30)
    seen = []
    monkeypatch.setattr("punchroll.pipeline.cut_and_master", lambda *args, **kwargs: seen.append(args[3]) or
                        {"summary": {"raw_minutes": 9.0, "edited_minutes": 8.0, "cuts": 7}})
    assert main(["batch", str(project)]) == 0
    assert not seen
    _touch(tmp_path / changed, now - 10)
    assert main(["batch", str(project)]) == 0
    assert seen == ["chapter"]


def test_batch_preserves_old_transcript_and_uses_new_copy_on_next_run(tmp_path, monkeypatch, capsys):
    audio = tmp_path / "chapter.wav"
    audio.write_bytes(b"audio")
    project = tmp_path / "book.toml"
    project.write_text('[[chapter]]\nname = "chapter"\naudio = "chapter.wav"\n', encoding="utf-8")
    marks = tmp_path / "markup"
    marks.mkdir()
    original = marks / "chapter.transcript.md"
    original.write_text("~~in-progress edits~~", encoding="utf-8")
    _touch(original, time.time() - 60)
    monkeypatch.setattr("punchroll.pipeline.measure", lambda *args: (None, None, None, []))
    monkeypatch.setattr("punchroll.pipeline.write_transcript", lambda *args: "new transcript")
    assert main(["batch", str(project)]) == 0
    assert original.read_text(encoding="utf-8") == "~~in-progress edits~~"
    capsys.readouterr()
    assert main(["batch", str(project)]) == 0
    printed = capsys.readouterr().out
    assert "chapter.transcript.2.md" in printed
    assert "writing the transcript" not in printed
    assert not (marks / "chapter.transcript.3.md").exists()


@pytest.mark.parametrize("output_ext", ["mp3", "wav", None])
def test_batch_proofs_finished_output_or_external_audio(tmp_path, monkeypatch, capsys, output_ext):
    (tmp_path / "source.wav").write_bytes(b"audio")
    (tmp_path / "book.md").write_text("The finished words.\n", encoding="utf-8")
    project = tmp_path / "book.toml"
    project.write_text('script = "book.md"\n[[chapter]]\nname = "chapter"\naudio = "source.wav"\n', encoding="utf-8")
    out = tmp_path / "edited"
    out.mkdir()
    if output_ext:
        (out / f"chapter.{output_ext}").write_bytes(b"finished")
    seen = []

    def proof(audio, lines, desc, folder, rec):
        seen.append(Path(audio))
        data = {"duration": "1:00", "pickups": [], "small": [], "not_found": [],
                "acx": {"rms_db": -20, "true_peak_db": -3.5, "noise_floor_db": -65}}
        (folder / f"{Path(audio).stem}.verify.json").write_text(json.dumps(data), encoding="utf-8")
        return "report"

    monkeypatch.setattr("punchroll.cli._proof", proof)
    assert main(["batch", str(project), "--proof"]) == 0
    expected = out / f"chapter.{output_ext}" if output_ext else tmp_path / "source.wav"
    assert seen == [expected]
    assert f"Proofing: {expected}" in capsys.readouterr().out


@pytest.mark.parametrize("edit", [{"render_version": RENDER_VERSION - 1}, {}, [], "broken JSON"])
def test_finished_rejects_outdated_or_incomplete_edit_map(tmp_path, edit):
    source = tmp_path / "raw.wav"
    source.write_bytes(b"source")
    _touch(source, time.time() - 60)
    for ext in ("wav", "report.md"):
        (tmp_path / f"chapter.{ext}").write_bytes(b"finished")
    (tmp_path / "chapter.edit.json").write_text(edit if isinstance(edit, str) else json.dumps(edit), encoding="utf-8")
    assert not finished(tmp_path, "chapter", [source], mp3=False)


def test_assemble_cli_writes_float_intermediate_and_source_map(tmp_path, capsys):
    import numpy as np
    import soundfile as sf
    source = tmp_path / "source.wav"
    pickup = tmp_path / "pickup.wav"
    sf.write(str(source), np.full(100, 0.25, dtype=np.float32), 1000, subtype="FLOAT")
    sf.write(str(pickup), np.full(100, 1.25, dtype=np.float32), 1000, subtype="FLOAT")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"sample_rate": 1000, "sources": {"main": "source.wav", "pickup": "pickup.wav"},
                               "clips": [{"source": "main", "start": 0, "end": 0.05},
                                         {"source": "pickup", "start": 0.01, "end": 0.05, "note": "replacement"}]}), encoding="utf-8")
    output = tmp_path / "assembled.wav"
    assert main(["assemble", str(plan), "-o", str(output)]) == 0
    audio, sr = sf.read(str(output))
    assert sf.info(str(output)).subtype == "FLOAT"
    assert sr == 1000 and len(audio) == 90
    np.testing.assert_allclose(audio[:50], 0.25)
    np.testing.assert_allclose(audio[50:], 1.25)  # float intermediate does not clip before mastering
    report = json.loads(output.with_suffix(".assembly.json").read_text(encoding="utf-8"))
    assert report["sources"]["pickup"] == str(pickup.resolve())
    assert report["edl"][1]["source"] == "pickup"
    assert report["edl"][1]["raw_in"] == 0.01
    assert report["edl"][1]["clean_in"] == 0.05
    assert report["edl"][1]["note"] == "replacement"
    assert "Unmastered assembly" in capsys.readouterr().out


def test_assemble_cli_refuses_to_overwrite_source(tmp_path, capsys):
    source = tmp_path / "source.wav"
    source.write_bytes(b"original recording")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"sample_rate": 48000, "sources": {"main": "source.wav"},
                               "clips": [{"source": "main", "start": 0, "end": 1}]}), encoding="utf-8")
    assert main(["assemble", str(plan), "-o", str(source)]) == 2
    assert "would overwrite an input" in capsys.readouterr().err
    assert source.read_bytes() == b"original recording"


def test_cut_and_master_saves_retained_words_sound_map_and_removal_audit(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    from punchroll.config import Settings
    from punchroll.markup import write_transcript
    from punchroll.pieces import Piece, Room
    from punchroll.pipeline import cut_and_master
    sr = 16000
    pieces = [Piece("word", 0.5, 1.0, "alpha"), Piece("quiet", 1.0, 1.2),
              Piece("sound", 1.2, 1.3, level=-24), Piece("quiet", 1.3, 1.5),
              Piece("word", 1.5, 2.0, "bravo"), Piece("quiet", 2.0, 2.2),
              Piece("word", 2.2, 2.7, "charlie")]
    x = np.random.default_rng(1).normal(0, 0.0001, int(3.2 * sr)).astype(np.float32)
    for p in pieces:
        if p.kind == "word":
            a, b = round(p.a * sr), round(p.b * sr)
            x[a:b] += (0.2 * np.sin(2 * np.pi * 400 * np.arange(b - a) / sr)).astype(np.float32)
    words = [{"text": p.text, "start": p.a, "end": p.b} for p in pieces if p.kind == "word"]
    room = Room(x, sr, words)
    source, marks = tmp_path / "raw.wav", tmp_path / "marks.md"
    sf.write(str(source), x, sr)
    marks.write_text(write_transcript(pieces, source.name).replace("bravo", "~~bravo~~"), encoding="utf-8")
    monkeypatch.setattr("punchroll.pipeline.measure", lambda *args: (x, sr, room, pieces))
    settings = Settings()
    settings.master.noise_reduction = "off"
    out = tmp_path / "edited"
    cut_and_master(source, marks, out, "chapter", settings, mp3=False, log=lambda *args: None)
    data = json.loads((out / "chapter.edit.json").read_text(encoding="utf-8"))
    assert [w["text"] for w in data["kept"]] == ["alpha", "charlie"]
    assert data["sounds"][0]["kept"] and data["sounds"][0]["raw"] == 1.2
    assert [w["text"] for w in data["removed_words_not_retained"]] == ["bravo"]
    assert data["render_version"] == RENDER_VERSION
    assert finished(out, "chapter", [source, marks], mp3=False)
    original_edit = (out / "chapter.edit.json").read_bytes()
    logs = []
    cut_and_master(source, marks, out, "chapter", settings, mp3=False, report_only=True, log=logs.append)
    assert (out / "chapter.edit.json").read_bytes() == original_edit
    assert (out / "chapter.dry-run.report.md").is_file()
    assert "chapter.dry-run.report.md" in logs[-1]


@pytest.mark.parametrize("source_name,markup_name,output_name,report_only", [
    ("raw.wav", "marks.md", None, False),
    ("raw.wav", "chapter.report.md", "chapter", False),
    ("raw.wav", "chapter.dry-run.report.md", "chapter", True),
])
def test_cut_refuses_to_overwrite_recording_or_markup(tmp_path, monkeypatch, source_name, markup_name, output_name, report_only):
    from punchroll.pipeline import cut_and_master
    source, markup = tmp_path / source_name, tmp_path / markup_name
    source.write_bytes(b"original recording")
    markup.write_text("editor's decisions", encoding="utf-8")
    monkeypatch.setattr("punchroll.pipeline.measure", lambda *args: pytest.fail("must reject before processing inputs"))
    with pytest.raises(ValueError, match="would overwrite an input"):
        cut_and_master(source, markup, tmp_path, output_name, report_only=report_only)
    assert source.read_bytes() == b"original recording"
    assert markup.read_text(encoding="utf-8") == "editor's decisions"


def test_cut_refuses_to_overwrite_a_hardlink_to_the_source(tmp_path, monkeypatch):
    from punchroll.pipeline import cut_and_master
    source, markup = tmp_path / "raw.wav", tmp_path / "marks.md"
    source.write_bytes(b"original recording")
    markup.write_text("editor's decisions", encoding="utf-8")
    os.link(source, tmp_path / "chapter.wav")
    monkeypatch.setattr("punchroll.pipeline.measure", lambda *args: pytest.fail("must reject before processing inputs"))
    with pytest.raises(ValueError, match="would overwrite an input"):
        cut_and_master(source, markup, tmp_path, "chapter")
    assert source.read_bytes() == b"original recording"
