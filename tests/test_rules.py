"""Word rules from the Pronunciations tab."""
from textreader.pronunciation import (apply, clean_rules, describe, new_rule, replacement_for,
                                      spell_out, spoken_words)
from textreader.word_timing import tokenize


def rule(text, mode="say", say="", **options):
    r = new_rule(text, mode, say)
    r.update(options)
    return r


def read(text, *rules, engine=None):
    return apply(text, list(rules), engine)[0]


def test_say_it_as():
    assert read("Nguyen called.", rule("Nguyen", say="win")) == "win called."


def test_spell_it_out():
    assert read("Run the SQL query", rule("SQL", "spell")) == "Run the ess cue el query"
    assert spell_out("A1") == "ay one"


def test_skip_leaves_no_stray_space_before_punctuation():
    assert read("See York[1], then go.", rule("[1]", "skip")) == "See York, then go."


def test_whole_word_only():
    gif = rule("GIF", say="jif")
    assert read("a GIF file", gif) == "a jif file"
    assert read("GIFT shop", gif) == "GIFT shop"
    # Replacements are padded so they never run into the next word
    assert read("GIFT shop", rule("GIF", say="jif", whole_word=False)) == "jif T shop"


def test_whole_word_with_symbols_next_to_a_word():
    # A rule that starts with a symbol still matches when it's stuck to the word before it
    assert read("New York[1] is big", rule("[1]", "skip")) == "New York is big"


def test_match_case():
    rx = rule("Rx", say="prescription", match_case=True)
    assert read("Rx filled", rx) == "prescription filled"
    assert read("RX filled", rx) == "RX filled"
    assert read("RX filled", rule("Rx", say="prescription")) == "prescription filled"


def test_longest_rule_wins():
    rules = [rule("New", say="knew"), rule("New York", say="the big apple")]
    assert read("New York and New Jersey", *rules) == "the big apple and knew Jersey"


def test_turned_off_rules_and_other_engines_are_ignored():
    assert read("GIF", rule("GIF", say="jif", enabled=False)) == "GIF"
    piper_only = rule("GIF", say="jif", engine="Piper")
    assert read("GIF", piper_only, engine="Piper") == "jif"
    assert read("GIF", piper_only, engine="gTTS") == "GIF"


def test_replacement_and_description():
    assert replacement_for(rule("SQL", "spell"), "SQL") == "ess cue el"
    assert describe(rule("SQL", "spell")) == "spelled: ess cue el"
    assert describe(rule("[1]", "skip")) == "(not read)"


def test_clean_rules_drops_bad_entries():
    cleaned = clean_rules([{"text": "GIF", "mode": "say", "say": "jif"}, {"text": ""}, "junk", None])
    assert [r["text"] for r in cleaned] == ["GIF"]
    assert cleaned[0]["whole_word"] is True and cleaned[0]["enabled"] is True


def test_spoken_words_follow_the_replacement():
    text = "Ask Nguyen now"
    spoken, edits = apply(text, [rule("Nguyen", say="win")])
    assert spoken_words(text, tokenize(text), edits) == ["Ask", "win", "now"]
