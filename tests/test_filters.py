"""Links, emails, paths and codes are read in the short form chosen in Options."""
import pytest

from textreader import pronunciation
from textreader.pronunciation import FILTERS, apply, clean_filters, filter_example


def read(text, **choices):
    """What the speech engine is sent for `text`, with no word rules."""
    return apply(text, [], filters=clean_filters(choices))[0]


URL = "https://github.com/masonje/textReader/pull/6"
EMAIL = "jane.doe@example.com"
PATH = "/home/jane/projects/textReader/reader.py"
CODE = "6bb6c43f139d6d0111b6d152aaaf150bcfc26570"


@pytest.mark.parametrize("choice, expected", [
    ("site_end", "github.com path 6"),
    ("site", "github.com weblink"),
    ("link", "link"),
    ("full", URL),
])
def test_urls(choice, expected):
    assert read(URL, urls=choice) == expected


@pytest.mark.parametrize("choice, expected", [
    ("full", EMAIL),
    ("user", "jane doe"),
    ("name", "email to jane doe"),
    ("email", "email address"),
])
def test_emails(choice, expected):
    assert read(EMAIL, emails=choice) == expected


@pytest.mark.parametrize("choice, expected", [
    ("tail", "path slash textReader slash reader dot py"),
    ("file_path", "file path slash textReader slash reader.py"),
    ("name", "path to reader.py"),
    ("path", "file path"),
    ("full_slash", "file path home slash jane slash projects slash textReader slash reader.py"),
    ("full_words", "file path home jane projects textReader reader.py"),
])
def test_paths(choice, expected):
    assert read(PATH, paths=choice) == expected


@pytest.mark.parametrize("choice, expected", [
    ("length", "40 character code six five seven zero"),
    ("short", "code six bee bee six"),
    ("code", "code"),
    ("full", CODE),
])
def test_codes(choice, expected):
    assert read(CODE, codes=choice) == expected


def test_all_digit_code_says_digit():
    assert read("4111111111111111", codes="length") == "16 digit code one one one one"


@pytest.mark.parametrize("path, expected", [
    ("~/github/textReader/reader.py", "file path home slash github slash textReader slash reader.py"),
    ("../notes/todo.txt", "file path up a folder slash notes slash todo.txt"),
])
def test_full_path_words(path, expected):
    assert read(path, paths="full_slash") == expected


def test_drive_letter_path():
    assert read(r"C:\Users\jane\notes.txt", paths="full_words") == "file path C drive Users jane notes.txt"


def test_trailing_punctuation_is_kept_out_of_links():
    assert read(f"See {URL}.", urls="site_end") == "See github.com path 6."
    assert read(f"(see {URL})", urls="site_end") == "(see github.com path 6)"


def test_link_with_brackets_keeps_balanced_brackets():
    url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    assert read(url, urls="full") == url


@pytest.mark.parametrize("text", [
    "version 1.8.1 ships today",
    "call 555-1234 now",
    "the and/or choice",
    "a well-known example",
])
def test_ordinary_text_is_left_alone(text):
    assert read(text) == text


def test_examples_match_what_is_read():
    for kind, spec in FILTERS.items():
        for choice in spec["choices"]:
            assert filter_example(kind, choice) == read(spec["example"], **{kind: choice})


def test_clean_filters_falls_back_to_defaults():
    cleaned = clean_filters({"urls": "skip", "paths": "tail", "bogus": "x"})
    assert cleaned == {"urls": "site_end", "emails": "full", "paths": "tail", "codes": "length"}
    assert clean_filters(None) == {k: f["default"] for k, f in FILTERS.items()}


def test_every_kind_has_no_skip_choice():
    for spec in FILTERS.values():
        assert "skip" not in spec["choices"]
        assert spec["default"] in spec["choices"]


def test_filters_run_before_word_rules():
    rules = [pronunciation.new_rule("github", "say", "git hub")]
    spoken, _ = apply(f"Open {URL} on github", rules, filters=clean_filters({}))
    assert spoken == "Open github.com path 6 on git hub"
