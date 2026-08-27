#!/bin/bash

# Build script for textReader PyInstaller executable

set -e  # Exit on error

echo "🔨 Building textReader executable..."

# Activate virtual environment
if [ -d ".venv" ]; then
    echo "📦 Activating virtual environment..."
    source .venv/bin/activate
else
    echo "❌ Virtual environment not found. Run: python -m venv .venv"
    exit 1
fi

# Install/upgrade PyInstaller if needed
echo "📥 Ensuring PyInstaller is installed..."
pip install -q pyinstaller

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build dist *.spec

# Build with PyInstaller
echo "🚀 Running PyInstaller..."
pyinstaller \
    --onefile \
    --windowed \
    --icon "pireader.png" \
    --add-data "tts_engines:tts_engines" \
    --add-data "pireader.png:." \
    --hidden-import=gtts \
    --hidden-import=pyttsx3 \
    --hidden-import=coqui_tts \
    reader.py

echo "✅ Build complete!"
echo "📁 Executable location: dist/reader"

cp ./dist/reader ~/.local/bin/

