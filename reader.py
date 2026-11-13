
__version__ = "1.4.0"

# Dependency check
import sys

if "--version" in sys.argv[1:]:
    print(f"Clipboard Reader {__version__}")
    sys.exit(0)

import shutil
import json
import math
from pathlib import Path
missing = []
def check_dep(mod, pip_name=None):
    try:
        __import__(mod)
    except ImportError:
        missing.append(pip_name or mod)

# Check Python packages
check_dep('pyperclip')
check_dep('pygame')
check_dep('pystray')
check_dep('PIL', 'Pillow')
check_dep('pynput')
check_dep('tkinter')

# Check ffmpeg
if shutil.which('ffmpeg') is None:
    missing.append('ffmpeg (system package)')

if missing:
    print("Missing dependencies:")
    for dep in missing:
        print(f"  - {dep}")
    print("\nPlease install the missing dependencies and try again.")
    sys.exit(1)

import pyperclip
import time
import pygame
import os
import threading
import queue
import wave
from pystray import Icon
from PIL import Image, ImageDraw
from pynput import keyboard
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import tkinter.font as tkfont
from tts_engines import get_engine, list_engines
from tts_engines.base import SynthesisCancelled, run_cancellable

if "--check-engines" in sys.argv[1:]:
    # Diagnostics: report each engine's dependencies and try a short phrase with its default voice
    import tempfile
    for name in sorted(list_engines(), key=str.lower):
        engine = get_engine(name)
        missing = engine.check_dependencies()
        if missing:
            print(f"{name:10} not available: {', '.join(missing)}")
            continue
        try:
            voices = engine.list_voices()
            voice = next((v for v, label in voices if "download" not in label), voices[0][0] if voices else None)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "test." + engine.output_ext)
                engine.synthesize("Testing one two three.", path, threading.Event(), voice=voice)
                size = os.path.getsize(path) if os.path.exists(path) else 0
            print(f"{name:10} {'OK' if size else 'NO AUDIO'}: {len(voices)} voices, tested {voice or 'default'}")
        except Exception as e:
            print(f"{name:10} ERROR: {e}")
    sys.exit(0)
import word_timing

# Initialize pygame mixer for audio playback
pygame.mixer.init()


def resource_path(relative_path):
    """Resolve a bundled resource path, whether running from source or a PyInstaller build."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

APP_ICON_PATH = resource_path("pireader.png")

# Settings persistence
SETTINGS_DIR = Path.home() / ".textReader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
SETTINGS_DIR.mkdir(exist_ok=True)

DEFAULT_HOTKEYS = {
    "read_selected_text": "Win+Esc",
    "play": "Win+Shift+R",
    "pause": "Win+Shift+P",
    "stop": "Win+Shift+S",
}
HOTKEY_ORDER = ("read_selected_text", "play", "pause", "stop")
HOTKEY_LABELS = {
    "read_selected_text": "Read Selected Text",
    "play": "Play/Resume",
    "pause": "Pause",
    "stop": "Stop",
}
MODIFIER_KEYS = {"win", "ctrl", "alt", "shift"}
KEY_ALIASES = {
    "cmd": "win",
    "command": "win",
    "super": "win",
    "windows": "win",
    "control": "ctrl",
    "escape": "esc",
    "return": "enter",
}

def normalize_hotkey_part(part):
    key_name = part.strip().lower()
    return KEY_ALIASES.get(key_name, key_name)

def parse_hotkey(hotkey):
    if not isinstance(hotkey, str):
        return None
    parts = [normalize_hotkey_part(part) for part in hotkey.split("+")]
    parts = [part for part in parts if part]
    combo = frozenset(parts)
    if not combo or all(part in MODIFIER_KEYS for part in combo):
        return None
    return combo

def format_hotkey(combo):
    display_names = {
        "win": "Win",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "esc": "Esc",
        "enter": "Enter",
        "space": "Space",
        "tab": "Tab",
        "backspace": "Backspace",
        "delete": "Delete",
    }
    ordered_parts = [part for part in ("win", "ctrl", "alt", "shift") if part in combo]
    ordered_parts.extend(sorted(part for part in combo if part not in MODIFIER_KEYS))
    return "+".join(display_names.get(part, part.upper() if len(part) == 1 else part.title()) for part in ordered_parts)

def hotkey_dropdown_values(hotkey):
    combo = parse_hotkey(hotkey) or parse_hotkey(DEFAULT_HOTKEYS["play"])
    modifier = "+".join(part for part in ("Win", "Ctrl", "Alt") if part.lower() in combo)
    if "shift" in combo:
        modifier = f"{modifier}+Shift" if modifier else "Shift"
    key = next((part for part in combo if part not in MODIFIER_KEYS), "r")
    return modifier or "Win", key.upper() if len(key) == 1 else key.title()

def build_hotkey_from_dropdowns(modifier, key):
    parts = [part.strip() for part in modifier.split("+") if part.strip()]
    parts.append(key.strip())
    return "+".join(parts)

def validate_hotkey_settings(candidate_hotkeys):
    normalized_hotkeys = {}
    parsed_hotkeys = {}
    errors = []
    for action in HOTKEY_ORDER:
        hotkey = candidate_hotkeys.get(action, DEFAULT_HOTKEYS[action])
        combo = parse_hotkey(hotkey)
        if combo is None:
            errors.append(f"{HOTKEY_LABELS[action]} needs a key like Win+Shift+R or Ctrl+Alt+P.")
            continue
        normalized_hotkeys[action] = format_hotkey(combo)
        parsed_hotkeys[action] = combo
    seen = {}
    for action, combo in parsed_hotkeys.items():
        if combo in seen:
            errors.append(f"{HOTKEY_LABELS[action]} duplicates {HOTKEY_LABELS[seen[combo]]}.")
        seen[combo] = action
    return normalized_hotkeys, errors

def default_settings():
    return {
        "debug_mode": False,
        "playback_speed": 1.0,
        "tts_engine": "gTTS",
        "hotkeys": DEFAULT_HOTKEYS.copy(),
        "theme": "auto",
        "view_mode": "compact",
        "full_window_size": "",
        "voices": {},
        "disabled_engines": [],
        "disabled_voices": {},
        "voice_stats": {},
        "voice_ratings": {},
    }

def normalize_loaded_hotkeys(raw_hotkeys):
    loaded_hotkeys = DEFAULT_HOTKEYS.copy()
    if isinstance(raw_hotkeys, dict):
        loaded_hotkeys.update({action: raw_hotkeys.get(action, loaded_hotkeys[action]) for action in HOTKEY_ORDER})
    normalized_hotkeys, errors = validate_hotkey_settings(loaded_hotkeys)
    if errors:
        return DEFAULT_HOTKEYS.copy()
    return normalized_hotkeys

def load_settings():
    loaded_settings = default_settings()
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved_settings = json.load(f)
            if isinstance(saved_settings, dict):
                loaded_settings.update(saved_settings)
                loaded_settings["hotkeys"] = normalize_loaded_hotkeys(saved_settings.get("hotkeys"))
        except Exception:
            pass
    return loaded_settings
def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"debug_mode": debug_mode, "playback_speed": playback_speed, "tts_engine": tts_engine, "hotkeys": hotkeys, "theme": ui_theme, "view_mode": view_mode, "full_window_size": full_window_size, "voices": engine_voices,
                       "disabled_engines": sorted(disabled_engines),
                       "disabled_voices": {k: sorted(v) for k, v in disabled_voices.items() if v},
                       "voice_stats": voice_stats, "voice_ratings": voice_ratings}, f, indent=2)
    except Exception:
        pass

# Global state
is_running = True
is_paused = False
settings = load_settings()
debug_mode = settings.get("debug_mode", False)
audio_file_mp3 = str(SETTINGS_DIR / "clipboard_speech.mp3")
audio_file_wav = str(SETTINGS_DIR / "clipboard_speech.wav")
cmd_pressed = False
shift_pressed = False
pressed_keys = set()
active_hotkeys = set()
control_window = None
playback_speed = settings.get("playback_speed", 1.0)
tts_engine = settings.get("tts_engine", "gTTS")
hotkeys = settings.get("hotkeys", DEFAULT_HOTKEYS.copy())
ui_theme = settings.get("theme", "auto")  # "auto" follows the desktop, or "dark" / "light"
view_mode = settings.get("view_mode", "compact")  # "compact" (controls only) or "full"
full_window_size = settings.get("full_window_size", "")  # "WxH" remembered for full mode
engine_voices = settings.get("voices", {})  # engine name -> chosen voice id
# Engines and voices hidden from the drop-downs (managed in the full view)
disabled_engines = set(settings.get("disabled_engines", []) or [])
disabled_voices = {k: set(v) for k, v in (settings.get("disabled_voices", {}) or {}).items()}
# Measured build speed per voice ("engine|voice" -> {"runs": n, "rtf": seconds of work per second of audio})
voice_stats = settings.get("voice_stats", {}) or {}
# The user's own star ratings ("engine|voice" -> 1-5); engines provide defaults
voice_ratings = settings.get("voice_ratings", {}) or {}

def voice_key(engine_name, voice_id):
    return f"{engine_name}|{voice_id or ''}"

def record_speed(engine_name, voice_id, build_seconds, audio_seconds):
    """Fold one build into the running average (recent reads count most)."""
    if audio_seconds < 0.5 or build_seconds <= 0:
        return
    key = voice_key(engine_name, voice_id)
    stat = voice_stats.get(key, {"runs": 0, "rtf": 0.0})
    weight = min(stat["runs"], 9)
    stat["rtf"] = (stat["rtf"] * weight + build_seconds / audio_seconds) / (weight + 1)
    stat["runs"] += 1
    voice_stats[key] = stat

def speed_word(rtf):
    if rtf < 0.05:
        return "Very fast"
    if rtf < 0.25:
        return "Fast"
    if rtf < 0.6:
        return "Moderate"
    if rtf < 1.0:
        return "Slow"
    return "Very slow"

def generated_where(engine, long=False):
    """Where an engine makes its speech: on this computer, or by an online service."""
    if engine.needs_internet:
        who = engine.service or "an online service"
        if long:
            return f"Online by {who}. The text you read is sent to {who}'s servers."
        return f"Online ({who})" if engine.service else "Online"
    if long:
        return "Locally, on this computer. Nothing you read is sent anywhere."
    return "Locally"

def stars(rating):
    rating = max(0, min(5, int(round(rating))))
    return "★" * rating + "☆" * (5 - rating)

def enabled_engines():
    """Engine names to offer, in display order (all of them if everything was disabled)."""
    names = sorted(list_engines(), key=str.lower)
    return [n for n in names if n not in disabled_engines] or names

def enabled_voices(engine_name, voices):
    """The voices to offer for an engine (all of them if every voice was disabled)."""
    off = disabled_voices.get(engine_name, set())
    return [v for v in voices if v[0] not in off] or list(voices)
if not isinstance(engine_voices, dict):
    engine_voices = {}

# What is being read aloud, for the full view. reading_serial changes whenever
# the text changes so the UI knows to reload it.
reading_text = ""
reading_spans = []      # (start, end) character offsets per word
reading_timeline = []   # estimated start time (s) per word
reading_serial = 0
reading_lock = threading.Lock()

# Bumped by Stop; a playback thread that sees a newer generation gives up
# instead of starting audio after the user already pressed Stop.
playback_generation = 0
audio_preparing = False  # True while audio is being converted for playback
playback_start_time = None
playback_pause_start = None
playback_pause_accum = 0.0
current_audio_duration = 0.0
current_progress = 0.0
taskbar_icon_photo = None
engine_missing_deps = False
tray_icon = None
current_build = None      # cancel Event for the audio build in progress, if any
voices_changed_callback = None  # set by the UI: refresh the voice list for an engine
build_counter = 0
# Tk is only safe to touch from the main thread; other threads queue calls here.
main_thread_calls = queue.Queue()

def get_output_path(engine_name):
    """Return output path based on engine output format."""
    engine = get_engine(engine_name)
    if engine and engine.output_ext == "mp3":
        return audio_file_mp3
    return audio_file_wav

def check_engine_dependencies(engine_name):
    """Check dependencies for the selected engine and return missing list."""
    if debug_mode:
        print(f"🐛 [DEBUG] Checking dependencies for engine: {engine_name}")
    engine = get_engine(engine_name)
    if engine is None:
        if debug_mode:
            print(f"🐛 [DEBUG] Engine not found: {engine_name}")
        return [f"Unknown TTS engine: {engine_name}"]
    missing_deps = engine.check_dependencies()
    if debug_mode:
        if missing_deps:
            print(f"🐛 [DEBUG] Missing deps for {engine_name}: {missing_deps}")
        else:
            print(f"🐛 [DEBUG] All deps satisfied for {engine_name}")
    return missing_deps

check_engine_dependencies(tts_engine)

def cleanup_audio_files():
    """Remove any existing audio files from previous runs."""
    try:
        if os.path.exists(audio_file_mp3):
            os.remove(audio_file_mp3)
        if os.path.exists(audio_file_wav):
            os.remove(audio_file_wav)
        for speed_file in SETTINGS_DIR.glob("clipboard_speech_speed.*"):
            speed_file.unlink(missing_ok=True)
        # Partial files from builds that were cancelled or interrupted
        for leftover in SETTINGS_DIR.glob("clipboard_speech.building*"):
            leftover.unlink(missing_ok=True)
    except Exception:
        pass

def has_audio_file():
    """Return True if there is an audio file available for playback."""
    try:
        file_path = get_output_path(tts_engine)
        return os.path.exists(file_path)
    except Exception:
        pass
    return False

def key_name_for(key):
    special_keys = {
        "cmd": "win",
        "cmd_l": "win",
        "cmd_r": "win",
        "ctrl": "ctrl",
        "ctrl_l": "ctrl",
        "ctrl_r": "ctrl",
        "alt": "alt",
        "alt_l": "alt",
        "alt_r": "alt",
        "alt_gr": "alt",
        "shift": "shift",
        "shift_l": "shift",
        "shift_r": "shift",
        "esc": "esc",
        "enter": "enter",
        "space": "space",
        "tab": "tab",
        "backspace": "backspace",
        "delete": "delete",
    }
    for key_attr, key_name in special_keys.items():
        if key == getattr(keyboard.Key, key_attr, None):
            return key_name
    if hasattr(key, 'char') and key.char:
        char = key.char
        # With Ctrl held, X reports control characters (Ctrl+Z -> "\x1a"); use the key itself
        if len(char) == 1 and ord(char) < 32:
            vk = getattr(key, 'vk', None)
            if vk and 32 < vk < 127:
                return chr(vk).lower()
            if 1 <= ord(char) <= 26:
                return chr(ord(char) + 96)
        return char.lower()
    if hasattr(key, 'name') and key.name:
        return normalize_hotkey_part(key.name)
    return None

def trigger_hotkey(action):
    if action == "read_selected_text":
        # Hotkeys fire on the pynput thread; the build dialog must be created on Tk's thread.
        main_thread_calls.put(read_selected_text)
    elif action == "play":
        on_play()
    elif action == "pause":
        on_pause()
    elif action == "stop":
        on_stop()

def create_lips_icon():
    """Create a lips icon for the system tray"""
    image = Image.new('RGB', (64, 64), color='white')
    draw = ImageDraw.Draw(image)
    
    # Draw lips (pink/red color)
    # Top lip
    draw.ellipse([16, 20, 48, 35], fill='#FF69B4', outline='#FF1493')
    # Bottom lip
    draw.ellipse([16, 32, 48, 47], fill='#FF69B4', outline='#FF1493')
    # Mouth line
    draw.line([16, 32, 48, 32], fill='#FF1493', width=2)
    
    return image

def ensure_lips_icon_file():
    """Create lips icon file and return its path."""
    icon_path = SETTINGS_DIR / "lips_icon.png"
    try:
        img = create_lips_icon()
        img.save(icon_path)
    except Exception:
        pass
    return icon_path

def wait_for_audio_file(file_path, timeout=2.0):
    """Wait for audio file to exist and be non-empty."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return True
        except Exception:
            pass
        time.sleep(0.05)
    return False

