"""Keyboard shortcut names: parsing, formatting and checking "Win+Shift+R" style strings."""

DEFAULT_HOTKEYS = {
    "read_selected_text": "Win+Esc",
    "play": "Win+Shift+R",
    "pause": "Win+Shift+P",
    "stop": "Win+Shift+S",
}
HOTKEY_ORDER = ("read_selected_text", "play", "pause", "stop")
HOTKEY_LABELS = {
    "read_selected_text": "Read Selected Text",
    "play": "Play/Resume",
    "pause": "Pause",
    "stop": "Stop",
}
MODIFIER_KEYS = {"win", "ctrl", "alt", "shift"}
KEY_ALIASES = {
    "cmd": "win",
    "command": "win",
    "super": "win",
    "windows": "win",
    "control": "ctrl",
    "escape": "esc",
    "return": "enter",
}

def normalize_hotkey_part(part):
    key_name = part.strip().lower()
    return KEY_ALIASES.get(key_name, key_name)

def parse_hotkey(hotkey):
    if not isinstance(hotkey, str):
        return None
    parts = [normalize_hotkey_part(part) for part in hotkey.split("+")]
    parts = [part for part in parts if part]
    combo = frozenset(parts)
    if not combo or all(part in MODIFIER_KEYS for part in combo):
        return None
    return combo

def format_hotkey(combo):
    display_names = {
        "win": "Win",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "esc": "Esc",
        "enter": "Enter",
        "space": "Space",
        "tab": "Tab",
        "backspace": "Backspace",
        "delete": "Delete",
    }
    ordered_parts = [part for part in ("win", "ctrl", "alt", "shift") if part in combo]
    ordered_parts.extend(sorted(part for part in combo if part not in MODIFIER_KEYS))
    return "+".join(display_names.get(part, part.upper() if len(part) == 1 else part.title()) for part in ordered_parts)

def hotkey_dropdown_values(hotkey):
    combo = parse_hotkey(hotkey) or parse_hotkey(DEFAULT_HOTKEYS["play"])
    modifier = "+".join(part for part in ("Win", "Ctrl", "Alt") if part.lower() in combo)
    if "shift" in combo:
        modifier = f"{modifier}+Shift" if modifier else "Shift"
    key = next((part for part in combo if part not in MODIFIER_KEYS), "r")
    return modifier or "Win", key.upper() if len(key) == 1 else key.title()

def build_hotkey_from_dropdowns(modifier, key):
    parts = [part.strip() for part in modifier.split("+") if part.strip()]
    parts.append(key.strip())
    return "+".join(parts)

def validate_hotkey_settings(candidate_hotkeys):
    normalized_hotkeys = {}
    parsed_hotkeys = {}
    errors = []
    for action in HOTKEY_ORDER:
        hotkey = candidate_hotkeys.get(action, DEFAULT_HOTKEYS[action])
        combo = parse_hotkey(hotkey)
        if combo is None:
            errors.append(f"{HOTKEY_LABELS[action]} needs a key like Win+Shift+R or Ctrl+Alt+P.")
            continue
        normalized_hotkeys[action] = format_hotkey(combo)
        parsed_hotkeys[action] = combo
    seen = {}
    for action, combo in parsed_hotkeys.items():
        if combo in seen:
            errors.append(f"{HOTKEY_LABELS[action]} duplicates {HOTKEY_LABELS[seen[combo]]}.")
        seen[combo] = action
    return normalized_hotkeys, errors

# What each shortcut's button does, for the hover hint
HOTKEY_HINTS = {
    "read_selected_text": "Read the selected text aloud (or the clipboard, if nothing is selected)",
    "play": "Play, or resume after a pause",
    "pause": "Pause reading",
    "stop": "Stop reading",
}

def hotkey_hint(action, current_hotkeys):
    """Hover hint for a button: what it does and the shortcut that does the same."""
    combo = parse_hotkey(current_hotkeys.get(action)) or parse_hotkey(DEFAULT_HOTKEYS[action])
    return f"{HOTKEY_HINTS[action]}\nShortcut: {format_hotkey(combo)}"
