# Clipboard Reader
Reads text aloud. Python version of text aloud mp3 to run on Linux, Windows, or macOS.

**Version:** 1.5.0 — see [Changelog](#changelog) for what changed in each version.

## Requirements

- Python 3.7+
- The following Python packages (install with `pip install -r requirements.txt`):
	- pyperclip
	- gtts (for gTTS engine)
	- pyttsx3 (for pyttsx3 engine)
	- piper-tts (for Piper engine)
	- edge-tts (for Edge TTS engine)
	- pygame
	- pystray
	- Pillow
	- pynput
	- coqui-tts (optional, for Coqui TTS; not in requirements.txt because it needs PyTorch. The app can install it for you, see below.)

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
	- Required methods: `check_dependencies()`, `synthesize(text, output_path, cancel_event=None, voice=None)`
	- Optional: `list_voices()` returns `(voice_id, label)` pairs, best default first
	- `run_cancellable(cmd, cancel_event, input_text=None)`: helper that runs an external command and kills it if the build is cancelled
	- `SynthesisCancelled`: exception an engine raises when it stops because of a cancel

- tts_engines/__init__.py
	- Auto-discovers engine modules named `engine_*.py`
	- Registers all `TTSEngine` subclasses
	- Exposes `list_engines()` and `get_engine(name)`

### Included engines

Pick the engine and voice in the control window. Each engine remembers its own voice choice.

In the Full view, **Engines & Voices…** (bottom left) opens a list of every engine and voice showing where its speech is **Generated**, its **Speed**, and its **Quality**:
- **Generated:** "Locally" means the speech is made on your computer and nothing you read leaves it (Piper, Coqui, eSpeak-NG, Festival, pyttsx3). "Online (Google)" for gTTS and "Online (Microsoft)" for Edge TTS mean the text you read is sent to that company's servers, which return the audio. Piper downloads each voice once but then runs offline.
- **Details:** select an engine or voice to see its details: gender, accent, whether it needs the internet, download size, audio format, the model or service behind it, and for Edge voices Microsoft's personality and "good for" tags.
- **Speed** is measured, not guessed. Every read (and every Preview) records how long the voice took to build compared with how long the speech is. "About 8 s to build 1 minute of speech" means fast. Builds that include a one-time download or model load are skipped.
- **Quality** starts at a typical rating for the engine. Click the stars to rate a voice yourself, or **reset** to go back to the default.
- **▶ Preview** speaks a short sample with the selected voice. If the voice isn't downloaded yet, a Downloading Voice window shows the progress (with Cancel) and then plays the sample.
- **Downloaded voices** (Piper) show their size on disk and have a **Download** button with a progress bar and Cancel, or a **Delete download** button that frees the space (the voice downloads again next time it's used). Selecting the engine shows how many voices are downloaded and the total size. Downloads keep going if you close the window.
- **On/off:** click a row's ☑ box to turn it on or off. Turned-off ones disappear from the Engine and Voice drop-downs. **All voices on** and **All voices off** act on the selected engine. At least one engine, and one voice per engine, always stays on.

These are saved in settings.json as `disabled_engines`, `disabled_voices`, `voice_stats` and `voice_ratings`.

| Engine | Voices | Quality | Needs |
|---|---|---|---|
| [Piper](tts_engines/engine_piper.py) | 15 English voices (US, UK, Scottish; male and female) | Natural neural voices, offline | Each voice is ~63 MB, downloaded the first time it's used (or from Engines & Voices) to `~/.textReader/voices/piper`; downloaded voices can be deleted there |
| [Edge TTS](tts_engines/engine_edge.py) | ~47 English voices from Microsoft (US, UK, Australia, Canada, India, Ireland, and more) | Very natural neural voices | Internet connection |
| [gTTS](tts_engines/engine_gtts.py) | 8 English accents (US, UK, Australia, Canada, India, Ireland, South Africa, Nigeria) | Good | Internet connection |
| [pyttsx3](tts_engines/engine_pyttsx3.py) | The system's speech voices (eSpeak on Linux, SAPI on Windows, NSSpeech on macOS) | Robotic on Linux | — |
| [eSpeak-NG](tts_engines/engine_espeak.py) | English accents, plus female variants of US and UK English | Robotic | `espeak-ng` |
| [Festival](tts_engines/engine_festival.py) | Installed Festival voices (e.g. `festvox-kallpc16k`) | Robotic | `festival` |
| [Coqui TTS](tts_engines/engine_coqui.py) | One voice (Tacotron2) | Neural, slow on CPU | Installed on request, about 1 GB (see below) |

**Installing Coqui TTS:** pick Coqui TTS as the engine and the app offers to install it. It creates a private Python environment in `~/.textReader/engines/coqui` and installs CPU-only PyTorch and Coqui there (about 1 GB, several minutes). It shows the progress, and you can cancel. Coqui then runs in a background worker process that keeps the model loaded between reads. To remove it, delete `~/.textReader/engines`. If you run from source and have `coqui-tts` installed in the app's own environment, that is used instead.

Run `reader --check-engines` (or `python reader.py --check-engines`) to see which engines work and try each one.

### Adding a new engine
1. Create a new engine file in tts_engines with the `engine_*.py` prefix (e.g., engine_mytts.py).
2. Implement a subclass of `TTSEngine` with:
	- `name`: what shows up in the UI dropdown
	- `output_ext`: `mp3` or `wav`
	- `check_dependencies()`: return a list of missing deps
	- `list_voices()` (optional): return `(voice_id, label)` pairs; the UI shows the labels and passes the chosen `voice_id` back
	- `synthesize(text, output_path, cancel_event=None, voice=None)`: write audio to output_path. Check `cancel_event.is_set()` where you can and raise `SynthesisCancelled`; for external commands use `run_cancellable()`. Engines that can't be interrupted can ignore it, and the app throws away their output.
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
- **Surprise me:** tick "Surprise me with a random voice" (Full view, bottom left) and each read uses a random voice from the engines and voices you have turned on. Voices that would need a download first are skipped, and the same voice isn't picked twice in a row. The Now Reading header shows which voice was used. If the picked voice fails (for example, an online service doesn't answer), another engine is tried automatically.
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
	"surprise_voice": false,
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
- The Compact view shows the version at the bottom of the window.
- From a terminal: `reader --version` (or `python reader.py --version`).

## Keyboard Shortcuts
- **Win+Escape** — Read selected text
- **Win+Shift+R** — Resume/Play
- **Win+Shift+P** — Pause
- **Win+Shift+S** — Stop

## Changelog

The version number is also stored in `__version__` at the top of `reader.py`.

### 1.5.0 — 2026-11-13
- **Added:** "Surprise me with a random voice" checkbox (Full view options, above Debug). Each read picks a random voice from the engines and voices that are on and ready (no downloads), avoiding an immediate repeat. Saved as `surprise_voice`.
- **Added:** The Now Reading header shows the voice and engine used for the current read.
- **Added:** If a surprise voice fails, the app tries a voice from a different engine (up to two more) and says so in the dialog.
- **Changed:** Debug is now a checkbox instead of an ON/OFF drop-down.
- **Fixed:** gTTS could fail with "Engine produced no audio" when Google sent back an empty reply (usually while it's limiting requests). gTTS now retries once, then explains what happened. Error messages stay up for 8 seconds instead of 2.
- **Fixed:** Play replays the last read even when it used a different engine than the one selected.

### 1.4.0 — 2026-11-13
- **Added:** Download progress for voices. When a read needs a voice that isn't downloaded yet, the Building dialog shows "Downloading voice: 21.3 of 63 MB (34%)" with a progress bar before it builds.
- **Added:** In Engines & Voices, Piper voices have a **Download** button with progress and Cancel, and a **Delete download** button (with confirmation). Each voice shows its size on disk, and the engine shows the total downloaded.
- **Added:** Preview of a voice that isn't downloaded opens a Downloading Voice window with progress and Cancel, then builds and plays the sample.
- **Changed:** In the voice details panel, Preview, Download/Delete and the rating now sit at the top so they're never cut off by long detail lists.
- **Fixed:** Cancelling a Piper download no longer leaves the voice's config file behind.
- **Engines:** new optional `voice_download_info()`, `download_voice(progress=…)` and `delete_voice()` for engines with downloadable voices.

### 1.3.0 — 2026-11-13
- **Added:** Voice choice. A Voice drop-down under Engine lists each engine's voices, and the choice is remembered per engine (`"voices"` in settings.json).
- **Added:** Piper engine: natural, offline neural voices (15 English voices). Each downloads on first use.
- **Added:** Edge TTS engine: Microsoft's online neural voices (about 47 English voices).
- **Added:** gTTS accents (US, UK, Australia, Canada, India, Ireland, South Africa, Nigeria); female and regional eSpeak voices; the system voices for pyttsx3; and installed Festival voices.
- **Added:** An Engines & Voices manager (Full view, bottom left) to turn engines and individual voices on or off, so the drop-downs only show the ones you use.
- **Added:** A "Generated" column and field showing whether each engine and voice makes speech on this computer or through an online service (gTTS: Google, Edge TTS: Microsoft), including that the text being read is sent to that service. Engines name their service with a new `service` attribute.
- **Added:** Voice details in the manager: each engine and voice shows what it is (gender, accent, online/offline, download size, audio format, model or service, and Edge's personality and "good for" tags), its measured speed, and a star quality rating you can change, plus a Preview button. Engines can provide this through new optional `about`, `quality`, `needs_internet`, `describe_voice()` and `voice_ready()`.
- **Added:** `--check-engines` reports which engines work and tests each one.
- **Fixed:** pyttsx3 wasn't installed and failed with "Engine produced no audio" on multi-line text, because its eSpeak driver could return before it finished writing the file.
- **Fixed:** The speed setting only worked with gTTS. It now applies to every engine.
- **Added:** The app can install Coqui TTS for you. Choosing it offers a one-click install into a private environment (CPU-only PyTorch, about 1 GB) with a live log and Cancel. Coqui then runs in a background worker, so it also works in the packaged app. Engines can offer this through new optional `can_install()` and `install()` methods.
- **Fixed:** After switching to an engine with missing dependencies, the status still said "Stopped" and the buttons came back on, because the startup code kept a separate copy of the "missing dependencies" flag.
- **Changed:** Drop-down lists grow wider than their box so long voice names aren't cut off.

### 1.2.0 — 2026-11-12
- **Added:** Compact and Full views. Compact is the existing control window. Full adds a resizable "Now Reading" panel that shows the text being read aloud, highlights the current word, dims words already read, scrolls to follow along, and shows "Word N of M". The view and the Full window size are remembered.
- **Added:** `word_timing.py` estimates word timings from the text and the pauses in the audio.
- **Added:** A play timer (elapsed / total, e.g. `0:08 / 1:47`) at the top right of the progress bar.
- **Changed:** The window title is just "Clipboard Reader". The version shows only at the bottom of the Compact view.
- **Changed:** Settings such as Debug moved to an options area at the bottom of the Full view's left column, where future options will go too. It's hidden in the Compact view, which keeps Compact smaller.
- **Fixed:** Reading could be impossible to stop. Stop stayed greyed out until audio actually started, which can take 20 seconds or more for long text. Stop pressed while audio was being slowed down (speeds below 1.0x) was ignored, and reading started anyway. Stop is now available, and the status shows "Building audio…" or "Preparing audio…", for the whole time. Stop always wins over audio that's still being prepared.
- **Fixed:** Shortcuts using Ctrl never fired, because with Ctrl held X reports a control character instead of the letter.
- **Fixed:** An error inside a hotkey handler could stop the keyboard listener and silently disable every hotkey until restart. Handlers now catch errors, and a watchdog restarts the listener if it ever stops.
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
