#!/bin/bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
helper="$repo/setup/macos/launcher-paths.sh"
launcher="$repo/Lorebook.command"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/lorebook launcher paths.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

source "$helper"

root_clone="$tmp/clean clone with spaces"
mkdir -p "$root_clone"
: > "$root_clone/novelWriter.py"
[ "$(lorebook_app_dir "$root_clone")" = "$root_clone" ]
mkdir -p "$root_clone/setup/macos" "$root_clone/.venv/bin"
cp "$helper" "$root_clone/setup/macos/launcher-paths.sh"
cp "$launcher" "$root_clone/Lorebook.command"
cat > "$root_clone/.venv/bin/novelwriter" <<'STUB'
#!/bin/bash
printf 'LAUNCH_CWD=%s\n' "$PWD"
STUB
cat > "$root_clone/.venv/bin/python3" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$root_clone/.venv/bin/novelwriter" "$root_clone/.venv/bin/python3"
root_output="$(bash "$root_clone/Lorebook.command")"
[[ "$root_output" == *"LAUNCH_CWD=$root_clone"* ]]

legacy_clone="$tmp/legacy clone with spaces"
mkdir -p "$legacy_clone/app"
: > "$legacy_clone/app/novelWriter.py"
[ "$(lorebook_app_dir "$legacy_clone")" = "$legacy_clone/app" ]
mkdir -p "$legacy_clone/setup/macos" "$legacy_clone/app/.venv/bin"
cp "$helper" "$legacy_clone/setup/macos/launcher-paths.sh"
cp "$launcher" "$legacy_clone/Lorebook.command"
cat > "$legacy_clone/app/.venv/bin/novelwriter" <<'STUB'
#!/bin/bash
printf 'LAUNCH_CWD=%s\n' "$PWD"
STUB
cat > "$legacy_clone/app/.venv/bin/python3" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$legacy_clone/app/.venv/bin/novelwriter" "$legacy_clone/app/.venv/bin/python3"
legacy_output="$(bash "$legacy_clone/Lorebook.command")"
[[ "$legacy_output" == *"LAUNCH_CWD=$legacy_clone/app"* ]]

if lorebook_app_dir "$tmp/missing clone" >/dev/null; then
  echo "Expected a missing application path to fail." >&2
  exit 1
fi

echo "Launcher layout checks passed."
