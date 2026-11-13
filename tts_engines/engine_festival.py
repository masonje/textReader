from __future__ import annotations

import glob
import os
import shutil
import threading
from typing import Dict, List, Optional

from .base import TTSEngine, Voice, run_cancellable

VOICE_DIRS = ["/usr/share/festival/voices", "/usr/lib/festival/voices", "/usr/local/share/festival/voices"]


class FestivalEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Festival", output_ext="wav")
        self.about = "The Festival Speech Synthesis System from the University of Edinburgh. Diphone voices: fast, intelligible, and robotic."
        self.quality = 1

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("text2wave") is None:
            missing.append("festival (system package)")
        return missing

    def list_voices(self) -> List[Voice]:
        """Installed Festival voices (e.g. kal_diphone from festvox-kallpc16k)."""
        voices: List[Voice] = []
        for base in VOICE_DIRS:
            for path in sorted(glob.glob(os.path.join(base, "*", "*"))):
                name = os.path.basename(path)
                if os.path.isdir(path) and name not in (v for v, _ in voices):
                    speaker, _, kind = name.partition("_")
                    voices.append((name, f"{speaker.upper()} ({kind})" if kind else speaker))
        return voices

    def describe_voice(self, voice_id: Optional[str]) -> Dict[str, str]:
        name = voice_id or "default"
        speaker, _, kind = name.partition("_")
        return {"Voice": speaker.upper(), "Type": kind or "—", "Gender": "Male" if speaker in ("kal", "ked", "rab", "don") else "—",
                "Accent": "American English" if speaker in ("kal", "ked") else "—",
                "Runs": "Offline, on this computer", "Audio": "WAV, 16 kHz mono" if "16k" in name or speaker == "kal" else "WAV"}

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        cmd = ["text2wave", "-o", output_path]
        if voice and voice.replace("_", "").isalnum():
            cmd += ["-eval", f"(voice_{voice})"]
        run_cancellable(cmd, cancel_event, input_text=text)
