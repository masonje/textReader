#!/bin/bash
# Install textReader: build the executable, generate the icon set, and
# register a .desktop launcher so the app shows the correct icon in both
# the app menu and the taskbar/dock.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor"
ICON_SOURCE="$SCRIPT_DIR/pireader.png"
ICON_SIZES=(16 32 48 128 256 512)

echo "Building reader executable..."
"$SCRIPT_DIR/build.sh"

echo "Installing executable to $BIN_DIR..."
mkdir -p "$BIN_DIR"
# Temp copy + rename so this works even while the app is running
cp "$SCRIPT_DIR/dist/reader" "$BIN_DIR/.reader.new"
chmod +x "$BIN_DIR/.reader.new"
mv -f "$BIN_DIR/.reader.new" "$BIN_DIR/reader"

echo "Generating icon set from $ICON_SOURCE..."
PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
	PYTHON="python3"
fi
for size in "${ICON_SIZES[@]}"; do
	dest_dir="$ICON_DIR/${size}x${size}/apps"
	mkdir -p "$dest_dir"
	"$PYTHON" - "$ICON_SOURCE" "$dest_dir/reader.png" "$size" <<'EOF'
import sys
from PIL import Image
src, dest, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS).save(dest)
EOF
done

echo "Writing desktop launcher..."
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/reader.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Screen Reader
Comment=screen reader
Exec=$BIN_DIR/reader
Icon=reader
StartupWMClass=Reader
Terminal=false
Categories=Utility;
EOF
chmod +x "$APPS_DIR/reader.desktop"

echo "Refreshing desktop and icon caches..."
update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true

echo "Install complete. Launch 'Screen Reader' from your app menu."
