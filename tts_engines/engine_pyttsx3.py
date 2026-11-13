from __future__ import annotations

import os
import threading
import time
from typing import List, Optional

from .base import SynthesisCancelled, TTSEngine, Voice

_pyttsx3_engine = None
_pyttsx3_lock = threading.Lock()


def _get_engine():
    global _pyttsx3_engine
    if _pyttsx3_engine is None:
        import pyttsx3

        _pyttsx3_engine = pyttsx3.init()
    return _pyttsx3_engine


def _wait_for_file(path: str, cancel_event: Optional[threading.Event], timeout: float = 120.0) -> None:
    """pyttsx3 may finish writing after runAndWait() returns; wait until the file stops growing."""
    last_size, stable_since = -1, None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cancel_event is not None and cancel_event.is_set():
            raise SynthesisCancelled()
        size = os.path.getsize(path) if os.path.exists(path) else -1
        if size > 0 and size == last_size:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 0.3:
                return
        else:
            stable_since = None
        last_size = size
        time.sleep(0.05)


def _is_english(voice) -> bool:
    langs = [str(lang).lower() for lang in (voice.languages or [])]
    return any(lang.startswith("en") and "shaw" not in lang for lang in langs)


class Pyttsx3Engine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="pyttsx3", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            missing.append("pyttsx3")
        return missing

    def list_voices(self) -> List[Voice]:
        """The system speech voices pyttsx3 can use (eSpeak on Linux, SAPI on Windows, NSSpeech on macOS)."""
        with _pyttsx3_lock:
            engine = _get_engine()
            voices = engine.getProperty("voices") or []
        english = [v for v in voices if _is_english(v)] or list(voices)
        result: List[Voice] = []
        for v in english:
            gender = (getattr(v, "gender", None) or "").lower()
            name = v.name[len("English ("):-1] if v.name.startswith("English (") and v.name.endswith(")") else v.name
            label = name + (f" ({gender})" if gender in ("male", "female") else "")
            result.append((v.id, label))
        # American English first when present
        result.sort(key=lambda item: (0 if item[0].endswith("/en-us") else 1, item[1]))
        return result

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        # Can't be interrupted mid-run; on cancel the caller discards the output.
        with _pyttsx3_lock:
            engine = _get_engine()
            try:
                engine.stop()
            except Exception:
                pass
            if voice:
                engine.setProperty("voice", voice)
            # Line breaks can make pyttsx3's eSpeak driver return before the file is written
            engine.save_to_file(" ".join(text.split()), output_path)
            engine.runAndWait()
        _wait_for_file(output_path, cancel_event)
