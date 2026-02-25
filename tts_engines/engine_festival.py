from __future__ import annotations

import shutil
import subprocess
from typing import List

from .base import TTSEngine


class FestivalEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Festival", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("text2wave") is None:
            missing.append("festival (system package)")
        return missing

    def synthesize(self, text: str, output_path: str) -> None:
        subprocess.run(
            ["text2wave", "-o", output_path],
            input=text,
            text=True,
            check=False,
            timeout=20,
        )
