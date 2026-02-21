#!/bin/bash
# Setup script for textReader project dependencies
set -e

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install required system packages
echo "Installing required system packages..."
sudo apt-get install -y build-essential python3.12-dev python3.12-tk portaudio19-dev xclip

echo "All required system packages installed."

echo "If you have not yet created a virtual environment, run:"
echo "  python3.12 -m venv .venv"
echo "Then activate it with:"
echo "  source .venv/bin/activate"
echo "Then install Python dependencies with:"
echo "  pip install -r requierments.txt"
