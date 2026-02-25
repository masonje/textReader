from __future__ import annotations

from typing import List

from .base import TTSEngine


class GTTSEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="gTTS", output_ext="mp3")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        try:
            import gtts  # noqa: F401
        except Exception:
            missing.append("gTTS")
        return missing

    def synthesize(self, text: str, output_path: str) -> None:
        from gtts import gTTS

        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(output_path)
