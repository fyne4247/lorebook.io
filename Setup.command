#!/bin/bash
# Setup.command — first-time setup for Lorebook (novelWriter + Claude sidebar)
# Double-click in Finder. First time: right-click → Open if Gatekeeper warns.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/setup/macos/launcher-paths.sh"
APP="$(lorebook_app_dir "$ROOT")" || APP=""
VENV="$APP/.venv"
# Always prefer the venv interpreter by absolute path (Homebrew macOS often
# has no bare `python` command — only python3).
PY=""

BOLD=$(tput bold 2>/dev/null); RESET=$(tput sgr0 2>/dev/null)
GREEN=$(tput setaf 2 2>/dev/null); YELLOW=$(tput setaf 3 2>/dev/null); RED=$(tput setaf 1 2>/dev/null)

ok()   { printf "  %s✓%s %s\n" "$GREEN" "$RESET" "$1"; }
warn() { printf "  %s!%s %s\n" "$YELLOW" "$RESET" "$1"; }
err()  { printf "  %s✗%s %s\n" "$RED" "$RESET" "$1"; }

ask_yn() {
  # ask_yn "question" "y|n"(default) -> 0 yes, 1 no
  local prompt="$1" default="${2:-y}" reply
  if [ "$default" = "y" ]; then
    read -r -p "$prompt [Y/n] " reply
    [ -z "$reply" ] && reply=y
  else
    read -r -p "$prompt [y/N] " reply
    [ -z "$reply" ] && reply=n
  fi
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

echo ""
echo "${BOLD}Lorebook — setup (macOS)${RESET}"
echo "Installs a local Python venv and dependencies for the novelWriter fork."
echo "App path: $APP"
echo ""

# Make launchers executable for future double-clicks
chmod +x "$ROOT/Setup.command" "$ROOT/Lorebook.command" 2>/dev/null || true

if [ ! -d "$APP" ] || [ ! -f "$APP/novelWriter.py" ]; then
  err "Could not find novelWriter.py in this folder or its app/ subfolder."
  read -r -p "Press Enter to close..."
  exit 1
fi

# System Python 3.11+
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found. Install Python 3.11+ (e.g. brew install python@3.12)."
  read -r -p "Press Enter to close..."
  exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')
if [ "$PY_OK" != "1" ]; then
  err "Python $PY_VER is too old. Need 3.11+."
  read -r -p "Press Enter to close..."
  exit 1
fi
ok "Python $PY_VER"

# Venv
if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv at $VENV ..."
  python3 -m venv "$VENV"
  ok "Created venv"
else
  ok "venv already exists"
fi

# Resolve venv python (python3 first — bare `python` is often missing on macOS)
if [ -x "$VENV/bin/python3" ]; then
  PY="$VENV/bin/python3"
elif [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
else
  err "No python in $VENV/bin — try deleting $VENV and re-running Setup."
  read -r -p "Press Enter to close..."
  exit 1
fi
ok "Using $PY"

"$PY" -m pip install --upgrade pip wheel setuptools -q

echo "Installing novelWriter dependencies (PyQt6, etc.) ..."
# Runtime deps; editable install if possible
if (cd "$APP" && "$PY" -m pip install -e . -q); then
  ok "Installed app (editable)"
else
  warn "Editable install failed; installing declared dependencies only"
  "$PY" -m pip install "pyqt6>=6.4" "pyenchant>=3.3.0" -q
  if [[ "$(uname -s)" == "Darwin" ]]; then
    "$PY" -m pip install pyobjc -q || warn "pyobjc optional install failed"
  fi
  ok "Installed runtime packages"
fi

# Verify the actual native Qt platform before continuing with setup.
if "$PY" "$APP/setup/macos/verify_qt.py" "$PY"; then
  ok "Native Qt Cocoa startup verified"
else
  err "Qt could not start on macOS, even after one repair attempt."
  echo "  Check the Python/PyQt6 installation, then run Setup.command again."
  read -r -p "Press Enter to close..."
  exit 1
fi

# Optional dev/test extras (best-effort)
(cd "$APP" && "$PY" -m pip install pytest pytest-qt pytest-timeout -q) 2>/dev/null && ok "Test tools installed" || true

# ---------------------------------------------------------------------------
# Optional spell checker (Enchant + Hunspell dictionary)
# ---------------------------------------------------------------------------
echo ""
echo "${BOLD}Spell checking${RESET}"
echo "novelWriter uses Enchant/Hunspell for spell check. Without a dictionary"
echo "you will see 'Failed to load enchant' errors (harmless, but no underlines)."
echo ""

SPELL_LANG=""
if ask_yn "Install a spell-check dictionary now?" "y"; then
  echo ""
  echo "Choose a language:"
  echo "  1) English (US)     en_US"
  echo "  2) English (UK)     en_GB"
  echo "  3) French           fr_FR"
  echo "  4) German           de_DE"
  echo "  5) Spanish          es_ES"
  echo "  6) Italian          it_IT"
  echo "  7) Norwegian Bokmål nb_NO"
  echo "  8) Dutch            nl_NL"
  echo "  9) Polish           pl_PL"
  echo " 10) Portuguese (BR)  pt_BR"
  echo " 11) Russian          ru_RU"
  echo "  0) Skip"
  echo ""
  read -r -p "Number [1]: " choice
  [ -z "$choice" ] && choice=1

  case "$choice" in
    1) SPELL_LANG="en_US"; DICT_SUB="en"; DICT_FILE="en_US" ;;
    2) SPELL_LANG="en_GB"; DICT_SUB="en"; DICT_FILE="en_GB" ;;
    3) SPELL_LANG="fr_FR"; DICT_SUB="fr_FR"; DICT_FILE="fr_FR" ;;
    4) SPELL_LANG="de_DE"; DICT_SUB="de"; DICT_FILE="de_DE_frami" ;;
    5) SPELL_LANG="es_ES"; DICT_SUB="es"; DICT_FILE="es_ES" ;;
    6) SPELL_LANG="it_IT"; DICT_SUB="it_IT"; DICT_FILE="it_IT" ;;
    7) SPELL_LANG="nb_NO"; DICT_SUB="no"; DICT_FILE="nb_NO" ;;
    8) SPELL_LANG="nl_NL"; DICT_SUB="nl_NL"; DICT_FILE="nl_NL" ;;
    9) SPELL_LANG="pl_PL"; DICT_SUB="pl_PL"; DICT_FILE="pl_PL" ;;
    10) SPELL_LANG="pt_BR"; DICT_SUB="pt_BR"; DICT_FILE="pt_BR" ;;
    11) SPELL_LANG="ru_RU"; DICT_SUB="ru_RU"; DICT_FILE="ru_RU" ;;
    0|"") SPELL_LANG="" ;;
    *)
      warn "Unknown choice — skipping spell-check install."
      SPELL_LANG=""
      ;;
  esac

  if [ -n "$SPELL_LANG" ]; then
    echo ""
    echo "Installing Enchant + Hunspell support for ${SPELL_LANG}..."

    HAVE_BREW=0
    command -v brew >/dev/null 2>&1 && HAVE_BREW=1

    if [ "$HAVE_BREW" -eq 1 ]; then
      if ! brew list enchant &>/dev/null; then
        echo "  brew install enchant ..."
        brew install enchant || warn "brew install enchant failed"
      else
        ok "enchant already installed (Homebrew)"
      fi
      if ! brew list hunspell &>/dev/null; then
        echo "  brew install hunspell ..."
        brew install hunspell || warn "brew install hunspell failed"
      else
        ok "hunspell already installed (Homebrew)"
      fi
      # Preferred dictionary directory (Homebrew share)
      if BREW_PREFIX="$(brew --prefix 2>/dev/null)"; then
        HUNSPELL_DIR="$BREW_PREFIX/share/hunspell"
      else
        HUNSPELL_DIR="$HOME/Library/Spelling"
      fi
    else
      warn "Homebrew not found — will only download dictionary files."
      echo "  (Install brew from https://brew.sh then re-run Setup for full Enchant support.)"
      HUNSPELL_DIR="$HOME/Library/Spelling"
    fi

    mkdir -p "$HUNSPELL_DIR"
    # Also put a copy where Enchant's hunspell provider often looks on macOS
    ENCHANT_USER_DICT="$HOME/Library/Application Support/enchant/hunspell"
    mkdir -p "$ENCHANT_USER_DICT"
    mkdir -p "$HOME/.config/enchant"

    # LibreOffice dictionaries (Apache-2.0 / LGPL) raw files on GitHub
    BASE_URL="https://raw.githubusercontent.com/LibreOffice/dictionaries/master"
    AFF_URL="${BASE_URL}/${DICT_SUB}/${DICT_FILE}.aff"
    DIC_URL="${BASE_URL}/${DICT_SUB}/${DICT_FILE}.dic"

    download_dict() {
      local url="$1" dest="$2"
      if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$dest"
      elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$dest" "$url"
      else
        return 1
      fi
    }

    TMPD=$(mktemp -d)
    if download_dict "$AFF_URL" "$TMPD/${SPELL_LANG}.aff" \
      && download_dict "$DIC_URL" "$TMPD/${SPELL_LANG}.dic"; then
      # Install under the chosen tag name (en_US.aff / en_US.dic)
      cp "$TMPD/${SPELL_LANG}.aff" "$HUNSPELL_DIR/${SPELL_LANG}.aff"
      cp "$TMPD/${SPELL_LANG}.dic" "$HUNSPELL_DIR/${SPELL_LANG}.dic"
      cp "$TMPD/${SPELL_LANG}.aff" "$ENCHANT_USER_DICT/${SPELL_LANG}.aff"
      cp "$TMPD/${SPELL_LANG}.dic" "$ENCHANT_USER_DICT/${SPELL_LANG}.dic"
      # German LO pack uses de_DE_frami — also alias as de_DE if needed
      if [ "$DICT_FILE" != "$SPELL_LANG" ]; then
        cp "$TMPD/${SPELL_LANG}.aff" "$HUNSPELL_DIR/${DICT_FILE}.aff" 2>/dev/null || true
        cp "$TMPD/${SPELL_LANG}.dic" "$HUNSPELL_DIR/${DICT_FILE}.dic" 2>/dev/null || true
      fi
      ok "Dictionary files installed for ${SPELL_LANG}"
      ok "  → $HUNSPELL_DIR"
    else
      warn "Could not download dictionary from LibreOffice repo."
      echo "  URLs tried:"
      echo "    $AFF_URL"
      echo "    $DIC_URL"
      echo "  You can add dicts later via novelWriter Tools → Add Dictionaries (Windows-oriented)"
      echo "  or place .aff/.dic files in: $HUNSPELL_DIR"
    fi
    rm -rf "$TMPD"

    # Prefer Hunspell when Enchant chooses a backend
    ORDERING="$HOME/.config/enchant/enchant.ordering"
    if [ ! -f "$ORDERING" ]; then
      printf '%s\n' '*:hunspell,aspell,AppleSpell' > "$ORDERING"
      ok "Wrote $ORDERING"
    else
      ok "Enchant ordering already present"
    fi

    # Reinstall pyenchant so it binds against the system libenchant
    echo "  Reinstalling pyenchant in the venv..."
    if "$PY" -m pip install --force-reinstall --no-cache-dir "pyenchant>=3.3.0" -q; then
      ok "pyenchant reinstalled"
    else
      warn "pyenchant reinstall failed — spell check may still not work"
    fi

    # Export for this session + hint for Lorebook.command
    export DICPATH="$HUNSPELL_DIR${DICPATH:+:$DICPATH}"
    # Persist DICPATH for Lorebook.command
    echo "$HUNSPELL_DIR" > "$APP/.venv/dicpath.txt"
    ok "Saved dictionary path for the launcher"

    # Quick verify
    if DICPATH="$HUNSPELL_DIR" "$PY" -c "
