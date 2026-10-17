"""Fire on made-up voices: each part answers to the thing it measures, and the scale is what it says it is."""
import json

import numpy as np
import pytest
import soundfile as sf

from punchroll.cli import main
from punchroll.fire import fire_measures, fire_score, hottest_minutes, reference_from
from punchroll.scorecard import add_fire, rank_rows, scorecard_markdown

SR = 16000


def voice(seconds, f0=120.0, glide_st=0.0, rolloff=1.2, seed=0, sr=SR):
    """A buzzy stand-in for a voice, in 1.1 s 'phrases' with 0.4 s gaps.

    glide_st: the pitch swings this many semitones either way, 0.7 times a second (movement).
    rolloff: the harmonics fall off as 1/k**rolloff; smaller is brighter.
    """
    t = np.arange(int(seconds * sr)) / sr
    f = f0 * 2 ** (glide_st * np.sin(2 * np.pi * 0.7 * t) / 12)
    phase = 2 * np.pi * np.cumsum(f) / sr
    top = f0 * 2 ** (abs(glide_st) / 12)
    x = sum(np.sin(k * phase) / k ** rolloff for k in range(1, 60) if k * top < 7600)
    on = (t % 1.5) < 1.1
    rng = np.random.default_rng(seed)
    return (0.2 * on * x / np.max(np.abs(x)) + rng.normal(0, 1e-4, len(t))).astype(np.float32)


def test_lift_follows_the_pitch():
    m = fire_measures(voice(20.0, f0=140.0), SR)
    assert abs(m["pitch_hz"] - 140.0) < 2.0
    assert abs(m["lift"] - 12 * np.log2(1.4)) < 0.3


def test_lift_at_a_recording_sample_rate():
    m = fire_measures(voice(20.0, f0=110.0, sr=44100), 44100)
    assert abs(m["pitch_hz"] - 110.0) < 2.0


def test_movement_grows_with_a_moving_pitch():
    steady = fire_measures(voice(20.0, glide_st=0.0), SR)
    moving = fire_measures(voice(20.0, glide_st=3.0), SR)
    assert moving["movement"] > steady["movement"] + 3.0


def test_range_grows_with_wider_swings():
    narrow = fire_measures(voice(20.0, glide_st=1.0), SR)
    wide = fire_measures(voice(20.0, glide_st=4.0), SR)
    # a sine swing of +-g semitones spans 2 g sin(0.4 pi) = 1.9 g from its 10th to its 90th percentile
    assert abs(narrow["range"] - 1.9) < 0.3 and abs(wide["range"] - 7.6) < 0.5
    assert fire_measures(voice(20.0, glide_st=0.0), SR)["range"] < 0.5


def test_brightness_grows_with_stronger_upper_harmonics():
    dark = fire_measures(voice(20.0, rolloff=2.0), SR)
    bright = fire_measures(voice(20.0, rolloff=0.7), SR)
    assert bright["brightness"] > dark["brightness"] + 200
    assert abs(bright["lift"] - dark["lift"]) < 0.2          # the same pitch either way


def test_too_little_voice_gives_nothing():
    assert fire_measures(np.random.default_rng(1).normal(0, 1e-4, SR * 3).astype(np.float32), SR) is None


def test_the_scale_puts_the_reference_set_at_50_with_10_a_step():
    rng = np.random.default_rng(4)
    ms = [{"lift": rng.normal(4, 1), "movement": rng.normal(13, 1), "range": rng.normal(12, 0.6),
           "brightness": rng.normal(400, 25)} for _ in range(30)]
    ref = reference_from(ms)
    scores = np.array([fire_score(m, ref) for m in ms])
    assert scores.mean() == pytest.approx(50, abs=1e-9) and scores.std() == pytest.approx(10, abs=1e-9)
    hot = {k: ref["mean"][k] + ref["sd"][k] for k in ("lift", "movement", "range", "brightness")}
    assert fire_score(hot, ref) > 60


def test_a_scale_set_before_range_was_added_still_reads():
    old = {"mean": {"lift": 4.0, "movement": 13.0, "brightness": 400.0}, "sd": {"lift": 1.0, "movement": 1.0, "brightness": 25.0},
           "raw_mean": 0.0, "raw_sd": 1.0}
    assert fire_score({"lift": 5.0, "movement": 14.0, "range": 99.0, "brightness": 425.0}, old) == pytest.approx(60.0)


