#!/bin/bash

# Locate the application in either the public repository root or legacy app/ layout.
lorebook_app_dir() {
  local root="$1"
  if [ -f "$root/novelWriter.py" ]; then
    printf '%s\n' "$root"
  elif [ -f "$root/app/novelWriter.py" ]; then
    printf '%s\n' "$root/app"
  else
    return 1
  fi
}
