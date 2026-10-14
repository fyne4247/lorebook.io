#!/usr/bin/env python3
"""
Verify that the active Python environment can start Qt's native Cocoa app.

This file is a part of novelWriter
Copyright (C) 2018 Veronica Berglyd Olsen and novelWriter contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

from pathlib import Path

PROBE_TIMEOUT = int(os.environ.get("LOREBOOK_QT_PROBE_TIMEOUT", "30"))
INSTALL_TIMEOUT = int(os.environ.get("LOREBOOK_QT_INSTALL_TIMEOUT", "600"))

_PROBE = textwrap.dedent(
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication([])
    platform = app.platformName()
    print(f"QT_PLATFORM={platform}", flush=True)
    app.quit()
    raise SystemExit(0 if platform == "cocoa" else 1)
    """
)


def _disable_core_dumps() -> None:
    """Keep a Qt startup crash from leaving a core file in the project folder."""
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_disable_core_dumps,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or exc.stderr or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        print(f"Command timed out after {timeout} seconds: {' '.join(command)}")
        if output.strip():
            print(output.strip())
        return None
    except OSError as exc:
        print(f"Could not run {' '.join(command)}: {exc}")
        return None


def _show_output(result: subprocess.CompletedProcess[str]) -> None:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if output:
        print(output)


def _probe(python: str) -> bool | None:
    result = _run([python, "-c", _PROBE], PROBE_TIMEOUT)
    if result is None:
        return None
    _show_output(result)
    if result.returncode:
        print(f"Native Qt Cocoa startup exited with status {result.returncode}.")
        return False
    return "QT_PLATFORM=cocoa" in result.stdout


def main() -> int:
    """Run the native Qt check and repair PyQt6 once if necessary."""
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} VENV_PYTHON", file=sys.stderr)
        return 2

    python = sys.argv[1]
    print("Checking native Qt Cocoa startup...")
    probe = _probe(python)
    if probe is True:
        print("Native Qt Cocoa startup is working.")
        return 0
    if probe is None:
        print("Native Qt Cocoa check timed out or could not run; skipping repair.", file=sys.stderr)
        return 1

    print("Repairing PyQt6 once, then checking Cocoa startup again...")
    install = _run(
        [python, "-m", "pip", "install", "--force-reinstall", "PyQt6>=6.4"],
        INSTALL_TIMEOUT,
    )
    if install is None:
        print("PyQt6 repair could not be completed.", file=sys.stderr)
        return 1
    _show_output(install)
    if install.returncode:
        print(f"PyQt6 repair exited with status {install.returncode}.", file=sys.stderr)
        return 1

    if _probe(python) is True:
        print("Native Qt Cocoa startup is working after the repair attempt.")
        return 0

    print(
        "Qt could not start its native Cocoa platform. Check the Python and PyQt6 installation, "
        "then run Setup.command again.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
