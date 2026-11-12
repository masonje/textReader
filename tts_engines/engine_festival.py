from __future__ import annotations

import shutil
import threading
from typing import List, Optional

from .base import TTSEngine, run_cancellable


class FestivalEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Festival", output_ext="wav")

    def check_dependencies(self) -> List[str]:
        missing: List[str] = []
        if shutil.which("text2wave") is None:
            missing.append("festival (system package)")
        return missing

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        run_cancellable(["text2wave", "-o", output_path], cancel_event, input_text=text)