def get_audio_duration(file_path):
    """Return audio duration in seconds, or 0 on failure."""
    try:
        if file_path.endswith(".wav"):
            with wave.open(file_path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate:
                    return frames / float(rate)
                return 0.0
        import subprocess
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 0.0
    except Exception:
        return 0.0

def set_reading_text(text):
    """Record the text that is about to be read aloud (any thread)."""
    global reading_text, reading_spans, reading_timeline, reading_serial
    with reading_lock:
        reading_text = text
        reading_spans = word_timing.tokenize(text)
        reading_timeline = []
        reading_serial += 1

def update_reading_timeline(audio_path, duration):
    """Estimate when each word is spoken in `audio_path` (call from a worker thread)."""
    global reading_timeline
    with reading_lock:
        text, spans, serial = reading_text, reading_spans, reading_serial
    if not spans or duration <= 0:
        return
    # A quick even spread first, so highlighting starts at once...
    rough = word_timing.build_timeline(text, duration, [], spans)
    with reading_lock:
        if serial == reading_serial:
            reading_timeline = rough
    # ...then refine it using the pauses actually found in the audio
    refined = word_timing.build_timeline(text, duration, word_timing.detect_silences(audio_path), spans)
    with reading_lock:
        if serial == reading_serial:
            reading_timeline = refined
    if debug_mode:
        print(f"🐛 [DEBUG] Word timeline ready: {len(refined)} words over {duration:.1f}s")

def playback_position():
    """Seconds of audio played so far, or None when nothing is loaded."""
    if playback_start_time is None:
        return None
    now = playback_pause_start if (is_paused and playback_pause_start is not None) else time.monotonic()
    return max(0.0, now - playback_start_time - playback_pause_accum)

def play_audio():
    """Play the generated audio file at the selected speed"""
    global playback_start_time, playback_pause_start, playback_pause_accum, current_audio_duration, audio_preparing
    generation = playback_generation
    stopped = lambda: generation != playback_generation or not is_running
    audio_preparing = True
    try:
        # Choose file based on engine
        file_to_play = get_output_path(tts_engine)
        if not wait_for_audio_file(file_to_play, 20):
            print("⚠️ Audio file not ready for playback")
            return
        # Adjust speed for MP3 only
        if playback_speed != 1.0:
            temp_speed_file = str(SETTINGS_DIR / ("clipboard_speech_speed" + os.path.splitext(file_to_play)[1]))
            try:
                run_cancellable(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", file_to_play,
                     "-filter:a", f"atempo={playback_speed}", temp_speed_file],
                    cancel_check=stopped,
                )
                file_to_play = temp_speed_file
            except SynthesisCancelled:
                return
            except Exception as e:
                print(f"⚠️ Speed change failed, playing at normal speed: {e}")
        if stopped():
            return  # Stop was pressed while the audio was being prepared
        pygame.mixer.music.load(file_to_play)
        current_audio_duration = get_audio_duration(file_to_play)
        if stopped():
            return
        playback_start_time = time.monotonic()
        playback_pause_start = None
        playback_pause_accum = 0.0
        pygame.mixer.music.play()
        audio_preparing = False
        update_reading_timeline(file_to_play, current_audio_duration)
        while pygame.mixer.music.get_busy() and is_running and not is_paused and not stopped():
            time.sleep(0.1)
    except Exception as e:
        print(f"Error playing audio: {e}")
    finally:
        if generation == playback_generation:
            audio_preparing = False

def on_play():
    """Resume/play reading"""
    global is_paused, playback_pause_start, playback_pause_accum

    if is_paused and playback_start_time is not None:
        # Resume paused playback from where it left off
        # (pygame reports get_busy() == False while paused, so check our own state)
        pygame.mixer.music.unpause()
        is_paused = False
        if playback_pause_start is not None:
            playback_pause_accum += time.monotonic() - playback_pause_start
            playback_pause_start = None
        print("▶ Resumed from pause")
    else:
        # Start fresh playback from beginning, honoring speed
        def threaded_play():
            play_audio()
        threading.Thread(target=threaded_play, daemon=True).start()
        is_paused = False
        print("▶ Playing")

def on_pause():
    """Pause/resume current playback"""
    global is_paused, playback_pause_start, playback_pause_accum
    if pygame.mixer.music.get_busy():
        if is_paused:
            pygame.mixer.music.unpause()
            is_paused = False
            if playback_pause_start is not None:
                playback_pause_accum += time.monotonic() - playback_pause_start
                playback_pause_start = None
            print("▶ Resumed")
        else:
            is_paused = True
            playback_pause_start = time.monotonic()
            pygame.mixer.music.pause()
            print("⏸ Paused")
    elif is_paused:
        pygame.mixer.music.unpause()
        is_paused = False
        if playback_pause_start is not None:
            playback_pause_accum += time.monotonic() - playback_pause_start
            playback_pause_start = None
        print("▶ Resumed")
    else:
        print("⚠️ Nothing playing to pause")

def on_stop():
    """Stop and reset playback"""
    global is_paused, playback_start_time, playback_pause_start, playback_pause_accum, current_audio_duration, current_progress
    global playback_generation, audio_preparing
    playback_generation += 1
    audio_preparing = False
    is_paused = False
    playback_start_time = None
    playback_pause_start = None
    playback_pause_accum = 0.0
    current_audio_duration = 0.0
    current_progress = 0.0
    if current_build is not None:
        current_build.set()
    pygame.mixer.music.stop()
    print("⏹ Stopped")

