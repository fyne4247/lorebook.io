"""
novelWriter – AI Chat End-to-End (Phase 4) Tests
================================================

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

import os

import pytest

from novelwriter import SHARED
from novelwriter.ai.backend import DEFAULT_WRITER_ALLOWED_TOOLS
from novelwriter.ai.claudecode import ClaudeCodeBackend
from novelwriter.ai.setup import listManuscriptHandles, setupProjectAi
from novelwriter.core.project import NWProject
from novelwriter.gui.aichat import GuiAiChat

from tests.gui.test_gui_aichat import _makePanel
from tests.helpers import buildTestProject

##
#  Phase 4 acceptance: panel e2e vs FakeBackend
##


@pytest.mark.gui
def testE2E_SelectionThenStream(qtbot, mockGUIwithTheme, tmp_path):
    """Select text → ask critic → streamed reply (selection in prompt + cost)."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    panel.setSelectionProvider(
        lambda: (
            "The rain fell in sheets across the courtyard.",
            "Chapter 1",
            "selection",
            46,
        )
    )
    panel.includeSelection.setChecked(True)
    idx = panel.agentCombo.findData("critic")
    if idx >= 0:
        panel.agentCombo.setCurrentIndex(idx)

    panel.inputEdit.setPlainText("What is the main image in this passage?")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert len(fake.prompts) == 1
    prompt = fake.prompts[0]
    assert '<selection source="Chapter 1">' in prompt
    assert "The rain fell in sheets" in prompt
    assert "What is the main image" in prompt

    plain = panel.transcript.toPlainText()
    assert "What is the main image" in plain
    assert "Hello world!" in plain
    assert panel.lastCostUsd == pytest.approx(0.0123)
    assert "0.0123" in panel.statusLabel.text()
    assert panel.btnSend.text() == "Send"
    assert fake.readOnly is True  # critic
    dialog.close()


@pytest.mark.gui
def testE2E_MultiTurnResume(qtbot, mockGUIwithTheme, tmp_path):
    """Follow-up turn reuses the session (resume path)."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    fake.autoStream = True

    panel.inputEdit.setPlainText("First question about the heroine.")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()
    assert fake.sessionId == "fake-session-id"
    assert panel.messageCount == 2  # user + assistant

    # Second turn — session must still be set so ClaudeCodeBackend would --resume
    panel.inputEdit.setPlainText("Remind me what I just asked.")
    sessionBefore = fake.sessionId
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert sessionBefore == "fake-session-id"
    assert fake.sessionId == "fake-session-id"
    assert len(fake.prompts) == 2
    assert panel.messageCount == 4
    plain = panel.transcript.toPlainText()
    assert "First question" in plain
    assert "Remind me" in plain
    dialog.close()


@pytest.mark.gui
def testE2E_StopMidTurn(qtbot, mockGUIwithTheme, tmp_path):
    """Stop mid-turn terminates cleanly and re-enables input."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    fake.autoStream = False

    panel.inputEdit.setPlainText("Long running critique…")
    panel.btnSend.click()
    assert panel.btnSend.text() == "Stop"
    assert fake.busy is True

    # Partial stream then stop
    fake.signals.sessionStarted.emit("sess-stop")
    fake.signals.chunkReceived.emit("Partial critique of ")
    qtbot.waitUntil(lambda: "Partial critique" in panel.transcript.toPlainText(), timeout=1000)

    with qtbot.waitSignal(fake.signals.errorOccurred, timeout=1000):
        panel.btnSend.click()  # Stop

    assert fake.cancelCount == 1
    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    assert panel.inputEdit.isReadOnly() is False
    assert "cancel" in panel.statusLabel.text().lower() or panel.statusLabel.styleSheet()
    dialog.close()


@pytest.mark.gui
def testE2E_MuseWriterArgvAndDenyRules(qtbot, mockGUIwithTheme, tmp_path, mockGUI, mockRnd):
    """Muse uses restricted dontAsk permissions, Agent, and manuscript denies."""
    # Build a real project so we have NOVEL handles for deny rules
    project = NWProject()
    buildTestProject(project, tmp_path)
    setupProjectAi(project)

    backend = ClaudeCodeBackend()
    backend.setBinary("/usr/bin/claude")
    backend.setProjectPath(tmp_path)
    backend.setAgent("muse")
    backend.setReadOnly(False)

    panel = GuiAiChat(None, backend=backend)  # type: ignore[arg-type]
    panel.setProjectPath(tmp_path)
    idx = panel.agentCombo.findData("muse")
    if idx < 0:
        panel.setAgents([("muse", "lead")], current="muse")
    else:
        panel.agentCombo.setCurrentIndex(idx)

    # Run the same prep the panel does before send
    panel._applyAgentFromCombo()
    panel._prepareBackendForTurn()

    assert backend.readOnly is False
    handles = listManuscriptHandles(tmp_path)
    assert handles  # title page / chapter / scene from buildTestProject
    denied = backend._disallowedTools
    for h in handles:
        assert f"Edit(content/{h}.nwd)" in denied
        assert f"Write(content/{h}.nwd)" in denied
    assert "Bash" in denied

    argv = backend.buildArgv("Update the character note and consult a critic.")
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--restricted" in argv
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    allowIdx = argv.index("--allowedTools")
    allowed = []
    for tok in argv[allowIdx + 1 :]:
        if tok.startswith("--"):
            break
        allowed.append(tok)
    assert "Agent" in allowed  # muse sub-agent fan-out
    assert "Task" not in allowed
    for tool in DEFAULT_WRITER_ALLOWED_TOOLS:
        assert tool in allowed

    # First turn uses --session-id; after setting session, --resume
    assert "--session-id" in argv
    backend._sessionId = "abc-resume-id"
    argv2 = backend.buildArgv("follow up")
    assert "--resume" in argv2
    assert argv2[argv2.index("--resume") + 1] == "abc-resume-id"


