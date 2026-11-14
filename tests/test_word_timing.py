"""Word highlight timing for the Full view."""
from textreader.word_timing import build_timeline, tokenize, word_at


def test_tokenize():
    assert tokenize("Hi  there,\nfriend") == [(0, 2), (4, 10), (11, 17)]


def test_timeline_is_increasing_and_inside_the_audio():
    text = "One two three. Four, five six."
    timeline = build_timeline(text, 5.0)
    assert len(timeline) == 6
    assert timeline[0] == 0.0
    assert all(a < b for a, b in zip(timeline, timeline[1:]))
    assert timeline[-1] < 5.0


def test_sentence_end_adds_a_pause():
    text = "aa bb. cc dd"
    t = build_timeline(text, 4.0)
    gaps = [b - a for a, b in zip(t, t[1:])]
    assert gaps[1] > gaps[0] and gaps[1] > gaps[2]


def test_words_that_are_not_read_take_almost_no_time():
    text = "Hello [1] world"
    plain = build_timeline(text, 3.0)
    skipped = build_timeline(text, 3.0, spoken=["Hello", "", "world"])
    assert (skipped[2] - skipped[1]) < (plain[2] - plain[1])


def test_longer_replacements_take_longer():
    text = "See SQL here"
    as_written = build_timeline(text, 3.0)
    spelled = build_timeline(text, 3.0, spoken=["See", "ess cue el", "here"])
    assert (spelled[2] - spelled[1]) > (as_written[2] - as_written[1])


def test_empty_text_or_audio():
    assert build_timeline("", 3.0) == []
    assert build_timeline("a b", 0) == [0.0, 0.0]


def test_word_at():
    timeline = [0.0, 1.0, 2.5]
    assert word_at(timeline, -0.1) == -1
    assert word_at(timeline, 0.0) == 0
    assert word_at(timeline, 1.7) == 1
    assert word_at(timeline, 9.0) == 2
