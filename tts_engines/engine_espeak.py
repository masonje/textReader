from __future__ import annotations

import shutil
import subprocess
import threading
from typing import List, Optional

from .base import TTSEngine, Voice, run_cancellable

# Shown first, in this order, when installed. "+f3" is eSpeak's female variant.
PREFERRED = [
    ("en-us", "America (male)"),
    ("en-us+f3", "America (female)"),
    ("en-gb", "Great Britain (male)"),
    ("en-gb+f3", "Great Britain (female)"),
]


def short_label(name: str) -> str:
    """All voices here are English, so "English (Scotland)" reads better as "Scotland"."""
    if name.startswith("English (") and name.endswith(")"):
        return name[len("English ("):-1]
    return name


class EspeakEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="eSpeak-NG", output_ext="wav")
        self._voices: Optional[List[Voice]] = None

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("espeak-ng") is None:
            missing.append("espeak-ng (system package)")
        return missing

    def list_voices(self) -> List[Voice]:
        if self._voices is not None:
            return self._voices
        voices: List[Voice] = []
        try:
            out = subprocess.run(
                ["espeak-ng", "--voices=en"], capture_output=True, text=True, timeout=5, check=False
            ).stdout
        except Exception:
            out = ""
        installed = {}
        has_mbrola = shutil.which("mbrola") is not None
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            language, gender, name, file = parts[1], parts[2], parts[3], parts[4]
            if file.startswith("mb/"):
                if not has_mbrola:
                    continue  # MBROLA voices are listed but need the mbrola program
                voice_id = file.split("/", 1)[1]
            else:
                voice_id = language
            if voice_id in installed or "shaw" in voice_id or language == "variant":
                continue
            gender_word = {"M": "male", "F": "female"}.get(gender.split("/")[-1], "")
            label = short_label(name.replace("_", " "))  # "English (Scotland)" -> "Scotland"
            installed[voice_id] = f"{label} ({gender_word})" if gender_word else label
        base_ids = {vid.split("+")[0] for vid, _ in PREFERRED}
        for voice_id, label in PREFERRED:
            if voice_id.split("+")[0] in installed:
                voices.append((voice_id, label))
        for voice_id, label in installed.items():
            if voice_id not in base_ids:
                voices.append((voice_id, label))
        self._voices = voices
        return voices

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        cmd = ["espeak-ng", "-w", output_path, "--stdin"]
        if voice:
            cmd[1:1] = ["-v", voice]
        run_cancellable(cmd, cancel_event, input_text=text)
