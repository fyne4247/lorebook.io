"""novelWriter - Persistent Claude Code Backend Tests.
==================================================

Covers the argv builder, change-detecting setters (respawn-on-change), and the
pre-spawn turn guards for :class:`ClaudeCodePersistentBackend`. No real process
is launched: spawning is monkeypatched where a turn would otherwise start one.

Copyright (C) 2026 novelWriter contributors
"""

from __future__ import annotations

from novelwriter.ai.backend import (
    BASE_DISALLOWED_TOOLS,
    DEFAULT_WRITER_ALLOWED_TOOLS,
    buildDisallowedTools,
)
from novelwriter.ai.claudecode import ClaudeCodePersistentBackend


def _collectAfter(argv: list[str], flag: str) -> list[str]:
    """Return the tokens following ``flag`` up to the next ``--option``."""
    out: list[str] = []
    for tok in argv[argv.index(flag) + 1 :]:
        if tok.startswith("--"):
            break
        out.append(tok)
    return out


class TestPersistentBuildArgv:
    def test_stream_json_io_and_no_prompt_flag(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        argv = be.buildArgv()
        # Prompt is delivered via stdin, never as -p.
        assert "-p" not in argv
        assert "--print" in argv
        assert argv[argv.index("--input-format") + 1] == "stream-json"
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--include-partial-messages" in argv
        assert "--verbose" in argv
        assert "--replay-user-messages" in argv

    def test_remote_control_disabled_by_default(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        assert "--remote-control" not in be.buildArgv()

    def test_remote_control_flag_and_name(self):
        be = ClaudeCodePersistentBackend(remoteControl=True, remoteControlName="lorebook")
        be.setBinary("/usr/bin/claude")
        argv = be.buildArgv()
        assert "--remote-control" in argv
        assert argv[argv.index("--remote-control") + 1] == "lorebook"

    def test_remote_control_without_name(self):
        be = ClaudeCodePersistentBackend(remoteControl=True)
        be.setBinary("/usr/bin/claude")
        argv = be.buildArgv()
        assert "--remote-control" in argv
        # No positional name → the next token is another flag.
        assert argv[argv.index("--remote-control") + 1].startswith("--")

    def test_session_id_first_then_resume(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        argv = be.buildArgv()
        assert "--session-id" in argv
        assert "--resume" not in argv
        assert len(argv[argv.index("--session-id") + 1]) == 36  # uuid4

        be._sessionId = "00000000-0000-0000-0000-000000000001"
        argv2 = be.buildArgv()
        assert argv2[argv2.index("--resume") + 1] == be._sessionId
        assert "--session-id" not in argv2

    def test_read_only_agent_dont_ask(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        be.setAgent("critic")
        argv = be.buildArgv()
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "--restricted" in argv
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-prompts") + 1] == "none"
        assert _collectAfter(argv, "--tools") == ["Read", "Glob", "Grep", "Skill"]
        assert "--allowedTools" not in argv
        assert argv[argv.index("--agent") + 1] == "critic"

    def test_writing_agent_uses_closed_tools_and_denies(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        be.setAgent("muse")
        be.setReadOnly(False)
        be.setDisallowedTools(buildDisallowedTools(["bb2c23b3c42cc"]))
        argv = be.buildArgv()
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "--restricted" in argv
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-prompts") + 1] == "none"
        assert _collectAfter(argv, "--tools") == ["Read", "Glob", "Grep", "Skill", "Agent", "Edit", "Write"]
        allowed = _collectAfter(argv, "--allowedTools")
        for tool in DEFAULT_WRITER_ALLOWED_TOOLS:
            assert tool in allowed
        denied = _collectAfter(argv, "--disallowedTools")
        for base in BASE_DISALLOWED_TOOLS:
            assert base in denied
        assert "Edit(content/bb2c23b3c42cc.nwd)" in denied

    def test_model_and_effort_optional(self):
        be = ClaudeCodePersistentBackend()
        be.setBinary("/usr/bin/claude")
        be.setReadOnly(True)
        argv = be.buildArgv()
        assert "--model" not in argv
        assert "--effort" not in argv
        be.setModel("sonnet")
        be.setEffort("high")
        argv = be.buildArgv()
        assert argv[argv.index("--model") + 1] == "sonnet"
        assert argv[argv.index("--effort") + 1] == "high"


class TestRespawnOnChange:
    """Config is fixed at spawn, so only *changes* should mark the session dirty."""

    def test_setters_mark_dirty_only_on_change(self):
        be = ClaudeCodePersistentBackend()
        be.setModel("sonnet")
        assert be._dirty is True
        be._dirty = False
        be.setModel("sonnet")  # same value
        assert be._dirty is False
        be.setModel("opus")  # changed
        assert be._dirty is True

    def test_disallowed_tools_no_false_dirty(self):
        be = ClaudeCodePersistentBackend()
        tools = buildDisallowedTools(["bb2c23b3c42cc"])
        be.setDisallowedTools(tools)
        be._dirty = False
        be.setDisallowedTools(list(tools))  # identical list
        assert be._dirty is False

    def test_remote_control_toggle_marks_dirty(self):
        be = ClaudeCodePersistentBackend()
        be.setRemoteControl(True, "x")
        assert be._dirty is True
        assert be.remoteControl is True
        be._dirty = False
        be.setRemoteControl(True, "x")
        assert be._dirty is False

    def test_project_change_resets_session(self, tmp_path):
        be = ClaudeCodePersistentBackend()
        be._sessionId = "old"
        be.setProjectPath(tmp_path)
        assert be.sessionId is None
        assert be._dirty is True


class TestPersistentTurnGuards:
    def test_empty_prompt(self, qtbot):
        be = ClaudeCodePersistentBackend()
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("   ")
        assert any("empty" in e.lower() for e in errors)
        assert be.busy is False

    def test_busy_refuses_second_turn(self, qtbot):
        be = ClaudeCodePersistentBackend()
        be._busy = True
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("second")
        assert any("already" in e.lower() for e in errors)

    def test_missing_binary(self, qtbot, monkeypatch, tmp_path):
        be = ClaudeCodePersistentBackend()
        be.setProjectPath(tmp_path)
        monkeypatch.setattr(be, "resolveBinary", lambda: None)
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("hello")
        assert any("not found" in e.lower() for e in errors)
        assert be.busy is False

    def test_missing_project(self, qtbot, monkeypatch):
        be = ClaudeCodePersistentBackend()
        monkeypatch.setattr(be, "resolveBinary", lambda: "/usr/bin/claude")
        errors: list[str] = []
        be.signals.errorOccurred.connect(errors.append)
        be.startTurn("hello")
        assert any("project" in e.lower() for e in errors)
        assert be.busy is False

    def test_new_conversation_clears_session(self):
        be = ClaudeCodePersistentBackend()
        be._sessionId = "old-session"
        be.newConversation()
        assert be.sessionId is None
