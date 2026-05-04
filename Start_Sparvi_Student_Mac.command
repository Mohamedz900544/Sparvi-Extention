#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT_DIR/Sparvi Extention Desktop Python exe"
STUDENT_APP="$APP_DIR/dist-macos/Sparvi Desktop Student.app"
STUDENT_BINARY="$APP_DIR/dist-macos/Sparvi Desktop Student"
LOG_FILE="${TMPDIR:-/tmp}/sparvi-desktop-student.log"

export SPARVI_DESKTOP_ROLE=student

if [ -d "$STUDENT_APP" ]; then
  open "$STUDENT_APP"
  exit 0
fi

if [ -x "$STUDENT_BINARY" ]; then
  "$STUDENT_BINARY" >"$LOG_FILE" 2>&1 &
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to run Sparvi Desktop Student."
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
