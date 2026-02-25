from __future__ import annotations

import threading
from typing import List

from .base import TTSEngine

_coqui_engine = None
_coqui_lock = threading.Lock()


def _get_engine():
    global _coqui_engine
    if _coqui_engine is None:
        from TTS.api import TTS as CoquiTTS

        _coqui_engine = CoquiTTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)
    return _coqui_engine


class CoquiEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Coqui TTS", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        try:
            import TTS  # noqa: F401
        except Exception:
            missing.append("TTS")
        return missing

    def synthesize(self, text: str, output_path: str) -> None:
        engine = _get_engine()
        with _coqui_lock:
            engine.tts_to_file(text=text, file_path=output_path)
