from __future__ import annotations

import threading
from typing import List

from .base import TTSEngine

_pyttsx3_engine = None
_pyttsx3_lock = threading.Lock()


def _get_engine():
    global _pyttsx3_engine
    if _pyttsx3_engine is None:
        import pyttsx3

        _pyttsx3_engine = pyttsx3.init()
    return _pyttsx3_engine


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

    def synthesize(self, text: str, output_path: str) -> None:
        engine = _get_engine()
        with _pyttsx3_lock:
            try:
                engine.stop()
            except Exception:
                pass
            engine.save_to_file(text, output_path)
            engine.runAndWait()
