"""Piper: fast, natural-sounding neural voices that run offline.

Each voice is a ~63 MB model downloaded from the official Piper voice
repository the first time it's used, then kept in ~/.textReader/voices/piper.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
import wave
from typing import Dict, List, Optional

from .base import DATA_DIR, SynthesisCancelled, TTSEngine, Voice

VOICE_DIR = DATA_DIR / "voices" / "piper"
URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/{locale}/{speaker}/{quality}/{name}{ext}?download=true"

# Single-speaker English voices, medium quality (~63 MB each)
VOICES: List[Voice] = [
    ("en_US-lessac-medium", "Lessac (US, female)"),
    ("en_US-amy-medium", "Amy (US, female)"),
    ("en_US-kristin-medium", "Kristin (US, female)"),
    ("en_US-kathleen-medium", "Kathleen (US, female)"),
    ("en_US-hfc_female-medium", "HFC (US, female)"),
    ("en_US-ryan-medium", "Ryan (US, male)"),
    ("en_US-joe-medium", "Joe (US, male)"),
    ("en_US-john-medium", "John (US, male)"),
    ("en_US-bryce-medium", "Bryce (US, male)"),
    ("en_US-hfc_male-medium", "HFC (US, male)"),
    ("en_GB-jenny_dioco-medium", "Jenny (UK, female)"),
    ("en_GB-cori-medium", "Cori (UK, female)"),
    ("en_GB-alba-medium", "Alba (Scotland, female)"),
    ("en_GB-alan-medium", "Alan (UK, male)"),
    ("en_GB-northern_english_male-medium", "Northern (UK, male)"),
]
_VOICE_IDS = {voice_id for voice_id, _ in VOICES}

_loaded: Dict[str, object] = {}
_lock = threading.Lock()


def _model_path(name: str) -> str:
    return str(VOICE_DIR / f"{name}.onnx")


def _download(name: str, cancel_event: Optional[threading.Event]) -> None:
    """Fetch a voice model and its config, checking for cancel between chunks."""
    locale, speaker, quality = name.split("-", 2)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".onnx.json", ".onnx"):
        dest = VOICE_DIR / f"{name}{ext}"
        if dest.exists():
            continue
        url = URL.format(locale=locale, speaker=speaker, quality=quality, name=name, ext=ext)
        part = dest.with_name(dest.name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "textReader"})
        with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as out:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    out.close()
                    part.unlink(missing_ok=True)
                    raise SynthesisCancelled()
                block = response.read(256 * 1024)
                if not block:
                    break
                out.write(block)
        os.replace(part, dest)


class PiperEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Piper", output_ext="wav")
        self.about = ("Fast neural voices that run entirely on your computer (Piper, from the Open Home Foundation). "
                      "Each voice is a separate ~63 MB download.")
        self.quality = 4

    def check_dependencies(self) -> List[str]:
        try:
            import piper  # noqa: F401
        except Exception:
            return ["piper-tts"]
        return []

    def list_voices(self) -> List[Voice]:
        result = []
        for voice_id, label in VOICES:
            if not os.path.exists(_model_path(voice_id)):
                label += " · download"
            result.append((voice_id, label))
        return result

    def describe_voice(self, voice_id: Optional[str]) -> Dict[str, str]:
        name = voice_id if voice_id in _VOICE_IDS else VOICES[0][0]
        label = dict(VOICES)[name]
        speaker, _, rest = label.partition(" (")
        region, _, gender = rest.rstrip(")").partition(", ")
        quality = name.rsplit("-", 1)[1]
        details = {"Speaker": speaker, "Gender": gender.capitalize() or "—", "Accent": region or "—",
                   "Runs": "Offline, on this computer", "Model": name, "Model quality": quality}
        model = _model_path(name)
        if os.path.exists(model):
            details["Download"] = f"Downloaded ({os.path.getsize(model) / 1e6:.0f} MB)"
            try:
                config = json.loads(open(model + ".json").read())
                rate = config.get("audio", {}).get("sample_rate")
                if rate:
                    details["Audio"] = f"WAV, {rate / 1000:g} kHz mono"
                if config.get("dataset"):
                    details["Trained on"] = config["dataset"]
            except Exception:
                pass
        else:
            details["Download"] = "Not downloaded yet (about 63 MB, on first use)"
            details["Audio"] = "WAV, 22.05 kHz mono"
        return details

    def voice_ready(self, voice_id: Optional[str]) -> bool:
        name = voice_id if voice_id in _VOICE_IDS else VOICES[0][0]
        return os.path.exists(_model_path(name)) and name in _loaded

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        from piper import PiperVoice

        name = voice if voice in _VOICE_IDS else VOICES[0][0]
        if not os.path.exists(_model_path(name)):
            _download(name, cancel_event)
        with _lock:
            model = _loaded.get(name)
            if model is None:
                model = PiperVoice.load(_model_path(name))
                _loaded[name] = model
        # Piper yields audio one sentence at a time; check for cancel between them.
        with wave.open(output_path, "wb") as wav:
            first = True
            for chunk in model.synthesize(text):
                if cancel_event is not None and cancel_event.is_set():
                    raise SynthesisCancelled()
                if first:
                    wav.setframerate(chunk.sample_rate)
                    wav.setsampwidth(chunk.sample_width)
                    wav.setnchannels(chunk.sample_channels)
                    first = False
                wav.writeframes(chunk.audio_int16_bytes)