def toggle_debug():
    """Toggle debug mode"""
    global debug_mode
    debug_mode = not debug_mode
    save_settings()
    status = "ON" if debug_mode else "OFF"
    print(f"🐛 Debug mode: {status}")

def start_build(text):
    """Synthesize `text` in the background with a cancellable progress dialog.

    Must run on the Tk main thread. The worker thread never touches Tk; it
    reports back through a queue that the main thread polls.
    """
    global current_build, build_counter
    if current_build is not None:
        current_build.set()  # starting a new read cancels the previous build

    cancel_event = threading.Event()
    current_build = cancel_event
    build_counter += 1
    engine_name = tts_engine
    voice = engine_voices.get(engine_name)
    final_path = get_output_path(engine_name)
    root, ext = os.path.splitext(final_path)
    # Build into a private file so a cancelled or stale build never clobbers the real one.
    temp_path = f"{root}.building{build_counter}{ext}"
    results = queue.Queue()

    def remove_temp():
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    def worker():
        try:
            engine = get_engine(engine_name)
            if engine is None:
                results.put(("error", "Unknown TTS engine"))
                return
            missing_deps = engine.check_dependencies()
            if missing_deps:
                results.put(("error", f"Missing: {', '.join(missing_deps)}"))
                return
            download = engine.voice_download_info(voice)
            if download and not download["downloaded"]:
                # Fetch the voice first, reporting progress to the dialog
                results.put(("progress", (0, download["size_bytes"])))
                engine.download_voice(voice, lambda done, total: results.put(("progress", (done, total))), cancel_event)
                results.put(("progress", None))  # download finished; now building
                if voices_changed_callback is not None:
                    voices_changed_callback(engine_name)
            ready = engine.voice_ready(voice)  # False: this build includes a download or model load
            started = time.monotonic()
            engine.synthesize(text, temp_path, cancel_event, voice=voice)
            build_seconds = time.monotonic() - started
            if cancel_event.is_set():
                raise SynthesisCancelled()
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                results.put(("error", "Engine produced no audio"))
                return
            results.put(("done", (ready, build_seconds, get_audio_duration(temp_path))))
        except SynthesisCancelled:
            results.put(("cancelled", None))
        except Exception as e:
            results.put(("error", str(e)))

    dialog, content = themed_toplevel(control_window, "Building Audio")
    dialog.minsize(340, 0)  # wide enough for the "Downloading Voice" title
    dialog.attributes("-topmost", True)
    label = ttk.Label(content, text="Building audio for playback…")
    label.pack(anchor="w")
    progress = ttk.Progressbar(content, orient=tk.HORIZONTAL, length=240, mode="indeterminate")
    progress.pack(fill=tk.X, pady=(10, 12))
    progress.start(10)

    def close_dialog():
        try:
            if dialog.winfo_exists():
                dialog.destroy()
        except Exception:
            pass

    def on_cancel():
        if not cancel_event.is_set():
            cancel_event.set()
            print("✖ Cancelled audio build")
        close_dialog()

    cancel_btn = ttk.Button(content, text="Cancel", command=on_cancel)
    cancel_btn.pack(anchor="e")
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    dialog.bind("<Escape>", lambda _e: on_cancel())

    def finish():
        global current_build
        if current_build is cancel_event:
            current_build = None

    def show_download(update):
        """Switch the dialog between 'downloading the voice' and 'building'."""
        try:
            if update is None:
                dialog.title("Building Audio")
                label.config(text="Building audio for playback…")
                progress.configure(mode="indeterminate", value=0)
                progress.start(10)
                return
            done, total = update
            if str(progress.cget("mode")) != "determinate":
                progress.stop()
                progress.configure(mode="determinate", maximum=100)
                dialog.title("Downloading Voice")
            progress.configure(value=100 * done / total if total else 0)
            label.config(text=f"Downloading voice: {done / 1e6:.1f} of {total / 1e6:.0f} MB "
                              f"({100 * done / total if total else 0:.0f}%)")
        except tk.TclError:
            pass  # the dialog was closed

    def poll():
        if cancel_event.is_set():
            close_dialog()  # e.g. cancelled by the Stop hotkey or a newer read
        while True:
            try:
                status, message = results.get_nowait()
            except queue.Empty:
                control_window.after(100, poll)
                return
            if status != "progress":
                break
            if not cancel_event.is_set():
                show_download(message)
        finish()
        if status == "done" and not cancel_event.is_set():
            close_dialog()
            try:
                os.replace(temp_path, final_path)
                set_reading_text(text)
            except Exception as e:
                print(f"Error saving audio: {e}")
                remove_temp()
                return
            threading.Thread(target=play_audio, daemon=True).start()
            if message and message[0]:
                record_speed(engine_name, voice, message[1], message[2])
                save_settings()
            if voices_changed_callback is not None:
                voices_changed_callback(engine_name)  # e.g. a Piper voice just finished downloading
            return
        remove_temp()
        if status == "error" and not cancel_event.is_set():
            print(f"Error building audio: {message}")
            try:
                progress.stop()
                progress.pack_forget()
                label.config(text=f"Error: {message}", style="Error.TLabel", wraplength=240)
                cancel_btn.config(text="Close")
            except Exception:
                pass
            control_window.after(2000, close_dialog)
        else:
            close_dialog()

    threading.Thread(target=worker, daemon=True).start()
    control_window.after(100, poll)

