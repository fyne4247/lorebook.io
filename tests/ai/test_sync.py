"""
novelWriter – AI Turn Sync Tests
================================

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
from novelwriter.ai.setup import listManuscriptHandles, setupProjectAi
from novelwriter.ai.claudecode import ClaudeCodePersistentBackend
from novelwriter.ai.sync import (
    AiTurnSync,
    backupManuscriptFiles,
    detectManuscriptTouches,
    diffContentHashes,
    importInboxNotes,
    isKbHandle,
    revertManuscriptFiles,
    snapshotContentHashes,
)
from novelwriter.core.project import NWProject
from novelwriter.enum import nwItemClass

from tests.helpers import C, buildTestProject


##
#  Pure helpers
##


class TestContentDiff:
    def test_snapshot_and_diff(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "aaa.nwd").write_text("one", encoding="utf-8")
        (content / "bbb.nwd").write_text("two", encoding="utf-8")
        before = snapshotContentHashes(tmp_path)
        assert set(before) == {"aaa", "bbb"}

        (content / "aaa.nwd").write_text("ONE", encoding="utf-8")
        (content / "ccc.nwd").write_text("new", encoding="utf-8")
        after = snapshotContentHashes(tmp_path)
        changed = diffContentHashes(before, after)
        assert "aaa" in changed
        assert "ccc" in changed
        assert "bbb" not in changed


class TestManuscriptProtection:
    def test_detect_and_revert(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        original = b"%%~name: Scene\n# Scene\n\nOriginal prose.\n"
        (content / "ms1.nwd").write_bytes(original)
        backup = backupManuscriptFiles(tmp_path, ["ms1"])
        assert backup["ms1"] == original

        (content / "ms1.nwd").write_bytes(b"%%~name: Scene\n# Scene\n\nHACKED.\n")
        touched = detectManuscriptTouches(tmp_path, backup)
        assert touched == ["ms1"]

        reverted = revertManuscriptFiles(tmp_path, backup, touched)
        assert reverted == ["ms1"]
        assert (content / "ms1.nwd").read_bytes() == original


##
#  Inbox import
##


@pytest.mark.core
def testImportInboxNotes(projPath, mockGUI, mockRnd):
    project = NWProject()
    buildTestProject(project, projPath)

    inbox = projPath / "_inbox" / "CHARACTER"
    inbox.mkdir(parents=True)
    (inbox / "Marla Vance.md").write_text(
        "# Marla Vance\n\n@tag: Marla\n\nA new character from the AI.\n",
        encoding="utf-8",
    )

    handles = importInboxNotes(project, projPath)
    assert len(handles) == 1
    h = handles[0]
    assert h in project.tree
    item = project.tree[h]
    assert item is not None
    assert item.itemClass == nwItemClass.CHARACTER
    assert item.itemName == "Marla Vance"
    text = project.storage.getDocumentText(h)
    assert "Marla" in text
    # Staging file removed
    assert not (inbox / "Marla Vance.md").exists()


##
#  Full AiTurnSync with GuiMain
##


@pytest.mark.gui
def testTurnSync_BeginEndKbLock(qtbot, nwGUI, projPath, mockRnd):
    """beginTurn locks open kb note; endTurn unlocks and reloads changes."""
    buildTestProject(nwGUI, projPath)
    setupProjectAi(SHARED.project)

    # Create a character note and open it
    charRoot = SHARED.project.tree.findRoot(nwItemClass.CHARACTER)
    assert charRoot
    cHandle = SHARED.project.newFile("Jane", charRoot)
    assert cHandle
    SHARED.project.writeNewFile(cHandle, 1, False, "Jane is the heroine.\n")
    assert nwGUI.openDocument(cHandle)

    sync = nwGUI.aiSync
    deny = sync.beginTurn(projPath)
    assert sync.active is True
    assert nwGUI.docEditor.isReadOnly() is True
    assert isKbHandle(cHandle) is True
    # Deny list includes manuscript files
    ms = listManuscriptHandles(projPath)
    assert ms
    for h in ms:
        assert f"Edit(content/{h}.nwd)" in deny

    # Simulate agent edit on disk
    content = projPath / "content" / f"{cHandle}.nwd"
    raw = content.read_text(encoding="utf-8")
    content.write_text(raw + "\nAgent added a trait.\n", encoding="utf-8")

    result = sync.endTurn()
    assert sync.active is False
    assert nwGUI.docEditor.isReadOnly() is False
    assert cHandle in result.changedDocs
    # Editor reloaded
    assert "Agent added a trait" in nwGUI.docEditor.getText()


@pytest.mark.gui
def testTurnSync_ManuscriptLockedAndReverts(qtbot, nwGUI, projPath, mockRnd):
    """Manuscript edits are blocked during a turn and disk changes are reverted."""
    buildTestProject(nwGUI, projPath)
    assert nwGUI.openDocument(C.hSceneDoc)

    sync = nwGUI.aiSync
    sync.beginTurn(projPath)
    assert nwGUI.docEditor.isReadOnly() is True

    msPath = projPath / "content" / f"{C.hSceneDoc}.nwd"
    original = msPath.read_bytes()
    nwGUI.docEditor.setCursorPosition(len(nwGUI.docEditor.getText()))
    qtbot.keyClicks(nwGUI.docEditor, "Author edit")
    nwGUI.saveDocument()
    assert msPath.read_bytes() == original

    # Agent "breaks out" and edits manuscript on disk
    msPath.write_bytes(original + b"\nILLEGAL MANUSCRIPT EDIT\n")

    result = sync.endTurn()
    assert C.hSceneDoc in result.manuscriptTouched
    assert C.hSceneDoc in result.manuscriptReverted
    assert msPath.read_bytes() == original


@pytest.mark.gui
def testTurnSync_InboxImportOnEnd(qtbot, nwGUI, projPath, mockRnd):
    """endTurn imports _inbox notes into the tree."""
    buildTestProject(nwGUI, projPath)
    setupProjectAi(SHARED.project)

    sync = nwGUI.aiSync
    sync.beginTurn(projPath)

    inbox = projPath / "_inbox" / "WORLD"
    inbox.mkdir(parents=True)
    (inbox / "Ravenfield.md").write_text(
        "# Ravenfield\n\nA coastal town.\n",
        encoding="utf-8",
    )

    result = sync.endTurn()
    assert len(result.importedDocs) == 1
    h = result.importedDocs[0]
    assert h in SHARED.project.tree
    item = SHARED.project.tree[h]
    assert item is not None
    assert item.itemClass == nwItemClass.WORLD
    assert item.itemName == "Ravenfield"


@pytest.mark.gui
def testTurnSync_PanelWiresBeginEnd(qtbot, nwGUI, projPath, mockRnd):
    """GuiAiChat + FakeBackend runs begin/end sync around a turn."""
    from tests.gui.test_gui_aichat import FakeBackend

    buildTestProject(nwGUI, projPath)
    setupProjectAi(SHARED.project)
    nwGUI.aiChat.openProjectTasks()

    fake = FakeBackend()
    nwGUI.aiChat.setBackend(fake)
    nwGUI.aiChat.setProjectPath(projPath)

    # Open kb note so lock applies
    charRoot = SHARED.project.tree.findRoot(nwItemClass.CHARACTER)
    cHandle = SHARED.project.newFile("Locked Note", charRoot)
    SHARED.project.writeNewFile(cHandle, 1, False, "body\n")
    nwGUI.openDocument(cHandle)

    nwGUI.aiChat.inputEdit.setPlainText("Please update the character.")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        nwGUI.aiChat.btnSend.click()

    # After complete, sync should be inactive and editor unlocked
    assert nwGUI.aiSync.active is False
    assert nwGUI.docEditor.isReadOnly() is False


@pytest.mark.gui
@pytest.mark.parametrize("failure", ["malformed-project", "backup"])
def testAiTurnSafetyPreparationFailureAborts(failure, qtbot, monkeypatch, nwGUI, projPath, mockRnd):
    """A failed safety snapshot never starts a writer or leaves sync active."""
    from novelwriter.ai import sync as aiSync
    from tests.gui.test_gui_aichat import FakeBackend

    buildTestProject(nwGUI, projPath)
    assert nwGUI.openDocument(C.hSceneDoc)
    if failure == "malformed-project":
        (projPath / "nwProject.nwx").write_text("<broken", encoding="utf-8")
    else:
        monkeypatch.setattr(
            aiSync,
            "backupManuscriptFiles",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("backup failed")),
        )

    backend = FakeBackend()
    nwGUI.aiChat.setBackend(backend)
    nwGUI.aiChat.setProjectPath(projPath)
    nwGUI.aiChat.setPreTurnHook(lambda: None)
    nwGUI.aiChat.inputEdit.setPlainText("Update a note")
    nwGUI.aiChat.btnSend.click()

    assert backend.prompts == []
    assert nwGUI.aiSync.active is False
    assert nwGUI.docEditor.isReadOnly() is False
    assert "safely prepare" in nwGUI.aiChat.statusLabel.text().lower()


@pytest.mark.gui
def testProjectCloseStopsPersistentAiBeforeSave(qtbot, monkeypatch, nwGUI, projPath, mockRnd):
    """Close ends persistent AI sync and restores manuscript before project save."""
    buildTestProject(nwGUI, projPath)
    assert nwGUI.openDocument(C.hSceneDoc)
    sync = nwGUI.aiSync
    sync.beginTurn(projPath)
    assert nwGUI.docEditor.isReadOnly() is True

    msPath = projPath / "content" / f"{C.hSceneDoc}.nwd"
    original = msPath.read_bytes()
    msPath.write_bytes(original + b"\nAI write during turn\n")

    backend = ClaudeCodePersistentBackend()
    backend._busy = True
    stopped: list[bool] = []
    monkeypatch.setattr(backend, "_teardownProcess", lambda: stopped.append(True))
    nwGUI.aiChat.setBackend(backend)
    oldSaveProject = nwGUI.saveProject

    def saveProject(autoSave: bool = False) -> bool:
        assert stopped == [True]
        assert sync.active is False
        assert nwGUI.docEditor.isReadOnly() is False
        assert msPath.read_bytes() == original
        return oldSaveProject(autoSave)

    monkeypatch.setattr(nwGUI, "saveProject", saveProject)
    CONFIG.backupOnClose = False
    assert nwGUI.closeProject(isYes=True) is True
    assert not SHARED.hasProject
