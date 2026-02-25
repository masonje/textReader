from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class TTSEngine:
    name: str
    output_ext: str

    def check_dependencies(self) -> List[str]:
        return []

    def synthesize(self, text: str, output_path: str) -> None:
        raise NotImplementedError()
