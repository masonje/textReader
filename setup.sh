#!/bin/bash
# Setup script for textReader project dependencies
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
	festival

echo "All required system packages installed."

# Create virtual environment if missing
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
	echo "Creating virtual environment..."
	python3 -m venv "$SCRIPT_DIR/.venv"
fi

# Install Python dependencies
echo "Installing Python dependencies..."
REQ_FILE="$SCRIPT_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
	REQ_FILE="$SCRIPT_DIR/requierments.txt"
fi
"$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SCRIPT_DIR/.venv/bin/python" -m pip install -r "$REQ_FILE"

# Ensure run.sh is executable
chmod +x "$SCRIPT_DIR/run.sh"

# Create desktop launcher
DESKTOP_FILE="$HOME/Desktop/TextReader.desktop"
echo "Creating desktop launcher at $DESKTOP_FILE..."
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Text Reader
Comment=Clipboard Reader
Exec=$SCRIPT_DIR/run.sh
Path=$SCRIPT_DIR
Icon=audio-x-generic
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP_FILE"

echo "Setup complete. You can launch Text Reader from your desktop."
