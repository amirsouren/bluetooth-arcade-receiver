#!/usr/bin/env bash
# =============================================================================
# Bluetooth Arcade Receiver — one-shot installer for Ubuntu 22.04 / 24.04
#
#   git clone <repo-url> && cd bluetooth-arcade-receiver && ./install.sh
#
# What it does:
#   1. checks python3 (>= 3.10 recommended) and the venv module;
#   2. ensures PyGObject is importable (installs the distro python3-gi package
#      via apt when missing — no compiler/libgirepository headers needed);
#   3. creates ./venv with --system-site-packages (spec 08 fallback);
#   4. pip-installs requirements.txt into it;
#   5. generates ~/.local/share/applications/bluetooth-arcade-receiver.desktop
#      from the bluetooth-arcade.desktop template in this repository.
#
# Afterwards: launch "Bluetooth Arcade Receiver" from the Ubuntu app menu, or
# run   venv/bin/python -m src.main   from the project root.
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
APP_ID="bluetooth-arcade-receiver"
APPS_DIR="$HOME/.local/share/applications"

say()  { printf '==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

say "Bluetooth Arcade Receiver installer"

# --- 1. Python ---------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die \
  "python3 not found. Install it with:  sudo apt install python3"
python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"python3 {sys.version.split()[0]} is too old; 3.9+ required")
PY
python3 -c 'import venv' 2>/dev/null || die \
  "the venv module is missing. Install it with:  sudo apt install python3-venv"

# --- 2. PyGObject (distro package avoids building from source) ---------------
if ! python3 -c 'import gi' 2>/dev/null; then
  if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    say "python3-gi not found — installing distro PyGObject (sudo apt)"
    sudo apt-get update
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-glib-2.0
  else
    die "PyGObject missing and cannot apt-install it.
       Install manually:  sudo apt install python3-gi python3-gi-cairo gir1.2-glib-2.0
       (Building it from PyPI instead additionally needs pkg-config +
        libgirepository-1.0-dev — see README.)"
  fi
fi
python3 -c 'import gi' || die "PyGObject (import gi) still unavailable"

# --- 3. Virtual environment --------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  say "creating virtualenv at $VENV_DIR (--system-site-packages)"
  python3 -m venv --system-site-packages "$VENV_DIR"
else
  say "reusing existing virtualenv at $VENV_DIR"
fi

# --- 4. Python dependencies --------------------------------------------------
say "installing Python dependencies (PySide6, pydbus, PyGObject)"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"

# --- 5. Sanity check ---------------------------------------------------------
say "verifying imports"
"$VENV_DIR/bin/python" - <<'PY'
import gi            # noqa: F401  (PyGObject, system package)
import pydbus        # noqa: F401
import PySide6       # noqa: F401
print("    gi, pydbus, PySide6 OK")
PY

# --- 6. Desktop launcher (app menu entry) ------------------------------------
say "installing app-menu launcher -> $APPS_DIR/$APP_ID.desktop"
mkdir -p "$APPS_DIR"
sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" \
    "$PROJECT_DIR/bluetooth-arcade.desktop" > "$APPS_DIR/$APP_ID.desktop"
chmod 644 "$APPS_DIR/$APP_ID.desktop"
command -v update-desktop-database >/dev/null 2>&1 \
  && update-desktop-database "$APPS_DIR" 2>/dev/null || true

# Remove the legacy launcher from earlier local installs (hard-coded paths).
[ -f "$APPS_DIR/bluetooth-arcade.desktop" ] && rm -f "$APPS_DIR/bluetooth-arcade.desktop"

echo
say "Done! Start the arcade receiver:"
echo "    * app menu  ->  \"Bluetooth Arcade Receiver\",  or"
echo "    * terminal  ->  cd $PROJECT_DIR && venv/bin/python -m src.main"
echo
echo "Quick test without a phone:  venv/bin/python tests/mock_player.py"
echo "Backend test suite:          venv/bin/pip install pytest && venv/bin/python -m pytest tests/ -q"