def test_the_hottest_minute_is_found():
    x = np.concatenate([voice(20.0, glide_st=0.5, rolloff=1.8), voice(20.0, f0=135.0, glide_st=3.0, rolloff=0.8),
                        voice(20.0, glide_st=0.5, rolloff=1.8, seed=2)])
    m = fire_measures(x, SR, minute_s=20.0)
    assert [round(mm["at"]) for mm in m["minutes"]] == [0, 20, 40]
    ref = reference_from([m] + [{k: v for k, v in mm.items() if k != "at"} for mm in m["minutes"]])
    assert hottest_minutes(m, ref)[0][0] == pytest.approx(20.0)


def test_scorecard_sorts_by_fire_and_shows_the_three_parts():
    def row(name, lift, move, rng, bright, clicks):
        parts = {"lift": lift, "movement": move, "range": rng, "brightness": bright}
        return {"name": name, "minutes": 5.0, "clicks": clicks, "noise_floor": -80.0, "recorded": "17 Oct 2026",
                "tone_bands": np.zeros(3), "pitch": 120.0, "pace": 140.0, "pesq": None, "pesq_low": None,
                "lowest": [], "fire_measures": parts | {"minutes": [{"at": 60.0} | parts]},
                "fire_note": "Fire scale: test."}
    rows = [row("flat", 3.0, 11.0, 10.0, 380.0, 0.5), row("fiery", 5.0, 14.0, 13.0, 440.0, 2.0),
            row("middling", 4.0, 13.0, 12.0, 400.0, 1.0)]
    rank_rows(rows)
    add_fire(rows, reference_from([r["fire_measures"] for r in rows]))
    md = scorecard_markdown(rows)
    assert md.index("| fiery |") < md.index("| middling |") < md.index("| flat |")
    head = next(l for l in md.splitlines() if l.startswith("| Recording"))
    for col in ("Recorded", "Fire", "Lift st", "Movement st/s", "Range st", "Brightness Hz", "Hottest minutes", "Order"):
        assert col in head
    assert "Fire scale: test." in md


def test_scorecard_command_scores_several_projects_and_fixes_the_scale(tmp_path, capsys):
    (tmp_path / "edited").mkdir()
    for i, (name, f0, glide, roll) in enumerate([("calm", 115.0, 0.5, 1.8), ("lively", 140.0, 3.0, 0.9)]):
        sf.write(tmp_path / "edited" / f"{name}.wav", voice(20.0, f0=f0, glide_st=glide, rolloff=roll, seed=i), SR)
        (tmp_path / f"{name}.toml").write_text(
            f'out = "edited"\n\n[[chapter]]\nname = "{name}"\nrecorded = "17 Oct 2026"\n', encoding="utf-8")
    out = tmp_path / "card.md"
    assert main(["scorecard", str(tmp_path / "calm.toml"), str(tmp_path / "lively.toml"), "-o", str(out),
                 "--calibrate-fire"]) == 0
    ref = json.loads((tmp_path / "fire-reference.json").read_text(encoding="utf-8"))
    assert ref["recordings"] == 2 and set(ref["mean"]) == {"lift", "movement", "range", "brightness"}
    md = out.read_text(encoding="utf-8")
    assert md.index("| lively |") < md.index("| calm |") and "Fire scale: set on" in md
    table = out.with_suffix(".csv").read_text(encoding="utf-8-sig").splitlines()
    assert table[0].startswith("Recording,Recorded,Minutes,Fire,Lift st,Movement st/s,Range st,Brightness Hz")
    assert [line.split(",")[0] for line in table[1:]] == ["lively", "calm"]
    # the next run reads the saved scale instead of setting a new one
    assert main(["scorecard", str(tmp_path / "calm.toml"), "-o", str(out)]) == 0
    assert "(fire-reference.json)" in out.read_text(encoding="utf-8")
    capsys.readouterr()


def test_fire_command_scores_any_files_on_the_saved_scale(tmp_path, capsys):
    calm, lively = voice(20.0, f0=115.0, glide_st=0.5, rolloff=1.8), voice(20.0, f0=140.0, glide_st=3.0, rolloff=0.9, seed=1)
    ref = reference_from([fire_measures(calm, SR), fire_measures(lively, SR)], note="two test voices")
    (tmp_path / "fire-reference.json").write_text(json.dumps(ref), encoding="utf-8")
    for name, x in (("probe - cold.wav", calm), ("probe - warm.wav", lively)):
        sf.write(tmp_path / name, x, SR)
    assert main(["fire", str(tmp_path / "probe - *.wav"), "--reference", str(tmp_path / "fire-reference.json"),
                 "--minutes"]) == 0
    out = capsys.readouterr().out
    rows = {l.split("|")[1].strip(): l for l in out.splitlines() if l.startswith("| probe")}
    fire = {k: float(v.split("|")[3]) for k, v in rows.items()}
    assert fire["probe - warm.wav"] > fire["probe - cold.wav"] and "two test voices" in out
