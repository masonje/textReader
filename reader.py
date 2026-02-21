
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
check_dep('gtts', 'gTTS')
check_dep('pyttsx3')
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
from gtts import gTTS
import time
import pygame
import os
import threading
from pystray import Icon
from PIL import Image, ImageDraw
from pynput import keyboard
import tkinter as tk
from tkinter import ttk

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
        if tts_engine == "gTTS":
            return os.path.exists(audio_file_mp3)
        if tts_engine == "pyttsx3":
            return os.path.exists(audio_file_wav)
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

def play_audio():
    """Play the generated audio file at the selected speed"""
    try:
        # Choose file based on engine
        file_to_play = audio_file_mp3 if tts_engine == "gTTS" else audio_file_wav
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
    global is_paused
    if pygame.mixer.music.get_busy():
        if is_paused:
            pygame.mixer.music.unpause()
            is_paused = False
            print("▶ Resumed")
        else:
            is_paused = True
            pygame.mixer.music.pause()
            print("⏸ Paused")
    elif is_paused:
        pygame.mixer.music.unpause()
        is_paused = False
        print("▶ Resumed")
    else:
        print("⚠️ Nothing playing to pause")

def on_stop():
    """Stop and reset playback"""
    global is_paused
    is_paused = False
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
        os.system('xclip -selection primary -o | xclip -selection clipboard')
        time.sleep(0.1)  # Give clipboard time to update
        current_text = pyperclip.paste()
        if current_text.strip():
            if debug_mode:
                print(f"\n🐛 [DEBUG] Reading selected text:")
                print(f"🐛 [DEBUG] {repr(current_text)}\n")
            print(f"Speaking: {current_text[:50]}...")

            # Show modal dialog with cancel button
            cancel_flag = {'cancel': False}
            def build_mp3_gtts():
                import queue
                import threading
                result_queue = queue.Queue()
                def gtts_worker():
                    try:
                        from gtts import gTTS
                        tts = gTTS(text=current_text, lang='en', slow=False)
                        tts.save(audio_file_mp3)
                        result_queue.put(None)
                    except Exception as e:
                        result_queue.put(e)
                thread = threading.Thread(target=gtts_worker, daemon=True)
                thread.start()
                try:
                    thread.join(timeout=10)
                    if thread.is_alive():
                        result_queue.put(Exception("gTTS generation timed out. Check your internet connection."))
                        # Optionally kill thread (not possible in Python, but dialog will close)
                    result = result_queue.get()
                    if result is None and not cancel_flag['cancel']:
                        threading.Thread(target=play_audio, daemon=True).start()
                    elif isinstance(result, Exception):
                        label.config(text=f"Error: {result}", foreground="red")
                        time.sleep(2)
                except Exception as e:
                    label.config(text=f"Error: {e}", foreground="red")
                    time.sleep(2)
                finally:
                    dialog.destroy()

            def build_mp3_pyttsx3():
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                    engine.save_to_file(current_text, audio_file_wav)
                    engine.runAndWait()
                    if not cancel_flag['cancel']:
                        threading.Thread(target=play_audio, daemon=True).start()
                except Exception as e:
                    print(f"Error: {e}")
                finally:
                    dialog.destroy()

            def build_mp3():
                if tts_engine == "gTTS":
                    build_mp3_gtts()
                elif tts_engine == "pyttsx3":
                    build_mp3_pyttsx3()
                else:
                    print("Error: Unknown TTS engine")
                    dialog.destroy()

            dialog = tk.Toplevel(control_window)
            dialog.title("Building MP3")
            dialog.geometry("300x100")
            dialog.attributes("-topmost", True)
            dialog.grab_set()
            label = ttk.Label(dialog, text="Building MP3 for playback...", font=("Arial", 10))
            label.pack(pady=10)
            def on_cancel():
                cancel_flag['cancel'] = True
                dialog.destroy()
            cancel_btn = ttk.Button(dialog, text="Cancel", command=on_cancel)
            cancel_btn.pack(pady=5)
            threading.Thread(target=build_mp3, daemon=True).start()
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
    engine_dropdown = ttk.Combobox(engine_frame, textvariable=engine_var, values=["gTTS", "pyttsx3"], state="readonly", width=12)
    engine_dropdown.pack(side=tk.LEFT, padx=2)
    def on_engine_select(event=None):
        global tts_engine
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
        # Disable Read Clipboard button briefly to prevent race conditions
        if hasattr(window, 'set_buttons_state'):
            window.set_buttons_state('disabled')
            window.after(500, lambda: hasattr(window, 'set_buttons_state') and window.set_buttons_state('normal'))
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
    # Set window icon
    try:
        img = create_lips_icon()
        icon_path = SETTINGS_DIR / "lips_icon.png"
        img.save(icon_path)
        photo = tk.PhotoImage(file=icon_path)
        window.iconphoto(False, photo)
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
    info = ttk.Label(window, text="Shortcuts:\nWin+Shift+T: Read Selected Text\nWin+Shift+R: Play\nWin+Shift+P: Pause\nWin+Shift+S: Stop", 
                     font=("Arial", 8), justify=tk.LEFT)
    info.pack(pady=10)
    def update_status():
        if pygame.mixer.music.get_busy():
            if is_paused:
                status_label.config(text="Status: Paused")
            else:
                status_label.config(text="Status: Playing")
            speed_slider.state(["disabled"])
        else:
            status_label.config(text="Status: Stopped")
            speed_slider.state(["!disabled"])
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
        window.after(500, update_status)
    update_status()
    def on_close():
        global is_running
        is_running = False
        window.destroy()
        os._exit(0)  # Force exit to stop all threads and tray
    window.protocol("WM_DELETE_WINDOW", on_close)
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
    image = create_lips_icon()
    icon = Icon("Clipboard Reader", image, title="Clipboard Reader")
    print("System tray icon created.")
    icon.run(setup=lambda icon: None)

# Remove any leftover audio files from previous runs
cleanup_audio_files()

# Start clipboard monitoring in background thread
monitor_thread = threading.Thread(target=clipboard_monitor, daemon=True)
monitor_thread.start()

# Setup keyboard listener
listener = setup_hotkeys()

# Run control window in background thread
window_thread = threading.Thread(target=create_control_window, daemon=False)
window_thread.start()

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

# Run system tray icon on main thread (requires main event loop)
try:
    run_tray()
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
