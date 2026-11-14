#!/bin/bash
# Setup script for textReader project dependencies
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install required system packages
echo "Installing required system packages..."
sudo apt-get install -y \
	build-essential \
	python3 \
	python3-venv \
	python3-tk \
	ffmpeg \
	xclip \
	espeak-ng \
	festival \
	libsdl2-dev \
	libsdl2-mixer-dev \
	pkg-config \
	libfreetype-dev

echo "All required system packages installed."

# Create virtual environment if missing
if [ ! -d "$ROOT/.venv" ]; then
	echo "Creating virtual environment..."
	python3 -m venv "$ROOT/.venv"
fi

# Install the app and its Python dependencies (from pyproject.toml) into the venv.
# Editable (-e): the venv runs the code in this folder, so changes take effect on restart.
# [dev] adds pytest, pyflakes and PyInstaller.
echo "Installing Python dependencies..."
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -e "$ROOT[dev]"
"$ROOT/.venv/bin/python" -m pip install --force-reinstall --no-cache-dir pygame==2.6.1

# Create desktop launcher
DESKTOP_FILE="$HOME/Desktop/TextReader.desktop"
echo "Creating desktop launcher at $DESKTOP_FILE..."
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Text Reader
Comment=Clipboard Reader
Exec=$ROOT/.venv/bin/textreader
Path=$ROOT
Icon=audio-x-generic
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP_FILE"

echo "Setup complete. You can launch Text Reader from your desktop."
