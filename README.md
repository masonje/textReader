# Clipboard Reader
Reads text aloud. Python version of text aloud mp3 to run on Linux, Windows, or macOS.

**Version:** 1.2.0 — see [Changelog](#changelog) for what changed in each version.

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
	- coqui-tts (for Coqui TTS engine, requires Python 3.11 or lower)

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
	- Required methods: `check_dependencies()`, `synthesize(text, output_path, cancel_event=None)`
	- `run_cancellable(cmd, cancel_event, input_text=None)`: helper that runs an external command and kills it if the build is cancelled
	- `SynthesisCancelled`: exception an engine raises when it stops because of a cancel

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
	- `synthesize(text, output_path, cancel_event=None)`: write audio to output_path. Check `cancel_event.is_set()` where you can and raise `SynthesisCancelled`; for external commands use `run_cancellable()`. Engines that can't be interrupted can ignore it, and the app throws away their output.
3. No manual registration required. The module is auto-discovered on startup.

The main app (reader.py) only calls `get_engine()` and `synthesize()` and does not contain per-engine logic.

## Build and Install (Linux)

`./install.sh` builds a single-file executable with PyInstaller (via `build.sh`), copies it to `~/.local/bin/reader`, installs the icon set, and adds a "Screen Reader" launcher to the app menu.

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
- Two views: **Compact** (just the controls, small enough to leave on screen) and **Full** (adds a panel showing the text being read, with the current word highlighted). Switch with the Full View ▸ / ◂ Compact button.
- Reads clipboard text aloud
- Adjustable playback speed (0.5x–2x)
- System tray icon
- GUI controls
- Configurable keyboard shortcuts

## Preferences
Settings are saved in `~/.textReader/settings.json`. The control window includes a Shortcuts button that opens a shortcut preferences dialog with dropdowns for modifier and key choices. The same values can also be edited directly in JSON:

```json
{
	"debug_mode": false,
	"playback_speed": 1.0,
	"tts_engine": "gTTS",
	"theme": "auto",
	"view_mode": "compact",
	"full_window_size": "",
	"hotkeys": {
		"read_selected_text": "Win+Esc",
		"play": "Win+Shift+R",
		"pause": "Win+Shift+P",
		"stop": "Win+Shift+S"
	}
}
```

`theme` can be `"auto"` (follow the desktop's light/dark setting), `"dark"`, or `"light"`.
`view_mode` is `"compact"` or `"full"`, and `full_window_size` remembers the Full view's size (for example `"840x460"`). Both are saved automatically.

## Word Highlighting (Full view)
None of the TTS engines report when each word is spoken, so [word_timing.py](word_timing.py) estimates it:
1. Each word is weighted by length, with extra time after punctuation where voices pause.
2. ffmpeg's `silencedetect` finds where speech starts and ends and the pauses in between.
3. Pauses are matched to the punctuation they belong to, which keeps long text from drifting.

In testing with gTTS, sentence starts landed within about 0.1 s of the real audio. Within a sentence, the highlight is an estimate and can run slightly ahead of or behind the voice.

## Checking the Version
- The control window shows the version in its title bar and at the bottom of the window.
- From a terminal: `reader --version` (or `python reader.py --version`).

## Keyboard Shortcuts
- **Win+Escape** — Read selected text
- **Win+Shift+R** — Resume/Play
- **Win+Shift+P** — Pause
- **Win+Shift+S** — Stop

## Changelog

The version number is also stored in `__version__` at the top of `reader.py`.

### 1.2.0 — 2026-11-12
- **Added:** Compact and Full views. Compact is the existing control window. Full adds a resizable "Now Reading" panel that shows the text being read aloud, highlights the current word, dims words already read, scrolls to follow along, and shows "Word N of M". The view and the Full window size are remembered.
- **Added:** `word_timing.py` estimates word timings from the text and the pauses in the audio.
- **Fixed:** Pressing Play while paused restarted from the beginning instead of resuming, because pygame reports "not busy" while paused. Resuming also kept the time spent paused, which threw off the progress bar.

### 1.1.0 — 2026-11-12
- **Added:** The version is shown in the control window's title bar and footer, and `--version` prints it.
- **Added:** Light and dark themes. The app follows the desktop's light/dark setting (GNOME `color-scheme`, macOS, or Windows), or you can set `"theme"` in settings.json. The control window, Shortcut Preferences, the build dialog, drop-down lists, and message boxes all use the same colors.
- **Changed:** Cleaner control window layout with aligned Engine/Debug/Speed rows, full-width buttons, and Read Clipboard as the main action. The "Building MP3" dialog is now "Building Audio", since most engines produce WAV.
- **Fixed:** `install.sh` and `build.sh` failed with "Text file busy" when the app was running. They now copy to a temporary file and rename it into place.
- **Fixed:** Cancel in the "Building MP3" dialog sometimes did nothing, or let the audio keep building and then play.
	- The dialog is now always created and updated on the Tk main thread. Hotkey reads are handed to it instead of opening the dialog from the keyboard-listener thread.
	- Cancel, the window's close button, and Esc close the dialog immediately.
	- Builds really stop: Festival and eSpeak-NG processes are killed, and gTTS stops between text chunks. pyttsx3 and Coqui can't be interrupted, so their output is thrown away.
	- Audio is built into a temporary file and only replaces the playback file if the build wasn't cancelled. Leftover temporary files are removed at startup.
	- The Stop hotkey/button cancels a build in progress, and starting a new read cancels the previous build.
- **Changed:** `TTSEngine.synthesize()` takes an optional `cancel_event`. Added the `run_cancellable()` helper and the `SynthesisCancelled` exception in `tts_engines/base.py`.
- **Changed:** eSpeak-NG reads its text from stdin, so text starting with `-` isn't treated as an option.

### 1.0.0 — 2026-08-27
First versioned baseline, covering everything up to this point:
- Clipboard and selected-text reading with play, pause, stop, and adjustable speed (0.5x–2x).
- Pluggable TTS engines in `tts_engines/`: gTTS, pyttsx3, eSpeak-NG, Festival, and Coqui TTS.
- Configurable keyboard shortcuts with a preferences dialog, saved to `~/.textReader/settings.json`.
- System tray icon and control window.
- Ubuntu 26.04 support.
- `build.sh` and `install.sh` for a PyInstaller build with an app-menu launcher and icon.
