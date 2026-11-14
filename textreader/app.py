"""Clipboard Reader: the main window, playback, hotkeys and tray icon.

Start it with `python -m textreader` (or run.sh); see textreader/__main__.py.
"""
import shutil
import json
import math
from pathlib import Path
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

from . import __version__, options, player, pronunciation, word_timing
from .engines import get_engine, list_engines
from .engines.base import SynthesisCancelled, run_cancellable
from .hotkeys import (DEFAULT_HOTKEYS, HOTKEY_LABELS, HOTKEY_ORDER, hotkey_hint, normalize_hotkey_part,
                      parse_hotkey, validate_hotkey_settings)
from .theme import PALETTE, Tooltip, _theme_fonts, apply_theme, themed_toplevel, widen_popdown


def check_engines():
    """Diagnostics: report each engine's dependencies and try a short phrase with its default voice."""
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


def resource_path(relative_path):
    """A file inside the textreader package (also works in a PyInstaller build,
    where the package is unpacked with its assets)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

APP_ICON_PATH = resource_path(os.path.join("assets", "pireader.png"))

# Settings persistence
SETTINGS_DIR = Path.home() / ".textReader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
SETTINGS_DIR.mkdir(exist_ok=True)

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
        "surprise_voice": False,
        "pronunciations": [],
        "text_filters": pronunciation.clean_filters(None),
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
                       "voice_stats": voice_stats, "voice_ratings": voice_ratings,
                       "surprise_voice": surprise_voice,
                       "pronunciations": pronunciations,
                       "text_filters": text_filters}, f, indent=2)
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
surprise_voice = bool(settings.get("surprise_voice", False))  # pick a random voice for each read
# Pronunciation rules: how to say particular words, names and symbols (see pronunciation.py)
pronunciations = pronunciation.clean_rules(settings.get("pronunciations", []))
# How to read web links, emails, file paths and long codes ("urls" -> "site", ...)
text_filters = pronunciation.clean_filters(settings.get("text_filters"))

# Voice lists by engine, filled in the background so a surprise pick never waits on a slow engine
voice_cache = {}
last_voice_used = None  # (engine name, voice label) of the most recent read
last_audio_file = None  # the file the most recent read built (its engine may differ from the selected one)

def prefetch_voice_lists():
    for name in list_engines():
        engine = get_engine(name)
        try:
            if not engine.check_dependencies():
                voice_cache[name] = engine.list_voices()
        except Exception:
            pass

def pick_surprise_voice(exclude_engines=()):
    """A random (engine, voice_id, label) from the engines and voices that are on and ready to use.

    Voices that would need a download first are skipped, and the previous pick is avoided
    when there's anything else to choose from.
    """
    import random
    candidates = []
    for name in enabled_engines():
        if name in exclude_engines:
            continue
        engine = get_engine(name)
        try:
            if engine.check_dependencies():
                continue
        except Exception:
            continue
        voices = voice_cache.get(name)
        if voices is None:
            continue  # still being listed
        if not voices:
            candidates.append((name, None, "default voice"))
            continue
        for voice_id, label in enabled_voices(name, voices):
            try:
                download = engine.voice_download_info(voice_id)
            except Exception:
                download = None
            if download and not download["downloaded"]:
                continue
            candidates.append((name, voice_id, label.split(" · ")[0]))
    if not candidates:
        return None
    if last_voice_used is not None and len(candidates) > 1:
        candidates = [c for c in candidates if (c[0], c[2]) != last_voice_used] or candidates
    return random.choice(candidates)

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
reading_spoken = None   # what is said for each word after pronunciation rules (None: as written)
reading_timeline = []   # estimated start time (s) per word
reading_serial = 0
reading_lock = threading.Lock()

# Bumped by Stop; a playback thread that sees a newer generation gives up
# instead of starting audio after the user already pressed Stop.
playback_generation = 0
audio_preparing = False  # True while audio is being converted for playback
audio_out = None  # the player (see player.py), created in main()
current_audio_duration = 0.0  # length of the file being played, at normal speed
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
        file_path = last_audio_file or get_output_path(tts_engine)
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

def set_reading_text(text, edits=()):
    """Record the text that is about to be read aloud (any thread).

    `edits` are the pronunciation changes made to it, so word timing follows
    what is really said.
    """
    global reading_text, reading_spans, reading_spoken, reading_timeline, reading_serial
    with reading_lock:
        reading_text = text
        reading_spans = word_timing.tokenize(text)
        reading_spoken = pronunciation.spoken_words(text, reading_spans, edits) if edits else None
        reading_timeline = []
        reading_serial += 1

def update_reading_timeline(audio_path, duration):
    """Estimate when each word is spoken in `audio_path` (call from a worker thread)."""
    global reading_timeline
    with reading_lock:
        text, spans, spoken, serial = reading_text, reading_spans, reading_spoken, reading_serial
    if not spans or duration <= 0:
        return
    # A quick even spread first, so highlighting starts at once...
    rough = word_timing.build_timeline(text, duration, [], spans, spoken)
    with reading_lock:
        if serial == reading_serial:
            reading_timeline = rough
    # ...then refine it using the pauses actually found in the audio
    refined = word_timing.build_timeline(text, duration, word_timing.detect_silences(audio_path), spans, spoken)
    with reading_lock:
        if serial == reading_serial:
            reading_timeline = refined
    if debug_mode:
        print(f"🐛 [DEBUG] Word timeline ready: {len(refined)} words over {duration:.1f}s")

def playback_position():
    """Seconds into the audio file (at normal speed), or None when nothing is loaded."""
    return audio_out.position() if audio_out is not None else None

def play_audio(file_to_play=None):
    """Play the generated audio file at the selected speed"""
    global current_audio_duration, audio_preparing, is_paused
    generation = playback_generation
    stopped = lambda: generation != playback_generation or not is_running
    audio_preparing = True
    try:
        # Choose file based on engine
        file_to_play = file_to_play or last_audio_file or get_output_path(tts_engine)
        if not wait_for_audio_file(file_to_play, 20):
            print("⚠️ Audio file not ready for playback")
            return
        current_audio_duration = get_audio_duration(file_to_play)
        is_paused = False
        if not audio_out.play(file_to_play, playback_speed, cancel_check=stopped) or stopped():
            return  # Stop was pressed while the audio was being prepared
        audio_preparing = False
        update_reading_timeline(file_to_play, current_audio_duration)
    except Exception as e:
        print(f"Error playing audio: {e}")
    finally:
        if generation == playback_generation:
            audio_preparing = False

def on_play():
    """Resume/play reading"""
    global is_paused
    if is_paused and audio_out.busy():
        audio_out.resume()
        is_paused = False
        print("▶ Resumed from pause")
    else:
        # Start fresh playback from the beginning
        is_paused = False
        threading.Thread(target=play_audio, daemon=True).start()
        refresh_selection_lock()
        print("▶ Playing")

def on_pause():
    """Pause/resume current playback"""
    global is_paused
    if not audio_out.busy():
        print("⚠️ Nothing playing to pause")
    elif is_paused:
        audio_out.resume()
        is_paused = False
        print("▶ Resumed")
    else:
        audio_out.pause()
        is_paused = True
        print("⏸ Paused")

def on_stop():
    """Stop and reset playback"""
    global is_paused, current_audio_duration, current_progress
    global playback_generation, audio_preparing
    playback_generation += 1
    audio_preparing = False
    is_paused = False
    current_audio_duration = 0.0
    current_progress = 0.0
    if current_build is not None:
        current_build.set()
    audio_out.stop()
    refresh_selection_lock()
    print("⏹ Stopped")

def toggle_debug():
    """Toggle debug mode"""
    global debug_mode
    debug_mode = not debug_mode
    save_settings()
    status = "ON" if debug_mode else "OFF"
    print(f"🐛 Debug mode: {status}")

def refresh_selection_lock():
    """Update the Engine/Voice lock now instead of at the next status check (any thread)."""
    lock = getattr(control_window, "lock_selection", None)
    if lock is not None:
        main_thread_calls.put(lock)

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
    refresh_selection_lock()
    build_counter += 1
    engine_name = tts_engine
    voice = engine_voices.get(engine_name)
    voice_label = None
    if surprise_voice:
        pick = pick_surprise_voice()
        if pick is not None:
            engine_name, voice, voice_label = pick
            print(f"🎲 Surprise voice: {voice_label} ({engine_name})")
    if voice_label is None:
        labels = dict(voice_cache.get(engine_name, []))
        voice_label = labels.get(voice, "default voice").split(" · ")[0] if voice else "default voice"
    surprised = surprise_voice
    results = queue.Queue()
    # What this build is using; a surprise build can switch voices if one fails.
    job = {}

    def set_target(name, voice_id, label):
        final = get_output_path(name)
        root, ext = os.path.splitext(final)
        # Build into a private file so a cancelled or stale build never clobbers the real one.
        job.update(engine=name, voice=voice_id, label=label, final=final,
                   temp=f"{root}.building{build_counter}{ext}")
    set_target(engine_name, voice, voice_label)

    def remove_temp():
        try:
            if os.path.exists(job["temp"]):
                os.remove(job["temp"])
        except Exception:
            pass

    def worker():
        failed = []
        while True:
            outcome = build_once()
            if outcome is None or not surprised or cancel_event.is_set() or len(failed) >= 2:
                if outcome is not None:
                    results.put(("error", outcome))
                return
            # Surprise mode: try a different engine instead of giving up
            failed.append(job["engine"])
            remove_temp()
            pick = pick_surprise_voice(exclude_engines=failed)
            if pick is None:
                results.put(("error", outcome))
                return
            print(f"⚠️ {job['engine']} failed ({outcome}); trying {pick[2]} ({pick[0]})")
            results.put(("retry", f"{job['engine']} didn't work. Trying {pick[2]} ({pick[0]}) instead…"))
            set_target(*pick)

    def build_once():
        """Build with the current target. Returns None when finished (or cancelled), else an error message."""
        engine_name, voice, temp_path = job["engine"], job["voice"], job["temp"]
        try:
            engine = get_engine(engine_name)
            if engine is None:
                return "Unknown TTS engine"
            missing_deps = engine.check_dependencies()
            if missing_deps:
                return f"Missing: {', '.join(missing_deps)}"
            download = engine.voice_download_info(voice)
            if download and not download["downloaded"]:
                # Fetch the voice first, reporting progress to the dialog
                results.put(("progress", (0, download["size_bytes"])))
                engine.download_voice(voice, lambda done, total: results.put(("progress", (done, total))), cancel_event)
                results.put(("progress", None))  # download finished; now building
                if voices_changed_callback is not None:
                    voices_changed_callback(engine_name)
            ready = engine.voice_ready(voice)  # False: this build includes a download or model load
            spoken, edits = pronunciation.apply(text, pronunciations, engine_name, text_filters)
            job["edits"] = edits
            if not spoken.strip():
                return "Nothing left to read: your pronunciation settings skip all of this text"
            if edits and debug_mode:
                print(f"🐛 [DEBUG] Pronunciation: {len(edits)} change(s) → {spoken[:200]!r}")
            started = time.monotonic()
            engine.synthesize(spoken, temp_path, cancel_event, voice=voice)
            build_seconds = time.monotonic() - started
            if cancel_event.is_set():
                raise SynthesisCancelled()
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                return f"{engine_name} produced no audio"
            results.put(("done", (ready, build_seconds, get_audio_duration(temp_path))))
            return None
        except SynthesisCancelled:
            results.put(("cancelled", None))
            return None
        except Exception as e:
            return str(e)

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
            if status == "retry":
                try:
                    show_download(None)
                    label.config(text=message, wraplength=300)
                except tk.TclError:
                    pass
                continue
            if status != "progress":
                break
            if not cancel_event.is_set():
                show_download(message)
        finish()
        engine_name, voice, voice_label, final_path = job["engine"], job["voice"], job["label"], job["final"]
        if status == "done" and not cancel_event.is_set():
            close_dialog()
            try:
                os.replace(job["temp"], final_path)
                set_reading_text(text, job.get("edits") or ())
            except Exception as e:
                print(f"Error saving audio: {e}")
                remove_temp()
                return
            global last_voice_used, last_audio_file
            last_voice_used = (engine_name, voice_label)
            last_audio_file = final_path
            threading.Thread(target=play_audio, args=(final_path,), daemon=True).start()
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
                label.config(text=f"Error: {message}", style="Error.TLabel", wraplength=300)
                cancel_btn.config(text="Close")
            except Exception:
                pass
            control_window.after(8000, close_dialog)
        else:
            close_dialog()

    threading.Thread(target=worker, daemon=True).start()
    control_window.after(100, poll)

def get_clipboard_text(timeout=2.0):
    """Return the clipboard text, or "" if the clipboard doesn't answer in time.

    The program that owns the clipboard has to hand the text over. If it is busy
    or stuck, pyperclip waits forever and freezes the app, so on Linux xclip is
    run with a time limit.
    """
    import subprocess
    try:
        result = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                capture_output=True, timeout=timeout, check=False)
        if result.returncode != 0:
            return ""  # empty clipboard, or it holds something that isn't text
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("⚠️ The clipboard didn't answer (the app you copied from may be busy). Try copying again.")
        return ""
    except FileNotFoundError:
        return pyperclip.paste()  # no xclip: macOS, Windows, or Wayland without it

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
        current_text = get_clipboard_text()
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
                beep = pygame.mixer.Sound(str(beep_path))
                beep.play()
                time.sleep(duration)
                if beep_path.exists():
                    beep_path.unlink()
            except Exception as e:
                print(f"Error playing beep: {e}")
    except Exception as e:
        print(f"Error: {e}")

def play_sample(engine_name, voice_id, text, report):
    """Speak `text` with one voice, outside the normal read (worker thread).

    `report(message)` is called on the main thread with progress or errors
    ("" when the sample has finished playing).
    """
    import tempfile
    say = lambda message: main_thread_calls.put(lambda: report(message))
    tmp = None
    try:
        engine = get_engine(engine_name)
        missing = engine.check_dependencies()
        if missing:
            say(f"{engine_name} isn't ready: missing {', '.join(missing)}")
            return
        download = engine.voice_download_info(voice_id)
        if download and not download["downloaded"]:
            say("Downloading this voice first…")
        tmp = tempfile.mkdtemp(prefix="textreader-sample-")
        path = os.path.join(tmp, "sample." + engine.output_ext)
        engine.synthesize(text, path, threading.Event(), voice=voice_id)
        wav = path
        if not path.endswith(".wav"):
            wav = os.path.join(tmp, "sample.wav")
            run_cancellable(["ffmpeg", "-y", "-loglevel", "error", "-i", path, wav], timeout=30)
        sound = pygame.mixer.Sound(wav)
        say("Playing…")
        sound.play()
        time.sleep(sound.get_length() + 0.3)
        say("")
    except Exception as e:
        say(f"Couldn't play the sample: {e}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

def create_control_window():
    global control_window, playback_speed, hotkeys, engine_missing_deps
    window = tk.Tk(className="reader")
    window.title("Clipboard Reader")
    window.resizable(False, False)
    apply_theme(window, ui_theme, debug_mode)

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
        global last_audio_file
        last_audio_file = None
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
    voice_choices = {"engine": None, "ids": [], "ready": False}

    def show_voices(engine_name, voices):
        """Fill the Voice list for engine_name (main thread)."""
        if engine_name != tts_engine:
            return  # the user switched engines while this list was loading
        voice_choices["engine"] = engine_name
        voices = enabled_voices(engine_name, voices)
        voice_choices["ids"] = [voice_id for voice_id, _ in voices]
        if not voices:
            voice_choices["ready"] = False
            voice_dropdown.configure(values=["Default"], state="disabled")
            voice_var.set("Default")
            return
        saved = engine_voices.get(engine_name)
        index = voice_choices["ids"].index(saved) if saved in voice_choices["ids"] else 0
        engine_voices[engine_name] = voice_choices["ids"][index]
        voice_choices["ready"] = True
        voice_dropdown.configure(values=[label for _, label in voices])
        voice_dropdown.current(index)
        lock_selection()

    def lock_selection():
        """Grey out Engine and Voice while audio is being built, played or paused."""
        reading = current_build is not None or audio_preparing or (audio_out is not None and audio_out.busy())
        engine_dropdown.configure(state="disabled" if reading else "readonly")
        voice_dropdown.configure(state="readonly" if voice_choices.get("ready") and not reading else "disabled")
    window.lock_selection = lock_selection

    def load_voices(engine_name, show_loading=True):
        """List the engine's voices in the background (some engines are slow to list)."""
        if show_loading:
            voice_choices["ready"] = False
            voice_dropdown.configure(values=[], state="disabled")
            voice_var.set("Loading voices…")
        def worker():
            engine = get_engine(engine_name)
            try:
                voices = engine.list_voices() if engine and not engine.check_dependencies() else []
            except Exception as e:
                print(f"Could not list voices for {engine_name}: {e}")
                voices = []
            if voices or not (engine and engine.check_dependencies()):
                voice_cache[engine_name] = voices
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
        if v != playback_speed and audio_out is not None:
            audio_out.set_speed(v)
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
        if position is not None and current_audio_duration > 0:
            # Shown in real time, so it follows the speed setting
            position = min(position, current_audio_duration)
            time_label.config(text=f"{format_time(position / playback_speed)} / "
                                   f"{format_time(current_audio_duration / playback_speed)}")
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

    options_btn = ttk.Button(button_frame, text="Options…", command=lambda: open_options())
    options_btn.grid(row=3, column=0, padx=(0, 4), pady=(3, 0), sticky="ew")
    mode_btn = ttk.Button(button_frame, text="Full View ▸")
    mode_btn.grid(row=3, column=1, padx=(4, 0), pady=(3, 0), sticky="ew")

    # Hover hints: what each button does and its keyboard shortcut (read when shown,
    # so they follow changes made in Options → Shortcuts)
    for button, action in ((read_btn, "read_selected_text"), (play_btn, "play"),
                           (pause_btn, "pause"), (stop_btn, "stop")):
        Tooltip(button, lambda action=action: hotkey_hint(action, hotkeys))
    Tooltip(options_btn, "Engines & voices, pronunciations, and keyboard shortcuts")

    # Options area: bottom of the left column, shown only in the full view.
    # Add future settings as more rows in options_form.
    options_frame = ttk.Frame(content)
    ttk.Separator(options_frame).pack(fill=tk.X, pady=(0, 10))
    options_form = ttk.Frame(options_frame)
    options_form.pack(fill=tk.X)
    options_form.columnconfigure(1, weight=1)
    surprise_var = tk.BooleanVar(value=surprise_voice)
    def on_surprise_toggle():
        global surprise_voice
        surprise_voice = bool(surprise_var.get())
        save_settings()
    ttk.Checkbutton(options_form, text="Surprise me with a random voice", variable=surprise_var,
                    command=on_surprise_toggle).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
    debug_var = tk.BooleanVar(value=debug_mode)
    def on_debug_toggle():
        global debug_mode
        debug_mode = bool(debug_var.get())
        save_settings()
    ttk.Checkbutton(options_form, text="Debug mode", variable=debug_var,
                    command=on_debug_toggle).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)

    open_options, set_options_busy = options.create(
        window, engine_var, engine_dropdown, load_voices, on_engine_select, safe_showerror)

    version_label = ttk.Label(content, text=f"Version {__version__}", style="Muted.TLabel")
    version_label.pack(pady=(12, 0))

    # ---- Full view: the text being read, with the current word highlighted
    p = PALETTE
    divider = ttk.Separator(window, orient=tk.VERTICAL)
    reading_panel = ttk.Frame(window, padding=(14, 14, 16, 12))
    reading_header = ttk.Frame(reading_panel)
    reading_header.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(reading_header, text="Now Reading", style="Header.TLabel").pack(side=tk.LEFT)
    voice_used_label = ttk.Label(reading_header, text="", style="Muted.TLabel")
    voice_used_label.pack(side=tk.LEFT, padx=(10, 0))
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

    def word_menu(event):
        """Right-click a word (or a selection) to change how it's read."""
        try:
            word = reading_view.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            index = reading_view.index(f"@{event.x},{event.y}")
            word = reading_view.get(f"{index} wordstart", f"{index} wordend")
            if "placeholder" in reading_view.tag_names(index):
                word = ""
        word = " ".join(word.split()).strip(".,;:!?\"'“”‘’()[]{}")
        if not word or len(word) > 60:
            return
        menu = tk.Menu(reading_view, tearoff=0, background=PALETTE["field"], foreground=PALETTE["fg"],
                       activebackground=PALETTE["accent"], activeforeground=PALETTE["accent_fg"],
                       borderwidth=1, relief=tk.SOLID)
        existing = any(str(r["text"]).lower() == word.lower() for r in pronunciations)
        menu.add_command(label=f"{'Edit' if existing else 'Change'} how “{word}” is read…",
                         command=lambda: open_options(word=word))
        menu.add_command(label="Pronunciations…", command=lambda: open_options("words"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    reading_view.bind("<Button-3>", word_menu)

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
            used = f"{last_voice_used[1]} · {last_voice_used[0]}" if last_voice_used else ""
            if voice_used_label.cget("text") != used:
                voice_used_label.config(text=used)
            position = playback_position()
            playing = audio_out.busy()
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
        set_options_busy(disabled)
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
        lock_selection()
        if busy_preparing and not audio_out.busy():
            status_label.config(text="Building audio…" if current_build is not None else "Preparing audio…")
            speed_slider.state(["disabled"])
            progress_var.set(0.0)
        elif audio_out.busy():
            if is_paused:
                status_label.config(text="Paused")
            else:
                status_label.config(text="Playing")
            # With mpv the speed can change while reading; otherwise only between reads
            speed_slider.state(["!disabled"] if audio_out.live_speed else ["disabled"])
            position = playback_position()
            if position is not None and current_audio_duration > 0:
                current_progress = max(0.0, min(100.0, (position / current_audio_duration) * 100.0))
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
        if audio_out.busy():
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

listener = None


def main():
    """Start the background threads and the control window; clean up on exit."""
    global is_running, listener, audio_out
    pygame.mixer.init()  # used for voice samples and the "nothing to read" beep
    audio_out = player.create_player(str(SETTINGS_DIR))
    print(f"🔊 Playback: {audio_out.name}" + ("" if audio_out.live_speed else " (speed changes apply to the next read)"))

    # Remove any leftover audio files from previous runs
    cleanup_audio_files()

    # List every engine's voices in the background (used by "Surprise me")
    threading.Thread(target=prefetch_voice_lists, daemon=True).start()

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
    audio_out.close()
    if os.path.exists(audio_file_mp3):
        os.remove(audio_file_mp3)
    if os.path.exists(audio_file_wav):
        os.remove(audio_file_wav)
    for speed_file in SETTINGS_DIR.glob("clipboard_speech_speed.*"):
        speed_file.unlink(missing_ok=True)
    icon_path = SETTINGS_DIR / "lips_icon.png"
    if os.path.exists(icon_path):
        os.remove(icon_path)