import os, enchant
os.environ['DICPATH'] = '$HUNSPELL_DIR'
ok = enchant.dict_exists('$SPELL_LANG')
print('dict_exists $SPELL_LANG:', ok)
raise SystemExit(0 if ok else 1)
" 2>/dev/null; then
      ok "Enchant can load ${SPELL_LANG}"
      echo ""
      echo "  In Lorebook: set project spell language to ${SPELL_LANG}"
      echo "  (Project → Project Settings → Spell check language)."
    else
      warn "Enchant still cannot see ${SPELL_LANG}."
      echo "  Try re-launching Lorebook.command after this Setup finishes."
      echo "  Dict files are in: $HUNSPELL_DIR"
      echo "  Debug:"
      echo "    export DICPATH=\"$HUNSPELL_DIR\""
      echo "    $PY -c \"import enchant; print(enchant.dict_exists('$SPELL_LANG'))\""
    fi
  fi
else
  ok "Skipped spell-check install (you can re-run Setup later)"
fi

# Claude CLI
echo ""
if command -v claude >/dev/null 2>&1; then
  ok "Claude Code CLI found: $(command -v claude)"
  echo "  (If chat fails with auth errors, run: claude login)"
else
  warn "Claude Code CLI not on PATH."
  echo "  Install Claude Code, then either add it to PATH or set the binary"
  echo "  path in Preferences → AI Assistant after launch."
fi

echo ""
echo "${BOLD}Done.${RESET}"
echo "  • Daily launch: double-click  Lorebook.command"
echo "  • Open any existing novelWriter project (File → Open) — no conversion needed."
echo "  • First time per project: Tools → Set up AI for Project"
echo ""
read -r -p "Press Enter to close..."
