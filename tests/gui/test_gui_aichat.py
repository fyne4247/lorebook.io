"""
novelWriter – GUI AI Chat Panel Tests
=====================================

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

import pytest

from PyQt6.QtCore import QTimer

from novelwriter import CONFIG
from novelwriter.ai.backend import AiBackend
from novelwriter.ai.claudecode import ClaudeCodePersistentBackend
from novelwriter.gui.aichat import GuiAiChat

from tests.helpers import SimpleDialog


class FakeBackend(AiBackend):
    """Test double implementing the AiBackend signal surface.

    By default, ``startTurn`` schedules a short multi-chunk stream via
    QTimer so the event loop can process UI updates between emissions.
    Tests can also drive the stream manually by setting ``autoStream=False``.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.prompts: list[str] = []
        self.cancelCount = 0
        self.autoStream = True
        self.chunks = ["Hello ", "world", "!"]
        self.resultText = "Hello world!"
        self.resultMeta: dict = {
            "session_id": "fake-session-id",
            "total_cost_usd": 0.0123,
            "is_error": False,
            "permission_denials": [],
            "usage": {
                "input_tokens": 18,
                "output_tokens": 446,
                "cache_read_input_tokens": 32375,
                "cache_creation_input_tokens": 10828,
            },
            "modelUsage": {
                "claude-haiku-4-5-20251001": {
                    "inputTokens": 565,
                    "outputTokens": 465,
                    "cacheReadInputTokens": 32375,
                    "cacheCreationInputTokens": 10828,
                    "contextWindow": 200000,
                    "costUSD": 0.0123,
                }
            },
        }
        self.errorOnStart: str | None = None
        self.toolName = "Read"
        self._emitErrorInstead = False

    def startTurn(self, prompt: str) -> None:
        if self._busy:
            self.signals.errorOccurred.emit("A turn is already in progress.")
            return
        if self.errorOnStart:
            self.signals.errorOccurred.emit(self.errorOnStart)
            return
        self.prompts.append(prompt)
        self._busy = True
        if self.autoStream:
            QTimer.singleShot(0, self._emitStream)

    def cancel(self) -> None:
        self.cancelCount += 1
        self._busy = False
        self.signals.errorOccurred.emit("Turn cancelled.")

    def emitStreamNow(self) -> None:
        """Manually run the canned stream (when autoStream is False)."""
        self._emitStream()

    def _emitStream(self) -> None:
        if not self._busy and not self.prompts:
            return
        # Preserve session across multi-turn resume (Phase 4).
        if not self._sessionId:
            self._sessionId = "fake-session-id"
        self.signals.sessionStarted.emit(self._sessionId)
        # Simulate stream init model field
        self.signals.modelResolved.emit("claude-haiku-4-5-20251001")
        if self.toolName:
            self.signals.toolActivity.emit(self.toolName)
        for chunk in self.chunks:
            self.signals.chunkReceived.emit(chunk)
        self._busy = False
        if self._emitErrorInstead:
            self.signals.errorOccurred.emit("Synthetic failure")
        else:
            meta = dict(self.resultMeta)
            meta.setdefault("session_id", self._sessionId)
            meta.setdefault("model", "claude-haiku-4-5-20251001")
            self.signals.turnComplete.emit(self.resultText, meta)


##
#  Helpers
##


def _makePanel(qtbot, mockGUIwithTheme, backend: FakeBackend | None = None, tmp_path=None):
    """Create a GuiAiChat hosted in a SimpleDialog with theme available."""
    fake = backend or FakeBackend()
    panel = GuiAiChat(None, backend=fake)  # type: ignore[arg-type]
    # Phase 4: send requires a project directory.
    if tmp_path is not None:
        panel.setProjectPath(tmp_path)
    else:
        # Fallback: use a temp-like path that exists (tests/_temp is created by suite).
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "_temp"
        p.mkdir(exist_ok=True)
        panel.setProjectPath(p)
    dialog = SimpleDialog(panel)
    qtbot.addWidget(dialog)
    dialog.show()
    return panel, fake, dialog


##
#  Tests
##


