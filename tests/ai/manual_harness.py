#!/usr/bin/env python3
"""Manual harness: stream a single Claude Code turn and print chunks to stdout.

Usage (from app/):
  .venv/bin/python tests/ai/manual_harness.py /path/to/project "your question" [--agent critic]

Requires the Claude Code CLI on PATH and a project directory that is NOT under
any .claude/ path segment (Phase 0 gotcha).

Copyright (C) 2026 novelWriter contributors
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

# Allow running without install: repo root on sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402

from novelwriter.ai.claudecode import ClaudeCodeBackend  # noqa: E402


def main() -> int:
    """Run one interactive Claude Code turn for manual diagnostics."""
    parser = argparse.ArgumentParser(description="Stream one Claude Code turn.")
    parser.add_argument("project", type=Path, help="novelWriter project directory")
    parser.add_argument("prompt", help="User prompt for the turn")
    parser.add_argument("--agent", default="critic", help="Agent name (default: critic)")
    parser.add_argument("--model", default="", help="Model override (empty = agent default)")
    parser.add_argument("--effort", default="", help="Effort override")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Use acceptEdits writer posture (default: dontAsk read-only)",
    )
    args = parser.parse_args()

    if not args.project.is_dir():
        print(f"error: not a directory: {args.project}", file=sys.stderr)
        return 2

    app = QCoreApplication(sys.argv)
    backend = ClaudeCodeBackend()
    backend.setProjectPath(args.project)
    backend.setAgent(args.agent)
    backend.setModel(args.model)
    backend.setEffort(args.effort)
    backend.setReadOnly(not args.write)

    def on_session(sid: str) -> None:
        print(f"\n[session] {sid}", flush=True)

    def on_chunk(text: str) -> None:
        print(text, end="", flush=True)

    def on_tool(name: str) -> None:
        print(f"\n[tool] {name}", flush=True)

    def on_complete(text: str, meta: dict) -> None:
        cost = meta.get("total_cost_usd")
        print(f"\n\n[complete] cost_usd={cost} chars={len(text)}", flush=True)
        app.quit()

    def on_error(msg: str) -> None:
        print(f"\n[error] {msg}", file=sys.stderr, flush=True)
        app.exit(1)

    backend.signals.sessionStarted.connect(on_session)
    backend.signals.chunkReceived.connect(on_chunk)
    backend.signals.toolActivity.connect(on_tool)
    backend.signals.turnComplete.connect(on_complete)
    backend.signals.errorOccurred.connect(on_error)

    # Start after the event loop is running.
    QTimer.singleShot(0, lambda: backend.startTurn(args.prompt))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
