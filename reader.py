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

# Global state
is_running = True
is_paused = False
debug_mode = False
audio_file = "/tmp/clipboard_speech.mp3"
cmd_pressed = False
shift_pressed = False
control_window = None

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
    """Play the generated audio file"""
    try:
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
        # Wait for playback to finish
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
        # Start fresh playback from beginning
        try:
            pygame.mixer.music.load(audio_file)
            pygame.mixer.music.play()
            is_paused = False
            print("▶ Playing")
        except Exception as e:
            print(f"Error playing audio: {e}")

def on_pause():
    """Pause reading clipboard"""
    global is_paused
    if pygame.mixer.music.get_busy():
        is_paused = True
        pygame.mixer.music.pause()
        print("⏸ Paused")
    else:
        print("⚠️ Nothing playing to pause")

def on_stop():
    """Stop and reset playback"""
    global is_paused
    is_paused = True
    pygame.mixer.music.stop()
    print("⏹ Stopped")

def toggle_debug():
    """Toggle debug mode"""
    global debug_mode
    debug_mode = not debug_mode
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
            tts = gTTS(text=current_text, lang='en', slow=False)
            tts.save(audio_file)
            play_audio()
        else:
            print("⚠️ No text to read")
    except Exception as e:
        print(f"Error: {e}")

def create_control_window():
    """Create a control window with buttons"""
    global control_window
    
    window = tk.Tk()
    window.title("Clipboard Reader Control")
    window.geometry("250x300")
    window.resizable(False, False)
    
    # Set window icon
    try:
        img = create_lips_icon()
        img.save('/tmp/lips_icon.png')
        photo = tk.PhotoImage(file='/tmp/lips_icon.png')
        window.iconphoto(False, photo)
    except:
        pass
    
    # Title label
    title = ttk.Label(window, text="Clipboard Reader", font=("Arial", 12, "bold"))
    title.pack(pady=10)
    
    # Status label
    status_label = ttk.Label(window, text="Status: Running", font=("Arial", 10))
    status_label.pack(pady=5)
    
    # Debug label
    debug_label = ttk.Label(window, text="Debug: OFF", font=("Arial", 9), foreground="gray")
    debug_label.pack(pady=2)
    
    def update_status():
        if is_paused:
            status_label.config(text="Status: Paused")
        elif is_running:
            status_label.config(text="Status: Running")
        else:
            status_label.config(text="Status: Stopped")
        
        # Update debug label
        debug_text = "Debug: ON" if debug_mode else "Debug: OFF"
        debug_color = "green" if debug_mode else "gray"
        debug_label.config(text=debug_text, foreground=debug_color)
        
        window.after(500, update_status)
    
    update_status()
    
    # Button frame
    button_frame = ttk.Frame(window)
    button_frame.pack(pady=10)
    
    # Play button
    play_btn = ttk.Button(button_frame, text="▶ Play", command=on_play, width=12)
    play_btn.grid(row=0, column=0, padx=5, pady=5)
    
    # Pause button
    pause_btn = ttk.Button(button_frame, text="⏸ Pause", command=on_pause, width=12)
    pause_btn.grid(row=0, column=1, padx=5, pady=5)
    
    # Stop button
    stop_btn = ttk.Button(button_frame, text="⏹ Stop", command=on_stop, width=12)
    stop_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    
    # Debug button
    debug_btn = ttk.Button(button_frame, text="🐛 Debug", command=toggle_debug, width=12)
    debug_btn.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    
    # Read text button
    read_btn = ttk.Button(button_frame, text="📄 Read Text", command=read_selected_text, width=12)
    read_btn.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    
    # Keyboard shortcuts info
    info = ttk.Label(window, text="Shortcuts:\nWin+Shift+T: Read Text\nWin+Shift+R: Play\nWin+Shift+P: Pause\nWin+Shift+S: Stop", 
                     font=("Arial", 8), justify=tk.LEFT)
    info.pack(pady=10)
    
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
if os.path.exists(audio_file):
    os.remove(audio_file)