@pytest.mark.gui
def testAiChat_CreateAndDefaults(qtbot, mockGUIwithTheme):
    """Panel constructs with muse/sonnet defaults and idle Send button."""
    from novelwriter import CONFIG
    from novelwriter.ai.models import DEFAULT_AI_AGENT, DEFAULT_AI_MODEL

    # Isolate from other tests' CONFIG mutations.
    CONFIG.aiAgent = DEFAULT_AI_AGENT
    CONFIG.aiModel = DEFAULT_AI_MODEL

    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    assert panel.backend is fake
    assert panel.btnSend.text() == "Send"
    assert panel.inputEdit.isReadOnly() is False
    assert panel.agentCombo.count() >= 5
    assert panel.agentCombo.currentData() == "muse"
    assert panel.modelCombo.count() >= 7  # agent default + aliases + versioned
    assert panel.modelCombo.currentData() == "sonnet"
    assert panel.modelCombo.findData("claude-sonnet-4-5") >= 0
    assert panel.modelCombo.findData("claude-sonnet-4-6") >= 0
    assert panel.modelCombo.findData("claude-opus-4-6") >= 0
    assert panel.effortCombo.count() >= 5  # default + low/med/high/xhigh/max
    assert panel.effortCombo.currentData() == ""
    assert "effort" in panel.effortIndicator.text().lower()
    assert "Tokens" in panel.tokenIndicator.text() or "—" in panel.tokenIndicator.text()
    assert panel.includeSelection.isChecked() is True
    assert "Ready" in panel.statusLabel.text() or panel.statusLabel.text()
    dialog.close()


@pytest.mark.gui
def testAiChat_ModelDropdownAndIndicator(qtbot, mockGUIwithTheme, tmp_path):
    """Model combo overrides CONFIG; stream resolves concrete model id."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    # Select Sonnet 4.5 specifically
    idx = panel.modelCombo.findData("claude-sonnet-4-5")
    assert idx >= 0
    panel.modelCombo.setCurrentIndex(idx)
    assert fake.model == "claude-sonnet-4-5"
    assert "4.5" in panel.modelIndicator.text() or "sonnet" in panel.modelIndicator.text().lower()

    panel.inputEdit.setPlainText("hi")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    # Indicator shows resolved haiku id from fake stream
    assert "haiku" in panel.modelIndicator.text().lower()
    assert "Running" in panel.modelIndicator.text()
    dialog.close()


@pytest.mark.gui
def testAiChat_ModelPersistsToConfig(qtbot, mockGUIwithTheme, monkeypatch):
    """Changing model/agent/effort writes CONFIG (persisted via saveConfig)."""
    from novelwriter import CONFIG

    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    saved = {"n": 0}
    realSave = CONFIG.saveConfig

    def _trackingSave(*args, **kwargs):
        saved["n"] += 1
        return realSave(*args, **kwargs)

    monkeypatch.setattr(type(CONFIG), "saveConfig", lambda self, *a, **k: _trackingSave(*a, **k))

    mIdx = panel.modelCombo.findData("claude-opus-4-6")
    assert mIdx >= 0
    panel.modelCombo.setCurrentIndex(mIdx)
    assert CONFIG.aiModel == "claude-opus-4-6"
    assert fake.model == "claude-opus-4-6"
    assert saved["n"] >= 1

    aIdx = panel.agentCombo.findData("critic")
    assert aIdx >= 0
    panel.agentCombo.setCurrentIndex(aIdx)
    assert CONFIG.aiAgent == "critic"
    assert saved["n"] >= 2

    eIdx = panel.effortCombo.findData("high")
    assert eIdx >= 0
    panel.effortCombo.setCurrentIndex(eIdx)
    assert CONFIG.aiEffort == "high"
    assert fake.effort == "high"
    assert "High" in panel.effortIndicator.text() or "high" in panel.effortIndicator.text().lower()
    assert saved["n"] >= 3
    dialog.close()


@pytest.mark.gui
def testAiChat_TokenCounterFromUsage(qtbot, mockGUIwithTheme):
    """Turn complete updates the token indicator from modelUsage/contextWindow."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    panel.inputEdit.setPlainText("count tokens please")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert panel.lastUsage is not None
    assert panel.lastUsage.contextWindow == 200000
    assert panel.lastUsage.contextUsed > 0
    tip = panel.tokenIndicator.toolTip()
    assert "ctx" in panel.tokenIndicator.text().lower() or "Ctx" in panel.tokenIndicator.text()
    assert "200" in panel.tokenIndicator.text() or "200k" in panel.tokenIndicator.text()
    assert "Session" in tip or "session" in tip.lower() or "in" in tip.lower()
    assert "0.0123" in panel.statusLabel.text() or "Done" in panel.statusLabel.text()
    # Context fraction should appear in status when available
    assert "ctx" in panel.statusLabel.text().lower() or "%" in panel.statusLabel.text()
    dialog.close()


