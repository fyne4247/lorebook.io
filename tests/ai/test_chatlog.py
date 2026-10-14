"""
novelWriter – AI Chat Log Tests
===============================
"""  # noqa

from __future__ import annotations

import builtins

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from novelwriter.ai.chatlog import AiChatLog, chatLogDir


class TestAiChatLog:
    def test_empty_state_and_optional_messages(self):
        log = AiChatLog()
        assert log.turnCount == 0
        assert log.newSession() is None
        assert log.ensureFile() is None
        log.appendUser("  ")
        log.appendAssistant("  ")
        log.appendNote("  ")
        log._appendBlock("Assistant", "unattached")
        assert log.exportMarkdown("unused.md") is False
        assert log.renderMarkdown([("user", "Q"), ("assistant", "A"), ("system", "S")])

    def test_optional_assistant_metadata(self, tmp_path: Path):
        log = AiChatLog()
        log.setProjectPath(tmp_path)
        log.appendAssistant(
            "Answer",
            costUsd="not numeric",
            usage=SimpleNamespace(contextUsed=0, contextWindow=0, outputTokens=5),
        )
        log.appendAssistant(
            "Another answer",
            usage=SimpleNamespace(contextUsed="bad", contextWindow=0, outputTokens=0),
        )
        log.appendAssistant(
            "Context answer",
            usage=SimpleNamespace(contextUsed=100, contextWindow=1000, outputTokens=5),
        )
        log.appendAssistant(
            "Empty usage answer",
            usage=SimpleNamespace(contextUsed=0, contextWindow=1000, outputTokens=0),
        )
        assert log.path is not None
        text = log.path.read_text(encoding="utf-8")
        assert "out: 5 tok" in text
        assert "ctx: 100/1,000" in text
        assert text.count("## Assistant") == 4

    def test_create_file_failure(self, tmp_path: Path, monkeypatch):
        log = AiChatLog()
        log.setProjectPath(tmp_path)
        realOpen = Path.open

        def deniedOpen(path: Path, *args, **kwargs):
            if path.suffix == ".md":
                raise PermissionError("write denied")
            return realOpen(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deniedOpen)
        log.appendUser("cannot save")
        assert log.path is None

    def test_export_and_append_failures(self, tmp_path: Path, monkeypatch):
        log = AiChatLog()
        log.setProjectPath(tmp_path)
        log.appendUser("saved")
        assert log.path is not None
        source = log.path
        realRead = Path.read_text

        def deniedRead(path: Path, *args, **kwargs):
            if path == source:
                raise PermissionError("read denied")
            return realRead(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", deniedRead)
        assert log.exportMarkdown(tmp_path / "failed.md") is False

        realWrite = Path.write_text

        def deniedWrite(path: Path, *args, **kwargs):
            if path == tmp_path / "failed.md":
                raise PermissionError("write denied")
            return realWrite(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", deniedWrite)
        assert log.exportMessages(tmp_path / "failed.md", [("user", "Q")]) is False

        monkeypatch.setattr(Path, "read_text", realRead)
        monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("append denied")))
        log.appendNote("will fail to append")

    def test_no_project_and_blank_append_paths(self):
        log = AiChatLog()
        log.newSession(agent="muse", sessionId="session-id")
        log.appendAssistant("answer")
        assert log.path is None
        assert log.turnCount == 0

    def test_same_second_sessions_do_not_overwrite(self, tmp_path: Path, monkeypatch):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 14, 12, 0, 0)

        monkeypatch.setattr("novelwriter.ai.chatlog.datetime", FixedDateTime)
        log = AiChatLog()
        log.setProjectPath(tmp_path)

        log.newSession(agent="muse", sessionId="12345678-first")
        log.appendUser("First session", agent="muse", sessionId="12345678-first")
        firstPath = log.path
        assert firstPath is not None

        log.newSession(agent="muse", sessionId="12345678-second")
        log.appendUser("Second session", agent="muse", sessionId="12345678-second")

        assert log.path is not None
        assert log.path != firstPath
        assert firstPath.read_text(encoding="utf-8").find("First session") != -1
        assert log.path.read_text(encoding="utf-8").find("Second session") != -1
        assert len(list(chatLogDir(tmp_path).glob("*.md"))) == 2

    def test_append_and_export(self, tmp_path: Path):
        log = AiChatLog()
        log.setProjectPath(tmp_path)
        log.newSession(agent="critic", sessionId="abcd-1234")
        log.appendUser("Hello agent", agent="critic", sessionId="abcd-1234")
        log.appendAssistant(
            "Hello author.",
            model="claude-haiku-4-5-20251001",
            costUsd=0.0123,
            agent="critic",
            sessionId="abcd-1234",
        )
        assert log.path is not None
        assert log.turnCount == 1
        assert log.path.is_file()
        assert log.path.parent == chatLogDir(tmp_path)
        text = log.path.read_text(encoding="utf-8")
        assert "# AI Chat — critic" in text
        assert "## You" in text
        assert "Hello agent" in text
        assert "## Assistant" in text
        assert "Hello author." in text
        assert "0.0123" in text
        assert "haiku" in text

        dest = tmp_path / "export.md"
        assert log.exportMarkdown(dest) is True
        assert dest.read_text(encoding="utf-8") == text

    def test_export_messages_without_file(self, tmp_path: Path):
        log = AiChatLog()
        dest = tmp_path / "out" / "chat.md"
        ok = log.exportMessages(
            dest,
            [("user", "Q"), ("assistant", "A")],
            agent="muse",
            sessionId="s1",
            model="claude-opus",
        )
        assert ok is True
        text = dest.read_text(encoding="utf-8")
        assert "muse" in text
        assert "## You" in text
        assert "Q" in text
        assert "A" in text

    def test_no_project_skips_autosave(self):
        log = AiChatLog()
        log.appendUser("orphan")
        assert log.path is None


@pytest.mark.gui
def testChatLog_PanelAutosave(qtbot, mockGUIwithTheme, tmp_path):
    """Panel auto-saves turns under meta/ai-chat/."""
    from tests.gui.test_gui_aichat import _makePanel

    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    panel.inputEdit.setPlainText("Save me")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    logDir = chatLogDir(tmp_path)
    files = list(logDir.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Save me" in text
    assert "Hello world!" in text
    dialog.close()
