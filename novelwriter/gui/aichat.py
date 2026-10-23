"""
novelWriter – GUI AI Chat Panel
===============================

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

import contextlib
import logging
import re
import time

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from novelwriter import CONFIG, SHARED
from novelwriter.ai.agents import isProjectAiReady, scanProjectAgents
from novelwriter.ai.backend import (
    AiBackend,
    UsageSummary,
    formatTokenCount,
    isReadOnlyAgent,
    summarizeTurnUsage,
)
from novelwriter.ai.chatlog import AiChatLog, chatLogDir
from novelwriter.ai.claudecode import isClaudeAvailable, missingBinaryMessage
from novelwriter.ai.index import buildExpandBlocks, parseExpandRequests
from novelwriter.ai.models import (
    AI_EFFORT_CHOICES,
    AI_MODEL_CHOICES,
    DEFAULT_AI_AGENT,
    DEFAULT_AI_EFFORT,
    DEFAULT_AI_MODEL,
)
from novelwriter.common import formatFileFilter
from novelwriter.extensions.modified import NComboBox, NIconToolButton

if TYPE_CHECKING:
    from novelwriter.ai.sync import AiTurnSync

logger = logging.getLogger(__name__)

# Fallback agent list until the project has .claude/agents/ installed.
# muse first so a missing CONFIG selection still lands on a sensible default.
_DEFAULT_AGENTS: tuple[tuple[str, str], ...] = (
    ("muse", "Editorial lead / orchestrator"),
    ("critic", "Prose and craft critique"),
    ("editor", "Line and structural editing notes"),
    ("reader-sim", "Simulated reader reaction"),
    ("character-sim", "In-character perspective"),
    ("continuity-checker", "Continuity and canon check"),
    ("brainstormer", "Ideation and brainstorming"),
    ("outliner", "Outline and structure"),
    ("chronicler", "Timeline and chronicle notes"),
    ("style-creator", "Style samples and voice"),
)

# Selection provider: (text, label, kind, display_chars).
# kind in {"selection", "document", "documents", "empty"}.
# display_chars is the body size for the UI (may exclude XML wrappers).
SelectionProvider = Callable[[], tuple[str, str, str, int]]
# Optional hook run immediately before each backend turn (e.g. save-on-send).
PreTurnHook = Callable[[], None]


def _shortModelName(modelId: str) -> str:
    """Human-friendly short label for a full Claude model id."""
    mid = (modelId or "").strip()
    if not mid:
        return "—"
    # claude-sonnet-4-20250514 → sonnet-4
    # claude-haiku-4-5-20251001 → haiku-4-5
    lower = mid.lower().removeprefix("claude-")
    # Drop trailing date-like suffix -YYYYMMDD
    lower = re.sub(r"-\d{8}$", "", lower)
    return lower or mid


class GuiAiChat(QWidget):
    """GUI: Claude AI chat sidebar panel.

    Talks only to an :class:`AiBackend` via its signal hub. Does not own
    process details — Claude Code, FakeBackend, or a future Anthropic
    backend all look the same from here.

    Layout (top → bottom):
      header     agent combo + New Conversation
      transcript QTextBrowser (stream plain text; re-render markdown on complete)
      context    "Include selection" checkbox + live char count
      input      QPlainTextEdit + Send/Stop (Ctrl+Return)
      status     busy / tool activity / cost / error
    """

    def __init__(self, parent: QWidget, backend: AiBackend | None = None) -> None:
        super().__init__(parent=parent)

        logger.debug("Create: GuiAiChat")

        self._backend: AiBackend | None = None
        self._selectionProvider: SelectionProvider | None = None
        self._preTurnHook: PreTurnHook | None = None
        self._turnSync: AiTurnSync | None = None
        self._messages: list[tuple[str, str]] = []  # (role, text) role in {user, assistant}
        self._streamBuffer = ""
        self._streaming = False
        self._streamStatus = ""  # inline "Thinking…" / "Using X…" indicator
        self._lastStreamRender = 0.0  # monotonic ts for stream re-render throttle
        self._streamRenderPending = False  # a trailing stream render is queued
        self._projectPath: Path | None = None
        self._lastCostUsd: float | None = None
        self._lastUsage: UsageSummary | None = None
        self._sessionInputTokens = 0
        self._sessionOutputTokens = 0
        self._sessionCostUsd = 0.0
        self._lastResolvedModel = ""
        self._pendingUserText = ""  # last user message awaiting assistant reply
        self._chatLog = AiChatLog()

        iSz = SHARED.theme.baseIconSize

        # Header
        self.viewLabel = QLabel(self.tr("AI Assistant"), self)
        self.viewLabel.setFont(SHARED.theme.guiFontB)
        self.viewLabel.setContentsMargins(4, 4, 0, 2)

        self.agentCombo = NComboBox(self)
        self.agentCombo.setMinimumWidth(100)
        self.agentCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.agentCombo.setToolTip(self.tr("Agent"))
        self._populateDefaultAgents()
        self.agentCombo.currentIndexChanged.connect(self._onAgentChanged)

        self.modelCombo = NComboBox(self)
        self.modelCombo.setMinimumWidth(100)
        self.modelCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.modelCombo.setToolTip(
            self.tr(
                "Model override for Claude Code. 'Agent default' leaves --model unset so the agent's frontmatter wins."
            )
        )

        self.modelIndicator = QLabel(self.tr("Model: —"), self)
        self.modelIndicator.setStyleSheet("color: gray;")
        self.modelIndicator.setToolTip(self.tr("Concrete model id reported by Claude Code for the last turn."))
        self.modelIndicator.setWordWrap(True)

        self.effortCombo = NComboBox(self)
        self.effortCombo.setMinimumWidth(80)
        self.effortCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.effortCombo.setToolTip(self.tr("Claude Code effort level (--effort). 'Default' leaves the flag unset."))

        self.effortIndicator = QLabel(self.tr("Effort: —"), self)
        self.effortIndicator.setStyleSheet("color: gray;")
        self.effortIndicator.setToolTip(self.tr("Effort level that will be passed on the next send."))

        self.tokenIndicator = QLabel(self.tr("Tokens: —"), self)
        self.tokenIndicator.setStyleSheet("color: gray;")
        self.tokenIndicator.setToolTip(
            self.tr(
                "Context and token usage from the last Claude Code turn. "
                "Auto-compact is handled automatically by Claude Code when "
                "the session approaches the context window limit."
            )
        )
        self.tokenIndicator.setWordWrap(True)

        self._populateModels()
        self.modelCombo.currentIndexChanged.connect(self._onModelChanged)
        self._populateEfforts()
        self.effortCombo.currentIndexChanged.connect(self._onEffortChanged)
        self._refreshTokenIndicator()

        self.btnExport = NIconToolButton(self, iSz)
        self.btnExport.setToolTip(self.tr("Export conversation…"))
        self.btnExport.clicked.connect(self._onExportConversation)

        self.btnNew = NIconToolButton(self, iSz)
        self.btnNew.setToolTip(self.tr("New Conversation"))
        self.btnNew.clicked.connect(self._onNewConversation)

        # Transcript
        self.transcript = QTextBrowser(self)
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setOpenLinks(True)
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(self.tr("Conversation will appear here…"))
        # Light code-friendly stylesheet for GitHub-dialect markdown output.
        document = self.transcript.document()
        if document is not None:
            document.setDefaultStyleSheet(
                "pre, code { font-family: monospace; }"
                "pre { white-space: pre-wrap; }"
                "h1, h2, h3 { margin-top: 0.6em; margin-bottom: 0.3em; }"
                "p { margin-top: 0.3em; margin-bottom: 0.3em; }"
                "hr { margin: 0.8em 0; border: none; border-top: 1px solid #888888; }"
            )

        # Context row
        self.includeSelection = QCheckBox(self.tr("Include selection"), self)
        self.includeSelection.setChecked(True)
        self.includeSelection.setToolTip(
            self.tr(
                "Attach context to the next message, in order of priority:\n"
                "1) text highlighted in the editor\n"
                "2) files multi-selected in the project tree\n"
                "3) the single file selected in the tree, or the whole open document"
            )
        )
        self.selectionInfo = QLabel("", self)
        self.selectionInfo.setStyleSheet("color: gray;")

        # Input
        self.inputEdit = QPlainTextEdit(self)
        self.inputEdit.setPlaceholderText(self.tr("Ask the agent… (Ctrl+Return to send)"))
        self.inputEdit.setFixedHeight(90)
        self.inputEdit.setTabChangesFocus(True)

        self.btnSend = QPushButton(self.tr("Send"), self)
        self.btnSend.setDefault(True)
        self.btnSend.clicked.connect(self._onSendOrStop)

        # Status
        self.statusLabel = QLabel(self.tr("Ready"), self)
        self.statusLabel.setWordWrap(True)
        self.statusLabel.setContentsMargins(4, 0, 4, 2)

        # Shortcuts
        self._scSend = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._scSend.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._scSend.activated.connect(self._onSendOrStop)
        self._scSendEnter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        self._scSendEnter.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._scSendEnter.activated.connect(self._onSendOrStop)

        # Assemble
        self.headerBox = QHBoxLayout()
        self.headerBox.addWidget(self.viewLabel, 0)
        self.headerBox.addWidget(self.agentCombo, 1)
        self.headerBox.addWidget(self.modelCombo, 1)
        self.headerBox.addWidget(self.effortCombo, 1)
        self.headerBox.addWidget(self.btnExport, 0)
        self.headerBox.addWidget(self.btnNew, 0)
        self.headerBox.setContentsMargins(0, 0, 0, 0)
        self.headerBox.setSpacing(4)

        self.modelRow = QHBoxLayout()
        self.modelRow.addWidget(self.modelIndicator, 1)
        self.modelRow.addWidget(self.effortIndicator, 0)
        self.modelRow.addWidget(self.tokenIndicator, 0)
        self.modelRow.setContentsMargins(4, 0, 4, 0)
        self.modelRow.setSpacing(8)

        self.contextBox = QHBoxLayout()
        self.contextBox.addWidget(self.includeSelection, 0)
        self.contextBox.addWidget(self.selectionInfo, 1)
        self.contextBox.setContentsMargins(4, 0, 4, 0)

        self.inputBox = QHBoxLayout()
        self.inputBox.addWidget(self.inputEdit, 1)
        self.inputBox.addWidget(self.btnSend, 0, Qt.AlignmentFlag.AlignBottom)
        self.inputBox.setContentsMargins(0, 0, 0, 0)
        self.inputBox.setSpacing(4)

        self.outerBox = QVBoxLayout()
        self.outerBox.addLayout(self.headerBox, 0)
        self.outerBox.addLayout(self.modelRow, 0)
        self.outerBox.addWidget(self.transcript, 1)
        self.outerBox.addLayout(self.contextBox, 0)
        self.outerBox.addLayout(self.inputBox, 0)
        self.outerBox.addWidget(self.statusLabel, 0)
        self.outerBox.setContentsMargins(0, 0, 0, 0)
        self.outerBox.setSpacing(4)

        self.setLayout(self.outerBox)
        self.setMinimumWidth(240)
        self.updateTheme()

        if backend is not None:
            self.setBackend(backend)

        logger.debug("Ready: GuiAiChat")

    ##
    #  Properties
    ##

    @property
    def backend(self) -> AiBackend | None:
        """The active AI backend, if any."""
        return self._backend

    @property
    def isBusy(self) -> bool:
        """True while a turn is in flight."""
        return bool(self._backend and self._backend.busy) or self._streaming

    ##
    #  Public Methods
    ##

    def updateTheme(self) -> None:
        """Update theme-dependent icons and styles."""
        logger.debug("Theme Update: GuiAiChat")
        try:
            self.btnNew.setThemeIcon("btn_new", "action")
            # Reuse browse/save-style glyph for export if available.
            try:
                self.btnExport.setThemeIcon("btn_save", "action")
            except Exception:
                self.btnExport.setThemeIcon("browse", "action")
        except Exception:
            # Theme may not be fully initialised in isolated unit tests.
            logger.debug("Could not set AI panel icons", exc_info=True)

    def setBackend(self, backend: AiBackend) -> None:
        """Attach (or replace) the AI backend and wire its signals."""
        if self._backend is not None:
            self._disconnectBackend(self._backend)
        self._backend = backend
        self._connectBackend(backend)
        if self._projectPath is not None:
            backend.setProjectPath(self._projectPath)
        self._applyAgentFromCombo()
        self._applyModelFromCombo()
        self._applyEffortFromCombo()
        self._applyConfigSettings()
        logger.debug("AI backend attached: %s", type(backend).__name__)

    def setSelectionProvider(self, provider: SelectionProvider | None) -> None:
        """Set callback returning ``(text, label, kind, display_chars)``."""
        self._selectionProvider = provider
        self.refreshSelectionInfo()

    def setPreTurnHook(self, hook: PreTurnHook | None) -> None:
        """Set a callback invoked immediately before each backend turn.

        Used for save-on-send (flush editor + project) so agents read disk
        state that matches the UI.
        """
        self._preTurnHook = hook

    def setTurnSync(self, sync: AiTurnSync | None) -> None:
        """Attach the turn-lifecycle controller (lock, inbox, manuscript diff)."""
        self._turnSync = sync

    @property
    def lastCostUsd(self) -> float | None:
        """Cost of the most recently completed turn, if reported."""
        return self._lastCostUsd

    @property
    def lastUsage(self) -> UsageSummary | None:
        """Token usage from the most recently completed turn, if any."""
        return self._lastUsage

    @property
    def messageCount(self) -> int:
        """Number of completed user/assistant messages in the transcript."""
        return len(self._messages)

    def setProjectPath(self, path: Path | str | None) -> None:
        """Set project cwd for the backend (open novelWriter project root)."""
        self._projectPath = Path(path) if path else None
        if self._backend is not None:
            self._backend.setProjectPath(self._projectPath)
        self._chatLog.setProjectPath(self._projectPath)

    def setAgents(self, agents: list[tuple[str, str]], current: str = "") -> None:
        """Populate the agent combo from ``(name, description)`` pairs.

        If ``current`` is set and matches a name, that entry is selected.
        Otherwise falls back to CONFIG / muse.
        """
        prev = current or (self.agentCombo.currentData() or "") or CONFIG.aiAgent or DEFAULT_AI_AGENT
        self.agentCombo.blockSignals(True)
        self.agentCombo.clear()
        if not agents:
            self._populateDefaultAgents()
            self.agentCombo.blockSignals(False)
            self._applyAgentFromCombo()
            return
        for name, desc in agents:
            label = name if not desc else f"{name} — {desc}"
            # Keep the combo readable: truncate long folded descriptions.
            if len(label) > 60:
                label = label[:57] + "…"
            self.agentCombo.addItem(label, name)
            idx = self.agentCombo.count() - 1
            if desc:
                self.agentCombo.setItemData(idx, desc, Qt.ItemDataRole.ToolTipRole)
        # Restore selection (CONFIG / muse preferred)
        idx = self.agentCombo.findData(prev)
        if idx < 0:
            idx = self.agentCombo.findData(DEFAULT_AI_AGENT)
        self.agentCombo.setCurrentIndex(max(0, idx))
        self.agentCombo.blockSignals(False)
        self._applyAgentFromCombo()

    def refreshSelectionInfo(self, *_args: object) -> None:
        """Update the context-row character count from the selection provider.

        Extra ``*_args`` let this slot connect to signals that pass a handle
        or other payload (e.g. itemHandleChanged).
        """
        if self._selectionProvider is None:
            self.selectionInfo.setText("")
            return
        try:
            result = self._selectionProvider()
        except Exception:
            logger.debug("Selection provider failed", exc_info=True)
            self.selectionInfo.setText("")
            return
        # Support legacy (text, title) and current (text, label, kind, chars).
        kind = "document"
        if isinstance(result, tuple) and len(result) >= 4:
            text, label, kind, displayChars = result[0], result[1], result[2], int(result[3])
        elif isinstance(result, tuple) and len(result) >= 2:
            text, label = result[0], result[1]
            displayChars = len(text or "")
            if (text or "").lstrip().startswith("<document"):
                kind = "documents" if (text or "").count("<document") > 1 else "document"
        else:
            self.selectionInfo.setText("")
            return
        text = text or ""
        n = displayChars if displayChars >= 0 else len(text)
        if n == 0 or kind == "empty" or not text.strip():
            self.selectionInfo.setText(self.tr("No selection"))
            return
        src = f" · {label}" if label else ""
        if kind == "selection":
            self.selectionInfo.setText(self.tr("{0} chars selected{1}").format(f"{n:,}", src))
        elif kind == "documents":
            self.selectionInfo.setText(self.tr("{0} chars{1}").format(f"{n:,}", src))
        else:
            self.selectionInfo.setText(self.tr("{0} chars{1}").format(f"{n:,}", src))

    def clearConversation(self) -> None:
        """Clear the transcript and start a new backend session."""
        if self._backend and self._backend.busy:
            self._backend.cancel()
        if self._turnSync and self._turnSync.active:
            self._finishTurnSync(cancelled=True)
        if self._backend:
            self._backend.newConversation()
        self._messages.clear()
        self._streamBuffer = ""
        self._streaming = False
        self._pendingUserText = ""
        self._lastResolvedModel = ""
        self._resetSessionUsage()
        self.transcript.clear()
        agent = str(self.agentCombo.currentData() or "")
        self._chatLog.newSession(agent=agent)
        self._refreshModelIndicator(pending=True)
        self._refreshTokenIndicator()
        self._setBusyUi(False)
        self._setStatus(self.tr("New conversation"))

    def openProjectTasks(self) -> None:
        """Load agents and project path when a project is opened."""
        projectPath: Path | None = None
        if SHARED.hasProject and SHARED.project.storage.isOpen():
            projectPath = SHARED.project.storage.runtimePath or SHARED.project.storage.storagePath
        if projectPath is not None:
            projectPath = Path(projectPath)
        self.setProjectPath(projectPath)
        self._loadAgentsFromProject()
        self._applyConfigSettings()
        self.refreshSelectionInfo()
        agent = str(self.agentCombo.currentData() or CONFIG.aiAgent or "agent")
        self._chatLog.newSession(agent=agent)
        if projectPath and not isProjectAiReady(projectPath):
            self._setStatus(self.tr("AI not set up for this project. Use Tools → Set up AI for Project."))
        elif projectPath and not isClaudeAvailable(CONFIG.aiClaudeBin or None):
            self._setStatus(missingBinaryMessage(), error=True)
        elif projectPath:
            self._setStatus(self.tr("Ready"))
        else:
            self._setStatus(self.tr("No project open"))

    def closeProjectTasks(self) -> None:
        """Reset panel state when the project is closed."""
        if self._backend and self._backend.busy:
            self._backend.cancel()
        if self._backend:
            self._backend.newConversation()
        # Persistent backends suppress their teardown error callback. Stop the
        # child process first, then run the file backstop while project storage
        # is still open so no late write can race the restore.
        if self._turnSync and self._turnSync.active:
            self._finishTurnSync(cancelled=True)
        self._messages.clear()
        self._streamBuffer = ""
        self._streaming = False
        self._pendingUserText = ""
        self.transcript.clear()
        self._chatLog.close()
        self.setProjectPath(None)
        self._populateDefaultAgents()
        self._setBusyUi(False)
        self._setStatus(self.tr("No project open"))
        # Remember last agent selection
        if name := (self.agentCombo.currentData() or ""):
            CONFIG.aiAgent = str(name)

    def _loadAgentsFromProject(self) -> None:
        """Populate the agent combo from the project's .claude/agents/."""
        agents = scanProjectAgents(self._projectPath)
        preferred = CONFIG.aiAgent or DEFAULT_AI_AGENT
        if agents:
            pairs = [(a.name, a.description) for a in agents]
            self.setAgents(pairs, current=preferred)
        else:
            self._populateDefaultAgents()
        self._applyAgentFromCombo()

    def _applyConfigSettings(self) -> None:
        """Push CONFIG model/effort/binary into the backend."""
        if self._backend is None:
            return
        # Panel dropdowns are source of truth when present.
        if hasattr(self, "modelCombo"):
            model = str(self.modelCombo.currentData() or "")
        else:
            model = CONFIG.aiModel or ""
        self._backend.setModel(model)

        if hasattr(self, "effortCombo"):
            effort = str(self.effortCombo.currentData() or "")
        else:
            effort = CONFIG.aiEffort or ""
        self._backend.setEffort(effort)

        if hasattr(self._backend, "setBinary"):
            self._backend.setBinary(CONFIG.aiClaudeBin or None)
        self._refreshModelIndicator(pending=True)
        self._refreshEffortIndicator()

    def _runPreTurnHook(self) -> None:
        """Invoke the optional save-on-send hook."""
        if self._preTurnHook is None:
            return
        try:
            self._preTurnHook()
        except Exception:
            logger.exception("AI pre-turn hook failed")

    def _prepareBackendForTurn(self) -> bool:
        """Begin turn sync (snapshots, kb lock, INDEX) and set deny rules."""
        if self._backend is None or self._projectPath is None:
            return False

        try:
            if self._turnSync is not None:
                deny = self._turnSync.beginTurn(self._projectPath)
            else:
                # Fallback without sync controller (tests).
                from novelwriter.ai.backend import buildDisallowedTools
                from novelwriter.ai.setup import listManuscriptHandles, writeHandleIndex

                writeHandleIndex(self._projectPath)
                deny = buildDisallowedTools(listManuscriptHandles(self._projectPath))
        except Exception:
            logger.exception("AI turn safety preparation failed")
            if self._turnSync is not None and self._turnSync.active:
                self._turnSync.cancelTurn()
            self._setStatus(
                self.tr("Could not safely prepare the AI turn. Check the project files and try again."),
                error=True,
            )
            return False

        # Writing agents get explicit deny rules; read-only uses dontAsk only.
        if not self._backend.readOnly and not isReadOnlyAgent(self._backend.agent):
            self._backend.setDisallowedTools(deny)
        else:
            self._backend.setDisallowedTools([])
        return True

    def _finishTurnSync(self, *, cancelled: bool = False) -> None:
        """Run endTurn: inbox import, reload, manuscript backstop, unlock."""
        if self._turnSync is None or not self._turnSync.active:
            return
        try:
            result = self._turnSync.cancelTurn() if cancelled else self._turnSync.endTurn()
        except Exception:
            logger.exception("AI turn sync endTurn failed")
            with contextlib.suppress(Exception):
                self._turnSync.unlockEditor()
            return

        if result.manuscriptTouched:
            names = ", ".join(result.manuscriptTouched)
            from novelwriter import SHARED as _SHARED

            _SHARED.warn(
                self.tr("Manuscript protection triggered."),
                info=self.tr("The AI attempted to modify manuscript file(s) ({0}). Changes were reverted.").format(
                    names
                ),
            )
            self._setStatus(
                self.tr("Manuscript touch blocked — files reverted."),
                error=True,
            )
        elif result.importedDocs or result.changedDocs:
            parts = []
            if result.importedDocs:
                parts.append(self.tr("{0} new").format(len(result.importedDocs)))
            if result.changedDocs:
                parts.append(self.tr("{0} updated").format(len(result.changedDocs)))
            self._setStatus(self.tr("Synced: {0}").format(", ".join(parts)))

    ##
    #  Private: Backend wiring
    ##

    def _connectBackend(self, backend: AiBackend) -> None:
        s = backend.signals
        s.sessionStarted.connect(self._onSessionStarted)
        s.modelResolved.connect(self._onModelResolved)
        s.chunkReceived.connect(self._onChunkReceived)
        s.toolActivity.connect(self._onToolActivity)
        s.turnComplete.connect(self._onTurnComplete)
        s.errorOccurred.connect(self._onErrorOccurred)

    def _disconnectBackend(self, backend: AiBackend) -> None:
        s = backend.signals
        for signal, slot in (
            (s.sessionStarted, self._onSessionStarted),
            (s.modelResolved, self._onModelResolved),
            (s.chunkReceived, self._onChunkReceived),
            (s.toolActivity, self._onToolActivity),
            (s.turnComplete, self._onTurnComplete),
            (s.errorOccurred, self._onErrorOccurred),
        ):
            with contextlib.suppress(TypeError):
                signal.disconnect(slot)

    ##
    #  Private: UI slots
    ##

    @pyqtSlot()
    def _onSendOrStop(self) -> None:
        """Send the input when idle; cancel when a turn is busy."""
        if self.isBusy:
            self._cancelTurn()
        else:
            self._sendTurn()

    def _sendTurn(self) -> None:
        """Validate input, inject selection, start a backend turn."""
        if self._backend is None:
            self._setStatus(self.tr("No AI backend configured."), error=True)
            return

        if not self._projectPath or not Path(self._projectPath).is_dir():
            self._setStatus(
                self.tr("Open a project before chatting with the AI assistant."),
                error=True,
            )
            return

        userText = self.inputEdit.toPlainText().strip()
        if not userText:
            self._setStatus(self.tr("Enter a message first."), error=True)
            return

        # Save-on-send + index/deny prep so the agent sees current disk state.
        self._runPreTurnHook()
        if not self._prepareBackendForTurn():
            return

        prompt = self._buildPrompt(userText)
        self._applyAgentFromCombo()
        self._applyConfigSettings()

        # Record the visible user message (without the selection wrapper) and
        # show it immediately; streaming assistant text follows.
        self._messages.append(("user", userText))
        self._pendingUserText = userText
        self._streamBuffer = ""
        self._streaming = True
        self._streamStatus = self.tr("Thinking…")
        self._lastStreamRender = 0.0
        self._lastCostUsd = None
        # Render immediately with a distinct Assistant block so the user's turn
        # and the (still-empty) reply are visually separated from the first frame.
        self._rerenderTranscript(includeStream=True)
        self.inputEdit.clear()
        self._setBusyUi(True)
        self._setStatus(self.tr("Working…"))

        # Auto-save user turn to meta/ai-chat/
        agent = str(self.agentCombo.currentData() or self._backend.agent or "")
        sid = self._backend.sessionId or ""
        self._chatLog.appendUser(userText, agent=agent, sessionId=sid)

        logger.info(
            "AI panel send: agent=%s resume=%s chars=%d",
            self._backend.agent,
            bool(self._backend.sessionId),
            len(prompt),
        )
        self._backend.startTurn(prompt)

    def _cancelTurn(self) -> None:
        """Ask the backend to abort the in-flight turn."""
        if self._backend is None:
            return
        self._setStatus(self.tr("Cancelling…"))
        self._backend.cancel()

    @pyqtSlot()
    def _onNewConversation(self) -> None:
        """Clear transcript and session (button handler)."""
        self.clearConversation()

    @pyqtSlot()
    def _onExportConversation(self) -> None:
        """Export the current conversation to a user-chosen markdown file."""
        if not self._messages:
            self._setStatus(self.tr("Nothing to export yet."), error=True)
            return

        agent = str(self.agentCombo.currentData() or "agent")
        defaultName = f"ai-chat_{agent}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md"
        startDir = ""
        if self._projectPath:
            startDir = str(chatLogDir(self._projectPath) / defaultName)
        else:
            startDir = defaultName

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export AI Conversation"),
            startDir,
            filter=formatFileFilter([
                (self.tr("Markdown"), "*.md"),
                (self.tr("All Files"), "*"),
            ]),
        )
        if not path:
            return
        dest = Path(path)
        if not dest.suffix:
            dest = dest.with_suffix(".md")

        sid = self._backend.sessionId if self._backend else ""
        # Prefer copying the auto-log if it has content; else rebuild from memory.
        ok = False
        if self._chatLog.path and self._chatLog.path.is_file():
            ok = self._chatLog.exportMarkdown(dest)
        if not ok:
            ok = self._chatLog.exportMessages(
                dest,
                self._messages,
                agent=agent,
                sessionId=sid or "",
                model=self._lastResolvedModel,
            )
        if ok:
            self._setStatus(self.tr("Exported to {0}").format(dest.name))
            logger.info("AI chat exported to %s", dest)
        else:
            self._setStatus(self.tr("Export failed."), error=True)

    @pyqtSlot(int)
    def _onAgentChanged(self, _index: int) -> None:
        """Push the newly selected agent into the backend and persist."""
        self._applyAgentFromCombo()
        # Persist immediately so the choice survives force-quit / crash.
        try:
            CONFIG.saveConfig()
        except Exception:
            logger.debug("Could not save AI agent preference", exc_info=True)

    @pyqtSlot(int)
    def _onModelChanged(self, _index: int) -> None:
        """Push the selected model override into backend + CONFIG and persist."""
        self._applyModelFromCombo()
        try:
            CONFIG.saveConfig()
        except Exception:
            logger.debug("Could not save AI model preference", exc_info=True)

    @pyqtSlot(int)
    def _onEffortChanged(self, _index: int) -> None:
        """Push the selected effort into backend + CONFIG and persist."""
        self._applyEffortFromCombo()
        try:
            CONFIG.saveConfig()
        except Exception:
            logger.debug("Could not save AI effort preference", exc_info=True)

    ##
    #  Private: Backend signal slots
    ##

    @pyqtSlot(str)
    def _onSessionStarted(self, sessionId: str) -> None:
        """Session id received from the backend."""
        logger.debug("AI session started: %s", sessionId)
        self._setStatus(self.tr("Session {0}…").format(sessionId[:8]))

    @pyqtSlot(str)
    def _onModelResolved(self, modelId: str) -> None:
        """Concrete model id from stream init/result."""
        if modelId:
            self._lastResolvedModel = modelId
            self._refreshModelIndicator(resolved=modelId)
            short = _shortModelName(modelId)
            # Keep status informative without drowning the cost line later.
            if self.isBusy:
                self._setStatus(self.tr("Running {0}…").format(short))

    @pyqtSlot(str)
    def _onChunkReceived(self, chunk: str) -> None:
        """Append a streamed text delta to the transcript."""
        if not chunk:
            return
        if not self._streaming:
            # First chunk without a prior send (shouldn't happen) — start stream mode.
            self._streaming = True
        self._streamBuffer += chunk
        # Text is flowing — drop the "Thinking…/Using X…" indicator.
        self._streamStatus = ""
        # Re-render as a proper (separated) Assistant block. Throttled so long
        # replies don't thrash setMarkdown; a trailing timer guarantees the last
        # delta still paints even if chunks stop before the next window.
        now = time.monotonic()
        if now - self._lastStreamRender >= 0.06:
            self._lastStreamRender = now
            self._rerenderTranscript(includeStream=True)
        elif not self._streamRenderPending:
            self._streamRenderPending = True
            QTimer.singleShot(60, self._flushStreamRender)

    def _flushStreamRender(self) -> None:
        """Trailing render after a throttled chunk, so nothing is left unpainted."""
        self._streamRenderPending = False
        if self._streaming:
            self._lastStreamRender = time.monotonic()
            self._rerenderTranscript(includeStream=True)

    @pyqtSlot(str)
    def _onToolActivity(self, name: str) -> None:
        """Show tool activity in the status line and inline in the transcript."""
        if name:
            self._setStatus(self.tr("Using {0}…").format(name))
            if self._streaming:
                # Inline cue so a tool-running turn doesn't look frozen.
                self._streamStatus = self.tr("Using {0}…").format(name)
                self._lastStreamRender = time.monotonic()
                self._rerenderTranscript(includeStream=True)

    @pyqtSlot(str, dict)
    def _onTurnComplete(self, text: str, meta: dict) -> None:
        """Finalise the assistant message, run turn sync, re-enable input."""
        final = text if text else self._streamBuffer
        self._messages.append(("assistant", final))
        self._streamBuffer = ""
        self._streaming = False
        self._streamStatus = ""
        self._rerenderTranscript(includeStream=False)
        self._setBusyUi(False)

        usage = summarizeTurnUsage(meta if isinstance(meta, dict) else {})
        self._lastUsage = usage if usage.hasData or usage.costUsd is not None else None
        self._accumulateSessionUsage(usage)

        cost = usage.costUsd
        if cost is not None:
            self._lastCostUsd = float(cost)
            status = self.tr("Done · ${0}").format(f"{self._lastCostUsd:.4f}")
        else:
            self._lastCostUsd = None
            status = self.tr("Done")
        if usage.hasData:
            tokenBit = self._formatUsageStatusBit(usage)
            if tokenBit:
                status = f"{status} · {tokenBit}"
        self._setStatus(status)
        self._refreshTokenIndicator()

        # Auto-save assistant turn
        model = str(meta.get("model") or self._lastResolvedModel or "")
        sid = str(meta.get("session_id") or (self._backend.sessionId if self._backend else "") or "")
        agent = str(self.agentCombo.currentData() or (self._backend.agent if self._backend else "") or "")
        self._chatLog.appendAssistant(
            final,
            model=model,
            costUsd=self._lastCostUsd,
            agent=agent,
            sessionId=sid,
            usage=usage if usage.hasData else None,
        )
        self._pendingUserText = ""
        if self._chatLog.path:
            status = f"{status} · {self.tr('saved')}"
            self._setStatus(status)

        # Import inbox, reload changed notes, manuscript backstop, unlock.
        self._finishTurnSync(cancelled=False)

        logger.info(
            "AI turn complete: chars=%d cost=%s ctx=%s/%s session=%s log=%s",
            len(final),
            cost,
            usage.contextUsed,
            usage.contextWindow or "?",
            sid,
            self._chatLog.path,
        )

    @pyqtSlot(str)
    def _onErrorOccurred(self, message: str) -> None:
        """Surface a backend error, end turn sync, restore idle UI."""
        # If we were mid-stream with partial text, keep it as an assistant msg.
        if self._streamBuffer.strip():
            partial = self._streamBuffer + "\n\n*[interrupted]*"
            self._messages.append(("assistant", partial))
            self._streamBuffer = ""
            self._rerenderTranscript(includeStream=False)
            self._chatLog.appendAssistant(
                partial,
                model=self._lastResolvedModel,
                agent=str(self.agentCombo.currentData() or ""),
                sessionId=(self._backend.sessionId if self._backend else "") or "",
            )
        if message:
            self._chatLog.appendNote(message)
        self._pendingUserText = ""
        self._streaming = False
        self._streamStatus = ""
        # Drop any lingering live "Thinking…/Using X…" block from the transcript.
        self._rerenderTranscript(includeStream=False)
        self._setBusyUi(False)
        # Still run end-turn safety (manuscript check + unlock).
        cancelled = "cancel" in (message or "").lower()
        self._finishTurnSync(cancelled=cancelled)
        self._setStatus(message or self.tr("An error occurred."), error=True)
        logger.warning("AI panel error: %s", message)

    ##
    #  Private: helpers
    ##

    def _populateDefaultAgents(self) -> None:
        """Fill the combo with the built-in agent list; select muse/CONFIG."""
        self.agentCombo.blockSignals(True)
        self.agentCombo.clear()
        for name, desc in _DEFAULT_AGENTS:
            self.agentCombo.addItem(f"{name}", name)
            idx = self.agentCombo.count() - 1
            self.agentCombo.setItemData(idx, desc, Qt.ItemDataRole.ToolTipRole)
        preferred = CONFIG.aiAgent or DEFAULT_AI_AGENT
        idx = self.agentCombo.findData(preferred)
        if idx < 0:
            idx = self.agentCombo.findData(DEFAULT_AI_AGENT)
        self.agentCombo.setCurrentIndex(max(0, idx))
        self.agentCombo.blockSignals(False)

    def _populateModels(self) -> None:
        """Fill the model override combo (aligned with Preferences)."""
        self.modelCombo.blockSignals(True)
        self.modelCombo.clear()
        self.modelCombo.addItem(self.tr("Agent default"), "")
        for key, label in AI_MODEL_CHOICES:
            self.modelCombo.addItem(label, key)
        # Restore last preference (default sonnet). Empty string = agent default.
        preferred = CONFIG.aiModel if CONFIG.aiModel is not None else DEFAULT_AI_MODEL
        idx = self.modelCombo.findData(preferred)
        if idx < 0 and preferred:
            # Unknown / future model id — keep it selectable and pass through.
            self.modelCombo.addItem(preferred, preferred)
            idx = self.modelCombo.findData(preferred)
        if idx < 0:
            idx = self.modelCombo.findData(DEFAULT_AI_MODEL)
        self.modelCombo.setCurrentIndex(max(0, idx))
        self.modelCombo.blockSignals(False)
        self._refreshModelIndicator(pending=True)

    def _applyAgentFromCombo(self) -> None:
        """Copy the selected agent into the backend + read-only posture."""
        if self._backend is None:
            return
        name = str(self.agentCombo.currentData() or self.agentCombo.currentText() or "")
        self._backend.setAgent(name)
        # Safety: known critique agents always run under dontAsk.
        readOnly = isReadOnlyAgent(name)
        self._backend.setReadOnly(readOnly)
        if hasattr(self._backend, "setRemoteControl"):
            self._backend.setRemoteControl(
                CONFIG.aiRemoteControl and readOnly,
                CONFIG.aiRemoteControlName,
            )
        if name:
            CONFIG.aiAgent = name

    def _applyModelFromCombo(self) -> None:
        """Copy the selected model override into backend + CONFIG."""
        model = str(self.modelCombo.currentData() or "")
        CONFIG.aiModel = model
        if self._backend is not None:
            self._backend.setModel(model)
        self._refreshModelIndicator(pending=True)

    def _populateEfforts(self) -> None:
        """Fill the effort combo (aligned with Preferences)."""
        self.effortCombo.blockSignals(True)
        self.effortCombo.clear()
        self.effortCombo.addItem(self.tr("Default"), "")
        for key, label in AI_EFFORT_CHOICES:
            self.effortCombo.addItem(label, key)
        preferred = CONFIG.aiEffort if CONFIG.aiEffort is not None else DEFAULT_AI_EFFORT
        idx = self.effortCombo.findData(preferred)
        if idx < 0 and preferred:
            self.effortCombo.addItem(preferred, preferred)
            idx = self.effortCombo.findData(preferred)
        self.effortCombo.setCurrentIndex(max(0, idx))
        self.effortCombo.blockSignals(False)
        self._refreshEffortIndicator()

    def _applyEffortFromCombo(self) -> None:
        """Copy the selected effort into backend + CONFIG."""
        effort = str(self.effortCombo.currentData() or "")
        CONFIG.aiEffort = effort
        if self._backend is not None:
            self._backend.setEffort(effort)
        self._refreshEffortIndicator()

    def _refreshEffortIndicator(self) -> None:
        """Update the 'Effort: …' label under the header."""
        if not hasattr(self, "effortCombo") or not hasattr(self, "effortIndicator"):
            return
        effort = str(self.effortCombo.currentData() or "")
        label = self.effortCombo.currentText() if effort else self.tr("default")
        if effort:
            self.effortIndicator.setText(self.tr("Effort: {0}").format(label))
            self.effortIndicator.setStyleSheet("")
            self.effortIndicator.setToolTip(self.tr("Will pass --effort {0} on the next send.").format(effort))
        else:
            self.effortIndicator.setText(self.tr("Effort: default"))
            self.effortIndicator.setStyleSheet("color: gray;")
            self.effortIndicator.setToolTip(self.tr("No --effort flag — Claude Code uses its default."))

    def _resetSessionUsage(self) -> None:
        """Clear per-session token/cost totals (new conversation)."""
        self._lastUsage = None
        self._lastCostUsd = None
        self._sessionInputTokens = 0
        self._sessionOutputTokens = 0
        self._sessionCostUsd = 0.0

    def _accumulateSessionUsage(self, usage: UsageSummary) -> None:
        """Add one turn's billed input/output into session totals."""
        # Session totals track API-billed tokens (not cache-inflated context).
        self._sessionInputTokens += usage.inputTokens
        self._sessionOutputTokens += usage.outputTokens
        if usage.costUsd is not None:
            self._sessionCostUsd += float(usage.costUsd)

    def _formatUsageStatusBit(self, usage: UsageSummary) -> str:
        """Short status fragment for the last turn's context fill."""
        if usage.contextWindow > 0 and usage.contextUsed > 0:
            pct = usage.contextPercent or 0.0
            return self.tr("{0}/{1} ctx ({2}%)").format(
                formatTokenCount(usage.contextUsed),
                formatTokenCount(usage.contextWindow),
                f"{pct:.0f}",
            )
        if usage.outputTokens or usage.inputTokens:
            return self.tr("{0} in · {1} out").format(
                formatTokenCount(usage.inputTokens),
                formatTokenCount(usage.outputTokens),
            )
        return ""

    def _refreshTokenIndicator(self) -> None:
        """Update the Tokens label from the last turn + session totals."""
        if not hasattr(self, "tokenIndicator"):
            return
        usage = self._lastUsage
        if usage is None or not usage.hasData:
            self.tokenIndicator.setText(self.tr("Tokens: —"))
            self.tokenIndicator.setStyleSheet("color: gray;")
            self.tokenIndicator.setToolTip(
                self.tr(
                    "Token usage appears after each turn. "
                    "Claude Code auto-compacts the session when context is nearly full."
                )
            )
            return

        if usage.contextWindow > 0 and usage.contextUsed > 0:
            pct = usage.contextPercent or 0.0
            self.tokenIndicator.setText(
                self.tr("Ctx: {0}/{1} ({2}%)").format(
                    formatTokenCount(usage.contextUsed),
                    formatTokenCount(usage.contextWindow),
                    f"{pct:.0f}",
                )
            )
            # Warn when context is getting full (auto-compact territory).
            if pct >= 85:
                self.tokenIndicator.setStyleSheet("color: #c44;")
            elif pct >= 70:
                self.tokenIndicator.setStyleSheet("color: #c80;")
            else:
                self.tokenIndicator.setStyleSheet("")
        else:
            self.tokenIndicator.setText(
                self.tr("Tokens: {0} in · {1} out").format(
                    formatTokenCount(usage.inputTokens),
                    formatTokenCount(usage.outputTokens),
                )
            )
            self.tokenIndicator.setStyleSheet("")

        tipParts = [
            self.tr("Last turn: {0} in · {1} out").format(
                f"{usage.inputTokens:,}",
                f"{usage.outputTokens:,}",
            ),
        ]
        if usage.cacheReadTokens or usage.cacheCreateTokens:
            tipParts.append(
                self.tr("Cache: {0} read · {1} write").format(
                    f"{usage.cacheReadTokens:,}",
                    f"{usage.cacheCreateTokens:,}",
                )
            )
        if usage.contextWindow:
            tipParts.append(
                self.tr("Context ≈ {0} / {1}").format(
                    f"{usage.contextUsed:,}",
                    f"{usage.contextWindow:,}",
                )
            )
        tipParts.append(
            self.tr("Session: {0} in · {1} out · ${2}").format(
                f"{self._sessionInputTokens:,}",
                f"{self._sessionOutputTokens:,}",
                f"{self._sessionCostUsd:.4f}",
            )
        )
        tipParts.append(self.tr("Auto-compact is handled by Claude Code near the context limit."))
        self.tokenIndicator.setToolTip("\n".join(tipParts))

    def _refreshModelIndicator(self, pending: bool = False, resolved: str = "") -> None:
        """Update the 'Model: …' label under the header."""
        override = str(self.modelCombo.currentData() or "") if hasattr(self, "modelCombo") else ""
        overrideLabel = self.modelCombo.currentText() if hasattr(self, "modelCombo") else ""
        if resolved:
            short = _shortModelName(resolved)
            if override:
                self.modelIndicator.setText(self.tr("Running: {0}  (override: {1})").format(short, overrideLabel))
            else:
                self.modelIndicator.setText(self.tr("Running: {0}").format(short))
            self.modelIndicator.setToolTip(resolved)
            self.modelIndicator.setStyleSheet("")
        elif pending and override:
            self.modelIndicator.setText(self.tr("Next turn: {0}").format(overrideLabel))
            self.modelIndicator.setStyleSheet("color: gray;")
            self.modelIndicator.setToolTip(self.tr("Will pass --model {0} on the next send.").format(override))
        elif pending:
            self.modelIndicator.setText(self.tr("Next turn: agent default"))
            self.modelIndicator.setStyleSheet("color: gray;")
            self.modelIndicator.setToolTip(
                self.tr("No model override — Claude Code uses the agent's frontmatter model.")
            )
        else:
            self.modelIndicator.setText(self.tr("Model: —"))
            self.modelIndicator.setStyleSheet("color: gray;")

    def _buildPrompt(self, userText: str) -> str:
        """Build the backend prompt: expand blocks + optional selection + user text."""
        parts: list[str] = []

        # Phase 7: Expand [[Name]] → inject full note bodies (token-on-demand).
        if self._projectPath and (names := parseExpandRequests(userText)):
            try:
                blocks = buildExpandBlocks(self._projectPath, names)
                if blocks:
                    parts.append(blocks)
                    logger.info("AI expand inject: %s", ", ".join(names))
            except Exception:
                logger.debug("Expand injection failed", exc_info=True)

        if self.includeSelection.isChecked() and self._selectionProvider is not None:
            try:
                result = self._selectionProvider()
            except Exception:
                logger.debug("Selection provider failed during send", exc_info=True)
                result = ("", "", "empty", 0)
            selText, title, kind = "", "", "empty"
            if isinstance(result, tuple) and len(result) >= 4:
                selText, title, kind = result[0] or "", result[1] or "", result[2] or "empty"
            elif isinstance(result, tuple) and len(result) >= 2:
                selText, title = result[0] or "", result[1] or ""
                kind = (
                    "documents"
                    if selText.lstrip().startswith("<document") and selText.count("<document") > 1
                    else "document"
                    if selText.lstrip().startswith("<document")
                    else "selection"
                )
            if (selText or "").strip() and kind != "empty":
                # Pre-wrapped <document> blocks (tree files / Expand shape).
                if kind in {"document", "documents"} and selText.lstrip().startswith("<document"):
                    parts.append(selText.strip())
                    logger.info("AI document context: %s", title or kind)
                elif kind == "document" and not selText.lstrip().startswith("<document"):
                    # Whole open editor doc — wrap as a named document.
                    safe = (title or "document").replace('"', "'")
                    # Strip our " (whole)" suffix for a cleaner attribute.
                    safe = safe.removesuffix(" (whole)").removesuffix(" (selection)")
                    parts.append(f'<document title="{safe}">\n{selText.rstrip()}\n</document>')
                else:
                    # Editor highlight
                    src = (title or "").removesuffix(" (selection)").removesuffix(" (whole)")
                    parts.append(f'<selection source="{src}">\n{selText}\n</selection>')

        parts.append(userText)
        return "\n\n".join(parts)

    def _setBusyUi(self, busy: bool) -> None:
        """Toggle Send/Stop and disable input while a turn runs."""
        self.inputEdit.setReadOnly(busy)
        self.agentCombo.setEnabled(not busy)
        self.modelCombo.setEnabled(not busy)
        if hasattr(self, "effortCombo"):
            self.effortCombo.setEnabled(not busy)
        self.btnNew.setEnabled(not busy)
        self.btnExport.setEnabled(not busy)
        self.includeSelection.setEnabled(not busy)
        if busy:
            self.btnSend.setText(self.tr("Stop"))
        else:
            self.btnSend.setText(self.tr("Send"))

    def _setStatus(self, text: str, error: bool = False) -> None:
        """Update the status line; red-ish when error is set."""
        self.statusLabel.setText(text)
        if error:
            self.statusLabel.setStyleSheet("color: #c44;")
        else:
            self.statusLabel.setStyleSheet("")

    def _rerenderTranscript(self, includeStream: bool = False) -> None:
        """Rebuild the transcript as markdown from completed messages.

        During streaming we plain-append deltas; calling this with
        ``includeStream=False`` after completion replaces the live text with
        a clean GitHub-dialect markdown rendering (lists, fences, emphasis).
        """
        parts: list[str] = []
        for role, text in self._messages:
            body = (text or "").rstrip()
            if role == "user":
                # Escape leading markdown markers so user text stays literal.
                parts.append(f"### You\n\n{self._escapeUserMarkdown(body)}")
            else:
                parts.append(f"### Assistant\n\n{body}")
        if includeStream and (self._streamBuffer or self._streamStatus):
            body = self._streamBuffer.rstrip()
            seg = "### Assistant\n\n"
            if body:
                seg += body
                if self._streamStatus:
                    # Tool running after some text streamed — trail the cue.
                    seg += f"\n\n*{self._streamStatus}*"
            else:
                # No text yet — show the working indicator so it isn't blank/frozen.
                seg += f"*{self._streamStatus or self.tr('Working…')}*"
            parts.append(seg)

        md = "\n\n---\n\n".join(parts) if parts else ""
        self._setTranscriptMarkdown(md)
        # Scroll to bottom
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    @staticmethod
    def _escapeUserMarkdown(text: str) -> str:
        """Reduce accidental markdown rendering of user messages.

        Assistant replies keep full markdown. User text is lightly escaped so
        `# heading` or `* list` typed by the author does not reformat the bubble.
        """
        if not text:
            return ""
        lines = []
        for line in text.splitlines():
            if line.startswith(("#", ">", "-", "*", "+")) or (
                len(line) > 1 and line[0].isdigit() and line[1:3] in (". ", ") ")
            ):
                lines.append(f"\\{line}")
            else:
                lines.append(line)
        return "\n".join(lines)

    def _setTranscriptMarkdown(self, md: str) -> None:
        """Apply markdown to the transcript, preferring GitHub dialect."""
        if not md:
            self.transcript.clear()
            return
        doc = self.transcript.document()
        if doc is None:
            self.transcript.setMarkdown(md)
            return
        try:
            feature = QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            doc.setMarkdown(md, feature)
        except (TypeError, AttributeError, ValueError):
            self.transcript.setMarkdown(md)