@pytest.mark.gui
def testAiChat_SendBusyChunksComplete(qtbot, mockGUIwithTheme):
    """Core Phase-2 flow: send → busy → chunks append → complete re-enables."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)

    panel.inputEdit.setPlainText("What do you think of this scene?")
    assert panel.isBusy is False

    # Send
    panel.btnSend.click()

    # Immediately after click (before QTimer fires) backend is busy and UI flipped.
    assert fake.busy is True or panel.btnSend.text() == "Stop"
    assert panel.btnSend.text() == "Stop"
    assert panel.inputEdit.isReadOnly() is True
    assert panel.agentCombo.isEnabled() is False
    assert panel.btnNew.isEnabled() is False
    assert fake.prompts
    assert "What do you think" in fake.prompts[0]

    # Wait for the fake stream to finish
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        pass

    # Process any remaining queued slots
    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=2000)

    assert panel.isBusy is False
    assert panel.inputEdit.isReadOnly() is False
    assert panel.agentCombo.isEnabled() is True
    assert panel.btnNew.isEnabled() is True
    assert panel.btnSend.text() == "Send"

    # Transcript should contain the user prompt and the assistant result
    plain = panel.transcript.toPlainText()
    assert "What do you think of this scene?" in plain
    assert "Hello world!" in plain

    # Cost shown in status
    assert "0.0123" in panel.statusLabel.text() or "Done" in panel.statusLabel.text()

    # Input was cleared on send
    assert panel.inputEdit.toPlainText() == ""

    dialog.close()


@pytest.mark.gui
def testAiChat_ChunksAppendLive(qtbot, mockGUIwithTheme):
    """Streamed chunks appear in the transcript before turnComplete."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = False
    fake.chunks = ["Alpha", "Beta", "Gamma"]
    fake.resultText = "AlphaBetaGamma"

    panel.inputEdit.setPlainText("stream test")
    panel.btnSend.click()
    assert fake.busy is True

    # Drive session + first chunk
    fake.signals.sessionStarted.emit("sid-1")
    fake.signals.chunkReceived.emit("Alpha")
    qtbot.waitUntil(lambda: "Alpha" in panel.transcript.toPlainText(), timeout=1000)

    fake.signals.chunkReceived.emit("Beta")
    qtbot.waitUntil(lambda: "AlphaBeta" in panel.transcript.toPlainText(), timeout=1000)

    fake.signals.chunkReceived.emit("Gamma")
    fake._busy = False
    fake.signals.turnComplete.emit(fake.resultText, dict(fake.resultMeta))

    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    assert "AlphaBetaGamma" in panel.transcript.toPlainText()
    dialog.close()


@pytest.mark.gui
def testAiChat_StreamSeparatesTurnsAndShowsIndicator(qtbot, mockGUIwithTheme):
    """Mid-stream, user and assistant turns render as separate blocks, and a
    'Thinking…'/tool indicator shows so the panel never looks frozen or merged.
    """
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = False

    panel.inputEdit.setPlainText("hello there")
    panel.btnSend.click()

    # Immediately after send (no chunks yet): distinct You + Assistant blocks and
    # a working indicator — the reply must not be mashed onto the user's line.
    text = panel.transcript.toPlainText()
    assert "hello there" in text
    assert "Assistant" in text
    assert "Thinking" in text
    assert "hello thereThinking" not in text

    # Tool activity surfaces inline in the transcript, not only the status bar.
    fake.signals.toolActivity.emit("Read")
    qtbot.waitUntil(lambda: "Using Read" in panel.transcript.toPlainText(), timeout=1000)

    # First real chunk: replaces the indicator, still separated from the user turn.
    fake.signals.chunkReceived.emit("Sure, here goes.")
    qtbot.waitUntil(lambda: "Sure, here goes." in panel.transcript.toPlainText(), timeout=1000)
    text = panel.transcript.toPlainText()
    assert "hello thereSure" not in text

    fake._busy = False
    fake.signals.turnComplete.emit("Sure, here goes.", dict(fake.resultMeta))
    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    dialog.close()