def read_selected_text():
    """Read the currently selected text from clipboard"""
    try:
        # Copy selected text to clipboard first (requires xclip on Linux or xsel)
        try:
            import subprocess
            result = subprocess.run(
                ["xclip", "-selection", "primary", "-o"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            if result.stdout:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=result.stdout,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
        except Exception:
            pass
        time.sleep(0.1)  # Give clipboard time to update
        current_text = pyperclip.paste()
        if debug_mode:
            print(f"🐛 [DEBUG] Raw clipboard content:")
            print(f"🐛 [DEBUG] {repr(current_text)}\n")
        if current_text.strip():
            if debug_mode:
                print(f"\n🐛 [DEBUG] Reading selected text:")
                print(f"🐛 [DEBUG] {repr(current_text)}\n")
            print(f"Speaking: {current_text[:50]}...")

            start_build(current_text)
        else:
            print("⚠️ No text to read")
            # Play a short negative beep
            try:
                import wave
                import struct
                beep_path = SETTINGS_DIR / "negative_beep.wav"
                duration = 0.2  # seconds
                freq = 400      # Hz
                sample_rate = 44100
                n_samples = int(sample_rate * duration)
                # Save as WAV
                with wave.open(str(beep_path), 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    for sample_index in range(n_samples):
                        t = sample_index / sample_rate
                        s = 0.5 * math.sin(2 * math.pi * freq * t)
                        wf.writeframes(struct.pack('<h', int(s * 32767)))
                pygame.mixer.music.load(str(beep_path))
                pygame.mixer.music.play()
                time.sleep(duration)
                if beep_path.exists():
                    beep_path.unlink()
            except Exception as e:
                print(f"Error playing beep: {e}")
    except Exception as e:
        print(f"Error: {e}")

# ---------------------------------------------------------------------------
# Theme: one palette drives every window and dialog so light/dark stay consistent
# ---------------------------------------------------------------------------
PALETTES = {
    "dark": {
        "bg": "#232629", "surface": "#2c3034", "field": "#1b1e20",
        "button": "#383d42", "hover": "#43494f", "pressed": "#2f3438",
        "border": "#4a5056", "fg": "#e8eaed", "muted": "#9aa0a6", "disabled": "#6b7177",
        "accent": "#3d8fd6", "accent_hover": "#4f9de0", "accent_pressed": "#357fbf", "accent_fg": "#ffffff",
        "error": "#f28b82",
    },
    "light": {
        "bg": "#f3f4f6", "surface": "#e9ebee", "field": "#ffffff",
        "button": "#e3e6ea", "hover": "#d7dbe0", "pressed": "#cbd0d6",
        "border": "#c3c8ce", "fg": "#1f2328", "muted": "#5f6670", "disabled": "#a0a6ad",
        "accent": "#2f6fb5", "accent_hover": "#3a7cc4", "accent_pressed": "#285f9b", "accent_fg": "#ffffff",
        "error": "#c5221f",
    },
}
PALETTE = PALETTES["light"]
_theme_fonts = {}

def system_prefers_dark():
    """Best-effort check of the desktop's light/dark preference."""
    import subprocess
    try:
        if sys.platform.startswith("linux"):
            def gsetting(key):
                return subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", key],
                    capture_output=True, text=True, timeout=1, check=False,
                ).stdout.lower()
            if "dark" in gsetting("color-scheme"):
                return True
            return "dark" in gsetting("gtk-theme")
        if sys.platform == "darwin":
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1, check=False,
            ).stdout
            return "dark" in out.lower()
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False

def apply_theme(root):
    """Style all ttk widgets, classic Tk widgets and dialogs from one palette."""
    global PALETTE
    mode = ui_theme if ui_theme in PALETTES else ("dark" if system_prefers_dark() else "light")
    PALETTE = p = PALETTES[mode]

    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(size=10)
    for name in ("TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=default_font.cget("family"), size=10)
        except Exception:
            pass
    _theme_fonts["small"] = small = default_font.copy()
    small.configure(size=9)
    _theme_fonts["bold"] = bold = default_font.copy()
    bold.configure(weight="bold")

    style = ttk.Style(root)
    style.theme_use("clam")  # fully recolorable on every platform
    style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["field"], focuscolor=p["accent"], selectbackground=p["accent"],
                    selectforeground=p["accent_fg"], insertcolor=p["fg"], arrowcolor=p["fg"],
                    font=default_font)
    style.map(".", foreground=[("disabled", p["disabled"])])

    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Muted.TLabel", foreground=p["muted"], font=small)
    style.configure("Header.TLabel", font=bold)
    style.configure("Error.TLabel", foreground=p["error"])

    style.configure("TButton", background=p["button"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], focuscolor=p["button"],
                    padding=(10, 5), anchor="center")
    style.map("TButton",
              background=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              lightcolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              darkcolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              focuscolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    bordercolor=p["accent"], lightcolor=p["accent"], darkcolor=p["accent"],
                    focuscolor=p["accent"])
    style.map("Accent.TButton",
              background=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              lightcolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              darkcolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              focuscolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              bordercolor=[("disabled", p["border"])],
              foreground=[("disabled", p["disabled"])])

    style.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"], rowheight=24)
    style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", p["accent_fg"])])
    style.configure("Treeview.Heading", background=p["button"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], font=bold)
    style.map("Treeview.Heading", background=[("active", p["hover"])])
    style.configure("TCombobox", fieldbackground=p["field"], background=p["button"], foreground=p["fg"],
                    arrowcolor=p["fg"], bordercolor=p["border"], lightcolor=p["field"],
                    darkcolor=p["field"], padding=(6, 3))
    style.map("TCombobox",
              fieldbackground=[("disabled", p["surface"]), ("readonly", p["field"])],
              selectbackground=[("readonly", p["field"])],
              selectforeground=[("readonly", p["fg"])],
              background=[("disabled", p["surface"]), ("active", p["hover"]), ("readonly", p["button"])],
              bordercolor=[("focus", p["accent"])],
              arrowcolor=[("disabled", p["disabled"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("ComboboxPopdownFrame", background=p["field"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], relief="solid", borderwidth=1)
    # The combobox drop-down list is a classic Tk listbox
    root.option_add("*TCombobox*Listbox.background", p["field"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
    root.option_add("*TCombobox*Listbox.font", default_font)

    style.configure("Horizontal.TScale", background=p["button"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["button"], darkcolor=p["button"])
    style.map("Horizontal.TScale", background=[("disabled", p["surface"]), ("active", p["hover"])])
    style.configure("Vertical.TScrollbar", background=p["button"], troughcolor=p["field"],
                    bordercolor=p["field"], lightcolor=p["button"], darkcolor=p["button"],
                    arrowcolor=p["fg"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", p["hover"])],
              lightcolor=[("active", p["hover"])], darkcolor=[("active", p["hover"])])
    style.configure("TSeparator", background=p["border"])
    _theme_fonts["reading"] = reading = default_font.copy()
    reading.configure(size=13)
    style.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=8)

    # Classic Tk widgets and the built-in message boxes
    root.option_add("*background", p["bg"])
    root.option_add("*foreground", p["fg"])
    root.option_add("*activeBackground", p["hover"])
    root.option_add("*activeForeground", p["fg"])
    root.option_add("*highlightBackground", p["bg"])
    root.option_add("*Font", default_font)
    root.configure(background=p["bg"])
    if debug_mode:
        print(f"🐛 [DEBUG] UI theme: {mode} (setting: {ui_theme})")

def widen_popdown(combo):
    """Let a combobox's drop-down list grow wider than the box so long names aren't cut off.

    Tk always sizes the list to the box's width, so resize it right after it opens.
    """
    import re

    def adjust():
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            if str(combo.tk.call("wm", "state", popdown)) == "withdrawn":
                return
            font = tkfont.nametofont("TkDefaultFont")
            needed = max((font.measure(str(v)) for v in combo.cget("values")), default=0) + 44
            m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", combo.tk.call("wm", "geometry", popdown))
            if not m or needed <= int(m.group(1)):
                return
            x = min(int(m.group(3)), combo.winfo_screenwidth() - needed)
            combo.tk.call("wm", "geometry", popdown, f"{needed}x{m.group(2)}+{max(0, x)}{m.group(4)}")
        except Exception:
            pass

    # Tk places the list after running postcommand (and processes idle tasks while
    # doing it), so wait a moment before resizing.
    combo.configure(postcommand=lambda: combo.after(25, adjust))

def themed_toplevel(parent, title):
    """A dialog window with the app's background and a padded content frame."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(background=PALETTE["bg"])
    dialog.resizable(False, False)
    content = ttk.Frame(dialog, padding=14)
    content.pack(fill=tk.BOTH, expand=True)
    return dialog, content

def create_control_window():
    global control_window, playback_speed, hotkeys, engine_missing_deps
    window = tk.Tk(className="reader")
    window.title("Clipboard Reader")
    window.resizable(False, False)
    apply_theme(window)

    def safe_showwarning(title, message):
        try:
            if window.winfo_exists():
                messagebox.showwarning(title, message, parent=window)
        except Exception:
            pass

    def safe_showerror(title, message):
        try:
            if window.winfo_exists():
                messagebox.showerror(title, message, parent=window)
        except Exception:
            pass

    content = ttk.Frame(window, padding=(16, 14, 16, 8))
    content.pack(side=tk.LEFT, fill=tk.Y)

    # Settings form: label column + control column, aligned
    form = ttk.Frame(content)
    form.pack(fill=tk.X)
    form.columnconfigure(1, weight=1)

    ttk.Label(form, text="Engine").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=3)
    engine_var = tk.StringVar(value=tts_engine)
    engine_dropdown = ttk.Combobox(form, textvariable=engine_var, values=enabled_engines(), state="readonly", width=14)
    engine_dropdown.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
    def on_engine_select(event=None):
        global tts_engine, engine_missing_deps
        # Stop playback and clear audio files when switching engine
        on_stop()
        # Remove both audio files to avoid mismatches
        try:
            if os.path.exists(audio_file_mp3):
                os.remove(audio_file_mp3)
            if os.path.exists(audio_file_wav):
                os.remove(audio_file_wav)
        except Exception:
            pass
        tts_engine = engine_var.get()
        save_settings()
        load_voices(tts_engine)
        missing_deps = check_engine_dependencies(tts_engine)
        if missing_deps:
            window.set_buttons_state(True)
            engine_missing_deps = True
            handle_missing_engine(tts_engine, missing_deps)
        else:
            window.set_buttons_state(False)
            engine_missing_deps = False
    engine_dropdown.bind("<<ComboboxSelected>>", on_engine_select)

    def handle_missing_engine(engine_name, missing_deps):
        """Offer to install an engine the app can install; otherwise explain what's missing."""
        engine = get_engine(engine_name)
        if engine is not None and engine.can_install():
            question = (f"{engine_name} isn't installed yet.\n\n{engine.install_note}\n\nInstall it now?")
            if messagebox.askyesno(f"Install {engine_name}?", question, parent=window):
                open_install_dialog(engine_name)
            return
        safe_showwarning(
            "Missing Dependencies",
            f"The TTS engine '{engine_name}' is missing:\n\n" + "\n".join(missing_deps),
        )

    def open_install_dialog(engine_name):
        """Run engine.install() in the background with a live log and a Cancel button."""
        engine = get_engine(engine_name)
        cancel_event = threading.Event()
        lines = queue.Queue()
        result = {}
        dialog, body = themed_toplevel(window, f"Installing {engine_name}")
        dialog.transient(window)
        heading = ttk.Label(body, text=f"Installing {engine_name}…", style="Header.TLabel")
        heading.pack(anchor="w")
        progress = ttk.Progressbar(body, orient=tk.HORIZONTAL, length=460, mode="indeterminate")
        progress.pack(fill=tk.X, pady=(8, 8))
        progress.start(12)
        log_frame = ttk.Frame(body)
        log_frame.pack(fill=tk.BOTH, expand=True)
        log_view = tk.Text(log_frame, height=12, width=72, wrap=tk.NONE, font=_theme_fonts["small"],
                           background=PALETTE["field"], foreground=PALETTE["muted"], relief=tk.FLAT,
                           highlightthickness=1, highlightbackground=PALETTE["border"],
                           highlightcolor=PALETTE["border"], padx=8, pady=6)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_view.yview)
        log_view.configure(yscrollcommand=log_scroll.set, state=tk.DISABLED)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        button = ttk.Button(body, text="Cancel")
        button.pack(anchor="e", pady=(10, 0))

        def on_button():
            if "done" in result:
                dialog.destroy()
            elif not cancel_event.is_set():
                cancel_event.set()
                heading.config(text="Cancelling…")
                button.state(["disabled"])
        button.config(command=on_button)
        dialog.protocol("WM_DELETE_WINDOW", on_button)

        def worker():
            try:
                engine.install(lines.put, cancel_event)
                result["done"] = "ok"
            except SynthesisCancelled:
                result["done"] = "cancelled"
            except Exception as e:
                result["done"] = "error"
                result["error"] = str(e)

        def poll():
            global engine_missing_deps
            added = False
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    break
                log_view.configure(state=tk.NORMAL)
                log_view.insert(tk.END, line + "\n")
                if int(log_view.index("end-1c").split(".")[0]) > 2000:
                    log_view.delete("1.0", "500.0")  # keep the log from growing forever
                log_view.configure(state=tk.DISABLED)
                added = True
            if added:
                log_view.see(tk.END)
            if "done" not in result:
                dialog.after(150, poll)
                return
            progress.stop()
            button.state(["!disabled"])
            button.config(text="Close")
            status = result["done"]
            if status == "ok":
                heading.config(text=f"{engine_name} is installed and ready.")
                progress.configure(mode="determinate", value=100)
                if tts_engine == engine_name:
                    engine_missing_deps = False
                    window.set_buttons_state(False)
                    load_voices(engine_name)
            elif status == "cancelled":
                dialog.destroy()
                print(f"Install of {engine_name} cancelled")
            else:
                heading.config(text=f"Install failed: {result.get('error', '')}", style="Error.TLabel",
                               wraplength=460)
                print(f"Install of {engine_name} failed: {result.get('error')}")

        threading.Thread(target=worker, daemon=True).start()
        poll()

    ttk.Label(form, text="Voice").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=3)
    voice_var = tk.StringVar(value="Loading voices…")
    voice_dropdown = ttk.Combobox(form, textvariable=voice_var, values=[], state="disabled", width=14)
    voice_dropdown.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
    widen_popdown(voice_dropdown)
    voice_choices = {"engine": None, "ids": []}

    def show_voices(engine_name, voices):
        """Fill the Voice list for engine_name (main thread)."""
        if engine_name != tts_engine:
            return  # the user switched engines while this list was loading
        voice_choices["engine"] = engine_name
        voices = enabled_voices(engine_name, voices)
        voice_choices["ids"] = [voice_id for voice_id, _ in voices]
        if not voices:
            voice_dropdown.configure(values=["Default"], state="disabled")
            voice_var.set("Default")
            return
        saved = engine_voices.get(engine_name)
        index = voice_choices["ids"].index(saved) if saved in voice_choices["ids"] else 0
        engine_voices[engine_name] = voice_choices["ids"][index]
        voice_dropdown.configure(values=[label for _, label in voices], state="readonly")
        voice_dropdown.current(index)

    def load_voices(engine_name, show_loading=True):
        """List the engine's voices in the background (some engines are slow to list)."""
        if show_loading:
            voice_dropdown.configure(values=[], state="disabled")
            voice_var.set("Loading voices…")
        def worker():
            engine = get_engine(engine_name)
            try:
                voices = engine.list_voices() if engine and not engine.check_dependencies() else []
            except Exception as e:
                print(f"Could not list voices for {engine_name}: {e}")
                voices = []
            main_thread_calls.put(lambda: show_voices(engine_name, voices))
        threading.Thread(target=worker, daemon=True).start()

    def on_voice_select(event=None):
        index = voice_dropdown.current()
        if voice_choices["engine"] == tts_engine and 0 <= index < len(voice_choices["ids"]):
            engine_voices[tts_engine] = voice_choices["ids"][index]
            save_settings()
    voice_dropdown.bind("<<ComboboxSelected>>", on_voice_select)

    global voices_changed_callback
    voices_changed_callback = lambda name: main_thread_calls.put(lambda: load_voices(name, show_loading=False))
    load_voices(tts_engine)

    ttk.Label(form, text="Speed").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=3)
    speed_var = tk.DoubleVar(value=playback_speed)
    def on_speed_change(val):
        global playback_speed
        v = round(float(val) * 10) / 10.0
        if abs(v - speed_var.get()) > 1e-6:
            speed_var.set(v)
        playback_speed = v
        save_settings()
        slider_value_label.config(text=f"{playback_speed:.1f}x")
    speed_slider = ttk.Scale(form, from_=0.5, to=2.0, orient=tk.HORIZONTAL, variable=speed_var, command=on_speed_change, length=130)
    speed_slider.grid(row=2, column=1, sticky="ew", pady=3)
    slider_value_label = ttk.Label(form, text=f"{playback_speed:.1f}x", width=4, anchor="e")
    slider_value_label.grid(row=2, column=2, sticky="e", padx=(8, 0), pady=3)

    # Set window/taskbar icon
    try:
        global taskbar_icon_photo
        taskbar_icon_photo = tk.PhotoImage(file=APP_ICON_PATH)
        window.iconphoto(True, taskbar_icon_photo)
    except Exception:
        try:
            icon_path = ensure_lips_icon_file()
            taskbar_icon_photo = tk.PhotoImage(file=icon_path)
            window.iconphoto(True, taskbar_icon_photo)
        except Exception:
            pass

    ttk.Separator(content).pack(fill=tk.X, pady=(12, 10))

    # Status and playback progress
    status_row = ttk.Frame(content)
    status_row.pack(fill=tk.X)
    status_label = ttk.Label(status_row, text="Running", style="Header.TLabel")
    status_label.pack(side=tk.LEFT)
    time_label = ttk.Label(status_row, text="", style="Muted.TLabel")
    time_label.pack(side=tk.RIGHT)

    def format_time(seconds):
        seconds = int(max(0, seconds))
        h, rem = divmod(seconds, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    def update_time_label():
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        position = playback_position()
        if position is not None and (pygame.mixer.music.get_busy() or is_paused) and current_audio_duration > 0:
            position = min(position, current_audio_duration)
            time_label.config(text=f"{format_time(position)} / {format_time(current_audio_duration)}")
        else:
            time_label.config(text="")
        window.after(250, update_time_label)
    progress_var = tk.DoubleVar(value=0.0)
    progress_bar = ttk.Progressbar(content, orient=tk.HORIZONTAL, mode="determinate", maximum=100, variable=progress_var)
    progress_bar.pack(fill=tk.X, pady=(6, 12))

    # Playback buttons
    button_frame = ttk.Frame(content)
    button_frame.pack(fill=tk.X)
    button_frame.columnconfigure(0, weight=1, uniform="btn")
    button_frame.columnconfigure(1, weight=1, uniform="btn")
    play_btn = ttk.Button(button_frame, text="▶  Play", command=on_play)
    play_btn.grid(row=0, column=0, padx=(0, 4), pady=3, sticky="ew")
    pause_btn = ttk.Button(button_frame, text="❚❚  Pause", command=on_pause)
    pause_btn.grid(row=0, column=1, padx=(4, 0), pady=3, sticky="ew")
    stop_btn = ttk.Button(button_frame, text="■  Stop", command=on_stop)
    stop_btn.grid(row=1, column=0, columnspan=2, pady=3, sticky="ew")
    read_btn = ttk.Button(button_frame, text="Read Clipboard", command=read_selected_text, style="Accent.TButton")
    read_btn.grid(row=2, column=0, columnspan=2, pady=(3, 3), sticky="ew")

    def apply_hotkey_preferences(candidate_hotkeys):
        global hotkeys
        normalized_hotkeys, errors = validate_hotkey_settings(candidate_hotkeys)
        if errors:
            safe_showerror("Invalid Shortcuts", "\n".join(errors))
            return
        hotkeys = normalized_hotkeys
        save_settings()
        return True

    def open_shortcut_preferences():
        dialog, body = themed_toplevel(window, "Shortcut Preferences")
        dialog.transient(window)
        dialog.grab_set()

        modifier_options = [
            "Win",
            "Win+Shift",
            "Ctrl",
            "Ctrl+Shift",
            "Alt",
            "Alt+Shift",
            "Ctrl+Alt",
            "Ctrl+Alt+Shift",
        ]
        key_options = ["Esc", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Space", "Enter", "Tab"]
        shortcut_vars = {}

        ttk.Label(body, text="Action", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        ttk.Label(body, text="Modifier", style="Header.TLabel").grid(row=0, column=1, sticky="w", padx=4, pady=(0, 6))
        ttk.Label(body, text="Key", style="Header.TLabel").grid(row=0, column=2, sticky="w", padx=4, pady=(0, 6))

        for row_index, action in enumerate(HOTKEY_ORDER, start=1):
            modifier, key = hotkey_dropdown_values(hotkeys.get(action, DEFAULT_HOTKEYS[action]))
            modifier_var = tk.StringVar(value=modifier)
            key_var = tk.StringVar(value=key)
            shortcut_vars[action] = (modifier_var, key_var)
            ttk.Label(body, text=HOTKEY_LABELS[action]).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=3)
            ttk.Combobox(body, textvariable=modifier_var, values=modifier_options, state="readonly", width=16).grid(row=row_index, column=1, sticky="ew", padx=4, pady=3)
            ttk.Combobox(body, textvariable=key_var, values=key_options, state="readonly", width=8).grid(row=row_index, column=2, sticky="ew", padx=4, pady=3)

        def selected_hotkeys():
            return {
                action: build_hotkey_from_dropdowns(modifier_var.get(), key_var.get())
                for action, (modifier_var, key_var) in shortcut_vars.items()
            }

        def on_dialog_save():
            if apply_hotkey_preferences(selected_hotkeys()):
                dialog.destroy()

        def on_dialog_reset():
            for action, (modifier_var, key_var) in shortcut_vars.items():
                modifier, key = hotkey_dropdown_values(DEFAULT_HOTKEYS[action])
                modifier_var.set(modifier)
                key_var.set(key)

        button_row = ttk.Frame(body)
        button_row.grid(row=len(HOTKEY_ORDER) + 1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Button(button_row, text="Reset", command=on_dialog_reset, width=8).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Save", command=on_dialog_save, width=8, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(button_row, text="Cancel", command=dialog.destroy, width=8).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    shortcuts_btn = ttk.Button(button_frame, text="Shortcuts…", command=open_shortcut_preferences)
    shortcuts_btn.grid(row=3, column=0, padx=(0, 4), pady=(3, 0), sticky="ew")
    mode_btn = ttk.Button(button_frame, text="Full View ▸")
    mode_btn.grid(row=3, column=1, padx=(4, 0), pady=(3, 0), sticky="ew")

    # Options area: bottom of the left column, shown only in the full view.
    # Add future settings as more rows in options_form.
    options_frame = ttk.Frame(content)
    ttk.Separator(options_frame).pack(fill=tk.X, pady=(0, 10))
    options_form = ttk.Frame(options_frame)
    options_form.pack(fill=tk.X)
    options_form.columnconfigure(1, weight=1)
    ttk.Label(options_form, text="Debug").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=3)
    debug_var = tk.StringVar(value="ON" if debug_mode else "OFF")
    debug_dropdown = ttk.Combobox(options_form, textvariable=debug_var, values=["ON", "OFF"], state="readonly", width=14)
    debug_dropdown.grid(row=0, column=1, sticky="ew", pady=3)
    def on_debug_select(event=None):
        global debug_mode
        debug_mode = (debug_var.get() == "ON")
        save_settings()
    debug_dropdown.bind("<<ComboboxSelected>>", on_debug_select)
    manage_btn = ttk.Button(options_form, text="Engines & Voices…", command=lambda: open_engine_manager())
    manage_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 3))

    def refresh_engine_choices():
        """Re-apply enable/disable settings to the Engine and Voice lists."""
        names = enabled_engines()
        engine_dropdown.configure(values=names)
        if tts_engine not in names:
            engine_var.set(names[0])
            on_engine_select()  # the current engine was turned off: switch to the first one on
        else:
            load_voices(tts_engine, show_loading=False)

    # Voice downloads started from the manager ("engine|voice" -> progress); they keep
    # going if the dialog is closed. manager_hooks["refresh"] reloads an engine's
    # voices in the open dialog, if there is one.
    active_downloads = {}
    manager_hooks = {"refresh": None}

    def after_voice_files_changed(engine_name):
        if voices_changed_callback is not None:
            voices_changed_callback(engine_name)   # main Voice drop-down labels
        if manager_hooks["refresh"] is not None:
            manager_hooks["refresh"](engine_name)  # the manager's list and details

    def open_engine_manager():
        """Turn engines and voices on or off, and see details, speed and ratings for each."""
        dialog, body = themed_toplevel(window, "Engines & Voices")
        dialog.transient(window)
        dialog.resizable(True, True)
        dialog.minsize(950, 520)
        ttk.Label(body, text="Click a row's box to turn it on or off; turned-off engines and voices are hidden "
                             "from the drop-downs. Select a row to see its details.", wraplength=780).pack(anchor="w")

        panes = ttk.Frame(body)
        panes.pack(fill=tk.BOTH, expand=True, pady=(10, 8))
        tree_frame = ttk.Frame(panes)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_frame, columns=("where", "speed", "quality"), show="tree headings",
                            selectmode="browse", height=16)
        tree.heading("#0", text="Engine / voice", anchor="w")
        tree.heading("where", text="Generated", anchor="w")
        tree.heading("speed", text="Speed", anchor="w")
        tree.heading("quality", text="Quality", anchor="w")
        tree.column("#0", width=300, stretch=True)
        tree.column("where", width=130, stretch=False)
        tree.column("speed", width=90, stretch=False)
        tree.column("quality", width=96, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.tag_configure("off", foreground=PALETTE["disabled"])
        tree.tag_configure("engine", font=_theme_fonts["bold"])

        ttk.Separator(panes, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)
        details = ttk.Frame(panes, width=300)
        details.pack(side=tk.LEFT, fill=tk.Y)
        details.pack_propagate(False)

        note = ttk.Label(body, text="", style="Muted.TLabel")
        note.pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(10, 0))

        all_names = sorted(list_engines(), key=str.lower)
        voice_lists = {}   # engine -> [(voice_id, label)]
        rows = {}          # tree item -> ("engine", name) or ("voice", name, voice_id)
        engine_items = {}
        selected = {"row": None}

        def box(on):
            return "☑" if on else "☐"

        def rating_of(name, voice_id):
            return voice_ratings.get(voice_key(name, voice_id), get_engine(name).quality)

        def speed_of(name, voice_id=None):
            """(rtf, runs) for a voice, or the average over an engine's measured voices."""
            if voice_id is not None:
                stat = voice_stats.get(voice_key(name, voice_id))
                return (stat["rtf"], stat["runs"]) if stat else (None, 0)
            measured = [v for k, v in voice_stats.items() if k.split("|", 1)[0] == name]
            if not measured:
                return None, 0
            return sum(v["rtf"] for v in measured) / len(measured), sum(v["runs"] for v in measured)

        def engine_text(name):
            text = f"{box(name not in disabled_engines)}  {name}"
            voices = voice_lists.get(name)
            if voices:
                on = sum(1 for v, _ in voices if v not in disabled_voices.get(name, set()))
                text += f"   ({on} of {len(voices)} on)"
            elif voices is None:
                text += "   (loading…)"
            if get_engine(name).check_dependencies():
                text += "   – not installed"
            return text

        def redraw(name):
            item = engine_items[name]
            rtf, _ = speed_of(name)
            tree.item(item, text=engine_text(name),
                      values=(generated_where(get_engine(name)), speed_word(rtf) if rtf is not None else "—",
                              stars(get_engine(name).quality)),
                      tags=("engine",) + (("off",) if name in disabled_engines else ()))
            labels = dict(voice_lists.get(name, []))
            for child in tree.get_children(item):
                kind = rows.get(child)
                if kind and kind[0] == "voice":
                    on = kind[2] not in disabled_voices.get(name, set())
                    rtf, _ = speed_of(name, kind[2])
                    tree.item(child, text=f"{box(on)}  {labels.get(kind[2], kind[2])}",
                              values=(generated_where(get_engine(name)), speed_word(rtf) if rtf is not None else "—",
                                      stars(rating_of(name, kind[2]))),
                              tags=() if on and name not in disabled_engines else ("off",))

        for name in all_names:
            item = tree.insert("", tk.END, text="", open=False)
            engine_items[name] = item
            rows[item] = ("engine", name)
            redraw(name)

        def fill_voices(name, voices):
            previous = rows.get(selected["row"]) if selected["row"] else None
            voice_lists[name] = voices
            item = engine_items[name]
            for child in tree.get_children(item):
                tree.delete(child)
                rows.pop(child, None)
            reselect = None
            for voice_id, _ in voices:
                child = tree.insert(item, tk.END, text="")
                rows[child] = ("voice", name, voice_id)
                if previous and previous[0] == "voice" and previous[1] == name and previous[2] == voice_id:
                    reselect = child
            redraw(name)
            if reselect is not None:
                tree.selection_set(reselect)
                show_details(reselect)
            elif previous and previous[1] == name:
                show_details(selected["row"])

        def refresh_engine(name):
            def work():
                engine = get_engine(name)
                try:
                    voices = engine.list_voices() if not engine.check_dependencies() else []
                except Exception:
                    voices = []
                main_thread_calls.put(lambda: dialog.winfo_exists() and fill_voices(name, voices))
            threading.Thread(target=work, daemon=True).start()
        manager_hooks["refresh"] = refresh_engine
        dialog.bind("<Destroy>", lambda e: e.widget is dialog and manager_hooks.update(refresh=None))

        def load_all():
            for name in all_names:
                engine = get_engine(name)
                try:
                    voices = engine.list_voices() if not engine.check_dependencies() else []
                except Exception:
                    voices = []
                main_thread_calls.put(lambda n=name, v=voices: dialog.winfo_exists() and fill_voices(n, v))
        threading.Thread(target=load_all, daemon=True).start()

        # ---- details panel
        def clear_details():
            for child in details.winfo_children():
                child.destroy()

        def field(grid, row, label, value):
            ttk.Label(grid, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=2)
            ttk.Label(grid, text=value, wraplength=190, justify="left").grid(row=row, column=1, sticky="nw", pady=2)

        def speed_sentence(rtf, runs):
            if rtf is None:
                return "Not measured yet. Read something or press Preview."
            seconds = rtf * 60
            took = f"{seconds:.0f} s" if seconds >= 1.5 else f"{seconds:.1f} s"
            return f"{speed_word(rtf)}: about {took} to build 1 minute of speech ({runs} read{'s' if runs != 1 else ''})"

        def show_details(item):
            selected["row"] = item
            kind = rows.get(item)
            clear_details()
            if not kind:
                return
            name = kind[1]
            engine = get_engine(name)
            voice_id = kind[2] if kind[0] == "voice" else None
            label = dict(voice_lists.get(name, [])).get(voice_id, voice_id) if voice_id else name
            ttk.Label(details, text=label, style="Header.TLabel", wraplength=290).pack(anchor="w")
            subtitle = f"{name} voice" if voice_id else engine.about
            ttk.Label(details, text=subtitle, style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(2, 8))
            # Actions and rating go first so they're always visible; the detail rows follow
            actions = ttk.Frame(details)
            actions.pack(anchor="w", fill=tk.X)
            download_holder = ttk.Frame(details)
            download_holder.pack(anchor="w", fill=tk.X)
            rating_holder = ttk.Frame(details)
            rating_holder.pack(anchor="w", fill=tk.X)
            ttk.Separator(details).pack(fill=tk.X, pady=(10, 8))
            grid = ttk.Frame(details)
            grid.pack(anchor="w", fill=tk.X)
            row = 0
            if voice_id is None:
                missing = engine.check_dependencies()
                voices = voice_lists.get(name)
                field(grid, row, "Status", "Not installed" if missing else ("On" if name not in disabled_engines else "Off")); row += 1
                field(grid, row, "Voices", "loading…" if voices is None else str(len(voices) or 1)); row += 1
                field(grid, row, "Generated", generated_where(engine, long=True)); row += 1
                field(grid, row, "Internet", "Needed" if engine.needs_internet else "Not needed (works offline)"); row += 1
                field(grid, row, "Format", engine.output_ext.upper()); row += 1
                infos = []
                for v, _ in voices or []:
                    try:
                        info = engine.voice_download_info(v)
                    except Exception:
                        info = None
                    if info is not None:
                        infos.append(info)
                if infos:
                    got = [i for i in infos if i["downloaded"]]
                    total = sum(i["size_bytes"] for i in got)
                    field(grid, row, "On disk", f"{len(got)} of {len(infos)} voices downloaded · {total / 1e6:.0f} MB"); row += 1
                rtf, runs = speed_of(name)
                field(grid, row, "Speed", speed_sentence(rtf, runs)); row += 1
                field(grid, row, "Quality", f"{stars(engine.quality)}  (typical for this engine)"); row += 1
            else:
                try:
                    info = engine.describe_voice(voice_id)
                except Exception as e:
                    info = {"Details": f"unavailable ({e})"}
                field(grid, row, "Generated", generated_where(engine, long=True)); row += 1
                for key, value in info.items():
                    if key == "Runs":
                        continue  # covered by "Generated"
                    field(grid, row, key, value); row += 1
                rtf, runs = speed_of(name, voice_id)
                field(grid, row, "Speed", speed_sentence(rtf, runs)); row += 1

                rating_row = ttk.Frame(rating_holder)
                rating_row.pack(anchor="w", pady=(8, 0))
                ttk.Label(rating_row, text="Your rating", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
                current = rating_of(name, voice_id)
                key = voice_key(name, voice_id)
                for n in range(1, 6):
                    star = ttk.Label(rating_row, text="★" if n <= current else "☆", cursor="hand2",
                                     foreground=PALETTE["accent"], font=_theme_fonts["reading"])
                    star.pack(side=tk.LEFT)
                    star.bind("<Button-1>", lambda _e, n=n: set_rating(key, n))
                if key in voice_ratings:
                    reset = ttk.Label(rating_row, text="reset", style="Muted.TLabel", cursor="hand2")
                    reset.pack(side=tk.LEFT, padx=(8, 0))
                    reset.bind("<Button-1>", lambda _e: set_rating(key, None))
                else:
                    ttk.Label(rating_row, text="(default)", style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 0))

            if voice_id is not None:
                try:
                    download = engine.voice_download_info(voice_id)
                except Exception:
                    download = None
                if download is not None:
                    download_controls(name, voice_id, download, download_holder)

            preview_row = ttk.Frame(actions)
            preview_row.pack(anchor="w", fill=tk.X)
            preview_btn = ttk.Button(preview_row, text="▶  Preview", command=lambda: preview(name, voice_id, preview_status, preview_btn))
            preview_btn.pack(side=tk.LEFT)
            preview_status = ttk.Label(preview_row, text="", style="Muted.TLabel", wraplength=180)
            preview_status.pack(side=tk.LEFT, padx=(8, 0))
            if engine.check_dependencies():
                preview_btn.state(["disabled"])

        def download_controls(name, voice_id, info, parent):
            """Download button with progress, or Delete for a downloaded voice."""
            key = voice_key(name, voice_id)
            area = ttk.Frame(parent)
            area.pack(anchor="w", fill=tk.X, pady=(8, 0))
            job = active_downloads.get(key)
            if job and not job["finished"]:
                bar = ttk.Progressbar(area, orient=tk.HORIZONTAL, mode="determinate", maximum=100, length=290)
                bar.pack(anchor="w", fill=tk.X)
                status = ttk.Label(area, text="Starting download…", style="Muted.TLabel")
                status.pack(anchor="w", pady=(4, 0))
                ttk.Button(area, text="Cancel download", command=job["cancel"].set).pack(anchor="w", pady=(6, 0))

                def tick():
                    if not bar.winfo_exists():
                        return
                    if job["finished"]:
                        return  # the reload after the download redraws this panel
                    done, total = job["done"], job["total"] or 1
                    bar.configure(value=100 * done / total)
                    status.config(text=f"Downloading: {done / 1e6:.1f} of {total / 1e6:.0f} MB ({100 * done / total:.0f}%)")
                    bar.after(200, tick)
                tick()
                return
            if info["downloaded"]:
                ttk.Button(area, text="Delete download", command=lambda: delete_download(name, voice_id, info)).pack(side=tk.LEFT)
                ttk.Label(area, text=f"frees {info['size_bytes'] / 1e6:.0f} MB", style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 0))
            else:
                ttk.Button(area, text=f"Download ({info['size_bytes'] / 1e6:.0f} MB)",
                           command=lambda: start_download(name, voice_id, info)).pack(side=tk.LEFT)
            if job and job.get("error"):
                ttk.Label(parent, text=job["error"], style="Error.TLabel", wraplength=290).pack(anchor="w", pady=(4, 0))

        def start_download(name, voice_id, info):
            key = voice_key(name, voice_id)
            job = {"done": 0, "total": info["size_bytes"], "cancel": threading.Event(), "finished": False, "error": None}
            active_downloads[key] = job

            def progress(done, total):
                job["done"], job["total"] = done, total

            def work():
                try:
                    get_engine(name).download_voice(voice_id, progress, job["cancel"])
                except SynthesisCancelled:
                    job["error"] = "Download cancelled."
                except Exception as e:
                    job["error"] = f"Download failed: {e}"
                finally:
                    job["finished"] = True
                    main_thread_calls.put(lambda: after_voice_files_changed(name))
            threading.Thread(target=work, daemon=True).start()
            show_details(selected["row"])

        def delete_download(name, voice_id, info):
            label = dict(voice_lists.get(name, [])).get(voice_id, voice_id).split(" · ")[0]
            if not messagebox.askyesno(
                "Delete voice",
                f"Delete the downloaded {name} voice {label}?\n\nThis frees {info['size_bytes'] / 1e6:.0f} MB. "
                "It will download again the next time you use it.",
                parent=dialog,
            ):
                return
            try:
                get_engine(name).delete_voice(voice_id)
                active_downloads.pop(voice_key(name, voice_id), None)
            except Exception as e:
                note.config(text=f"Could not delete: {e}")
            after_voice_files_changed(name)

        def set_rating(key, value):
            if value is None:
                voice_ratings.pop(key, None)
            else:
                voice_ratings[key] = value
            save_settings()
            name = key.split("|", 1)[0]
            redraw(name)
            show_details(selected["row"])

        def preview(name, voice_id, status_label, button):
            """Speak a short sample with this voice (and measure its speed)."""
            if pygame.mixer.music.get_busy() or current_build is not None or audio_preparing:
                status_label.config(text="Stop the current reading first.")
                return
            engine = get_engine(name)
            if voice_id is None:
                choices = [v for v, _ in enabled_voices(name, voice_lists.get(name, []))]
                voice_id = engine_voices.get(name) if engine_voices.get(name) in choices else (choices[0] if choices else None)
            speaker = (dict(voice_lists.get(name, [])).get(voice_id, name) or name).split(" (")[0].split(" · ")[0]
            sample = f"Hello, this is {speaker}. Here is how I sound reading a sentence aloud."

            # A voice that isn't downloaded yet is fetched first, with a progress dialog
            try:
                download = engine.voice_download_info(voice_id)
            except Exception:
                download = None
            key = voice_key(name, voice_id)
            job = None
            if download and not download["downloaded"]:
                running = active_downloads.get(key)
                if running and not running["finished"]:
                    status_label.config(text="This voice is already downloading.")
                    return
                job = {"done": 0, "total": download["size_bytes"], "cancel": threading.Event(),
                       "finished": False, "error": None, "phase": "download"}
                active_downloads[key] = job
                preview_progress_dialog(job, speaker)
                show_details(selected["row"])  # the panel shows the download too
            else:
                button.state(["disabled"])
                status_label.config(text="Building sample…")

            def work():
                import tempfile
                if job is not None:
                    try:
                        engine.download_voice(voice_id, lambda d, t: job.update(done=d, total=t), job["cancel"])
                    except SynthesisCancelled:
                        job["error"] = "Download cancelled."
                    except Exception as e:
                        job["error"] = f"Download failed: {e}"
                    finally:
                        job["finished"] = True
                        main_thread_calls.put(lambda: after_voice_files_changed(name))
                    if job["error"]:
                        job["phase"] = "closed"
                        return
                    job["phase"] = "building"
                try:
                    ready = engine.voice_ready(voice_id)
                    tmp = tempfile.mkdtemp(prefix="textreader-preview-")
                    path = os.path.join(tmp, "sample." + engine.output_ext)
                    started = time.monotonic()
                    engine.synthesize(sample, path, threading.Event(), voice=voice_id)
                    took = time.monotonic() - started
                    length = get_audio_duration(path)
                    wav = path
                    if not path.endswith(".wav"):
                        wav = os.path.join(tmp, "sample.wav")
                        run_cancellable(["ffmpeg", "-y", "-loglevel", "error", "-i", path, wav], timeout=30)
                    sound = pygame.mixer.Sound(wav)
                    if job is not None:
                        job["phase"] = "closed"
                    sound.play()
                    def done():
                        if ready:
                            record_speed(name, voice_id, took, length)
                            save_settings()
                        if dialog.winfo_exists():
                            redraw(name)
                            show_details(selected["row"])
                    main_thread_calls.put(done)
                    time.sleep(sound.get_length() + 0.5)
                    shutil.rmtree(tmp, ignore_errors=True)
                except Exception as e:
                    if job is not None:
                        job["phase"] = "closed"
                    main_thread_calls.put(lambda: status_label.winfo_exists() and (
                        status_label.config(text=f"Preview failed: {e}"), button.state(["!disabled"])))
            threading.Thread(target=work, daemon=True).start()

        def preview_progress_dialog(job, speaker):
            """'Downloading Voice' window for a preview: download progress, then building, then it closes."""
            win, box = themed_toplevel(dialog, "Downloading Voice")
            win.transient(dialog)
            win.minsize(340, 0)
            text = ttk.Label(box, text=f"Downloading {speaker}…")
            text.pack(anchor="w")
            bar = ttk.Progressbar(box, orient=tk.HORIZONTAL, length=300, mode="determinate", maximum=100)
            bar.pack(fill=tk.X, pady=(10, 12))
            cancel = ttk.Button(box, text="Cancel", command=job["cancel"].set)
            cancel.pack(anchor="e")
            win.protocol("WM_DELETE_WINDOW", job["cancel"].set)

            def tick():
                if not win.winfo_exists():
                    return
                phase = job.get("phase")
                if phase == "closed":
                    win.destroy()
                    return
                if phase == "building":
                    if str(bar.cget("mode")) != "indeterminate":
                        win.title("Building Preview")
                        text.config(text=f"Downloaded. Building the {speaker} sample…")
                        bar.configure(mode="indeterminate")
                        bar.start(10)
                        cancel.state(["disabled"])
                else:
                    done, total = job["done"], job["total"] or 1
                    bar.configure(value=100 * done / total)
                    text.config(text=f"Downloading {speaker}: {done / 1e6:.1f} of {total / 1e6:.0f} MB ({100 * done / total:.0f}%)")
                win.after(150, tick)
            tick()

        def changed():
            save_settings()
            refresh_engine_choices()

        def toggle(item):
            kind = rows.get(item)
            if not kind:
                return
            note.config(text="")
            if kind[0] == "engine":
                name = kind[1]
                if name in disabled_engines:
                    disabled_engines.discard(name)
                elif len([n for n in all_names if n not in disabled_engines]) <= 1:
                    note.config(text="At least one engine has to stay on.")
                    return
                else:
                    disabled_engines.add(name)
            else:
                _, name, voice_id = kind
                off = disabled_voices.setdefault(name, set())
                if voice_id in off:
                    off.discard(voice_id)
                elif len(voice_lists.get(name, [])) - len(off) <= 1:
                    note.config(text=f"At least one {name} voice has to stay on.")
                    return
                else:
                    off.add(voice_id)
            redraw(kind[1])
            changed()
            if selected["row"] == item:
                show_details(item)

        def on_click(event):
            item = tree.identify_row(event.y)
            if not item or tree.identify_region(event.x, event.y) not in ("tree", "cell"):
                return
            element = tree.identify_element(event.x, event.y)
            if element in ("Treeitem.indicator", "indicator"):
                return  # the expand arrow only opens/closes the engine
            # Only clicks on the box (left part of the name column) toggle; elsewhere just selects
            if tree.identify_column(event.x) == "#0":
                bbox = tree.bbox(item, "#0")
                if bbox and event.x - bbox[0] < 60 + (20 if rows[item][0] == "voice" else 0):
                    toggle(item)
        tree.bind("<ButtonRelease-1>", on_click)
        tree.bind("<<TreeviewSelect>>", lambda _e: tree.selection() and show_details(tree.selection()[0]))
        tree.bind("<space>", lambda e: toggle(tree.focus()))

        def set_all_voices(on):
            item = tree.focus()
            kind = rows.get(item)
            if not kind:
                note.config(text="Select an engine or one of its voices first.")
                return
            name = kind[1]
            disabled_voices[name] = set() if on else {v for v, _ in voice_lists.get(name, [])[1:]}
            if not on:
                note.config(text=f"All {name} voices off except the first (one has to stay on).")
            redraw(name)
            changed()

        ttk.Button(buttons, text="All voices on", command=lambda: set_all_voices(True)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="All voices off", command=lambda: set_all_voices(False)).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(buttons, text="Close", style="Accent.TButton", command=dialog.destroy, width=8).pack(side=tk.RIGHT)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

        # Start with the current engine selected
        tree.selection_set(engine_items.get(tts_engine, engine_items[all_names[0]]))

    version_label = ttk.Label(content, text=f"Version {__version__}", style="Muted.TLabel")
    version_label.pack(pady=(12, 0))

    # ---- Full view: the text being read, with the current word highlighted
    p = PALETTE
    divider = ttk.Separator(window, orient=tk.VERTICAL)
    reading_panel = ttk.Frame(window, padding=(14, 14, 16, 12))
    reading_header = ttk.Frame(reading_panel)
    reading_header.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(reading_header, text="Now Reading", style="Header.TLabel").pack(side=tk.LEFT)
    word_count_label = ttk.Label(reading_header, text="", style="Muted.TLabel")
    word_count_label.pack(side=tk.RIGHT)
    text_frame = ttk.Frame(reading_panel)
    text_frame.pack(fill=tk.BOTH, expand=True)
    reading_view = tk.Text(
        text_frame, wrap=tk.WORD, font=_theme_fonts["reading"], relief=tk.FLAT, borderwidth=0,
        background=p["field"], foreground=p["fg"], insertbackground=p["fg"],
        selectbackground=p["accent"], selectforeground=p["accent_fg"],
        highlightthickness=1, highlightbackground=p["border"], highlightcolor=p["border"],
        padx=14, pady=12, spacing1=2, spacing2=4, spacing3=6, cursor="arrow",
        width=46, height=14,
    )
    reading_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=reading_view.yview)
    reading_view.configure(yscrollcommand=reading_scroll.set)
    reading_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    reading_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    reading_view.tag_configure("placeholder", foreground=p["muted"])
    reading_view.tag_configure("spoken", foreground=p["muted"])
    reading_view.tag_configure("current", background=p["accent"], foreground=p["accent_fg"])
    reading_view.configure(state=tk.DISABLED)

    view_state = {"serial": None, "word": None}

    def show_reading_text():
        with reading_lock:
            text, serial, count = reading_text, reading_serial, len(reading_spans)
        reading_view.configure(state=tk.NORMAL)
        reading_view.delete("1.0", tk.END)
        if text:
            reading_view.insert("1.0", text)
        else:
            reading_view.insert("1.0", "Text appears here while it's read aloud, "
                                       "with the current word highlighted.", "placeholder")
        reading_view.configure(state=tk.DISABLED)
        reading_view.yview_moveto(0)
        word_count_label.config(text=f"{count} words" if count else "")
        view_state["serial"] = serial
        view_state["word"] = None

    def highlight_word(index):
        """Highlight word `index` (-1 for none) and dim the words already spoken."""
        if index == view_state["word"]:
            return
        view_state["word"] = index
        reading_view.tag_remove("current", "1.0", tk.END)
        reading_view.tag_remove("spoken", "1.0", tk.END)
        with reading_lock:
            spans = reading_spans
        if 0 <= index < len(spans):
            start, end = spans[index]
            reading_view.tag_add("spoken", "1.0", f"1.0+{start}c")
            reading_view.tag_add("current", f"1.0+{start}c", f"1.0+{end}c")
            reading_view.see(f"1.0+{end}c")
            word_count_label.config(text=f"Word {index + 1} of {len(spans)}")
        elif spans:
            word_count_label.config(text=f"{len(spans)} words")

    def update_reading_view():
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        if view_mode == "full":
            if view_state["serial"] != reading_serial:
                show_reading_text()
            position = playback_position()
            playing = pygame.mixer.music.get_busy() or is_paused
            with reading_lock:
                timeline = reading_timeline
            if playing and position is not None and timeline:
                highlight_word(max(0, word_timing.word_at(timeline, position)))
            elif not playing:
                highlight_word(-1)
        window.after(80, update_reading_view)

    def compact_size():
        content.update_idletasks()
        return max(content.winfo_reqwidth(), 320), content.winfo_reqheight()

    def apply_view_mode(remember_size=True):
        global full_window_size
        # Compact shows the version footer; full shows the options area instead
        if view_mode == "full":
            version_label.pack_forget()
            options_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        else:
            options_frame.pack_forget()
            version_label.pack(pady=(12, 0))
        width, height = compact_size()
        if view_mode == "full":
            # Controls keep their natural width; the reading panel takes the rest
            content.pack_configure(fill=tk.Y, expand=False)
            divider.pack(side=tk.LEFT, fill=tk.Y)
            reading_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            window.resizable(True, True)
            window.minsize(width + 320, height)
            window.geometry(full_window_size or f"{width + 520}x{max(height, 460)}")
            mode_btn.config(text="◂ Compact")
            show_reading_text()
        else:
            if remember_size and window.winfo_ismapped() and reading_panel.winfo_ismapped():
                full_window_size = f"{window.winfo_width()}x{window.winfo_height()}"
            reading_panel.pack_forget()
            divider.pack_forget()
            # Controls stretch across the whole window so the margins are even
            content.pack_configure(fill=tk.BOTH, expand=True)
            window.minsize(width, height)
            window.geometry(f"{width}x{height}")
            window.resizable(False, False)
            mode_btn.config(text="Full View ▸")

    def toggle_view_mode():
        global view_mode
        view_mode = "compact" if view_mode == "full" else "full"
        apply_view_mode()
        save_settings()

    mode_btn.config(command=toggle_view_mode)
    apply_view_mode(remember_size=False)
    update_reading_view()

    def set_controls_state(disabled: bool):
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        ttk_state = "disabled" if disabled else "!disabled"
        play_btn.state([ttk_state])
        pause_btn.state([ttk_state])
        stop_btn.state([ttk_state])
        read_btn.state([ttk_state])
        speed_slider.state([ttk_state])
        shortcuts_btn.state([ttk_state])
    window.set_buttons_state = set_controls_state

    current_missing = check_engine_dependencies(tts_engine)
    if debug_mode:
        if current_missing:
            print(f"🐛 [DEBUG] Missing deps for selected engine {tts_engine}: {current_missing}")
        else:
            print(f"🐛 [DEBUG] Selected engine {tts_engine} dependencies satisfied")
    if current_missing:
        window.after(400, lambda: handle_missing_engine(tts_engine, current_missing))
    if current_missing:
        engine_missing_deps = True
        window.set_buttons_state(True)
    else:
        engine_missing_deps = False
        window.set_buttons_state(False)
    def update_status():
        global current_progress
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        if engine_missing_deps:
            play_btn.state(["disabled"])
            pause_btn.state(["disabled"])
            stop_btn.state(["disabled"])
            read_btn.state(["disabled"])
            speed_slider.state(["disabled"])
            status_label.config(text="Missing dependencies")
            window.after(500, update_status)
            return
        busy_preparing = current_build is not None or audio_preparing
        if busy_preparing and not pygame.mixer.music.get_busy() and not is_paused:
            status_label.config(text="Building audio…" if current_build is not None else "Preparing audio…")
            speed_slider.state(["disabled"])
            progress_var.set(0.0)
        elif pygame.mixer.music.get_busy() or is_paused:
            if is_paused:
                status_label.config(text="Paused")
            else:
                status_label.config(text="Playing")
            speed_slider.state(["disabled"])
            if playback_start_time and current_audio_duration > 0:
                if not is_paused:
                    now = time.monotonic()
                    elapsed = now - playback_start_time - playback_pause_accum
                    current_progress = max(0.0, min(100.0, (elapsed / current_audio_duration) * 100.0))
                progress_var.set(current_progress)
            else:
                progress_var.set(0.0)
        else:
            status_label.config(text="Stopped")
            speed_slider.state(["!disabled"])
            progress_var.set(0.0)
        if has_audio_file():
            play_btn.state(["!disabled"])
        else:
            play_btn.state(["disabled"])
        if pygame.mixer.music.get_busy() or (is_paused and has_audio_file()):
            pause_btn.state(["!disabled"])
            stop_btn.state(["!disabled"])
        else:
            pause_btn.state(["disabled"])
            # Stop stays available while audio is being built or prepared, so it can always be cancelled
            stop_btn.state(["!disabled"] if busy_preparing else ["disabled"])
        try:
            window.after(500, update_status)
        except Exception:
            pass
    update_status()
    update_time_label()
    def on_close():
        global is_running, full_window_size
        is_running = False
        try:
            if view_mode == "full":
                full_window_size = f"{window.winfo_width()}x{window.winfo_height()}"
                save_settings()
        except Exception:
            pass
        try:
            if tray_icon:
                tray_icon.stop()
        except Exception:
            pass
        try:
            window.quit()
            window.destroy()
        except Exception:
            pass
    try:
        if window.winfo_exists():
            window.protocol("WM_DELETE_WINDOW", on_close)
    except Exception:
        pass
    control_window = window

    def pump_main_thread_calls():
        while True:
            try:
                func = main_thread_calls.get_nowait()
            except queue.Empty:
                break
            try:
                func()
            except Exception as e:
                print(f"Error: {e}")
        window.after(50, pump_main_thread_calls)
    window.after(50, pump_main_thread_calls)
    window.mainloop()

def on_press(key):
    """Handle keyboard press events"""
    global cmd_pressed, shift_pressed
    try:
        key_name = key_name_for(key)
        if key_name:
            pressed_keys.add(key_name)
        if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
            cmd_pressed = True
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            shift_pressed = True
        for action in HOTKEY_ORDER:
            combo = parse_hotkey(hotkeys.get(action, DEFAULT_HOTKEYS[action]))
            if combo and combo.issubset(pressed_keys) and action not in active_hotkeys:
                active_hotkeys.add(action)
                if debug_mode:
                    print(f"🐛 [DEBUG] Hotkey: {action} (keys held: {sorted(pressed_keys)})")
                trigger_hotkey(action)
                break
    except Exception as e:
        # An exception here would stop the pynput listener and kill every hotkey
        print(f"Hotkey error: {e}")

def on_release(key):
    """Handle keyboard release events"""
    global cmd_pressed, shift_pressed
    try:
        if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
            cmd_pressed = False
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            shift_pressed = False
        key_name = key_name_for(key)
        if key_name:
            pressed_keys.discard(key_name)
        for action in list(active_hotkeys):
            combo = parse_hotkey(hotkeys.get(action, DEFAULT_HOTKEYS[action]))
            if not combo or not combo.issubset(pressed_keys):
                active_hotkeys.discard(action)
    except Exception as e:
        print(f"Hotkey error: {e}")

def setup_hotkeys():
    """Setup keyboard listener for control"""
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    return listener

def clipboard_monitor():
    """Monitor clipboard and speak new content"""
    global is_running, is_paused, listener

    while is_running:
        try:
            # Short pause to prevent high CPU usage
            time.sleep(0.5)
            # If the keyboard listener ever dies, start a new one so hotkeys keep working
            if is_running and listener is not None and not listener.is_alive():
                print("⚠️ Hotkey listener stopped; restarting it")
                pressed_keys.clear()
                active_hotkeys.clear()
                listener = setup_hotkeys()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

def run_tray():
    """Run the system tray icon (display only, no menu)"""
    global tray_icon
    try:
        image = Image.open(APP_ICON_PATH).convert("RGBA")
    except Exception:
        try:
            image = Image.open(ensure_lips_icon_file()).convert("RGBA")
        except Exception:
            image = create_lips_icon()
    tray_icon = Icon("clipboard_reader_tray", image, title="Clipboard Reader")
    print("System tray icon created.")
    tray_icon.run(setup=lambda icon: None)

# Remove any leftover audio files from previous runs
cleanup_audio_files()

listener = None

# Start clipboard monitoring in background thread
monitor_thread = threading.Thread(target=clipboard_monitor, daemon=True)
monitor_thread.start()

# Setup keyboard listener
listener = setup_hotkeys()

# Run system tray icon in background thread
tray_thread = threading.Thread(target=run_tray, daemon=True)
tray_thread.start()

print("=" * 50)
print(f"Clipboard Reader {__version__} started")
print("=" * 50)
print("📋 Using Google Text-to-Speech")
print("\n🎮 Keyboard Controls:")
for action in HOTKEY_ORDER:
    print(f"  {hotkeys.get(action, DEFAULT_HOTKEYS[action])}  - {HOTKEY_LABELS[action]}")
print("\nControl window opening...")
print("Lips icon in system tray...")
print("=" * 50)

# Run control window on main thread (Tkinter requires main thread)
try:
    create_control_window()
except KeyboardInterrupt:
    pass

# Cleanup
print("\nProgram stopped.")
is_running = False
listener.stop()
if os.path.exists(audio_file_mp3):
    os.remove(audio_file_mp3)
if os.path.exists(audio_file_wav):
    os.remove(audio_file_wav)
for speed_file in SETTINGS_DIR.glob("clipboard_speech_speed.*"):
    speed_file.unlink(missing_ok=True)
icon_path = SETTINGS_DIR / "lips_icon.png"
if os.path.exists(icon_path):
    os.remove(icon_path)
