"""End-to-end edit on synthetic audio: every 'word' is a tone at its own pitch.

The recording restarts the first sentence halfway through. The edited audio must
contain each word exactly once, in script order, and the master must meet ACX levels.
"""
import numpy as np

from punchroll.config import Settings
from punchroll.edit import build_edit
from punchroll.master import master
from punchroll.text import Line

SR = 16000
NAMES = "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()
MORE = "kilo lima mike".split()                            # for the tests that need a longer line, or a third one
TALK = "no sorry".split()                                  # what a reader says between takes
FREQ = {w: 400 + 130 * i for i, w in enumerate(NAMES + MORE + TALK)}


def synth(sequence):
    """sequence: list of words and pause lengths in seconds."""
    rng = np.random.default_rng(1)
    parts, words, t = [], [], 0.0
    for item in [1.0] + sequence + [1.0]:
        if isinstance(item, float):
            n = int(item * SR)
            parts.append(np.zeros(n, np.float32))
        else:
            n = int(0.25 * SR)
            tt = np.arange(n) / SR
            env = np.minimum(1, np.minimum(tt, tt[::-1]) / 0.02)
            parts.append((0.3 * env * np.sin(2 * np.pi * FREQ[item] * tt)).astype(np.float32))
            words.append({"text": item, "start": t, "end": t + 0.25})
        t += n / SR
    x = np.concatenate(parts)
    x += rng.normal(0, 10 ** (-62 / 20), len(x)).astype(np.float32)        # room noise
    return x, words


def detect(y):
    hop = int(0.05 * SR)
    seq = []
    for a in range(0, len(y) - hop, hop):
        fr = y[a:a + hop]
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        spec = np.abs(np.fft.rfft(fr * np.hanning(hop)))
        f = np.argmax(spec) * SR / hop
        w = min(FREQ, key=lambda k: abs(FREQ[k] - f))
        if not seq or seq[-1] != w:
            seq.append(w)
    return seq


def lines_for(sentences):
    return [Line(" ".join(s) + ".", "body", 0, list(s)) for s in sentences]


def take(words):
    """One take of these words, 0.15 s apart."""
    return [v for w in words for v in (w, 0.15)][:-1]


def edit(seq, lines, comps=True):
    """The edit of a recording, and the words heard in its finished audio."""
    settings = Settings()
    settings.comps = comps
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines, settings, log=lambda *a: None)
    return res, detect(res["audio"])


def test_restart_is_removed_and_order_kept():
    s1, s2 = NAMES[:6], NAMES[6:]
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.6,                       # abandoned start
           "alpha", 0.15, "bravo", 0.15, "charlie", 0.15, "delta", 0.15, "echo", 0.15, "foxtrot", 0.7,
           "golf", 0.15, "hotel", 0.15, "india", 0.15, "juliet"]
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines_for([s1, s2]), Settings(), log=lambda *a: None)
    assert res["summary"]["restarts"] == 1
    assert res["summary"]["words_cut"] == 3
    assert res["summary"]["lines_found"] == 2
    assert not res["pickups"]
    assert detect(res["audio"]) == NAMES
    # the abandoned start (about 1.5 s) is gone; 1.5 s of head and 3 s of tail room tone are added
    assert len(res["audio"]) < len(x) + 2.5 * SR

    y, m = master(res["audio"], SR, Settings().master, log=lambda *a: None)
    assert abs(m["rms_db"] + 20) < 0.3
    assert m["true_peak_db"] < -3


