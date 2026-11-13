from __future__ import annotations

import threading
from typing import List, Optional

from .base import SynthesisCancelled, TTSEngine, Voice

# gTTS has one voice per language, but the Google domain changes the accent.
ACCENTS: List[Voice] = [
    ("com", "US English"),
    ("co.uk", "British English"),
    ("com.au", "Australian English"),
    ("ca", "Canadian English"),
    ("co.in", "Indian English"),
    ("ie", "Irish English"),
    ("co.za", "South African English"),
    ("com.ng", "Nigerian English"),
]


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

    def list_voices(self) -> List[Voice]:
        return list(ACCENTS)

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        from gtts import gTTS

        tts = gTTS(text=text, lang="en", tld=voice or "com", slow=False)
        # gTTS fetches audio one text chunk at a time; check for cancel between chunks.
        with open(output_path, "wb") as f:
            for chunk in tts.stream():
                if cancel_event is not None and cancel_event.is_set():
                    raise SynthesisCancelled()
                f.write(chunk)
