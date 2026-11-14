"""Pronunciation rules: change how words, names, abbreviations and symbols are read aloud.

A rule matches some text and says what to do with it:

- "say":   read it as different text, e.g. "Nguyen" -> "win", "GIF" -> "jif"
- "spell": spell it out letter by letter, e.g. "SQL" -> "ess cue el"
- "skip":  don't read it at all, e.g. "[1]" footnote markers

Rules are plain dicts (saved in settings.json):

    {"text": "SQL", "mode": "spell", "say": "", "whole_word": true,
     "match_case": false, "engine": "", "enabled": true}

`engine` is "" for every engine, or one engine's name. The rules are applied
in a single pass (longest match first), so one rule's output is never changed
again by another rule.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

MODES = {"say": "Say it as", "spell": "Spell it out", "skip": "Don't read it"}

LETTER_NAMES = {
    "a": "ay", "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "eff", "g": "jee",
    "h": "aitch", "i": "eye", "j": "jay", "k": "kay", "l": "el", "m": "em", "n": "en",
    "o": "oh", "p": "pee", "q": "cue", "r": "ar", "s": "ess", "t": "tee", "u": "you",
    "v": "vee", "w": "double you", "x": "ex", "y": "why", "z": "zee",
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "&": "and", "@": "at", "#": "hash", "+": "plus", "%": "percent", "$": "dollar",
    "/": "slash", ".": "dot", "-": "dash", "_": "underscore",
}

Edit = Tuple[int, int, str]  # (start, end, replacement) in the original text

# ---- Filters for long things nobody wants spelled out: web links, email
# addresses, file paths and long codes (hashes, IDs). Each has a few ways to
# read it; "full" leaves it as written.

_TRAIL = ".,;:!?)]}>'\"”’"

URL_RE = re.compile(r"(?i)\b(?:https?://|ftp://|www\.)[^\s<>\"'`]+")
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
# Unix paths need a leading / with two or more parts (so "and/or" and "1/2" are left
# alone), or start with ~/ ./ ../ ; Windows paths start with a drive letter.
PATH_RE = re.compile(
    r"(?<![\w/:.~])(?:(?:~|\.\.?)(?:/[^\s/<>\"'`|]+)+/?|(?:/[^\s/<>\"'`|]+){2,}/?)"
    r"|\b[A-Za-z]:\\(?:[^\s\\<>\"'`|]+\\?)*"
)
# Codes: letters and digits run together, 12+ characters with at least 2 digits (git hashes,
# UUIDs, tracking numbers, licence keys, account numbers). Parts may be joined by - or _.
CODE_RE = re.compile(r"(?<![\w-])(?=(?:[\w-]*?\d){2})[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*(?![\w-])")

FILTERS = {
    "urls": {
        "label": "Web links",
        "example": "https://github.com/masonje/textReader/pull/6",
        "choices": {"site_end": "Site and last part: “github.com path 6”",
                    "site": "Site and “weblink”: “github.com weblink”", "link": "Just say “link”",
                    "full": "Read it in full"},
        "default": "site_end",
    },
    "emails": {
        "label": "Email addresses",
        "example": "jane.doe@example.com",
        "choices": {"full": "Read it in full", "user": "Just the name before the @: “jane doe”",
                    "name": "Email to the name: “email to jane doe”",
                    "email": "Just say “email address”"},
        "default": "full",
    },
    "paths": {
        "label": "File paths",
        "example": "/home/jane/projects/textReader/reader.py",
        "choices": {"tail": "Folder and file: “path slash textReader slash reader dot py”",
                    "file_path": "File path: “file path slash textReader slash reader.py”",
                    "name": "Say the file name: “path to reader.py”", "path": "Just say “file path”",
                    "full_slash": "In full, saying slashes: “file path home slash jane slash … slash reader.py”",
                    "full_words": "In full, no slashes: “file path home jane projects textReader reader.py”"},
        "default": "tail",
    },
    "codes": {
        "label": "Long codes",
        "example": "6bb6c43f139d6d0111b6d152aaaf150bcfc26570",  # a git commit
        "choices": {"length": "Length and last 4: “40 character code six five seven zero”",
                    "short": "Say the first 4: “code six bee bee six”", "code": "Just say “code”",
                    "full": "Read it in full"},
        "default": "length",
    },
}


def clean_filters(raw) -> Dict[str, str]:
    """Filter settings from settings.json, with defaults for anything missing or unknown."""
    raw = raw if isinstance(raw, dict) else {}
    return {name: (raw.get(name) if raw.get(name) in f["choices"] else f["default"])
            for name, f in FILTERS.items()}


def _strip_trailing(text: str, start: int, end: int) -> int:
    """Move `end` back over punctuation that ends the sentence rather than the link."""
    while end > start and text[end - 1] in _TRAIL:
        # Keep a closing bracket that has its opening one inside, e.g. wiki/Foo_(bar)
        ch = text[end - 1]
        pair = {")": "(", "]": "[", "}": "{"}.get(ch)
        if pair and text.count(pair, start, end) >= text.count(ch, start, end):
            break
        end -= 1
    return end


def _say_part(part: str) -> str:
    """A file or folder name read clearly: 'reader.py' -> 'reader dot py'."""
    return " dot ".join(p for p in part.split(".") if p) or part


def _say_filtered(kind: str, choice: str, matched: str) -> str:
    if kind == "urls":
        if choice == "link":
            return "link"
        rest = re.sub(r"(?i)^(?:https?://|ftp://)", "", matched)
        host = rest.split("/")[0].split("?")[0].split("#")[0]
        host = re.sub(r"(?i)^www\.", "", host.split("@")[-1].split(":")[0])
        if not host:
            return "link"
        if choice == "site_end":
            path = re.split(r"[?#]", rest, maxsplit=1)[0]
            parts = [p for p in path.split("/")[1:] if p]
            return f"{host} path {_say_part(parts[-1])}" if parts else host
        return f"{host} weblink"
    if kind == "emails":
        if choice == "email":
            return "email address"
        # The part before the @ as words: "jane.doe_99" -> "jane doe 99"
        name = " ".join(w for w in re.split(r"[._+\-]+", matched.split("@")[0]) if w) or "email"
        return name if choice == "user" else f"email to {name}"
    if kind == "paths":
        if choice == "path":
            return "file path"
        parts = [p for p in re.split(r"[/\\]", matched)
                 if p and p not in ("~", ".", "..") and not re.fullmatch(r"[A-Za-z]:", p)]
        if not parts:
            return "file path"
        if choice == "tail":
            return "path slash " + " slash ".join(_say_part(p) for p in parts[-2:])
        if choice == "file_path":
            return "file path slash " + " slash ".join(parts[-2:])
        if choice in ("full_slash", "full_words"):
            # Every folder, read as words: "~" is home, "C:" is "C drive", ".." is "up a folder"
            words = []
            for p in re.split(r"[/\\]", matched):
                if p in ("", "."):
                    continue
                words.append({"~": "home", "..": "up a folder"}.get(p) or
                             (f"{p[0].upper()} drive" if re.fullmatch(r"[A-Za-z]:", p) else p))
            return "file path " + (" slash " if choice == "full_slash" else " ").join(words)
        return f"path to {parts[-1]}"
    if kind == "codes":
        if choice == "code":
            return "code"
        chars = re.sub(r"[^0-9A-Za-z]", "", matched)
        if choice == "length":
            kind_word = "digit" if chars.isdigit() else "character"
            return f"{len(chars)} {kind_word} code {spell_out(chars[-4:])}"
        return "code " + spell_out(chars[:4])
    return matched


def find_filter_edits(text: str, filters: Optional[Dict[str, str]]) -> List[Edit]:
    """Edits for links, emails, paths and codes, per the filter settings (first match wins)."""
    if not filters or not text:
        return []
    edits: List[Edit] = []
    taken: List[Tuple[int, int]] = []
    for kind, regex in (("urls", URL_RE), ("emails", EMAIL_RE), ("paths", PATH_RE), ("codes", CODE_RE)):
        choice = filters.get(kind, "full")
        for m in regex.finditer(text):
            start, end = m.start(), _strip_trailing(text, m.start(), m.end())
            if end <= start or any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            if kind == "codes" and sum(ch.isalnum() for ch in text[start:end]) < 12:
                continue
            # Everything found is claimed (even "read in full") so later filters don't split it
            taken.append((start, end))
            if choice != "full":
                edits.append((start, end, _say_filtered(kind, choice, text[start:end])))
    return sorted(edits)


def filter_example(kind: str, choice: str) -> str:
    """What the filter's example sounds like with `choice`."""
    example = FILTERS[kind]["example"]
    if choice == "full":
        return example
    said = _say_filtered(kind, choice, example)
    return said if said else "(not read)"


