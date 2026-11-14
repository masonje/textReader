"""Keyboard shortcut strings."""
from textreader.hotkeys import (DEFAULT_HOTKEYS, build_hotkey_from_dropdowns, format_hotkey, hotkey_hint,
                                hotkey_dropdown_values, parse_hotkey, validate_hotkey_settings)


def test_parse_and_format_round_trip():
    assert format_hotkey(parse_hotkey("shift+win+r")) == "Win+Shift+R"
    assert format_hotkey(parse_hotkey("Ctrl+Alt+escape")) == "Ctrl+Alt+Esc"


def test_modifiers_alone_are_not_a_shortcut():
    assert parse_hotkey("Win+Shift") is None
    assert parse_hotkey("") is None
    assert parse_hotkey(None) is None


def test_dropdowns():
    assert hotkey_dropdown_values("Win+Shift+R") == ("Win+Shift", "R")
    assert build_hotkey_from_dropdowns("Ctrl+Alt", "P") == "Ctrl+Alt+P"


def test_defaults_are_valid():
    normalized, errors = validate_hotkey_settings(DEFAULT_HOTKEYS)
    assert errors == []
    assert normalized == DEFAULT_HOTKEYS


def test_duplicates_and_bad_keys_are_reported():
    _, errors = validate_hotkey_settings({**DEFAULT_HOTKEYS, "pause": "Win+Shift+R", "stop": "Win"})
    assert any("duplicates" in e for e in errors)
    assert any("Stop needs a key" in e for e in errors)


def test_hover_hint_shows_the_current_shortcut():
    assert hotkey_hint("stop", DEFAULT_HOTKEYS) == "Stop reading\nShortcut: Win+Shift+S"
    changed = {**DEFAULT_HOTKEYS, "play": "ctrl+alt+p"}
    assert hotkey_hint("play", changed).endswith("Shortcut: Ctrl+Alt+P")


def test_hover_hint_falls_back_to_the_default():
    assert hotkey_hint("read_selected_text", {}).endswith("Shortcut: Win+Esc")
    assert hotkey_hint("pause", {"pause": "Win"}).endswith("Shortcut: Win+Shift+P")
