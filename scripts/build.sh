#!/bin/bash

# Build script for textReader PyInstaller executable

set -e  # Exit on error

# Work from the repository root, wherever this is run from
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "🔨 Building textReader executable..."

# Activate virtual environment
if [ -d ".venv" ]; then
    echo "📦 Activating virtual environment..."
    source .venv/bin/activate
else
    echo "❌ Virtual environment not found. Run: scripts/setup.sh"
    exit 1
fi

# Install/upgrade PyInstaller if needed
echo "📥 Ensuring PyInstaller is installed..."
pip install -q pyinstaller

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build dist

# Build with PyInstaller
echo "🚀 Running PyInstaller..."
pyinstaller \
    --name reader \
    --onefile \
    --windowed \
    --specpath build \
    --paths "$ROOT" \
    --icon "$ROOT/textreader/assets/pireader.png" \
    --add-data "$ROOT/textreader/assets:textreader/assets" \
    --add-data "$ROOT/textreader/engines:textreader/engines" \
    --collect-submodules textreader \
    --hidden-import=gtts \
    --hidden-import=pyttsx3 \
    --collect-submodules pyttsx3 \
    --hidden-import=edge_tts \
    --collect-all piper \
    --hidden-import=onnxruntime \
    textreader/__main__.py

echo "✅ Build complete!"
echo "📁 Executable location: dist/reader"

# Copy to a temp name, then rename: replacing the file in one step works even
# while the app is running (a plain cp fails with "Text file busy").
mkdir -p ~/.local/bin
cp ./dist/reader ~/.local/bin/.reader.new
mv -f ~/.local/bin/.reader.new ~/.local/bin/reader
echo "📦 Installed to ~/.local/bin/reader (restart the app to use the new build)"

