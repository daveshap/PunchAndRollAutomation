from punchroll.align import Aligner, harmonize, last_take


def kept(hyp_text: str, lines: list[str], free=(), whole=False):
    hyp = hyp_text.split()
    line_toks = [ln.split() for ln in lines]
    script, sent_of = [], []
    for k, lt in enumerate(line_toks):
        script += lt
        sent_of += [k] * len(lt)
    ev, _ = Aligner(hyp, script, free_jumps=free).run()
    info = last_take(ev, hyp, sent_of, whole)
    return [i for i in range(len(hyp)) if info[i]["kept"]], hyp, info


def kept_words(hyp_text, lines):
    idx, hyp, _ = kept(hyp_text, lines)
    return " ".join(hyp[i] for i in idx)


def test_repeated_phrase_is_a_restart_and_last_reading_wins():
    idx, hyp, _ = kept("in each case in each case new industries emerged", ["in each case new industries emerged"])
    assert " ".join(hyp[i] for i in idx) == "in each case new industries emerged"
    assert idx[0] == 3                                    # the second reading was kept


def test_sentence_retake():
    lines = ["the sun rose", "the birds sang loudly", "we went home"]
    read = "the sun rose the birds sang the birds sang loudly we went home"
    assert kept_words(read, lines) == "the sun rose the birds sang loudly we went home"


def test_fillers_and_asides_between_lines_are_cut():
    lines = ["the economy grew", "wages did not"]
    read = "the um economy grew let me try that again wages did not"
    assert kept_words(read, lines) == "the economy grew wages did not"


def test_stray_word_before_a_restart_is_cut():
    lines = ["the office workers of the nineteen eighties saw computers arrive"]
    read = "the office workers of the eighteen the office workers of the nineteen eighties saw computers arrive"
    assert kept_words(read, lines) == "the office workers of the nineteen eighties saw computers arrive"


def test_word_the_later_take_left_out_is_not_patched_in_from_the_earlier_one():
    lines = ["a radiologist and a truck driver occupy different rungs", "both are exposed"]
    read = ("a radiologist and a truck driver occupy indire "
            "a radiologist and truck driver occupy different rungs both are exposed")
    idx, hyp, _ = kept(read, lines)
    assert " ".join(hyp[i] for i in idx) == "a radiologist and truck driver occupy different rungs both are exposed"
    assert idx[0] == 8                                    # nothing of the first take is left

    # the same for a phrase
    first = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    lines = [first, "red green blue"]
    idx, hyp, _ = kept(first + " one two three four five eleven twelve thirteen fourteen fifteen red green blue", lines)
    assert " ".join(hyp[i] for i in idx) == "one two three four five eleven twelve thirteen fourteen fifteen red green blue"
    assert idx[0] == 15

    # and for the last word of a line, when the take reads on into the next line
    assert kept_words(first + " eleven twelve thirteen fourteen red green blue", lines) == (
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen red green blue")

    # but a take that stops partway and moves on replaces only what it re-read
    assert kept_words(first + " one two three four five red green blue", lines) == (
        "six seven eight nine ten eleven twelve thirteen fourteen fifteen one two three four five red green blue")


def test_with_the_last_take_kept_whole_an_ending_it_dropped_stays_out():
    first = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    lines = [first, "red green blue", "cyan pink"]
    read = first + " no that part goes one two three four five six red green blue cyan pink"
    idx, hyp, info = kept(read, lines, whole=True)
    assert " ".join(hyp[i] for i in idx) == "one two three four five six red green blue cyan pink"
    assert {info[i]["why"] for i in range(6, 15)} == {"left out of the last take"}
    # only the sentence the take was in: a whole sentence it jumps over keeps the reading it had
    longer = [first, "red green blue", "cyan pink mauve teal", "the end comes"]
    idx, hyp, _ = kept(first + " red green blue cyan pink mauve teal one two three four five six cyan pink mauve teal the end comes",
                       longer, whole=True)
    assert " ".join(hyp[i] for i in idx) == "red green blue one two three four five six cyan pink mauve teal the end comes"
    # and without the flag the earlier ending completes the line, as before
    idx, hyp, _ = kept(read, lines)
    assert " ".join(hyp[i] for i in idx) == (
        "seven eight nine ten eleven twelve thirteen fourteen fifteen one two three four five six red green blue cyan pink")


def test_pickup_recorded_later_replaces_the_flawed_line():
    lines = ["first line here", "second line is tricky", "third line ends it"]
    read = "first line here second lime is tracky third line ends it second line is tricky"
    idx, hyp, info = kept(read, lines, free=[11])          # the pickup file starts at token 11
    assert " ".join(hyp[i] for i in idx) == "first line here third line ends it second line is tricky"
    assert set(range(3, 7)).isdisjoint(idx)               # the flawed reading is gone


def test_harmonize_compounds():
    lines, hyp, hw = harmonize([["chatgpt", "grew"], ["cow", "paths"]], ["chat", "gpt", "grew", "cowpaths"], [0, 1, 2, 3])
    assert lines == [["chat", "gpt", "grew"], ["cow", "paths"]]
    assert hyp == ["chat", "gpt", "grew", "cow", "paths"] and hw == [0, 1, 2, 3, 3]
