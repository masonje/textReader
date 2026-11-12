from __future__ import annotations

import shutil
import threading
from typing import List, Optional

from .base import TTSEngine, run_cancellable


class EspeakEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="eSpeak-NG", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("espeak-ng") is None:
            missing.append("espeak-ng (system package)")
        return missing

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        run_cancellable(["espeak-ng", "-w", output_path, "--stdin"], cancel_event, input_text=text)