def test_adlib_that_runs_on_is_kept_and_a_stray_word_is_cut():
    lines = lines_for([NAMES[:3], NAMES[3:5], NAMES[5:7]])
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.05, "hotel", 0.7,      # "hotel" runs on from the line's end
           "india", 0.05, "delta", 0.15, "echo", 0.7,                          # "india" leads straight into the next line
           "juliet", 0.7,                                                      # "juliet" stands apart from both
           "foxtrot", 0.15, "golf"]
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines, Settings(), log=lambda *a: None)
    assert detect(res["audio"]) == "alpha bravo charlie hotel india delta echo foxtrot golf".split()
    assert res["summary"]["words_cut"] == 1
    assert [c["words"] for c in res["cuts"]] == ["juliet"]
    assert [p["problem"] for p in res["pickups"]] == ["added 'hotel'", "added 'india'"]
    assert [p["line"] for p in res["pickups"]] == [1, 2]                        # each stays with the line it joins


# Three lines for the tests of a word added beside a take that is cut. "india" is the added word: the "Second," of
# "...three features. Second, it keeps spawning, no, sorry. Second, it keeps improving over time. And it spawns..."
LINES = lines_for([NAMES[:3], NAMES[3:7], MORE])
ONE, TWO, THREE = take(NAMES[:3]), take(NAMES[3:7]), take(MORE)
AS_WRITTEN = NAMES[:7] + MORE
WITH_INDIA = NAMES[:3] + ["india"] + NAMES[3:7] + MORE


def test_adlib_that_opens_a_retake_is_kept_and_the_abandoned_take_is_cut():
    seq = (ONE + [0.7, "india", 0.05, "delta", 0.15, "echo", 0.15, "juliet", 0.15, "no", 0.15, "sorry", 0.6,   # abandoned
                  "india", 0.05] + TWO + [0.7] + THREE)                                                   # read again
    for comps in (True, False):
        res, heard = edit(seq, LINES, comps)
        assert heard == WITH_INDIA                                             # the added word once, the abandoned take gone
        assert [c["words"] for c in res["cuts"]] == ["india delta echo juliet no sorry"]
        assert res["cuts"][0]["unsaid"] == ["juliet", "no"]                    # cut and not said again: the chatter, no more
        assert [(p["line"], p["problem"]) for p in res["pickups"]] == [(2, "added 'india'")]   # it opens the line read again

    # two added words open a retake as well, whether or not the abandoned take had them; three are an aside
    stop = ONE + [0.7, "delta", 0.15, "echo"]
    res, heard = edit(stop + [0.15, "juliet", 0.6, "india", 0.05, "hotel", 0.05] + TWO + [0.7] + THREE, LINES)
    assert heard == NAMES[:3] + ["india", "hotel"] + NAMES[3:7] + MORE
    res, heard = edit(stop + [0.6, "india", 0.05, "hotel", 0.05, "juliet", 0.05] + TWO + [0.7] + THREE, LINES)
    assert heard == AS_WRITTEN


def test_last_words_of_an_abandoned_take_are_not_kept_as_adlibs():
    start = ONE + [0.7, "delta", 0.15, "echo", 0.15]                           # line one, then line two as far as "echo"
    for end in (["juliet", 0.05],                                              # a stray word, and the retake with no pause
                ["juliet", 0.05, "india", 0.05],                               # a stray word and an added one in the same breath
                ["juliet", 0.05, "sorry", 0.05, "india", 0.05],                # a filler between them is not a pause
                ["juliet", 0.15, "hotel", 0.6]):                               # two stray words, a pause, the retake as written
        res, heard = edit(start + end + TWO + [0.7] + THREE, LINES)
        assert heard == AS_WRITTEN and not res["pickups"], end

    # once the reader has paused, a filler and an added word in one breath with the retake: the word opens it
    res, heard = edit(start + ["juliet", 0.6, "sorry", 0.05, "india", 0.05] + TWO + [0.7] + THREE, LINES)
    assert heard == WITH_INDIA
    # a retake that picks up partway through the line is left alone: the first take's "delta" still opens the line
    res, heard = edit(start + ["juliet", 0.6, "india", 0.05] + take(NAMES[4:7]) + [0.7] + THREE, LINES)
    assert heard == AS_WRITTEN and not res["pickups"]


