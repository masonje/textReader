"""Estimate when each word is spoken in a synthesized audio file.

None of the TTS engines report word timestamps, so this module estimates them:

1. Each word gets a weight from its length, plus extra weight after
   punctuation (speech engines pause there).
2. ffmpeg's silencedetect finds where speech really starts and ends, and the
   pauses in between.
3. Detected pauses are matched to the punctuation they most likely belong to,
   which pins the timeline back in place so errors don't build up over long text.

The result is a list of start times (seconds), one per word, that a UI can use
to highlight the word being spoken.
"""
from __future__ import annotations

import bisect
import re
import subprocess
from typing import List, Optional, Sequence, Tuple

WORD_RE = re.compile(r"\S+")

# Weight units are roughly "characters of speech".
WORD_GAP = 1.0          # small gap between every pair of words
SENTENCE_PAUSE = 6.0    # . ! ?
CLAUSE_PAUSE = 3.0      # , ; :
DASH_PAUSE = 1.5        # — – ) etc.
LINE_PAUSE = 6.0        # a line break

SILENCE_NOISE_DB = -35
SILENCE_MIN_SEC = 0.15


def tokenize(text: str) -> List[Tuple[int, int]]:
    """Return (start, end) character offsets for each word in `text`."""
    return [(m.start(), m.end()) for m in WORD_RE.finditer(text)]


def _word_weights(text: str, spans: Sequence[Tuple[int, int]]) -> Tuple[List[float], List[float]]:
    """Return (speech weight, pause-after weight) for each word."""
    speech, pauses = [], []
    for i, (start, end) in enumerate(spans):
        word = text[start:end]
        letters = sum(ch.isalnum() for ch in word)
        weight = max(letters, 1) + WORD_GAP
        digits = sum(ch.isdigit() for ch in word)
        if digits:
            weight += digits * 1.5  # numbers are read out as longer words
        speech.append(weight)

        stripped = word.rstrip("\"'”’)]}")
        tail = stripped[-1:] if stripped else ""
        pause = 0.0
        if tail in (".", "!", "?", "…"):
            pause = SENTENCE_PAUSE
        elif tail in (",", ";", ":"):
            pause = CLAUSE_PAUSE
        elif tail in ("—", "–", "-", ")"):
            pause = DASH_PAUSE
        next_start = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        if "\n" in text[end:next_start]:
            pause = max(pause, LINE_PAUSE)
        pauses.append(pause)
    return speech, pauses


def detect_silences(audio_path: str, timeout: float = 10.0) -> List[Tuple[float, Optional[float]]]:
    """Return (start, end) of silent stretches using ffmpeg. `end` is None if silence runs to the end."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-i", audio_path,
                "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_SEC}",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except Exception:
        return []
    silences: List[Tuple[float, Optional[float]]] = []
    start = None
    for line in result.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, None))
    return silences


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Piecewise-linear interpolation; xs must be increasing."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def build_timeline(
    text: str,
    duration: float,
    silences: Optional[Sequence[Tuple[float, Optional[float]]]] = None,
    spans: Optional[Sequence[Tuple[int, int]]] = None,
) -> List[float]:
    """Return the estimated start time (seconds) of every word in `text`."""
    spans = list(spans) if spans is not None else tokenize(text)
    if not spans or duration <= 0:
        return [0.0] * len(spans)
    speech, pauses = _word_weights(text, spans)

    # Cumulative units: word i starts at starts_u[i]; its pause starts at speech_end_u[i]
    starts_u, speech_end_u = [], []
    u = 0.0
    for s, p in zip(speech, pauses):
        starts_u.append(u)
        speech_end_u.append(u + s)
        u += s + p
    total_u = speech_end_u[-1]  # the last word's trailing pause isn't spoken

    # Trim leading and trailing silence
    speech_start, speech_end = 0.0, duration
    internal = []
    for s_start, s_end in silences or []:
        end = duration if s_end is None else s_end
        if s_start <= 0.05:
            speech_start = max(speech_start, end)
        elif s_end is None or end >= duration - 0.05:
            speech_end = min(speech_end, s_start)
        else:
            internal.append((s_start, end))
    if speech_end <= speech_start:
        speech_start, speech_end, internal = 0.0, duration, []

    # Anchor points mapping units -> seconds
    anchor_u = [0.0]
    anchor_t = [speech_start]
    # Candidate boundaries: after word i (only where text suggests a pause), strongest first on ties
    candidates = [i for i in range(len(spans) - 1) if pauses[i] > 0]
    for s_start, s_end in internal:
        if s_start <= anchor_t[-1]:
            continue
        mid = (s_start + s_end) / 2
        # Estimate boundary times by stretching between the last anchor and the end
        u0, t0 = anchor_u[-1], anchor_t[-1]
        span_u = max(total_u - u0, 1e-6)
        span_t = max(speech_end - t0, 1e-6)
        tolerance = 0.8 + 0.12 * (mid - t0)
        best, best_score = None, None
        for i in candidates:
            if speech_end_u[i] <= u0:
                continue
            est = t0 + (speech_end_u[i] - u0) / span_u * span_t
            if est - mid > tolerance:
                break  # candidates are in order; the rest are later still
            off = abs(est - mid)
            if off > tolerance:
                continue
            score = off / (1.0 + pauses[i] / SENTENCE_PAUSE)
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is None:
            continue  # a pause the text doesn't explain (e.g. an engine chunk break)
        anchor_u += [speech_end_u[best], starts_u[best + 1]]
        anchor_t += [s_start, s_end]
        candidates = [i for i in candidates if i > best]
    anchor_u.append(total_u)
    anchor_t.append(speech_end)

    return [_interp(u, anchor_u, anchor_t) for u in starts_u]


def word_at(timeline: Sequence[float], position: float) -> int:
    """Index of the word being spoken at `position` seconds (-1 before the first word)."""
    return bisect.bisect_right(timeline, position) - 1