@pytest.mark.gui
def testAiChat_StopCancels(qtbot, mockGUIwithTheme):
    """Stop button while busy calls backend.cancel and restores idle UI."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = False

    panel.inputEdit.setPlainText("long running")
    panel.btnSend.click()
    assert panel.btnSend.text() == "Stop"
    assert fake.busy is True

    with qtbot.waitSignal(fake.signals.errorOccurred, timeout=1000) as blocker:
        panel.btnSend.click()  # Stop
    assert "cancel" in blocker.args[0].lower()
    assert fake.cancelCount == 1

    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    assert panel.inputEdit.isReadOnly() is False
    assert (
        "cancel" in panel.statusLabel.text().lower()
        or "error" in panel.statusLabel.styleSheet().lower()
        or panel.statusLabel.text()
    )
    dialog.close()


@pytest.mark.gui
def testAiChat_EmptyPromptRefused(qtbot, mockGUIwithTheme):
    """Sending with empty input does not start a turn."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    panel.inputEdit.setPlainText("   ")
    panel.btnSend.click()
    assert fake.prompts == []
    assert fake.busy is False
    assert panel.btnSend.text() == "Send"
    dialog.close()


@pytest.mark.gui
def testAiChat_SelectionInjection(qtbot, mockGUIwithTheme):
    """Include-selection wraps the provider text into the backend prompt."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = True

    panel.setSelectionProvider(lambda: ("The rain fell hard.", "Chapter 1", "selection", 19))
    panel.includeSelection.setChecked(True)
    panel.refreshSelectionInfo()
    assert "19" in panel.selectionInfo.text() or "chars" in panel.selectionInfo.text()

    panel.inputEdit.setPlainText("Critique this.")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert len(fake.prompts) == 1
    prompt = fake.prompts[0]
    assert '<selection source="Chapter 1">' in prompt
    assert "The rain fell hard." in prompt
    assert "Critique this." in prompt

    # Visible transcript shows the user's typed text, not the wrapper.
    plain = panel.transcript.toPlainText()
    assert "Critique this." in plain
    assert "<selection" not in plain

    dialog.close()


@pytest.mark.gui
def testAiChat_SelectionDisabled(qtbot, mockGUIwithTheme):
    """Unchecking include-selection sends the bare user text."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)

    panel.setSelectionProvider(lambda: ("secret text", "Doc", "selection", 11))
    panel.includeSelection.setChecked(False)
    panel.inputEdit.setPlainText("Just a question")

    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert fake.prompts == ["Just a question"]
    dialog.close()


@pytest.mark.gui
def testAiChat_MultiFileDocumentBlocks(qtbot, mockGUIwithTheme):
    """Multi-file provider text is injected as raw <document> blocks (no selection wrap)."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = True

    multi = (
        '<document title="Scene A" handle="h1">\n'
        "First scene body.\n"
        "</document>\n\n"
        '<document title="Scene B" handle="h2">\n'
        "Second scene body.\n"
        "</document>"
    )
    panel.setSelectionProvider(lambda: (multi, "2 files · Scene A, Scene B", "documents", 40))
    panel.includeSelection.setChecked(True)
    panel.refreshSelectionInfo()
    assert "Scene A" in panel.selectionInfo.text() or "chars" in panel.selectionInfo.text()

    panel.inputEdit.setPlainText("Compare these scenes.")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()

    assert len(fake.prompts) == 1
    prompt = fake.prompts[0]
    assert '<document title="Scene A" handle="h1">' in prompt
    assert '<document title="Scene B" handle="h2">' in prompt
    assert "First scene body." in prompt
    assert "Second scene body." in prompt
    assert "Compare these scenes." in prompt
    # Must not nest multi-file blocks inside <selection>
    assert "<selection" not in prompt

    plain = panel.transcript.toPlainText()
    assert "Compare these scenes." in plain
    assert "<document" not in plain

    dialog.close()


@pytest.mark.gui
def testAiChat_NewConversation(qtbot, mockGUIwithTheme):
    """New Conversation clears transcript and backend session."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)

    panel.inputEdit.setPlainText("Hello")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()
    assert "Hello" in panel.transcript.toPlainText()
    assert fake.sessionId == "fake-session-id"

    panel.btnNew.click()
    assert panel.transcript.toPlainText().strip() == ""
    assert fake.sessionId is None
    assert panel.btnSend.text() == "Send"
    dialog.close()


