# Clipboard Reader
Reads text aloud. Python version of text aloud mp3 to run on Linux, Windows, or macOS.

## Requirements

- Python 3.7+
- The following Python packages (install with `pip install -r requirements.txt`):
	- pyperclip
	- gtts
	- pygame
	- pystray
	- Pillow
	- pynput

- ffmpeg (for audio speed control)

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