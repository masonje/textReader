# Clipboard Reader
Reads text aloud. Python version of text aloud mp3 to run on Linux, Windows, or macOS.

## Requirements

- Python 3.7+
- The following Python packages (install with `pip install -r requirements.txt`):
	- pyperclip
	- gtts (for gTTS engine)
	- pyttsx3 (for pyttsx3 engine)
	- pygame
	- pystray
	- Pillow
	- pynput
	- TTS (for Coqui TTS engine, requires Python 3.11 or lower)

- ffmpeg (for audio speed control)
- espeak-ng (for eSpeak-NG engine)
- festival + text2wave (for Festival engine)

## ffmpeg Installation

### Linux
- Ubuntu/Debian: `sudo apt-get install ffmpeg`
- Fedora: `sudo dnf install ffmpeg`
- Arch: `sudo pacman -S ffmpeg`

### macOS
- Homebrew: `brew install ffmpeg`

### Windows
- Download from [ffmpeg.org](https://ffmpeg.org/download.html)
- Add the ffmpeg `bin` directory to your PATH environment variable

## Usage
Run the script:

```bash
python reader.py
```

## TTS Engines (tts_engines)

Each TTS engine lives in the tts_engines directory and implements a common interface.

- tts_engines/base.py
	- Defines the `TTSEngine` base class
	- Required fields: `name`, `output_ext`
	- Required methods: `check_dependencies()`, `synthesize(text, output_path)`

- tts_engines/__init__.py
	- Auto-discovers engine modules named `engine_*.py`
	- Registers all `TTSEngine` subclasses
	- Exposes `list_engines()` and `get_engine(name)`

### Included engines
- gTTS: [tts_engines/engine_gtts.py](tts_engines/engine_gtts.py)
- pyttsx3: [tts_engines/engine_pyttsx3.py](tts_engines/engine_pyttsx3.py)
- eSpeak-NG: [tts_engines/engine_espeak.py](tts_engines/engine_espeak.py)
- Festival: [tts_engines/engine_festival.py](tts_engines/engine_festival.py)
- Coqui TTS: [tts_engines/engine_coqui.py](tts_engines/engine_coqui.py)

### Adding a new engine
1. Create a new engine file in tts_engines with the `engine_*.py` prefix (e.g., engine_mytts.py).
2. Implement a subclass of `TTSEngine` with:
	- `name`: what shows up in the UI dropdown
	- `output_ext`: `mp3` or `wav`
	- `check_dependencies()`: return a list of missing deps
	- `synthesize(text, output_path)`: write audio to output_path
3. No manual registration required. The module is auto-discovered on startup.

The main app (reader.py) only calls `get_engine()` and `synthesize()` and does not contain per-engine logic.

## Creating a Standalone Executable (PyInstaller)

1. Install PyInstaller:
	```bash
	pip install pyinstaller
	```

2. Build the executable:
	```bash
	pyinstaller --onefile --windowed reader.py
	```
	- `--onefile` creates a single executable file
	- `--windowed` prevents a terminal window from opening (for GUI apps)

3. Find your executable in the `dist` folder.

4. Copy the executable to your target system. Make sure ffmpeg is installed (see above).

## Features
- Reads clipboard text aloud
- Adjustable playback speed (0.5x–2x)
- System tray icon
- GUI controls
- Keyboard shortcuts