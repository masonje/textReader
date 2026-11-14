# Contributing to Clipboard Reader

This covers working on the code. For installing and using the app, see the [README](README.md).

## Development Setup

```bash
scripts/setup.sh
.venv/bin/textreader
```

`scripts/setup.sh` installs the system packages (ffmpeg, libmpv, espeak-ng, festival, Tk, …), creates `.venv`, and installs the app into it in "editable" mode with the `dev` extras (pytest, pyflakes, PyInstaller). Editable means it runs the code in this folder: edit, restart, and your change is live. `.venv/bin/python -m textreader` does the same.

## Project Layout

```
textreader/             the app, as one Python package
  __main__.py           entry point: --version, dependency check, --check-engines, start
  app.py                main window, playback, hotkeys, tray icon, settings
  options.py            the Options window and its tabs
  theme.py              light/dark palette and widget styles
  hotkeys.py            parsing and checking shortcut strings
  pronunciation.py      word rules and the links/paths/codes filters
  player.py             audio playback (mpv, or pygame as a fallback)
  word_timing.py        word-highlight timing
  engines/              one file per speech engine (see below)
  assets/pireader.png   app icon
scripts/                setup.sh, build.sh, install.sh
tests/                  pytest tests
docs/screenshots/       README pictures
pyproject.toml          package info, dependencies, test settings
```

## Tests

```bash
.venv/bin/python -m pytest
```

The tests cover the parts that can be checked without sound or a window: the pronunciation rules, the links/paths/codes filters, word-highlight timing, shortcut parsing and the mpv player (skipped if libmpv is missing). They take a few seconds. Check the engines themselves with `reader --check-engines`.

Check for unused imports and similar mistakes with:

```bash
.venv/bin/pyflakes textreader tests
```

## Speech Engines

Each TTS engine lives in the `textreader/engines` directory and implements a common interface.

- textreader/engines/base.py
	- Defines the `TTSEngine` base class
	- Required fields: `name`, `output_ext`
	- Required methods: `check_dependencies()`, `synthesize(text, output_path, cancel_event=None, voice=None)`
	- Optional: `list_voices()` returns `(voice_id, label)` pairs, best default first
	- `run_cancellable(cmd, cancel_event, input_text=None)`: helper that runs an external command and kills it if the build is cancelled
	- `SynthesisCancelled`: exception an engine raises when it stops because of a cancel

- textreader/engines/__init__.py
	- Auto-discovers engine modules named `engine_*.py`
	- Registers all `TTSEngine` subclasses
	- Exposes `list_engines()` and `get_engine(name)`

### Adding a new engine
1. Create a new engine file in `textreader/engines` with the `engine_*.py` prefix (e.g., engine_mytts.py).
2. Implement a subclass of `TTSEngine` with:
	- `name`: what shows up in the UI dropdown
	- `output_ext`: `mp3` or `wav`. Write whatever the engine produces natively: WAV for engines that run locally (no compression step), MP3 for online services that send MP3. Converting only adds time.
	- `check_dependencies()`: return a list of missing deps
	- `list_voices()` (optional): return `(voice_id, label)` pairs; the UI shows the labels and passes the chosen `voice_id` back
	- `synthesize(text, output_path, cancel_event=None, voice=None)`: write audio to output_path. Check `cancel_event.is_set()` where you can and raise `SynthesisCancelled`; for external commands use `run_cancellable()`. Engines that can't be interrupted can ignore it, and the app throws away their output.
3. No manual registration required. The module is auto-discovered on startup.

The main app (`textreader/app.py`) only calls `get_engine()` and `synthesize()` and does not contain per-engine logic.

## Building

`scripts/install.sh` builds a single-file executable with PyInstaller (via `scripts/build.sh`), copies it to `~/.local/bin/reader`, installs the icon set, and adds a "Screen Reader" launcher to the app menu.

`scripts/build.sh` on its own builds `dist/reader` and copies it to `~/.local/bin/reader`. The PyInstaller options (bundled engines and icon, hidden imports) are in that script; its spec file goes in `build/`. libmpv and ffmpeg aren't bundled, so the target system needs them installed.

After building, check it with `reader --version` and `reader --check-engines`.

## Debugging

As well as the user-facing [Troubleshooting](README.md#troubleshooting) options:

| Setting | What it does |
|---|---|
| `TR_MPV_LOG=/path/file.log` | Write mpv's full (verbose) playback log to that file. Without it only mpv errors are printed. |
| `SDL_AUDIODRIVER=dummy` | Silence pygame (voice previews and the beep). Playback through mpv is not affected. |
| `HOME=/some/test/folder` | Run with separate settings, voices and logs, so testing doesn't touch your own `~/.textReader`. |

## Releases

1. Set the version in [textreader/__init__.py](textreader/__init__.py) (`pyproject.toml` reads it from there) and on the **Version** line of the README.
2. Add an entry at the top of the README's Changelog.
3. Run the tests and `scripts/install.sh`, then check `reader --version` and `reader --check-engines`.
4. Open a pull request into `main`.
