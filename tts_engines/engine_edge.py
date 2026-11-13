"""Edge TTS: Microsoft's online neural voices (the ones used by Edge's Read Aloud).

Needs an internet connection, like gTTS. The full English voice list is
fetched once and cached in ~/.textReader/edge_voices.json.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Dict, List, Optional

from .base import DATA_DIR, SynthesisCancelled, TTSEngine, Voice

CACHE_FILE = DATA_DIR / "edge_voices_v2.json"  # v2 keeps full voice details
CACHE_MAX_AGE = 7 * 24 * 3600

# Used until the online list has been fetched (or if it can't be)
FALLBACK: List[Voice] = [
    ("en-US-AriaNeural", "Aria (US, female)"),
    ("en-US-JennyNeural", "Jenny (US, female)"),
    ("en-US-GuyNeural", "Guy (US, male)"),
    ("en-US-ChristopherNeural", "Christopher (US, male)"),
    ("en-GB-SoniaNeural", "Sonia (UK, female)"),
    ("en-GB-RyanNeural", "Ryan (UK, male)"),
    ("en-AU-NatashaNeural", "Natasha (Australia, female)"),
    ("en-AU-WilliamNeural", "William (Australia, male)"),
    ("en-CA-ClaraNeural", "Clara (Canada, female)"),
    ("en-IE-EmilyNeural", "Emily (Ireland, female)"),
    ("en-IN-NeerjaNeural", "Neerja (India, female)"),
]

REGIONS = {
    "US": "US", "GB": "UK", "AU": "Australia", "CA": "Canada", "IE": "Ireland", "IN": "India",
    "NZ": "New Zealand", "ZA": "South Africa", "SG": "Singapore", "PH": "Philippines",
    "NG": "Nigeria", "KE": "Kenya", "TZ": "Tanzania", "HK": "Hong Kong",
}


_details: Dict[str, dict] = {}  # ShortName -> Microsoft's voice metadata


def _label(short_name: str, gender: str) -> str:
    # "en-US-AndrewMultilingualNeural" -> "Andrew Multilingual (US, male)"
    _, region, name = short_name.split("-", 2)
    name = name.replace("Neural", "")
    for word in ("Multilingual", "Expressive"):
        name = name.replace(word, " " + word)
    name = " ".join(name.split())
    return f"{name} ({REGIONS.get(region, region)}, {gender.lower()})"


def _sort_key(voice: Voice):
    # The well-known adult voices first (Aria is the default), then by region and name
    favorites = [v for v, _ in FALLBACK]
    if voice[0] in favorites:
        return (0, favorites.index(voice[0]), "")
    region_order = ["en-US", "en-GB", "en-AU", "en-CA", "en-IE"]
    prefix = voice[0][:5]
    return (1, region_order.index(prefix) if prefix in region_order else len(region_order), voice[1])


class EdgeEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Edge TTS", output_ext="mp3")
        self.about = ("Microsoft's neural voices, the ones behind Edge's Read Aloud. The most natural-sounding "
                      "option here, with many accents.")
        self.quality = 5
        self.needs_internet = True
        self.service = "Microsoft"

    def check_dependencies(self) -> List[str]:
        try:
            import edge_tts  # noqa: F401
        except Exception:
            return ["edge-tts"]
        return []

    def list_voices(self) -> List[Voice]:
        listed = None
        try:
            if time.time() - CACHE_FILE.stat().st_mtime < CACHE_MAX_AGE:
                listed = json.loads(CACHE_FILE.read_text()) or None
        except Exception:
            pass
        if listed is None:
            try:
                import edge_tts

                listed = [v for v in asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=8))
                          if v.get("Locale", "").startswith("en-")]
                if listed:
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_FILE.write_text(json.dumps(listed))
            except Exception:
                listed = None
        if not listed:
            return list(FALLBACK)
        _details.update({v["ShortName"]: v for v in listed})
        return sorted(((v["ShortName"], _label(v["ShortName"], v.get("Gender", ""))) for v in listed), key=_sort_key)

    def describe_voice(self, voice_id: Optional[str]) -> Dict[str, str]:
        voice_id = voice_id or FALLBACK[0][0]
        if not _details:
            self.list_voices()
        info = _details.get(voice_id, {})
        label = _label(voice_id, info.get("Gender", "")) if info else dict(FALLBACK).get(voice_id, voice_id)
        details = {"Speaker": label.split(" (")[0], "Gender": info.get("Gender", "—")}
        friendly = info.get("FriendlyName", "")
        details["Accent"] = friendly.split(" - ", 1)[1] if " - " in friendly else info.get("Locale", "—")
        tags = info.get("VoiceTag", {}) or {}
        if tags.get("VoicePersonalities"):
            details["Personality"] = ", ".join(tags["VoicePersonalities"])
        if tags.get("ContentCategories"):
            details["Good for"] = ", ".join(tags["ContentCategories"])
        if "Multilingual" in voice_id:
            details["Note"] = "Multilingual: can also read other languages"
        details["Runs"] = "Online (Microsoft servers)"
        details["Audio"] = "MP3, 24 kHz mono"
        details["Voice id"] = voice_id
        return details

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        import edge_tts

        async def run():
            communicate = edge_tts.Communicate(text, voice or FALLBACK[0][0])
            with open(output_path, "wb") as out:
                async for chunk in communicate.stream():
                    if cancel_event is not None and cancel_event.is_set():
                        raise SynthesisCancelled()
                    if chunk["type"] == "audio":
                        out.write(chunk["data"])

        asyncio.run(run())
