"""The outtakes cut from the raw recording: levelled, faded, named, listed, and never written over."""
import json

import numpy as np
import pytest
import soundfile as sf

from punchroll import outtakes

SR = 44100


def test_clips_are_cut_levelled_and_listed(tmp_path):
    t = np.arange(4 * SR) / SR
    x = (0.05 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    raw = tmp_path / "take.wav"
    sf.write(raw, x, SR)
    listing = tmp_path / "outtakes.json"
    listing.write_text(json.dumps([
        {"n": 1, "rating": 3, "profanity": False, "start": 0.5, "end": 1.5, "words": "Wait, what? Let me try that again."},
        {"n": 2, "rating": 1, "profanity": True, "start": 2.0, "end": 2.6, "words": "Darn..."},
    ]), encoding="utf-8")
    out = tmp_path / "Outtakes"
    written = outtakes.clips(raw, listing, out, "a test")
    assert [p.name for p in written] == ["01 r3 - wait what let me try that again.wav", "02 r1 - darn.wav"]
    y, sr = sf.read(written[0])
    assert sr == SR and len(y) == SR
    assert abs(20 * np.log10(np.sqrt(np.mean(y[2000:-2000] ** 2))) - outtakes.LEVEL_DB) < 0.5
    assert abs(y[0]) < 1e-3 and abs(y[-1]) < 1e-3
    md = (out / "outtakes.md").read_text(encoding="utf-8")
    assert "# Outtakes: a test" in md and "| 02 r1 - darn.wav | 1 | yes | 2.00 | 2.60 | Darn... |" in md
    with pytest.raises(FileExistsError):
        outtakes.clips(raw, listing, out)


def test_a_take_must_end_after_it_starts(tmp_path):
    listing = tmp_path / "outtakes.json"
    listing.write_text(json.dumps([{"rating": 2, "start": 3.0, "end": 2.0, "words": "no"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        outtakes.load(listing)