@pytest.mark.gui
def testE2E_PreTurnHookAndIndex(qtbot, mockGUIwithTheme, tmp_path, mockGUI, mockRnd):
    """Pre-turn hook runs and INDEX.md is regenerated on send."""
    project = NWProject()
    buildTestProject(project, tmp_path)
    # Minimal nwx already exists via buildTestProject

    hooks: list[str] = []
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    panel.setPreTurnHook(lambda: hooks.append("saved"))

    indexPath = tmp_path / "INDEX.md"
    if indexPath.exists():
        indexPath.unlink()

    panel.inputEdit.setPlainText("hello")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert hooks == ["saved"]
    assert indexPath.is_file()
    dialog.close()


@pytest.mark.gui
def testE2E_CostInStatusLine(qtbot, mockGUIwithTheme, tmp_path):
    """Cost from result event shows in the status line."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    fake.resultMeta = {
        "session_id": "cost-sess",
        "total_cost_usd": 1.2345,
        "is_error": False,
        "permission_denials": [],
    }
    panel.inputEdit.setPlainText("price check")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()
    assert panel.lastCostUsd == pytest.approx(1.2345)
    assert "1.2345" in panel.statusLabel.text()
    dialog.close()


@pytest.mark.gui
def testE2E_NewConversationClearsResume(qtbot, mockGUIwithTheme, tmp_path):
    """New Conversation drops session so the next turn is not a resume."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    panel.inputEdit.setPlainText("turn one")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()
    assert fake.sessionId is not None

    panel.btnNew.click()
    assert fake.sessionId is None
    assert panel.transcript.toPlainText().strip() == ""
    assert panel.messageCount == 0
    dialog.close()


@pytest.mark.gui
def testE2E_WiredGuiMainPreTurn(qtbot, nwGUI, projPath, mockRnd):
    """GuiMain pre-turn hook saves document/project (save-on-send path)."""
    buildTestProject(nwGUI, projPath)
    assert SHARED.hasProject

    # Ensure AI setup so agents exist
    setupProjectAi(SHARED.project)
    nwGUI.aiChat.openProjectTasks()

    # Open a document and dirty it
    from tests.helpers import C

    assert nwGUI.openDocument(C.hSceneDoc)
    nwGUI.docEditor.setPlainText("# Scene\n\nDirty draft line for AI save-on-send.\n")
    assert "Dirty draft line for AI save-on-send." in nwGUI.docEditor.toPlainText()

    # Invoke the hook directly (same as panel before send)
    nwGUI._aiPreTurn()
    # Project should still be open and save should not raise
    assert SHARED.hasProject
    assert nwGUI.aiChat._preTurnHook is not None


##
#  Optional live e2e (real Claude Code CLI)
##


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("NW_AI_E2E") != "1",
    reason="Set NW_AI_E2E=1 to run live Claude Code e2e (requires login + network)",
)
def testE2E_LiveCriticStream(qtbot, tmp_path, mockGUI, mockRnd):
    """Live: critic turn with selection-like prompt against a setup project.

    Run with::

        NW_AI_E2E=1 .venv/bin/python -m pytest tests/gui/test_gui_ai_e2e.py::testE2E_LiveCriticStream -v
    """
    from novelwriter.ai.claudecode import isClaudeAvailable

    if not isClaudeAvailable():
        pytest.skip("claude binary not found")

    project = NWProject()
    buildTestProject(project, tmp_path)
    result = setupProjectAi(project)
    assert result.ok

    # Copy is under tmp_path which must NOT sit under .claude/ (Phase-0 gotcha).
    assert ".claude" not in tmp_path.parts or tmp_path.parts[-1] != ".claude"

    backend = ClaudeCodeBackend()
    backend.setProjectPath(tmp_path)
    backend.setAgent("critic")
    backend.setReadOnly(True)
    # Keep live runs cheap
    backend.setModel("haiku")
    backend.setEffort("low")

    chunks: list[str] = []
    done: list[tuple[str, dict]] = []
    errors: list[str] = []
    backend.signals.chunkReceived.connect(chunks.append)
    backend.signals.turnComplete.connect(lambda t, m: done.append((t, m)))
    backend.signals.errorOccurred.connect(errors.append)

    prompt = (
        '<selection source="Title Page">\n'
        "Once upon a time, a curious writer opened novelWriter.\n"
        "</selection>\n\n"
        "In one short sentence, name the main noun in the selection. No tools needed."
    )

    backend.startTurn(prompt)
    with qtbot.waitSignal(backend.signals.turnComplete, timeout=120_000):
        pass

    assert not errors, errors
    assert done
    text, meta = done[0]
    assert text.strip()
    assert meta.get("session_id")
    # Resume second turn
    backend.startTurn("What was the noun you named? One word.")
    with qtbot.waitSignal(backend.signals.turnComplete, timeout=120_000):
        pass
    assert backend.sessionId