def test_false_start_of_a_line_is_not_an_adlib():
    # "The- The end comes." At the first and last lines of a script the alignment takes a false start for chatter,
    # not for a restart, so its words come to the edge rule as unscripted ones. They are the line's own, said twice.
    last_line_again = ONE + [0.7] + TWO + [0.7] + THREE + [0.6, "kilo", 0.05, "juliet", 0.05] + THREE
    first_line_again = ["alpha", 0.15, "bravo", 0.6, "alpha", 0.05, "juliet", 0.05] + ONE + [0.7] + TWO + [0.7] + THREE
    for seq in (last_line_again, first_line_again):
        res, heard = edit(seq, LINES)
        assert heard == AS_WRITTEN and not res["pickups"]


def test_no_before_a_retake_calls_the_take_off_and_is_not_kept():
    stop = ONE + [0.7] + take(["delta", "echo", "juliet"]) + [0.6]             # line one, a take abandoned, a pause
    res, heard = edit(stop + ["no", 0.05] + TWO + [0.7] + THREE, LINES)        # "No, it keeps improving."
    assert heard == AS_WRITTEN and not res["pickups"]
    res, heard = edit(stop + ["no", 0.05, "india", 0.05] + TWO + [0.7] + THREE, LINES)   # "No, second, it keeps improving."
    assert heard == WITH_INDIA
    # between two lines that were both kept, no take was called off: "no" is an added word like any other
    res, heard = edit(ONE + [0.7, "no", 0.05] + TWO + [0.7] + THREE, LINES)
    assert heard == NAMES[:3] + ["no"] + NAMES[3:7] + MORE


def test_adlib_that_closes_a_line_is_kept_when_the_take_after_it_is_cut():
    # "...its golden age yet. We haven't seen, no. We haven't even begun...": line one read again with a word added at
    # its end, then line two started, abandoned, and read again
    start, rest = ["alpha", 0.15, "bravo", 0.6] + ONE, TWO + [0.7] + THREE
    res, heard = edit(start + [0.05, "india", 0.7] + take(["delta", "echo", "juliet"]) + [0.6] + rest, LINES)
    assert heard == WITH_INDIA
    assert [(p["line"], p["problem"]) for p in res["pickups"]] == [(1, "added 'india'")]     # it stays with the line it closes
    # if it runs on into the take that is cut, it is the first word of that take; and three added words are an aside
    res, heard = edit(start + [0.05, "india", 0.05] + take(["delta", "echo"]) + [0.6] + rest, LINES)
    assert heard == AS_WRITTEN
    res, heard = edit(start + [0.05, "india", 0.05, "hotel", 0.05, "juliet", 0.7] + take(["delta", "echo"]) + [0.6] + rest, LINES)
    assert heard == AS_WRITTEN
    # and partway through a line it is left alone: before a pause and a pickup, a word is as likely a slip as an ad-lib
    res, heard = edit(ONE + [0.7, "delta", 0.15, "echo", 0.05, "india", 0.6, "foxtrot", 0.15, "juliet", 0.6,
                             "foxtrot", 0.15, "golf", 0.7] + THREE, LINES)
    assert heard == AS_WRITTEN


def test_earlier_take_is_spliced_in_only_when_comps_are_on():
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.3, "delta", 0.15, "echo", 0.15, "foxtrot", 0.8,
           "alpha", 0.15, "bravo", 0.15, "charlie", 0.3, "delta", 0.15, "golf", 0.15, "foxtrot"]   # "golf" is a slip
    x, words = synth(seq)
    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), Settings(), log=lambda *a: None)
    assert len(res["comps"]) == 1 and not res["pickups"]
    assert detect(res["audio"]) == NAMES[:6]

    last_take_only = Settings()
    last_take_only.comps = False
    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), last_take_only, log=lambda *a: None)
    assert not res["comps"] and len(res["pickups"]) == 1
    assert detect(res["audio"]) == "alpha bravo charlie delta golf foxtrot".split()


