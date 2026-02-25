from __future__ import annotations

import shutil
import subprocess
from typing import List

from .base import TTSEngine


class EspeakEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="eSpeak-NG", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("espeak-ng") is None:
            missing.append("espeak-ng (system package)")
        return missing

    def synthesize(self, text: str, output_path: str) -> None:
        subprocess.run(
            ["espeak-ng", "-w", output_path, text],
            check=False,
            timeout=20,
        )