def new_rule(text: str = "", mode: str = "say", say: str = "") -> Dict[str, object]:
    return {"text": text, "mode": mode, "say": say, "whole_word": True,
            "match_case": False, "engine": "", "enabled": True}


def clean_rules(raw) -> List[Dict[str, object]]:
    """Validate rules loaded from settings, dropping anything malformed."""
    rules = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        rule = new_rule()
        rule.update({k: item[k] for k in rule if k in item})
        rule["text"] = str(rule["text"]).strip()
        rule["say"] = str(rule.get("say") or "")
        if rule["mode"] not in MODES:
            rule["mode"] = "say"
        for flag in ("whole_word", "match_case", "enabled"):
            rule[flag] = bool(rule[flag])
        rule["engine"] = str(rule.get("engine") or "")
        rules.append(rule)
    return rules


def spell_out(text: str) -> str:
    """'SQL' -> 'ess cue el'; characters without a name are left out."""
    names = [LETTER_NAMES.get(ch.lower()) for ch in text]
    return " ".join(n for n in names if n)


def replacement_for(rule: Dict[str, object], matched: str) -> str:
    mode = rule.get("mode")
    if mode == "spell":
        return spell_out(matched)
    if mode == "skip":
        return ""
    return str(rule.get("say") or "")


def describe(rule: Dict[str, object]) -> str:
    """Short text for the rule list, e.g. 'spelled: ess cue el'."""
    mode = rule.get("mode")
    if mode == "spell":
        return f"spelled: {spell_out(str(rule['text']))}"
    if mode == "skip":
        return "(not read)"
    return str(rule.get("say") or "")


