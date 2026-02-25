
# Dependency check
import sys
import shutil
import json
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
check_dep('numpy')

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
import wave
from pystray import Icon
from PIL import Image, ImageDraw
from pynput import keyboard
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tts_engines import get_engine, list_engines

# Initialize pygame mixer for audio playback
pygame.mixer.init()


# Settings persistence
SETTINGS_DIR = Path.home() / ".textReader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
SETTINGS_DIR.mkdir(exist_ok=True)
def load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"debug_mode": False, "playback_speed": 1.0, "tts_engine": "gTTS"}
def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"debug_mode": debug_mode, "playback_speed": playback_speed, "tts_engine": tts_engine}, f)
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
control_window = None
playback_speed = settings.get("playback_speed", 1.0)
tts_engine = settings.get("tts_engine", "gTTS")
playback_start_time = None
playback_pause_start = None
playback_pause_accum = 0.0
current_audio_duration = 0.0
current_progress = 0.0
taskbar_icon_photo = None
engine_missing_deps = False
tray_icon = None

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

def play_audio():
    """Play the generated audio file at the selected speed"""
    global playback_start_time, playback_pause_start, playback_pause_accum, current_audio_duration
    try:
        # Choose file based on engine
        file_to_play = get_output_path(tts_engine)
        if not wait_for_audio_file(file_to_play, 20):
            print("⚠️ Audio file not ready for playback")
            return
        pygame.mixer.music.load(file_to_play)
        # Adjust speed for MP3 only
        if playback_speed != 1.0 and tts_engine == "gTTS":
            import subprocess
            temp_speed_file = str(SETTINGS_DIR / "clipboard_speech_speed.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-i", audio_file_mp3,
                "-filter:a", f"atempo={playback_speed}", temp_speed_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pygame.mixer.music.load(temp_speed_file)
            file_to_play = temp_speed_file
        playback_start_time = time.monotonic()
        playback_pause_start = None
        playback_pause_accum = 0.0
        current_audio_duration = get_audio_duration(file_to_play)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy() and is_running and not is_paused:
            time.sleep(0.1)
    except Exception as e:
        print(f"Error playing audio: {e}")

def on_play():
    """Resume/play reading"""
    global is_paused
    
    if is_paused and pygame.mixer.music.get_busy():
        # Resume paused playback from where it left off
        pygame.mixer.music.unpause()
        is_paused = False
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
    is_paused = False
    playback_start_time = None
    playback_pause_start = None
    playback_pause_accum = 0.0
    current_audio_duration = 0.0
    current_progress = 0.0
    pygame.mixer.music.stop()
    print("⏹ Stopped")

def toggle_debug():
    """Toggle debug mode"""
    global debug_mode
    debug_mode = not debug_mode
    save_settings()
    status = "ON" if debug_mode else "OFF"
    print(f"🐛 Debug mode: {status}")

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

            # Show modal dialog with cancel button
            cancel_flag = {'cancel': False}
            def build_audio():
                try:
                    engine = get_engine(tts_engine)
                    if engine is None:
                        label.config(text="Error: Unknown TTS engine", foreground="red")
                        time.sleep(2)
                        return
                    missing_deps = engine.check_dependencies()
                    if missing_deps:
                        label.config(text=f"Missing: {', '.join(missing_deps)}", foreground="red")
                        time.sleep(2)
                        return
                    output_path = get_output_path(tts_engine)
                    engine.synthesize(current_text, output_path)
                    if not cancel_flag['cancel']:
                        threading.Thread(target=play_audio, daemon=True).start()
                except Exception as e:
                    label.config(text=f"Error: {e}", foreground="red")
                    time.sleep(2)
                finally:
                    dialog.destroy()

            dialog = tk.Toplevel(control_window)
            dialog.title("Building MP3")
            dialog.geometry("300x100")
            dialog.attributes("-topmost", True)
            dialog.grab_set()
            label = ttk.Label(dialog, text="Building MP3 for playback...", font=("Arial", 10))
            label.pack(pady=10)
            progress = ttk.Progressbar(dialog, orient=tk.HORIZONTAL, length=200, mode="indeterminate")
            progress.pack(pady=(0, 5))
            progress.start(10)
            def on_cancel():
                cancel_flag['cancel'] = True
                dialog.destroy()
            cancel_btn = ttk.Button(dialog, text="Cancel", command=on_cancel)
            cancel_btn.pack(pady=5)
            threading.Thread(target=build_audio, daemon=True).start()
            dialog.wait_window()
        else:
            print("⚠️ No text to read")
            # Play a short negative beep
            try:
                import numpy as np
                import wave
                import struct
                beep_path = SETTINGS_DIR / "negative_beep.wav"
                duration = 0.2  # seconds
                freq = 400      # Hz
                sample_rate = 44100
                n_samples = int(sample_rate * duration)
                t = np.linspace(0, duration, n_samples, False)
                tone = 0.5 * np.sin(2 * np.pi * freq * t)
                # Save as WAV
                with wave.open(str(beep_path), 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    for s in tone:
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

def create_control_window():
    global control_window, playback_speed
    window = tk.Tk()
    window.title("Clipboard Reader Control")
    window.geometry("250x400")
    window.resizable(False, False)

    # TTS engine dropdown
    engine_frame = ttk.Frame(window)
    engine_frame.pack(pady=5)
    engine_label = ttk.Label(engine_frame, text="TTS Engine:", font=("Arial", 9))
    engine_label.pack(side=tk.LEFT, padx=2)
    engine_var = tk.StringVar(value=tts_engine)
    engine_dropdown = ttk.Combobox(engine_frame, textvariable=engine_var, values=list_engines(), state="readonly", width=12)
    engine_dropdown.pack(side=tk.LEFT, padx=2)
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

    # Debug mode dropdown
    debug_frame = ttk.Frame(window)
    debug_frame.pack(pady=2)
    debug_label = ttk.Label(debug_frame, text="Debug Mode:", font=("Arial", 9))
    debug_label.pack(side=tk.LEFT, padx=2)
    debug_var = tk.StringVar(value="ON" if debug_mode else "OFF")
    debug_dropdown = ttk.Combobox(debug_frame, textvariable=debug_var, values=["ON", "OFF"], state="readonly", width=6)
    debug_dropdown.pack(side=tk.LEFT, padx=2)
    def on_debug_select(event=None):
        global debug_mode
        debug_mode = (debug_var.get() == "ON")
        save_settings()
    debug_dropdown.bind("<<ComboboxSelected>>", on_debug_select)
    # Set window/taskbar icon
    try:
        icon_path = ensure_lips_icon_file()
        photo = tk.PhotoImage(file=icon_path)
        global taskbar_icon_photo
        taskbar_icon_photo = photo
        window.iconphoto(False, taskbar_icon_photo)
    except:
        pass
    # Status label
    status_label = ttk.Label(window, text="Status: Running", font=("Arial", 10))
    status_label.pack(pady=5)
    # Speed slider
    speed_frame = ttk.Frame(window)
    speed_frame.pack(pady=5)
    speed_label = ttk.Label(speed_frame, text="Speed:", font=("Arial", 9))
    speed_label.pack(side=tk.LEFT, padx=2)
    speed_var = tk.DoubleVar(value=playback_speed)
    def on_speed_change(val):
        global playback_speed
        v = round(float(val) * 10) / 10.0
        if abs(v - speed_var.get()) > 1e-6:
            speed_var.set(v)
        playback_speed = v
        save_settings()
        slider_value_label.config(text=f"{playback_speed:.2f}x")
    speed_slider = ttk.Scale(speed_frame, from_=0.5, to=2.0, orient=tk.HORIZONTAL, variable=speed_var, command=on_speed_change, length=120)
    speed_slider.pack(side=tk.LEFT, padx=2)
    slider_value_label = ttk.Label(speed_frame, text=f"{playback_speed:.2f}x", font=("Arial", 9))
    slider_value_label.pack(side=tk.LEFT, padx=2)
    # Progress bar
    progress_label = ttk.Label(window, text="Progress:", font=("Arial", 9))
    progress_label.pack(pady=(5, 2))
    progress_var = tk.DoubleVar(value=0.0)
    progress_bar = ttk.Progressbar(window, orient=tk.HORIZONTAL, length=200, mode="determinate", maximum=100, variable=progress_var)
    progress_bar.pack(pady=(0, 5))
    # Button frame
    button_frame = ttk.Frame(window)
    button_frame.pack(pady=10)
    play_btn = ttk.Button(button_frame, text="▶ Play", command=on_play, width=12)
    play_btn.grid(row=0, column=0, padx=5, pady=5)
    pause_btn = ttk.Button(button_frame, text="⏸ Pause", command=on_pause, width=12)
    pause_btn.grid(row=0, column=1, padx=5, pady=5)
    stop_btn = ttk.Button(button_frame, text="⏹ Stop", command=on_stop, width=12)
    stop_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    read_btn = ttk.Button(button_frame, text="📄 Read Clipboard", command=read_selected_text, width=12)
    read_btn.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
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
    window.set_buttons_state = set_controls_state
    info = ttk.Label(window, text="Shortcuts:\nWin+Shift+T: Read Selected Text\nWin+Shift+R: Play\nWin+Shift+P: Pause\nWin+Shift+S: Stop", 
                     font=("Arial", 8), justify=tk.LEFT)
    info.pack(pady=10)
    def safe_showwarning(title, message):
        try:
            if window.winfo_exists():
                messagebox.showwarning(title, message)
        except Exception:
            pass

    missing_map = []
    for name in list_engines():
        missing = check_engine_dependencies(name)
        if missing:
            missing_map.append(f"{name}: {', '.join(missing)}")
    if debug_mode:
        if missing_map:
            print("🐛 [DEBUG] Missing engine dependencies found:")
            for line in missing_map:
                print(f"🐛 [DEBUG] {line}")
        else:
            print("🐛 [DEBUG] All engine dependencies satisfied")
    if missing_map:
        safe_showwarning(
            "Missing TTS Dependencies",
            "Some TTS engines are missing dependencies:\n\n" + "\n".join(missing_map),
        )
    current_missing = check_engine_dependencies(tts_engine)
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
            status_label.config(text="Status: Missing Dependencies")
            window.after(500, update_status)
            return
        if pygame.mixer.music.get_busy() or is_paused:
            if is_paused:
                status_label.config(text="Status: Paused")
            else:
                status_label.config(text="Status: Playing")
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
            status_label.config(text="Status: Stopped")
            speed_slider.state(["!disabled"])
            progress_var.set(0.0)
        debug_text = "Debug: ON" if debug_mode else "Debug: OFF"
        debug_color = "green" if debug_mode else "gray"
        debug_label.config(text=debug_text, foreground=debug_color)
        if has_audio_file():
            play_btn.state(["!disabled"])
        else:
            play_btn.state(["disabled"])
        if pygame.mixer.music.get_busy() or (is_paused and has_audio_file()):
            pause_btn.state(["!disabled"])
            stop_btn.state(["!disabled"])
        else:
            pause_btn.state(["disabled"])
            stop_btn.state(["disabled"])
        try:
            window.after(500, update_status)
        except Exception:
            pass
    update_status()
    def on_close():
        global is_running
        is_running = False
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
    window.mainloop()

def on_press(key):
    """Handle keyboard press events"""
    global cmd_pressed, shift_pressed
    try:
        if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
            cmd_pressed = True
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            shift_pressed = True
        elif cmd_pressed and shift_pressed:
            if hasattr(key, 'char') and key.char:
                if key.char.lower() == 'r':  # Win+Shift+R - Resume/Play
                    on_play()
                elif key.char.lower() == 'p':  # Win+Shift+P - Pause
                    on_pause()
                elif key.char.lower() == 's':  # Win+Shift+S - Stop
                    on_stop()
                elif key.char.lower() == 't':  # Win+Shift+T - Read selected Text
                    read_selected_text()
    except AttributeError:
        pass

def on_release(key):
    """Handle keyboard release events"""
    global cmd_pressed, shift_pressed
    try:
        if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
            cmd_pressed = False
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            shift_pressed = False
    except AttributeError:
        pass

def setup_hotkeys():
    """Setup keyboard listener for control"""
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    return listener

def clipboard_monitor():
    """Monitor clipboard and speak new content"""
    global is_running, is_paused
    
    while is_running:
        try:
            # Short pause to prevent high CPU usage
            time.sleep(0.5)
        except KeyboardInterrupt:
            break

def run_tray():
    """Run the system tray icon (display only, no menu)"""
    global tray_icon
    icon_path = ensure_lips_icon_file()
    try:
        image = Image.open(icon_path).convert("RGBA")
    except Exception:
        image = create_lips_icon()
    tray_icon = Icon("clipboard_reader_tray", image, title="Clipboard Reader")
    print("System tray icon created.")
    tray_icon.run(setup=lambda icon: None)

# Remove any leftover audio files from previous runs
cleanup_audio_files()

# Start clipboard monitoring in background thread
monitor_thread = threading.Thread(target=clipboard_monitor, daemon=True)
monitor_thread.start()

# Setup keyboard listener
listener = setup_hotkeys()

# Run system tray icon in background thread
tray_thread = threading.Thread(target=run_tray, daemon=True)
tray_thread.start()

print("=" * 50)
print("Clipboard Reader started")
print("=" * 50)
print("📋 Using Google Text-to-Speech")
print("\n🎮 Keyboard Controls:")
print("  Win+Shift+T  - Read Selected Text")
print("  Win+Shift+R  - Play/Resume")
print("  Win+Shift+P  - Pause")
print("  Win+Shift+S  - Stop")
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