def test_word_left_out_of_the_last_take_stays_out_unless_a_comp_restores_it():
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.15, "delta", 0.15, "echo", 0.8,              # abandoned
           "alpha", 0.15, "bravo", 0.15, "delta", 0.15, "echo", 0.15, "foxtrot"]                   # no "charlie"
    x, words = synth(seq)
    last_take_only = Settings()
    last_take_only.comps = False
    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), last_take_only, log=lambda *a: None)
    assert detect(res["audio"]) == "alpha bravo delta echo foxtrot".split()    # the first take's "charlie" is not dropped in
    assert res["summary"]["words_cut"] == 5 and len(res["edl"]) == 1
    assert [p["problem"] for p in res["pickups"]] == ["missing 'charlie'"]

    res = build_edit(x, SR, words, lines_for([NAMES[:6]]), Settings(), log=lambda *a: None)
    assert len(res["comps"]) == 1 and not res["pickups"]                       # with comps, spliced at a pause instead
    assert detect(res["audio"]) == NAMES[:6]


def test_sound_at_the_voices_level_with_no_word_for_it_is_cut_unless_it_stands_where_a_word_should():
    quiet = lambda *a: None                                                    # noqa: E731
    seq = ["alpha", 0.15, "bravo", 0.15, "charlie", 0.6, "juliet", 0.5, "delta", 0.15, "echo", 0.15, "foxtrot"]
    x, words = synth(seq)
    heard = [w for w in words if w["text"] != "juliet"]                        # a cut-off syllable the recognizer passed over
    res = build_edit(x, SR, heard, lines_for([NAMES[:3], NAMES[3:6]]), Settings(), log=quiet)
    assert detect(res["audio"]) == NAMES[:6]                                   # it would have sat in the pause between the lines
    assert [c["why"] for c in res["cuts"]] == ["stray sound"] and res["summary"]["stray_sounds"] == 1
    assert res["summary"]["words_heard"] == 6 and res["summary"]["words_cut"] == 0 and not res["pickups"]

    # the same sound where the script has a word that nothing else was heard for: it is that word, and it stays
    x, words = synth(["alpha", 0.15, "bravo", 0.15, "charlie", 0.15, "delta"])
    res = build_edit(x, SR, [w for w in words if w["text"] != "charlie"], lines_for([NAMES[:4]]), Settings(), log=quiet)
    assert detect(res["audio"]) == NAMES[:4] and res["summary"]["stray_sounds"] == 0
    assert [p["problem"] for p in res["pickups"]] == ["read '[sound]' for 'charlie'"]


def test_ending_the_last_take_dropped_stays_out_when_the_last_take_is_kept_whole():
    line1, line2 = NAMES + MORE[:1], MORE[1:]              # eleven words, then "lima mike"
    seq = [w for word in line1 for w in (word, 0.15)][:-1] + [0.8]             # the whole line, then a change of mind
    seq += [w for word in line1[:6] for w in (word, 0.15)][:-1] + [0.7, "lima", 0.15, "mike"]   # re-read without its last five words
    x, words = synth(seq)
    as_read = Settings()
    as_read.comps = False
    res = build_edit(x, SR, words, lines_for([line1, line2]), as_read, log=lambda *a: None)
    assert detect(res["audio"]) == line1[:6] + line2                           # nothing of the abandoned take comes back
    assert all(b["raw_in"] > a["raw_out"] for a, b in zip(res["edl"], res["edl"][1:]))       # the edit never goes back in the recording
    assert [p["line"] for p in res["pickups"]] == [1] and "missing" in res["pickups"][0]["problem"]

    res = build_edit(x, SR, words, lines_for([line1, line2]), Settings(), log=lambda *a: None)
    assert detect(res["audio"]) == line1 + line2                               # by default the earlier ending completes the line
