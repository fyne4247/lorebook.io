#!/bin/bash
# Focused simulation tests for verify_qt.py. Does not start a native GUI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HELPER="$SCRIPT_DIR/verify_qt.py"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT
ulimit -c 0

cat > "$TEST_DIR/fake-python" <<'PY'
#!/usr/bin/env python3
import os
import pathlib
import sys
import time

state = pathlib.Path(os.environ["FAKE_STATE"])
mode = os.environ["FAKE_MODE"]
args = sys.argv[1:]

if "-c" in args:
    count = int(state.read_text()) if state.exists() else 0
    count += 1
    state.write_text(str(count))
    if mode == "initial-timeout-recovers" and count == 1:
        time.sleep(5)
    if mode == "healthy" or (mode in {"recover", "initial-timeout-recovers", "pip-fail-recovers"} and count > 1):
        print("QT_PLATFORM=cocoa")
        raise SystemExit(0)
    raise SystemExit(1)

if "-m" in args and "pip" in args:
    pip_calls = pathlib.Path(os.environ["FAKE_PIP_CALLED"])
    count = int(pip_calls.read_text()) if pip_calls.exists() else 0
    pip_calls.write_text(str(count + 1))
    if mode == "install-timeout":
        time.sleep(5)
    if mode in {"pip-fail", "pip-fail-recovers", "install-timeout"}:
        raise SystemExit(1)
    raise SystemExit(0)

raise SystemExit(9)
PY
chmod +x "$TEST_DIR/fake-python"

assert_eq() {
  if [ "$1" != "$2" ]; then
    printf 'expected [%s], got [%s]\n' "$2" "$1" >&2
    exit 1
  fi
}

run_case() {
  local mode="$1" expected="$2" python_path="$3"
  export FAKE_MODE="$mode"
  export FAKE_STATE="$TEST_DIR/state-$mode"
  export FAKE_PIP_CALLED="$TEST_DIR/pip-$mode"
  rm -f "$FAKE_STATE" "$FAKE_PIP_CALLED"
  set +e
  LOREBOOK_QT_PROBE_TIMEOUT=1 LOREBOOK_QT_INSTALL_TIMEOUT=1 python3 "$HELPER" "$python_path" > "$TEST_DIR/output-$mode" 2>&1
  local status=$?
  set -e
  assert_eq "$status" "$expected"
}

run_case healthy 0 "$TEST_DIR/fake-python"
test ! -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_STATE")" 1

run_case recover 0 "$TEST_DIR/fake-python"
test -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_PIP_CALLED")" 1
assert_eq "$(cat "$FAKE_STATE")" 2

run_case pip-fail 1 "$TEST_DIR/fake-python"
test -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_PIP_CALLED")" 1
assert_eq "$(cat "$FAKE_STATE")" 1
grep -q 'repair exited with status 1' "$TEST_DIR/output-pip-fail"

run_case pip-fail-recovers 1 "$TEST_DIR/fake-python"
test -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_PIP_CALLED")" 1
assert_eq "$(cat "$FAKE_STATE")" 1
grep -q 'repair exited with status 1' "$TEST_DIR/output-pip-fail-recovers"

run_case persistent 1 "$TEST_DIR/fake-python"
test -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_PIP_CALLED")" 1
assert_eq "$(cat "$FAKE_STATE")" 2
grep -q 'could not start its native Cocoa platform' "$TEST_DIR/output-persistent"

run_case initial-timeout-recovers 1 "$TEST_DIR/fake-python"
test ! -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_STATE")" 1
grep -q 'timed out after 1 seconds' "$TEST_DIR/output-initial-timeout-recovers"

run_case install-timeout 1 "$TEST_DIR/fake-python"
test -e "$FAKE_PIP_CALLED"
assert_eq "$(cat "$FAKE_PIP_CALLED")" 1
assert_eq "$(cat "$FAKE_STATE")" 1
grep -q 'timed out after 1 seconds' "$TEST_DIR/output-install-timeout"

mkdir "$TEST_DIR/path with spaces"
cp "$TEST_DIR/fake-python" "$TEST_DIR/path with spaces/fake-python"
run_case healthy 0 "$TEST_DIR/path with spaces/fake-python"

printf 'Qt setup helper shell tests passed.\n'
