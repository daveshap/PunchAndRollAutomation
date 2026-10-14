import json

import numpy as np
import pytest
import soundfile as sf

from punchroll.assembly import AssemblyClip, SourceSpan, assemble, assemble_files, load_plan


def span(source, start, end, **kwargs):
    return AssemblyClip(SourceSpan(source, start, end), **kwargs)


def test_pickup_replaces_only_explicit_range_and_maps_sources():
    main = np.arange(100, dtype=np.float32) / 100
    pickup = np.full(20, -0.25, dtype=np.float32)
    result = assemble({"main": (main, 100), "pickup": (pickup, 100)},
                      [span("main", 0, .4), span("pickup", 0, .2), span("main", .6, 1)], 100)
    np.testing.assert_array_equal(result["audio"], np.r_[main[:40], pickup, main[60:]])
    assert [(e["source"], e["clean_in_sample"], e["clean_out_sample"]) for e in result["edl"]] == [
        ("main", 0, 40), ("pickup", 40, 60), ("main", 60, 100)]
    assert result["edl"][2]["source_in_sample"] == 60


def test_crossfade_has_constant_gain_and_auditable_overlap():
    sources = {"a": (np.ones(100, np.float32) * .2, 100)}
    clips = [span("a", 0, 1), span("a", 0, 1, crossfade=.1)]
    result = assemble(sources, clips, 100)
    np.testing.assert_allclose(result["audio"], .2, atol=1e-7)
    assert len(result["audio"]) == 190
    assert result["edl"][1]["clean_in_sample"] == 90
    assert result["edl"][1]["crossfade_samples"] == 10
    dry = assemble(sources, clips, 100, render=False)
    assert dry["audio"] is None
    assert dry["edl"] == result["edl"]
    assert dry["summary"]["samples"] == len(result["audio"])


def test_explicit_reference_matches_pickup_gain_without_changing_main():
    sources = {"main": (np.full(100, .2), 100), "pickup": (np.full(50, .1), 100)}
    clips = [span("main", 0, .5), span("pickup", 0, .5,
             match_level_to=SourceSpan("main", 0, .5), note="replacement sentence")]
    result = assemble(sources, clips, 100)
    np.testing.assert_allclose(result["audio"], .2, atol=1e-7)
    assert result["edl"][1]["gain_db"] == pytest.approx(6.020599913)
    assert result["edl"][0]["gain_db"] == 0
    assert result["edl"][1]["level_reference"]["source"] == "main"
    assert result["edl"][1]["note"] == "replacement sentence"


def test_resampling_and_one_sample_clip_are_not_dropped():
    sources = {"a": (np.array([.1, .2, .3], np.float32), 3),
               "b": (np.array([.4], np.float32), 4)}
    clips = [span("a", 0, 1), span("b", 0, .25)]
    result = assemble(sources, clips, 4)
    assert len(result["audio"]) == 5
    assert result["audio"][-1] == pytest.approx(.4)
    assert result["edl"][0]["source_out_sample"] == 3
    assert result["edl"][0]["clean_out_sample"] == 4
    assert assemble(sources, clips, 4, render=False)["edl"] == result["edl"]


def test_one_sample_crossfade_blends_both_sources():
    result = assemble({"a": (np.array([.2, .2]), 2), "b": (np.array([.4, .4]), 2)},
                      [span("a", 0, 1), span("b", 0, 1, crossfade=.5)], 2)
    np.testing.assert_allclose(result["audio"], [.2, .3, .4])


def test_overload_is_reported_without_limiting_and_sources_unchanged():
    audio = np.full(10, .8, np.float32)
    result = assemble({"a": (audio, 10)}, [span("a", 0, 1, gain_db=6.020599913)], 10)
    np.testing.assert_allclose(result["audio"], 1.6)
    np.testing.assert_allclose(audio, .8)
    assert result["summary"]["samples_over_full_scale"] == 10


@pytest.mark.parametrize("clips", [
    [], [span("missing", 0, 1)], [span("a", -.1, 1)], [span("a", 0, 1.1)],
    [span("a", .1, .1)], [span("a", 0, float("nan"))],
    [span("a", 0, 1, crossfade=.1)], [span("a", 0, 1, gain_db=float("inf"))],
    [span("a", 0, 1, level_sample=SourceSpan("a", 0, 1))],
    [span("a", 0, .1), span("a", 0, 1, crossfade=.2)],
    [span("a", 0, 1), span("a", 0, .5, crossfade=.4), span("a", 0, 1, crossfade=.4)],
])
def test_invalid_ranges_or_overlapping_fades_fail_without_rendering(clips):
    with pytest.raises(ValueError):
        assemble({"a": (np.ones(100), 100)}, clips, 100, render=False)


def test_level_matching_silence_is_rejected():
    with pytest.raises(ValueError, match="silent"):
        assemble({"a": (np.zeros(10), 10)},
                 [span("a", 0, 1, match_level_to=SourceSpan("a", 0, 1))], 10)


def test_file_wrapper_reads_and_records_sources_without_writing(tmp_path):
    source = tmp_path / "pickup.wav"
    sf.write(source, np.full(100, .2), 100, subtype="FLOAT")
    result = assemble_files({"pickup": source}, [span("pickup", 0, 1)], 100)
    np.testing.assert_allclose(result["audio"], .2)
    assert result["sources"] == {"pickup": str(source.resolve())}
    assert list(tmp_path.iterdir()) == [source]


def test_load_plan_resolves_relative_paths_and_explicit_matching(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"sample_rate": 48000, "sources": {"main": "main.wav", "p": "takes/p.wav"},
                               "clips": [{"source": "p", "start": 1, "end": 2, "gain_db": -2,
                                          "match_level_to": {"source": "main", "start": 0, "end": 1},
                                          "note": "pickup"}]}), encoding="utf-8")
    paths, clips, sr = load_plan(path)
    assert sr == 48000
    assert paths["p"] == tmp_path / "takes" / "p.wav"
    assert clips[0].span == SourceSpan("p", 1, 2)
    assert clips[0].match_level_to == SourceSpan("main", 0, 1)
    assert clips[0].gain_db == -2


@pytest.mark.parametrize("update,match", [
    ({"unknown": True}, "unknown fields"), ({"sample_rate": True}, "sample_rate"),
    ({"sources": []}, "sources"), ({"sources": {"main": ""}}, "file path"),
    ({"clips": []}, "clips"), ({"clips": [{}]}, "missing fields"),
    ({"clips": [{"source": "main", "start": 0, "end": 1, "crossfdae": .1}]}, "unknown fields"),
    ({"clips": [{"source": "absent", "start": 0, "end": 1}]}, "source"),
    ({"clips": [{"source": "main", "start": "0", "end": 1}]}, "finite number"),
    ({"clips": [{"source": "main", "start": 0, "end": 1, "gain_db": float("nan")}]}, "finite number"),
    ({"clips": [{"source": "main", "start": 0, "end": 1, "match_level_to": {}}]}, "missing fields"),
    ({"clips": [{"source": "main", "start": 0, "end": 1, "level_sample": {"source": "main", "start": 0, "end": 1}}]}, "requires"),
])
def test_load_plan_rejects_malformed_fields(tmp_path, update, match):
    data = {"sample_rate": 100, "sources": {"main": "a.wav"},
            "clips": [{"source": "main", "start": 0, "end": 1}]}
    data.update(update)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_plan(path)
