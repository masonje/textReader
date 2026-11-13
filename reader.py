
__version__ = "1.2.0"

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
            json.dump({"debug_mode": debug_mode, "playback_speed": playback_speed, "tts_engine": tts_engine, "hotkeys": hotkeys, "theme": ui_theme, "view_mode": view_mode, "full_window_size": full_window_size}, f, indent=2)
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
        temp_speed_file = str(SETTINGS_DIR / "clipboard_speech_speed.mp3")
        if os.path.exists(temp_speed_file):
            os.remove(temp_speed_file)
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
        if playback_speed != 1.0 and tts_engine == "gTTS":
            temp_speed_file = str(SETTINGS_DIR / "clipboard_speech_speed.mp3")
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
            engine.synthesize(text, temp_path, cancel_event)
            if cancel_event.is_set():
                raise SynthesisCancelled()
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                results.put(("error", "Engine produced no audio"))
                return
            results.put(("done", None))
        except SynthesisCancelled:
            results.put(("cancelled", None))
        except Exception as e:
            results.put(("error", str(e)))

    dialog, content = themed_toplevel(control_window, "Building Audio")
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

    def poll():
        if cancel_event.is_set():
            close_dialog()  # e.g. cancelled by the Stop hotkey or a newer read
        try:
            status, message = results.get_nowait()
        except queue.Empty:
            control_window.after(100, poll)
            return
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
    global control_window, playback_speed, hotkeys
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
    engine_dropdown = ttk.Combobox(form, textvariable=engine_var, values=list_engines(), state="readonly", width=14)
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
        missing_deps = check_engine_dependencies(tts_engine)
        if missing_deps:
            safe_showwarning(
                "Missing Dependencies",
                "The selected TTS engine is missing:\n\n" + "\n".join(missing_deps),
            )
            window.set_buttons_state(True)
            engine_missing_deps = True
        else:
            window.set_buttons_state(False)
            engine_missing_deps = False
    engine_dropdown.bind("<<ComboboxSelected>>", on_engine_select)

    ttk.Label(form, text="Speed").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=3)
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
    speed_slider.grid(row=1, column=1, sticky="ew", pady=3)
    slider_value_label = ttk.Label(form, text=f"{playback_speed:.1f}x", width=4, anchor="e")
    slider_value_label.grid(row=1, column=2, sticky="e", padx=(8, 0), pady=3)

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
    # Footer (full view only): Debug setting
    reading_footer = ttk.Frame(reading_panel)
    reading_footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
    ttk.Label(reading_footer, text="Debug").pack(side=tk.LEFT, padx=(0, 8))
    debug_var = tk.StringVar(value="ON" if debug_mode else "OFF")
    debug_dropdown = ttk.Combobox(reading_footer, textvariable=debug_var, values=["ON", "OFF"], state="readonly", width=6)
    debug_dropdown.pack(side=tk.LEFT)
    def on_debug_select(event=None):
        global debug_mode
        debug_mode = (debug_var.get() == "ON")
        save_settings()
    debug_dropdown.bind("<<ComboboxSelected>>", on_debug_select)

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
        # The version footer belongs to the compact view only
        if view_mode == "full":
            version_label.pack_forget()
        elif not version_label.winfo_ismapped():
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
        safe_showwarning(
            "Missing TTS Dependencies",
            f"The selected TTS engine '{tts_engine}' is missing:\n\n" + "\n".join(current_missing),
        )
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
temp_speed_file = str(SETTINGS_DIR / "clipboard_speech_speed.mp3")
if os.path.exists(temp_speed_file):
    os.remove(temp_speed_file)
icon_path = SETTINGS_DIR / "lips_icon.png"
if os.path.exists(icon_path):
    os.remove(icon_path)
