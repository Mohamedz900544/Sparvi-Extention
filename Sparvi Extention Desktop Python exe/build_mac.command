#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

DIST_DIR="dist-macos"
WORK_DIR="build-macos"
ICONSET_DIR="$WORK_DIR/icon.iconset"

echo "[1/5] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.9 or newer from https://www.python.org/downloads/macos/"
  exit 1
fi

echo "[2/5] Installing client build dependencies..."
python3 -m pip install -r requirements-client.txt

echo "[3/5] Cleaning old macOS build output..."
rm -rf "$DIST_DIR" "$WORK_DIR"

echo "[4/5] Preparing macOS icon..."
if [ -f "icon.png" ] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  mkdir -p "$ICONSET_DIR"
  sips -z 16 16 icon.png --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 icon.png --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 icon.png --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 icon.png --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 icon.png --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 icon.png --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 icon.png --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 icon.png --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 icon.png --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  sips -z 1024 1024 icon.png --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET_DIR" -o icon.icns
else
  echo "Skipping .icns generation; icon.png, sips, or iconutil was not found."
fi

echo "[5/5] Building macOS app bundles..."
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$WORK_DIR" \
  "Sparvi Desktop Pointer macOS.spec"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$DIST_DIR/Sparvi Desktop Pointer.app" || true
  codesign --force --deep --sign - "$DIST_DIR/Sparvi Desktop Student.app" || true
  codesign --force --deep --sign - "$DIST_DIR/Sparvi Desktop Teacher.app" || true
fi

echo
echo "Build finished successfully."
echo "macOS apps:"
echo "  $DIST_DIR/Sparvi Desktop Pointer.app"
echo "  $DIST_DIR/Sparvi Desktop Student.app"
echo "  $DIST_DIR/Sparvi Desktop Teacher.app"
echo
echo "On first launch, macOS may ask for Accessibility/Input Monitoring permission."