def active_rules(rules: Sequence[Dict[str, object]], engine: Optional[str]) -> List[Dict[str, object]]:
    return [r for r in rules if r.get("enabled", True) and str(r.get("text", "")).strip()
            and (not r.get("engine") or r.get("engine") == engine)]


def _pattern(rule: Dict[str, object]) -> str:
    body = re.escape(str(rule["text"]))
    if not rule.get("match_case"):
        body = f"(?i:{body})"
    text = str(rule["text"])
    if rule.get("whole_word", True):
        # Only guard the edges that are letters or digits: "cat" mustn't match inside
        # "concatenate", but a symbol like "[1]" or "&" may sit right against a word.
        if re.match(r"\w", text[0]):
            body = rf"(?<!\w){body}"
        if re.match(r"\w", text[-1]):
            body = rf"{body}(?!\w)"
    return body


def find_edits(text: str, rules: Sequence[Dict[str, object]], engine: Optional[str] = None) -> List[Edit]:
    """Where the rules change `text`: a list of (start, end, replacement), in order."""
    rules = active_rules(rules, engine)
    if not rules or not text:
        return []
    # Longest text first so "New York City" wins over "New York"
    ordered = sorted(rules, key=lambda r: -len(str(r["text"])))
    regex = re.compile("|".join(f"(?P<r{i}>{_pattern(r)})" for i, r in enumerate(ordered)))
    edits = []
    for m in regex.finditer(text):
        if m.end() == m.start():
            continue
        rule = ordered[int(m.lastgroup[1:])]
        edits.append((m.start(), m.end(), replacement_for(rule, m.group(0))))
    return edits


def apply_edits(text: str, edits: Sequence[Edit]) -> str:
    out, pos = [], 0
    for start, end, replacement in edits:
        out.append(text[pos:start])
        if replacement:
            # Keep words apart: "C++is" shouldn't run the replacement into the next word
            before = text[start - 1:start] if start else ""
            after = text[end:end + 1]
            pad_left = " " if before and not before.isspace() and before.isalnum() else ""
            pad_right = " " if after and after.isalnum() else ""
            out.append(f"{pad_left}{replacement}{pad_right}")
        pos = end
    out.append(text[pos:])
    spoken = "".join(out)
    spoken = re.sub(r"[ \t]{2,}", " ", spoken)
    # Skipped items can leave "See , or ." behind: drop the stray space and doubled commas
    spoken = re.sub(r"[ \t]+([,.;:!?])", r"\1", spoken)
    return re.sub(r",\s*([,.;:!?])", r"\1", spoken)


def apply(
    text: str,
    rules: Sequence[Dict[str, object]],
    engine: Optional[str] = None,
    filters: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[Edit]]:
    """Return (text to send to the speech engine, edits made).

    Links, emails, paths and codes are handled first; rules apply to the rest.
    """
    filtered = find_filter_edits(text, filters)
    edits = find_edits(text, rules, engine)
    if filtered:
        edits = sorted(filtered + [e for e in edits
                                   if not any(e[0] < f[1] and e[1] > f[0] for f in filtered)])
    return (apply_edits(text, edits) if edits else text), edits


def spoken_words(text: str, spans: Sequence[Tuple[int, int]], edits: Sequence[Edit]) -> List[str]:
    """What is actually said for each word of the original text (used to time the highlighting).

    An edit that covers several words is credited to the first of them.
    """
    if not edits:
        return [text[s:e] for s, e in spans]
    result = []
    for start, end in spans:
        parts, pos = [], start
        for e_start, e_end, replacement in edits:
            if e_end <= start or e_start >= end:
                continue
            parts.append(text[pos:max(pos, e_start)])
            if e_start >= start:
                parts.append(f" {replacement} ")
            pos = max(pos, e_end)
        parts.append(text[pos:end] if pos < end else "")
        result.append(" ".join("".join(parts).split()))
    return result
