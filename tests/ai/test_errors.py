"""
novelWriter – AI Error Classification Tests
===========================================

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

import sys

from unittest.mock import patch

from novelwriter.ai.claudecode import classifyClaudeError, missingBinaryMessage


class TestClassifyClaudeError:
    def test_not_logged_in(self):
        msg = classifyClaudeError(stderr="Error: not logged in. Run claude login")
        assert "claude login" in msg.lower()
        assert "not logged in" in msg.lower() or "credentials" in msg.lower()

    def test_auth_variants(self):
        for stderr in (
            "Please run /login",
            "unauthorized: invalid api key",
            "Authentication required",
        ):
            msg = classifyClaudeError(stderr=stderr)
            assert "login" in msg.lower() or "credentials" in msg.lower() or "logged" in msg.lower()

    def test_network(self):
        msg = classifyClaudeError(stderr="connection refused: network unreachable")
        assert "network" in msg.lower()

    def test_rate_limit(self):
        msg = classifyClaudeError(stderr="Error 429 rate limit exceeded")
        assert "rate limit" in msg.lower()

    def test_exit_code_with_detail(self):
        msg = classifyClaudeError(exitCode=1, stderr="something obscure failed")
        assert "1" in msg
        assert "obscure" in msg

    def test_exit_code_generic(self):
        msg = classifyClaudeError(exitCode=2)
        assert "2" in msg
        assert "claude login" in msg.lower()

    def test_failed_to_start_not_found(self):
        msg = classifyClaudeError(processError="No such file or directory", stderr="claude")
        assert "not found" in msg.lower() or "CLI" in msg

    def test_permission_denied(self):
        msg = classifyClaudeError(processError="Permission denied", stderr="claude")
        assert "permission" in msg.lower()

    def test_empty_result(self):
        msg = classifyClaudeError()
        assert "no result" in msg.lower()


class TestMissingBinaryMessage:
    def test_mentions_preferences(self):
        msg = missingBinaryMessage()
        assert "Preferences" in msg
        assert "Claude Code" in msg

    def test_macos_mentions_path_tip(self):
        with patch.object(sys, "platform", "darwin"):
            msg = missingBinaryMessage()
        assert "macOS" in msg or "PATH" in msg
        assert "homebrew" in msg.lower() or "opt/homebrew" in msg

    def test_windows_mentions_cmd(self):
        with patch.object(sys, "platform", "win32"):
            msg = missingBinaryMessage()
        assert "Windows" in msg or "claude.cmd" in msg
