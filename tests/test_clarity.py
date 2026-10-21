"""Clarity on made-up voices and recognizer output: landing and reset follow the pitch at sentence ends, the scale
is what it says it is, and the scorecard shows the four columns."""
import json
import math

import numpy as np
import soundfile as sf

from punchroll import clarity as cl
from punchroll import enunciation as en
from punchroll.cli import main

SR = 16000


def sentences(n, fall_st, seconds=2.4, f0=120.0):
    """n 'sentences' of buzzy voice, each 2 s of level pitch whose last word (0.4 s) falls by fall_st semitones,
    then 0.4 s of silence; and the recognizer's words for them, six to a sentence."""
    per = int(seconds * SR)
    t = np.arange(per) / SR
    voiced = t < seconds - 0.4
    drop = np.clip((t - (seconds - 0.8)) / 0.4, 0, 1) * fall_st
    f = f0 * 2 ** (-drop / 12)
    phase = 2 * np.pi * np.cumsum(f) / SR
    one = sum(np.sin(k * phase) / k for k in range(1, 30)) * voiced
    x = np.tile(0.1 * one / np.max(np.abs(one)), n).astype(np.float32)
    x += np.random.default_rng(0).normal(0, 1e-4, len(x)).astype(np.float32)
    words, text = [], []
    for s in range(n):
        for k in range(6):
            start = s * seconds + k * (seconds - 0.4) / 6
            words.append({"text": f"w{s}x{k}", "start": start, "end": start + (seconds - 0.4) / 6 - 0.02})
            text.append(f"w{s}x{k}" + ("." if k == 5 else ""))
    return x, words, " ".join(text)


def test_landing_grows_with_the_fall_at_each_statement_end():
    x, w, text = sentences(20, 0.0)
    flat = cl.landing_and_reset(w, text, x, SR)
    x, w, text = sentences(20, 4.0)
    falling = cl.landing_and_reset(w, text, x, SR)
    assert falling["statements"] >= 15 and falling["landing"] > flat["landing"] + 2.5   # semitones
    assert falling["reset"] > flat["reset"] + 2.5


def test_too_few_statements_say_nothing():
    x, w, text = sentences(5, 4.0)
    r = cl.landing_and_reset(w, text, x, SR)
    assert math.isnan(r["landing"]) and r["statements"] == 5


def test_the_scale_puts_the_reference_set_at_50_and_rewards_fewer_doubts():
    rng = np.random.default_rng(3)
    ms = [{"enunciation": rng.normal(5.8, 0.9), "landing": rng.normal(0.32, 0.08), "reset": rng.normal(0.7, 0.08)}
          for _ in range(30)]
    ref = cl.reference_from(ms, ["the"])
    scores = np.array([cl.clarity_score(m, ref) for m in ms])
    assert abs(scores.mean() - 50) < 1e-9 and abs(scores.std() - 10) < 1e-9
    base = {p: ref["mean"][p] for p in cl.PARTS}
    assert cl.clarity_score(base | {"enunciation": base["enunciation"] - 1}, ref) > 50
    assert math.isnan(cl.clarity_score(base | {"landing": float("nan")}, ref))


def doubting(texts, every):
    return [{"text": t, "start": float(k), "logp": math.log(0.5 if k % every == 0 else 0.99)} for k, t in enumerate(texts)]


def test_scorecard_adds_clarity_and_fixes_its_scale(tmp_path, monkeypatch, capsys):
    (tmp_path / "edited").mkdir()
    (tmp_path / "said").mkdir()
    heard = {}
    for name, fall, every in (("clear", 4.0, 50), ("vague", 0.5, 4)):
        x, w, text = sentences(20, fall)
        sf.write(tmp_path / "edited" / f"{name}.wav", x, SR)
        (tmp_path / "said" / f"{name}.md").write_text(f"# {name}\n\nWhat was said.\n\n{text}\n", encoding="utf-8")
        (tmp_path / f"{name}.toml").write_text(f'out = "edited"\ntranscripts = "said"\n\n[[chapter]]\nname = "{name}"\n',
                                               encoding="utf-8")
        heard[name] = (doubting(["the", "of", "and"] * 40, every), w)
    monkeypatch.setattr(en, "confidences", lambda path, x, sr, rec, cache: heard[path.stem][0])
    monkeypatch.setattr("punchroll.scorecard._timed_words", lambda path: (heard[path.stem][1], path))
    out = tmp_path / "card.md"
    assert main(["scorecard", str(tmp_path / "clear.toml"), str(tmp_path / "vague.toml"), "-o", str(out), "--composure"]) == 0
    md = out.read_text(encoding="utf-8")
    assert "| Composure | Enunciation /100 | Landing st | Reset st |" in md and "Composure scale: set on" in md
    rows = {l.split("|")[1].strip(): [c.strip() for c in l.split("|")] for l in md.splitlines()
            if l.startswith("| clear") or l.startswith("| vague")}
    col = md.splitlines()[[k for k, l in enumerate(md.splitlines()) if l.startswith("| Recording")][0]].split("|")
    c = [x.strip() for x in col].index("Composure")
    assert float(rows["clear"][c]) > float(rows["vague"][c])
    ref = json.loads((tmp_path / cl.REFERENCE_NAME).read_text(encoding="utf-8"))
    assert ref["everyday"] == ["and", "of", "the"] and set(ref["mean"]) == set(cl.PARTS)
    table = out.with_suffix(".csv").read_text(encoding="utf-8-sig").splitlines()
    assert "Composure,Enunciation /100,Landing st,Reset st" in table[0]
    capsys.readouterr()
