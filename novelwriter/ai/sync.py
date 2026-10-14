"""
novelWriter – AI Turn Sync Lifecycle
====================================

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

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from novelwriter import SHARED
from novelwriter.ai.backend import buildDisallowedTools
from novelwriter.ai.setup import listManuscriptHandles, writeHandleIndex
from novelwriter.enum import nwItemClass

if TYPE_CHECKING:
    from novelwriter.core.project import NWProject
    from novelwriter.guimain import GuiMain

logger = logging.getLogger(__name__)

# Classes agents may write (kb-like). Novel stays user-editable and denied to agents.
KB_ITEM_CLASSES: frozenset[nwItemClass] = frozenset({
    nwItemClass.CHARACTER,
    nwItemClass.WORLD,
    nwItemClass.TIMELINE,
    nwItemClass.OBJECT,
    nwItemClass.PLOT,
    nwItemClass.ENTITY,
    nwItemClass.CUSTOM,
})

_CLASS_BY_NAME: dict[str, nwItemClass] = {c.name: c for c in nwItemClass}


@dataclass
class AiTurnSyncResult:
    """Outcome of endTurn processing."""

    manuscriptTouched: list[str] = field(default_factory=list)
    manuscriptReverted: list[str] = field(default_factory=list)
    changedDocs: list[str] = field(default_factory=list)
    importedDocs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.manuscriptTouched


class AiTurnSync:
    """Turn-scoped safety + refresh layer for the AI sidebar.

    Lifecycle:
      * ``beginTurn`` — snapshot files, lock the open editor, build deny list
      * during turn — ``onEditorHandleChanged`` re-applies lock when the user
        switches documents
      * ``endTurn`` — manuscript diff (+revert), ``_inbox/`` import, reload
        changed docs, reindex, refresh tree, unlock
    """

    def __init__(self, mainGui: GuiMain) -> None:
        self._mainGui = mainGui
        self._active = False
        self._projectPath: Path | None = None
        # handle -> sha1 of full file bytes
        self._contentHashes: dict[str, str] = {}
        # Manuscript backups for revert (handle -> raw bytes)
        self._manuscriptBackup: dict[str, bytes] = {}
        self._manuscriptHandles: list[str] = []
        self._editorLocked = False

    ##
    #  Properties
    ##

    @property
    def active(self) -> bool:
        """True while an AI turn is in progress."""
        return self._active

    ##
    #  Public API
    ##

    def beginTurn(self, projectPath: Path | str | None = None) -> list[str]:
        """Start turn lifecycle. Returns ``--disallowedTools`` list for writers.

        Call after save-on-send. Idempotent if already active (re-snapshots).
        """
        path = self._resolveProjectPath(projectPath)
        if path is None:
            logger.error("AI sync beginTurn: no project path")
            return buildDisallowedTools()

        try:
            handles = listManuscriptHandles(path)
            contentHashes = snapshotContentHashes(path)
            manuscriptBackup = backupManuscriptFiles(path, handles)
            writeHandleIndex(path)
            self._projectPath = path
            self._manuscriptHandles = handles
            self._contentHashes = contentHashes
            self._manuscriptBackup = manuscriptBackup
            self._active = True
            self.applyEditorLock()
        except Exception:
            self.unlockEditor()
            self._reset()
            raise
        deny = buildDisallowedTools(self._manuscriptHandles)
        logger.info(
            "AI turn begin: path=%s manuscript=%d content=%d",
            path,
            len(self._manuscriptHandles),
            len(self._contentHashes),
        )
        return deny

    def endTurn(self) -> AiTurnSyncResult:
        """Finish turn: safety check, import, reload, unlock."""
        result = AiTurnSyncResult()
        if not self._active:
            self.unlockEditor()
            return result

        path = self._projectPath
        if path is None:
            self._reset()
            return result

        try:
            # 1. Manuscript protection backstop
            touched = detectManuscriptTouches(path, self._manuscriptBackup)
            if touched:
                result.manuscriptTouched = list(touched)
                reverted = revertManuscriptFiles(path, self._manuscriptBackup, touched)
                result.manuscriptReverted = reverted
                logger.warning(
                    "AI turn: manuscript touched and reverted: %s",
                    ", ".join(touched),
                )

            # 2. Import staging notes
            try:
                result.importedDocs = importInboxNotes(SHARED.project, path)
            except Exception as exc:
                logger.exception("AI sync: inbox import failed")
                result.errors.append(f"Inbox import: {exc}")

            # 3. Detect changed / new content files (excluding reverted manuscript)
            after = snapshotContentHashes(path)
            changed = diffContentHashes(self._contentHashes, after)
            # Manuscript handles that we reverted are not "agent updates"
            changed = [h for h in changed if h not in result.manuscriptReverted]
            result.changedDocs = changed

            # 4. Reload + reindex
            try:
                self._reloadAndReindex(changed + result.importedDocs)
            except Exception as exc:
                logger.exception("AI sync: reload/reindex failed")
                result.errors.append(f"Reload: {exc}")

            # 5. Refresh handle index for next turn
            try:
                writeHandleIndex(path)
            except Exception:
                logger.debug("AI sync: INDEX.md refresh failed", exc_info=True)

        finally:
            self.unlockEditor()
            self._reset()

        logger.info(
            "AI turn end: changed=%d imported=%d manuscript_touched=%d",
            len(result.changedDocs),
            len(result.importedDocs),
            len(result.manuscriptTouched),
        )
        return result

    def cancelTurn(self) -> AiTurnSyncResult:
        """End the turn after a cancel (still check manuscript + unlock)."""
        return self.endTurn()

    def onEditorHandleChanged(self, tHandle: str | None) -> None:
        """Re-apply kb lock when the user switches documents mid-turn."""
        if self._active:
            self.applyEditorLock()

    def applyEditorLock(self) -> None:
        """Lock the editor while an AI turn is active."""
        editor = self._mainGui.docEditor
        handle = editor.docHandle
        if self._active and handle:
            if not editor.isReadOnly():
                editor.setReadOnly(True)
                self._editorLocked = True
            if hasattr(editor.docHeader, "setAiLockBanner"):
                editor.docHeader.setAiLockBanner(True)
        else:
            if self._editorLocked and editor.docHandle and editor.isReadOnly():
                editor.setReadOnly(False)
            self._editorLocked = False
            if hasattr(editor.docHeader, "setAiLockBanner"):
                editor.docHeader.setAiLockBanner(False)

    def unlockEditor(self) -> None:
        """Clear AI lock state from the editor."""
        editor = self._mainGui.docEditor
        if self._editorLocked and editor.docHandle is not None and editor.isReadOnly():
            editor.setReadOnly(False)
        self._editorLocked = False
        if hasattr(editor.docHeader, "setAiLockBanner"):
            editor.docHeader.setAiLockBanner(False)

    ##
    #  Internals
    ##

    def _resolveProjectPath(self, projectPath: Path | str | None) -> Path | None:
        if projectPath:
            path = Path(projectPath)
            return path if path.is_dir() else None
        if SHARED.hasProject and SHARED.project.storage.isOpen():
            p = SHARED.project.storage.runtimePath or SHARED.project.storage.storagePath
            if p is not None:
                path = Path(p)
                return path if path.is_dir() else None
        return None

    def _reloadAndReindex(self, handles: list[str]) -> None:
        """Reload open editor/viewer if needed; reindex and refresh tree."""
        if not handles:
            return
        # Unique, valid handles
        uniq = []
        seen: set[str] = set()
        for h in handles:
            if h and h not in seen:
                seen.add(h)
                uniq.append(h)

        project = SHARED.project
        editor = self._mainGui.docEditor
        viewer = self._mainGui.docViewer

        for handle in uniq:
            if handle not in project.tree:
                continue
            text = project.storage.getDocumentText(handle)
            if text is not None:
                project.index.scanText(handle, text, blockSignal=False)

        project.tree.refreshItems(uniq)

        # Reload open editor if its doc was touched
        if editor.docHandle and editor.docHandle in seen:
            cursor = editor.getCursorPosition() if hasattr(editor, "getCursorPosition") else 0
            # loadText clears read-only; re-apply lock after if still active
            wasActive = self._active
            editor.loadText(editor.docHandle)
            if hasattr(editor, "setCursorPosition") and isinstance(cursor, int):
                editor.setCursorPosition(cursor)
            if wasActive:
                self.applyEditorLock()

        if viewer.docHandle and viewer.docHandle in seen:
            viewer.loadText(viewer.docHandle, updateHistory=False)

        # New imports may need a fuller tree refresh
        if any(h not in self._contentHashes for h in uniq):
            try:
                self._mainGui.projView.openProjectTasks()
            except Exception:
                logger.debug("AI sync: projView refresh failed", exc_info=True)

    def _reset(self) -> None:
        self._active = False
        self._projectPath = None
        self._contentHashes = {}
        self._manuscriptBackup = {}
        self._manuscriptHandles = []


# =============================================================================
#  Pure helpers (unit-tested without GuiMain)
# =============================================================================


def isKbHandle(tHandle: str) -> bool:
    """Return True if the handle is a knowledge-base (non-novel) file."""
    item = SHARED.project.tree[tHandle] if SHARED.hasProject else None
    if item is None or not item.isFileType():
        return False
    return item.itemClass in KB_ITEM_CLASSES


def snapshotContentHashes(projectPath: Path) -> dict[str, str]:
    """Return ``handle -> sha1`` for every ``content/*.nwd`` file."""
    content = Path(projectPath) / "content"
    out: dict[str, str] = {}
    if not content.is_dir():
        return out
    for path in content.glob("*.nwd"):
        try:
            out[path.stem] = hashlib.sha1(path.read_bytes()).hexdigest()
        except OSError:
            logger.debug("Could not hash %s", path, exc_info=True)
    return out


def backupManuscriptFiles(projectPath: Path, handles: list[str]) -> dict[str, bytes]:
    """Read raw bytes for each manuscript handle (for revert)."""
    content = Path(projectPath) / "content"
    out: dict[str, bytes] = {}
    for h in handles:
        path = content / f"{h}.nwd"
        if path.is_file():
            try:
                out[h] = path.read_bytes()
            except OSError:
                logger.debug("Could not backup manuscript %s", h, exc_info=True)
    return out


def detectManuscriptTouches(projectPath: Path, backup: dict[str, bytes]) -> list[str]:
    """Return manuscript handles whose on-disk bytes differ from the backup."""
    content = Path(projectPath) / "content"
    touched: list[str] = []
    for h, data in backup.items():
        path = content / f"{h}.nwd"
        try:
            if not path.is_file() or path.read_bytes() != data:
                touched.append(h)
        except OSError:
            touched.append(h)
    return touched


def revertManuscriptFiles(
    projectPath: Path,
    backup: dict[str, bytes],
    handles: list[str],
) -> list[str]:
    """Restore manuscript files from backup. Returns handles successfully reverted."""
    content = Path(projectPath) / "content"
    reverted: list[str] = []
    for h in handles:
        data = backup.get(h)
        if data is None:
            continue
        path = content / f"{h}.nwd"
        try:
            path.write_bytes(data)
            reverted.append(h)
        except OSError:
            logger.error("Failed to revert manuscript %s", h, exc_info=True)
    return reverted


def diffContentHashes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Handles that are new or whose hash changed."""
    changed: list[str] = []
    for h, digest in after.items():
        if before.get(h) != digest:
            changed.append(h)
    return changed


def importInboxNotes(project: NWProject, projectPath: Path) -> list[str]:
    """Import ``_inbox/<Class>/<Title>.md`` into the project tree.

    Returns list of new document handles. Removes imported files and cleans
    empty class folders under ``_inbox/``.
    """
    inbox = Path(projectPath) / "_inbox"
    if not inbox.is_dir():
        return []

    imported: list[str] = []
    for classDir in sorted(inbox.iterdir()):
        if not classDir.is_dir():
            # Stray files at inbox root — leave alone
            continue
        itemClass = _CLASS_BY_NAME.get(classDir.name.upper())
        if itemClass is None or itemClass in (
            nwItemClass.NO_CLASS,
            nwItemClass.NOVEL,
            nwItemClass.TRASH,
            nwItemClass.ARCHIVE,
        ):
            logger.warning("AI inbox: skipping unknown/forbidden class dir %s", classDir.name)
            continue

        root = project.tree.findRoot(itemClass)
        if root is None:
            root = project.newRoot(itemClass)
        if not root:
            continue

        for mdPath in sorted(classDir.glob("*.md")):
            title = mdPath.stem.strip() or "Untitled"
            try:
                body = mdPath.read_text(encoding="utf-8")
            except OSError:
                logger.error("AI inbox: cannot read %s", mdPath, exc_info=True)
                continue

            handle = project.newFile(title, root)
            if not handle:
                logger.error("AI inbox: newFile failed for %s", title)
                continue

            # Prefer writing the agent body as-is; add heading only if empty body.
            addHeading = not body.strip()
            if not project.writeNewFile(handle, 1, False, body if body.strip() else "", addHeading=addHeading):
                # File may already have been created empty — force-write body.
                doc = project.storage.getDocument(handle)
                text = body if body.strip() else f"# {title}\n\n"
                if not text.endswith("\n"):
                    text += "\n"
                doc.writeDocument(text, forceWrite=True)
                project.index.scanText(handle, text)

            imported.append(handle)
            try:
                mdPath.unlink()
            except OSError:
                logger.debug("AI inbox: could not remove %s", mdPath, exc_info=True)
            logger.info("AI inbox: imported %s → %s (%s)", mdPath.name, handle, itemClass.name)

        # Remove empty class dir
        try:
            if classDir.is_dir() and not any(classDir.iterdir()):
                classDir.rmdir()
        except OSError:
            pass

    return imported


def clearInbox(projectPath: Path) -> None:
    """Remove leftover empty structure under ``_inbox/`` (best-effort)."""
    inbox = Path(projectPath) / "_inbox"
    if not inbox.is_dir():
        return
    for child in list(inbox.iterdir()):
        if child.is_dir() and not any(child.iterdir()):
            try:
                child.rmdir()
            except OSError:
                pass
