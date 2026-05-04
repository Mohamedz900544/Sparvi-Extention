#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT_DIR/Sparvi Extention Desktop Python exe"
APP_BUNDLE="$APP_DIR/dist-macos/Sparvi Desktop Pointer.app"
APP_BINARY="$APP_DIR/dist-macos/Sparvi Desktop Pointer"
LOG_FILE="${TMPDIR:-/tmp}/sparvi-desktop-pointer.log"

if [ -d "$APP_BUNDLE" ]; then
  open "$APP_BUNDLE"
  exit 0
fi

if [ -x "$APP_BINARY" ]; then
  "$APP_BINARY" >"$LOG_FILE" 2>&1 &
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to run Sparvi Desktop Pointer."
  echo "Install Python 3.9 or newer from https://www.python.org/downloads/macos/"
  read -r -p "Press Enter to close..."
  exit 1
fi

cd "$APP_DIR"

VENV_DIR="$APP_DIR/.venv-macos"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements-client.txt
"$VENV_DIR/bin/python" client_app.py
