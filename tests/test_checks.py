"""The checks on a finished file: read it back against its mark-up, and find cut words that were never said again."""
from punchroll import checks


def words(text, start=0.0, step=0.4):
    return [{"text": w, "start": start + k * step, "end": start + k * step + 0.3} for k, w in enumerate(text.split())]


MARKUP = """# take.wav

<!--
Mark-up: what is not struck is what the finished file holds.
-->

0:01.0  ~~The system receives R D. {1.76}~~

0:04.0  The system receives a reward or penalty. {0.75} ~~{sound 0.02 -28}~~ {0.20}

0:08.0  ~~Here, hang on.~~ It learns {0.30} from EU V light.
"""


def test_kept_words_skip_whatever_is_struck():
    assert checks.kept_words(MARKUP) == "the system receives a reward or penalty it learns from eu v light".split()


def test_readback_finds_a_lost_word_and_marks_a_respelling():
    joins = [{"clean_in": 0.0}, {"clean_in": 3.0}]
    spelled = checks.readback(MARKUP, words("The system receives a reward or penalty. It learns from EUV light."), joins)
    assert [(r["kept"], r["heard"], r["spelling"]) for r in spelled] == [("eu v", "euv", True)]
    lost = checks.readback(MARKUP, words("The system receives a or penalty. It learns from EU V light."), joins)
    assert [(r["kept"], r["heard"], r["spelling"]) for r in lost] == [("reward", "", False)]
    assert lost[0]["nearest_join"] is not None


def test_a_retake_is_not_lost_but_an_aside_is():
    finished = words("The wish is granted exactly as he stated it.")
    retake = words("The wish is granted exactly as he stated. The wish is granted exactly as he stated it.")
    assert checks.lost_words(retake, finished) == []
    aside = words("The wish is granted exactly as he stated. God, that's bad. The wish is granted exactly as he stated it.")
    rows = checks.lost_words(aside, finished)
    assert len(rows) == 1 and "god that's bad" in rows[0]["cut"]
