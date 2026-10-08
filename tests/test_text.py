from punchroll.text import _markdown_blocks, build_lines, select_section, split_sentences, toks


def test_numbers_are_spoken():
    assert toks("In 1811, wages fell 31%.") == ["in", "eighteen", "eleven", "wages", "fell", "thirty", "one", "percent"]
    assert toks("$52,000 a year") == ["fifty", "two", "thousand", "dollars", "a", "year"]
    assert toks("$3.1 trillion") == ["three", "point", "one", "trillion", "dollars"]
    assert toks("the 1760s and the 20th century") == ["the", "seventeen", "sixties", "and", "the", "twentieth", "century"]
    assert toks("in the '90s") == ["in", "the", "nineties"]


def test_clock_times():
    assert toks("At 8:00 a.m. and 6:05 p.m.") == ["at", "eight", "a", "m", "and", "six", "oh", "five", "p", "m"]
    assert toks("They vote at 4:45.") == ["they", "vote", "at", "four", "forty", "five"]


def test_text_cleanup():
    assert toks("Mondragón’s café & bar") == ["mondragon's", "cafe", "and", "bar"]
    assert toks("post-labor, self-government") == ["post", "labor", "self", "government"]
    assert toks("Þingvellir, Søren, Straße") == ["thingvellir", "soren", "strasse"]


def test_sentence_split_keeps_abbreviations():
    s = split_sentences("Mr. Smith met the U.S. Navy at 6 a.m. Monday. Then he left! Did he? Yes.")
    assert s == ["Mr. Smith met the U.S. Navy at 6 a.m. Monday.", "Then he left!", "Did he?", "Yes."]


def test_markdown_blocks_skip_notes_tables_code():
    md = """---
title: x
---
# Chapter 1 {#ch1}

Text with a note.[^1] And a [link](http://x.y) and *emphasis*.
It wraps onto a second line.

| a | b |
|---|---|

```
code
```

[^1]: A footnote that is not read.
    More footnote.

## Section Two
- A list item.
"""
    blocks = _markdown_blocks(md.splitlines())
    assert blocks[0] == ("heading", "Chapter 1")
    assert blocks[1] == ("body", "Text with a note. And a link and emphasis. It wraps onto a second line.")
    assert ("heading", "Section Two") in blocks
    assert ("body", "A list item.") in blocks
    assert not any("footnote" in t or "code" in t for _, t in blocks)


def test_markdown_comments_are_not_read():
    md = "<!-- a note\nthat spans lines -->\n# Title\n\n<!-- one line -->\nBody text.\n"
    assert _markdown_blocks(md.splitlines()) == [("heading", "Title"), ("body", "Body text.")]


def test_select_section_and_lines():
    blocks = [("heading", "Chapter 1"), ("body", "One. Two."), ("heading", "Chapter 2"), ("body", "Three.")]
    sec = select_section(blocks, "Chapter 1", "Chapter 2")
    lines = build_lines(sec)
    assert [ln.text for ln in lines] == ["Chapter 1.", "One.", "Two."]
    assert lines[0].kind == "heading" and lines[0].is_title
    assert lines[0].tokens == ["chapter", "one"]
