from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, List, Optional, Type

from .base import TTSEngine


def _discover_engines() -> Dict[str, TTSEngine]:
    engines: Dict[str, TTSEngine] = {}
    for module_info in pkgutil.iter_modules(__path__):
        if not module_info.name.startswith("engine_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is TTSEngine:
                continue
            if issubclass(obj, TTSEngine):
                try:
                    instance = obj()
                except Exception:
                    continue
                engines[instance.name] = instance
    return engines


_ENGINES: Dict[str, TTSEngine] = _discover_engines()


def list_engines() -> List[str]:
    return sorted(_ENGINES.keys())


def get_engine(name: str) -> Optional[TTSEngine]:
    return _ENGINES.get(name)
