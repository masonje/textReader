from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

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
        self.about = "Google Translate's text-to-speech. A clear, natural female voice; the accent changes with the Google domain."
        self.quality = 3
        self.needs_internet = True
        self.service = "Google"

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        try:
            import gtts  # noqa: F401
        except Exception:
            missing.append("gTTS")
        return missing

    def list_voices(self) -> List[Voice]:
        return list(ACCENTS)

    def describe_voice(self, voice_id: Optional[str]) -> Dict[str, str]:
        accent = dict(ACCENTS).get(voice_id or "com", voice_id or "")
        return {
            "Gender": "Female",
            "Accent": accent,
            "Runs": "Online (Google servers)",
            "Audio": "MP3, 24 kHz mono",
            "Service": f"translate.google.{voice_id or 'com'}",
        }

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        from gtts import gTTS

        tts = gTTS(text=text, lang="en", tld=voice or "com", slow=False)
        # Google sometimes answers without any audio (usually when it's limiting requests).
        # gTTS doesn't treat that as an error, so check, and retry once after a short pause.
        for attempt in range(2):
            written = 0
            # gTTS fetches audio one text chunk at a time; check for cancel between chunks.
            with open(output_path, "wb") as f:
                for chunk in tts.stream():
                    if cancel_event is not None and cancel_event.is_set():
                        raise SynthesisCancelled()
                    f.write(chunk)
                    written += len(chunk)
            if written:
                return
            if attempt == 0:
                for _ in range(15):
                    if cancel_event is not None and cancel_event.is_set():
                        raise SynthesisCancelled()
                    time.sleep(0.1)
        raise RuntimeError("Google's text-to-speech sent back no audio. It may be limiting requests for "
                           "a few minutes; try again shortly or use another engine.")