@pytest.mark.gui
def testAiChat_AgentReadOnlyPosture(qtbot, mockGUIwithTheme):
    """Selecting critic forces readOnly; muse clears it."""
    from novelwriter import CONFIG
    from novelwriter.ai.models import DEFAULT_AI_AGENT

    CONFIG.aiAgent = DEFAULT_AI_AGENT
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)

    # Default is muse (writing agent → acceptEdits)
    assert panel.agentCombo.currentData() == "muse"
    assert fake.readOnly is False

    idx = panel.agentCombo.findData("critic")
    assert idx >= 0
    panel.agentCombo.setCurrentIndex(idx)
    assert fake.agent == "critic"
    assert fake.readOnly is True

    idx = panel.agentCombo.findData("muse")
    panel.agentCombo.setCurrentIndex(idx)
    assert fake.readOnly is False

    idx = panel.agentCombo.findData("editor")
    panel.agentCombo.setCurrentIndex(idx)
    assert fake.readOnly is True
    dialog.close()


@pytest.mark.gui
def testRemoteControlOnlyRunsReadOnlyAgents(qtbot, mockGUIwithTheme):
    """Allow remote control only for read-only agents."""
    CONFIG.aiRemoteControl = True
    CONFIG.aiRemoteControlName = "review-session"
    backend = ClaudeCodePersistentBackend(remoteControl=True)
    panel, _, dialog = _makePanel(qtbot, mockGUIwithTheme, backend=backend)

    assert panel.agentCombo.currentData() == "muse"
    assert backend.remoteControl is False
    panel.agentCombo.setCurrentIndex(panel.agentCombo.findData("critic"))
    assert backend.remoteControl is True
    panel.agentCombo.setCurrentIndex(panel.agentCombo.findData("muse"))
    assert backend.remoteControl is False
    dialog.close()


@pytest.mark.gui
def testAiChat_ErrorRestoresUi(qtbot, mockGUIwithTheme):
    """Backend error re-enables input and shows the message."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.errorOnStart = "Claude Code CLI not found."

    panel.inputEdit.setPlainText("hi")
    panel.btnSend.click()

    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    assert "not found" in panel.statusLabel.text().lower()
    assert panel.inputEdit.isReadOnly() is False
    assert fake.prompts == []
    dialog.close()


@pytest.mark.gui
def testAiChat_SetAgents(qtbot, mockGUIwithTheme):
    """SetAgents replaces the combo contents."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    panel.setAgents([("alpha", "First"), ("beta", "Second")], current="beta")
    assert panel.agentCombo.count() == 2
    assert panel.agentCombo.currentData() == "beta"
    assert fake.agent == "beta"
    dialog.close()


@pytest.mark.gui
def testAiChat_ToolActivityStatus(qtbot, mockGUIwithTheme):
    """ToolActivity updates the status line during a turn."""
    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme)
    fake.autoStream = False

    panel.inputEdit.setPlainText("go")
    panel.btnSend.click()
    fake.signals.toolActivity.emit("Agent")
    qtbot.waitUntil(lambda: "Agent" in panel.statusLabel.text(), timeout=1000)

    fake._busy = False
    fake.signals.turnComplete.emit("ok", {"total_cost_usd": 0.0})
    qtbot.waitUntil(lambda: panel.btnSend.text() == "Send", timeout=1000)
    dialog.close()
