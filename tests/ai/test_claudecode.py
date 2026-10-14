"""
novelWriter – Claude Code Backend Tests
=======================================

This file is a part of novelWriter
Copyright (C) 2026 novelWriter contributors

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

from pathlib import Path
from unittest.mock import patch

import pytest

from novelwriter.ai.backend import (
    BASE_DISALLOWED_TOOLS,
    DEFAULT_WRITER_ALLOWED_TOOLS,
    buildDisallowedTools,
)
from novelwriter.ai.claudecode import (
    ClaudeCodeBackend,
    isClaudeAvailable,
    resolveClaudeBinary,
)
from novelwriter.ai import isAiAvailable


##
#  Binary resolution
##


class TestResolveClaudeBinary:
    def test_explicit_path(self, tmp_path: Path):
        fake = tmp_path / "claude"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        assert resolveClaudeBinary(str(fake)) == str(fake.resolve())

    def test_explicit_missing_falls_through(self, tmp_path: Path):
        missing = str(tmp_path / "nope")
        # Should not return the missing path; may still find a system claude.
        result = resolveClaudeBinary(missing)
        if result is not None:
            assert Path(result).is_file()
            assert result != missing

    def test_config_ai_claude_bin(self, tmp_path: Path):
        fake = tmp_path / "my-claude"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)

        class _Cfg:
            aiClaudeBin = str(fake)

        with patch("novelwriter.ai.claudecode.CONFIG", _Cfg):
            assert resolveClaudeBinary() == str(fake.resolve())

    def test_which_used(self, tmp_path: Path):
        fake = tmp_path / "claude"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)

        class _Cfg:
            aiClaudeBin = ""

        with (
            patch("novelwriter.ai.claudecode.CONFIG", _Cfg),
            patch("novelwriter.ai.claudecode.shutil.which", return_value=str(fake)),
        ):
            assert resolveClaudeBinary() == str(fake.resolve())

    def test_is_claude_available_bool(self):
        # On this machine claude is installed; just ensure the function returns bool.
        assert isinstance(isClaudeAvailable(), bool)
        assert isAiAvailable() is isClaudeAvailable()


##
#  Argv builder — permission posture
##


class TestBuildArgv:
    def test_read_only_agent_uses_dont_ask(self):
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setAgent("critic")
        be.setReadOnly(True)
        argv = be.buildArgv("hello")
        assert "-p" in argv
        assert argv[argv.index("-p") + 1] == "hello"
        assert "--output-format" in argv
        assert "stream-json" in argv
        assert "--include-partial-messages" in argv
        assert "--verbose" in argv
        assert "--permission-mode" in argv
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "--allowedTools" not in argv
        assert "--disallowedTools" not in argv
        assert "--restricted" in argv
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-prompts") + 1] == "none"
        toolsIdx = argv.index("--tools")
        assert argv[toolsIdx + 1 : toolsIdx + 5] == ["Read", "Glob", "Grep", "Skill"]
        assert "--agent" in argv
        assert argv[argv.index("--agent") + 1] == "critic"

    def test_read_only_auto_from_agent_name(self):
        """Even if setReadOnly(False), known critique agents force dontAsk."""
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setAgent("editor")
        be.setReadOnly(False)
        argv = be.buildArgv("q")
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"

    def test_writing_agent_accept_edits_and_tools(self):
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setAgent("muse")
        be.setReadOnly(False)
        handles = ["bb2c23b3c42cc", "ae7339df26ded"]
        be.setDisallowedTools(buildDisallowedTools(handles))
        argv = be.buildArgv("update the character note")

        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "--restricted" in argv
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-prompts") + 1] == "none"
        toolsIdx = argv.index("--tools")
        assert argv[toolsIdx + 1 : argv.index("--allowedTools")] == [
            "Read",
            "Glob",
            "Grep",
            "Skill",
            "Agent",
            "Edit",
            "Write",
        ]

        # allowedTools: app-approved file tools only
        assert "--allowedTools" in argv
        allowIdx = argv.index("--allowedTools")
        # Collect tokens until next flag
        allowed: list[str] = []
        for tok in argv[allowIdx + 1 :]:
            if tok.startswith("--"):
                break
            allowed.append(tok)
        for tool in DEFAULT_WRITER_ALLOWED_TOOLS:
            assert tool in allowed
        assert "Agent" in allowed
        assert "Task" not in allowed

        assert "--disallowedTools" in argv
        denyIdx = argv.index("--disallowedTools")
        denied: list[str] = []
        for tok in argv[denyIdx + 1 :]:
            if tok.startswith("--"):
                break
            denied.append(tok)
        for base in BASE_DISALLOWED_TOOLS:
            assert base in denied
        assert "Edit(content/bb2c23b3c42cc.nwd)" in denied
        assert "Write(content/bb2c23b3c42cc.nwd)" in denied
        assert "Edit(content/ae7339df26ded.nwd)" in denied

    def test_session_id_first_turn(self):
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        argv = be.buildArgv("first")
        assert "--session-id" in argv
        assert "--resume" not in argv
        sid = argv[argv.index("--session-id") + 1]
        assert len(sid) == 36  # uuid4

    def test_resume_subsequent_turn(self):
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        be._sessionId = "00000000-0000-0000-0000-000000000001"
        argv = be.buildArgv("follow up")
        assert "--resume" in argv
        assert argv[argv.index("--resume") + 1] == be._sessionId
        assert "--session-id" not in argv

    def test_model_and_effort_optional(self):
        be = ClaudeCodeBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        # Unset → not in argv (honour agent frontmatter)
        argv = be.buildArgv("q")
        assert "--model" not in argv
        assert "--effort" not in argv

        be.setModel("sonnet")
        be.setEffort("high")
        argv = be.buildArgv("q")
        assert argv[argv.index("--model") + 1] == "sonnet"
        assert argv[argv.index("--effort") + 1] == "high"

    def test_new_conversation_clears_session(self):
        be = ClaudeCodeBackend()
        be._sessionId = "old-session"
        be.newConversation()
        assert be.sessionId is None
        argv = be.buildArgv("fresh")
        assert "--session-id" in argv
        assert "--resume" not in argv


##
#  startTurn guards (no real process)
##


class TestStartTurnGuards:
    def test_missing_binary(self, qtbot, monkeypatch, tmp_path):
        be = ClaudeCodeBackend()
        be.setProjectPath(tmp_path)
        monkeypatch.setattr(be, "resolveBinary", lambda: None)
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("hello")
        assert errors
        assert "not found" in errors[0].lower()
        assert be.busy is False

    def test_missing_project(self, qtbot, monkeypatch):
        be = ClaudeCodeBackend()
        monkeypatch.setattr(be, "resolveBinary", lambda: "/usr/bin/claude")
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("hello")
        assert errors
        assert "project" in errors[0].lower()

    def test_empty_prompt(self, qtbot, monkeypatch, tmp_path):
        be = ClaudeCodeBackend()
        be.setProjectPath(tmp_path)
        monkeypatch.setattr(be, "resolveBinary", lambda: "/usr/bin/claude")
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("   ")
        assert errors
        assert "empty" in errors[0].lower()

    def test_busy_refuses_second_turn(self, qtbot, monkeypatch, tmp_path):
        be = ClaudeCodeBackend()
        be.setProjectPath(tmp_path)
        monkeypatch.setattr(be, "resolveBinary", lambda: "/usr/bin/claude")
        be._busy = True
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("second")
        assert any("already" in e.lower() for e in errors)
