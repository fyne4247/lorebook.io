"""
novelWriter – AI Panel Wiring Tests
===================================

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

import pytest

from novelwriter import CONFIG, SHARED
from novelwriter.ai.agents import isProjectAiReady, scanProjectAgents
from novelwriter.ai.setup import setupProjectAi

from tests.helpers import buildTestProject


@pytest.mark.gui
def testAiWiring_PanelInMainWindow(qtbot, nwGUI, projPath, mockRnd):
    """AI panel is the third splitMain widget and starts from CONFIG."""
    assert hasattr(nwGUI, "aiChat")
    assert nwGUI.splitMain.count() == 3
    assert nwGUI.splitMain.widget(2) is nwGUI.aiChat

    # Default: hidden
    assert CONFIG.showAiPanel is False
    assert nwGUI.aiChat.isVisible() is False

    # Toggle via slot
    nwGUI.toggleAiPanelVisibility()
    assert CONFIG.showAiPanel is True
    assert nwGUI.aiChat.isVisible() is True
    assert nwGUI.mainMenu.aToggleAiPanel.isChecked() is True

    # Toggle back
    nwGUI.toggleAiPanelVisibility()
    assert CONFIG.showAiPanel is False
    assert nwGUI.aiChat.isVisible() is False


@pytest.mark.gui
def testAiWiring_SidebarAndMenu(qtbot, nwGUI):
    """Sidebar button and menu action exist and share the toggle signal path."""
    assert hasattr(nwGUI.sideBar, "tbAi")
    assert hasattr(nwGUI.sideBar, "toggleAiPanel")
    assert hasattr(nwGUI.mainMenu, "aToggleAiPanel")
    assert hasattr(nwGUI.mainMenu, "aSetupAi")

    # Sidebar click toggles visibility
    was = CONFIG.showAiPanel
    nwGUI.sideBar.tbAi.click()
    assert CONFIG.showAiPanel is (not was)


@pytest.mark.gui
def testAiWiring_OpenProjectLoadsAgents(qtbot, nwGUI, projPath, mockRnd):
    """Opening a project after AI setup populates agents from .claude/agents/."""
    buildTestProject(nwGUI, projPath)
    assert SHARED.hasProject

    # Before setup: not ready
    assert isProjectAiReady(projPath) is False

    result = setupProjectAi(SHARED.project)
    assert result.ok

    nwGUI.aiChat.openProjectTasks()
    agents = scanProjectAgents(projPath)
    assert len(agents) >= 10
    # Combo should list project agents (not just defaults)
    data = [nwGUI.aiChat.agentCombo.itemData(i) for i in range(nwGUI.aiChat.agentCombo.count())]
    assert "critic" in data
    assert "muse" in data

    # Project path set on backend
    assert nwGUI.aiChat.backend is not None
    assert nwGUI.aiChat.backend.projectPath == Path(projPath)

    # Selection provider returns text/label/kind/display_chars
    text, title, kind, n = nwGUI._aiSelectionProvider()
    assert isinstance(text, str)
    assert isinstance(title, str)
    assert kind in {"selection", "document", "documents", "empty"}
    assert isinstance(n, int)


@pytest.mark.gui
def testAiWiring_MultiFileTreeSelection(qtbot, nwGUI, projPath, mockRnd):
    """Multi-selecting FILE items in the project tree injects all as <document> blocks."""
    from PyQt6.QtCore import QItemSelectionModel

    from tests.helpers import C

    buildTestProject(nwGUI, projPath)
    assert SHARED.hasProject

    projTree = nwGUI.projView.projTree
    model = SHARED.project.tree.model
    handles = [C.hChapterDoc, C.hSceneDoc]
    for h in handles:
        assert SHARED.project.tree[h] is not None
        assert SHARED.project.tree[h].isFileType()

    # Write distinct bodies so we can assert injection content
    for i, h in enumerate(handles):
        doc = SHARED.project.storage.getDocument(h)
        assert doc.writeDocument(f"# File {i}\n\nBody of file {i}.\n") is True

    # Select both files in the tree
    sm = projTree.selectionModel()
    assert sm is not None
    sm.clearSelection()
    for h in handles:
        idx = model.indexFromHandle(h)
        assert idx.isValid()
        sm.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    selected = nwGUI.projView.getSelectedHandles()
    assert set(selected) == set(handles)

    text, label, kind, n = nwGUI._aiSelectionProvider()
    assert kind == "documents"
    assert text.lstrip().startswith("<document")
    assert text.count("<document") == 2
    assert "Body of file 0" in text
    assert "Body of file 1" in text
    assert C.hChapterDoc in text
    assert C.hSceneDoc in text
    # Label lists the two document names; display chars exclude XML wrappers
    assert "2 files" in label or "," in label
    assert n > 0
    assert n < len(text)  # body-only count is smaller than wrapped blocks

    # Char count refresh sees multi-file context
    nwGUI.aiChat.refreshSelectionInfo()
    info = nwGUI.aiChat.selectionInfo.text()
    assert any(c.isdigit() for c in info)

    # Editor highlight wins over multi-file tree selection
    assert nwGUI.openDocument(C.hChapterDoc) is True
    nwGUI.docEditor.setText("AAA unique highlight BBB\n\nMore body.")
    cursor = nwGUI.docEditor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(len("AAA unique highlight BBB"), cursor.MoveMode.KeepAnchor)
    nwGUI.docEditor.setTextCursor(cursor)
    assert "AAA unique highlight BBB" in nwGUI.docEditor.getSelectedText()
    # Re-assert multi-select still active in the tree
    sm = projTree.selectionModel()
    sm.clearSelection()
    for h in handles:
        idx = model.indexFromHandle(h)
        sm.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    text2, _label2, kind2, _n2 = nwGUI._aiSelectionProvider()
    assert kind2 == "selection"
    assert "AAA unique highlight BBB" in text2
    assert "<document" not in text2

    # Clearing the highlight returns to multi-file tree context
    cursor = nwGUI.docEditor.textCursor()
    cursor.clearSelection()
    nwGUI.docEditor.setTextCursor(cursor)
    text3, _label3, kind3, _n3 = nwGUI._aiSelectionProvider()
    assert kind3 == "documents"
    assert text3.count("<document") == 2


@pytest.mark.gui
def testAiWiring_ConfigRoundTrip(qtbot, fncPath):
    """AI config keys persist through save/load (including versioned models)."""
    CONFIG.showAiPanel = True
    CONFIG.aiPanelWidth = 420
    CONFIG.aiClaudeBin = "/usr/local/bin/claude"
    CONFIG.aiAgent = "muse"
    CONFIG.aiModel = "claude-sonnet-4-5"
    CONFIG.aiEffort = "high"
    assert CONFIG.saveConfig() is True

    CONFIG.showAiPanel = False
    CONFIG.aiPanelWidth = 100
    CONFIG.aiClaudeBin = ""
    CONFIG.aiAgent = "critic"
    CONFIG.aiModel = ""
    CONFIG.aiEffort = ""

    assert CONFIG.loadConfig() is True
    assert CONFIG.showAiPanel is True
    assert CONFIG.aiPanelWidth == 420
    assert CONFIG.aiClaudeBin == "/usr/local/bin/claude"
    assert CONFIG.aiAgent == "muse"
    assert CONFIG.aiModel == "claude-sonnet-4-5"
    assert CONFIG.aiEffort == "high"
