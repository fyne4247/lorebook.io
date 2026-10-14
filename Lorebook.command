#!/bin/bash
# Lorebook.command — launch the novelWriter + Claude AI sidebar (macOS)
# Double-click in Finder. First time: run Setup.command, then right-click → Open if needed.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/setup/macos/launcher-paths.sh"
APP="$(lorebook_app_dir "$ROOT")" || APP=""
VENV="$APP/.venv"

cd "$APP" || {
  echo "Could not enter $APP"
  read -r -p "Press Enter to close..."
  exit 1
}

if [ ! -d "$VENV" ]; then
  echo "No virtualenv yet. Run Setup.command first (double-click it)."
  read -r -p "Press Enter to close..."
  exit 1
fi

# Prefer absolute venv python3 — bare `python` is often missing on macOS Homebrew.
if [ -x "$VENV/bin/python3" ]; then
  PY="$VENV/bin/python3"
elif [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
else
  echo "No python in $VENV/bin — run Setup.command again."
  read -r -p "Press Enter to close..."
  exit 1
fi

export PYTHONPATH="$APP${PYTHONPATH:+:$PYTHONPATH}"
# Ensure venv bin is first so any console scripts resolve correctly
export PATH="$VENV/bin:$PATH"

# Spell-check dictionaries (written by Setup.command if user installed them)
_DIC_PARTS=()
if [ -f "$VENV/dicpath.txt" ]; then
  _DICPATH="$(tr -d '\n' < "$VENV/dicpath.txt")"
  if [ -n "$_DICPATH" ] && [ -d "$_DICPATH" ]; then
    _DIC_PARTS+=("$_DICPATH")
  fi
fi
if command -v brew >/dev/null 2>&1; then
  _BREW_HS="$(brew --prefix 2>/dev/null)/share/hunspell"
  if [ -d "$_BREW_HS" ]; then
    _DIC_PARTS+=("$_BREW_HS")
  fi
fi
if [ -d "$HOME/Library/Application Support/enchant/hunspell" ]; then
  _DIC_PARTS+=("$HOME/Library/Application Support/enchant/hunspell")
fi
if [ ${#_DIC_PARTS[@]} -gt 0 ]; then
  # Join with :
  _JOINED="${_DIC_PARTS[0]}"
  for ((i=1; i<${#_DIC_PARTS[@]}; i++)); do
    _JOINED="${_JOINED}:${_DIC_PARTS[$i]}"
  done
  export DICPATH="${_JOINED}${DICPATH:+:$DICPATH}"
fi

echo "Starting Lorebook (novelWriter) from:"
echo "  $APP"
echo "  Python: $PY"
[ -n "${DICPATH:-}" ] && echo "  DICPATH: $DICPATH"
echo ""

# Prefer installed entrypoint; fall back to start script
if [ -x "$VENV/bin/novelwriter" ]; then
  exec "$VENV/bin/novelwriter" "$@"
elif [ -f "$APP/novelWriter.py" ]; then
  exec "$PY" "$APP/novelWriter.py" "$@"
else
  echo "Could not find novelWriter entrypoint."
  read -r -p "Press Enter to close..."
  exit 1
fi
