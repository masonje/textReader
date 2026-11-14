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
    return re.sub(r"[ \t]{2,}", " ", spoken)


def apply(text: str, rules: Sequence[Dict[str, object]], engine: Optional[str] = None) -> Tuple[str, List[Edit]]:
    """Return (text to send to the speech engine, edits made)."""
    edits = find_edits(text, rules, engine)
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
