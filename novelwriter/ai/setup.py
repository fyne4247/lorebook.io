"""
novelWriter – AI Project Setup
==============================

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

import logging
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from novelwriter import CONFIG
from novelwriter.enum import nwItemClass

if TYPE_CHECKING:
    from novelwriter.core.project import NWProject

logger = logging.getLogger(__name__)
_CLAUDE_MARKER = "<!-- novelWriter managed AI instructions sha256:"

# Root classes that map onto the brainstormer kb layout.
KB_ROOT_CLASSES: tuple[nwItemClass, ...] = (
    nwItemClass.CHARACTER,
    nwItemClass.WORLD,
    nwItemClass.TIMELINE,
    nwItemClass.OBJECT,
    nwItemClass.PLOT,
)


@dataclass
class AiSetupResult:
    """Outcome of a Set up AI run."""

    ok: bool = True
    message: str = ""
    agentsInstalled: int = 0
    skillsInstalled: int = 0
    rootsCreated: list[str] = field(default_factory=list)
    claudeMdWritten: bool = False
    indexWritten: bool = False
    errors: list[str] = field(default_factory=list)


def defaultAiAssetsRoot() -> Path:
    """Return the versioned agents+skills bundled with the application."""
    return CONFIG.assetPath("ai") / "claude"


def setupProjectAi(
    project: NWProject,
    sourceRoot: Path | str | None = None,
    *,
    refresh: bool = False,
) -> AiSetupResult:
    """One-time (or refresh) AI setup for an open novelWriter project.

    Steps:
      1. Install ``.claude/agents`` + ``.claude/skills`` from the source tree.
         When ``refresh`` is True, existing files are overwritten and files no
         longer present in the source are pruned (a mirror); otherwise existing
         files are left untouched (first-run install).
      2. Create missing kb-class root folders (CHARACTER, WORLD, …).
      3. Write ``INDEX.md`` handle index and project ``CLAUDE.md``.
      4. Ensure ``_inbox/`` staging directory exists.
    """
    result = AiSetupResult()

    storage = project.storage
    if not storage.isOpen():
        result.ok = False
        result.message = "No project storage is open."
        return result

    # runtimePath is the live project directory (cwd for Claude Code).
    projectPath = storage.runtimePath or storage.storagePath
    if projectPath is None or not Path(projectPath).is_dir():
        result.ok = False
        result.message = "Project path is not available."
        return result
    projectPath = Path(projectPath)

    src = Path(sourceRoot) if sourceRoot else defaultAiAssetsRoot()
    if not src.is_dir():
        result.ok = False
        result.message = f"AI assets not found at {src}"
        result.errors.append(result.message)
        return result

    # 1. Install agents + skills
    try:
        nAgents, nSkills = installClaudeTree(src, projectPath, overwrite=refresh, mirror=refresh)
        result.agentsInstalled = nAgents
        result.skillsInstalled = nSkills
    except OSError as exc:
        result.ok = False
        result.errors.append(str(exc))
        result.message = f"Failed to install .claude/: {exc}"
        return result

    # 2. Kb roots
    try:
        result.rootsCreated = ensureKbRoots(project)
    except Exception as exc:
        logger.error("Failed to create kb roots: %s", exc)
        result.errors.append(str(exc))

    # 3. Index + CLAUDE.md
    try:
        writeHandleIndex(projectPath)
        result.indexWritten = True
    except Exception as exc:
        logger.error("Failed to write INDEX.md: %s", exc)
        result.errors.append(str(exc))

    try:
        writeProjectClaudeMd(projectPath)
        result.claudeMdWritten = True
    except Exception as exc:
        logger.error("Failed to write CLAUDE.md: %s", exc)
        result.errors.append(str(exc))

    # 4. Staging inbox
    try:
        inbox = projectPath / "_inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / ".gitkeep").touch(exist_ok=True)
    except OSError as exc:
        result.errors.append(str(exc))

    if result.errors:
        result.ok = False
        result.message = "AI setup incomplete: " + "; ".join(result.errors)
    else:
        result.ok = True
        parts = [
            f"{result.agentsInstalled} agents",
            f"{result.skillsInstalled} skills",
        ]
        if result.rootsCreated:
            parts.append(f"roots: {', '.join(result.rootsCreated)}")
        result.message = "AI setup complete: " + "; ".join(parts)

    logger.info("AI setup: %s", result.message)
    return result


def installClaudeTree(
    sourceRoot: Path,
    projectPath: Path,
    *,
    overwrite: bool = False,
    mirror: bool = False,
) -> tuple[int, int]:
    """Copy bundled agents and skills while tracking app-owned files.

    Refreshes update and prune unchanged app-managed files. Custom files and
    user-edited bundled files are preserved.
    """
    destRoot = projectPath / ".claude"
    destRoot.mkdir(parents=True, exist_ok=True)
    manifestPath = destRoot / ".novelwriter-assets.json"
    try:
        manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
        previous = manifest.get("files", {}) if isinstance(manifest, dict) else {}
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, json.JSONDecodeError):
        previous = {}

    current: dict[str, str] = {}
    counts = {"agents": 0, "skills": 0}
    for category in counts:
        src = sourceRoot / category
        if not src.is_dir():
            logger.warning("AI asset source missing: %s", src)
            continue
        for source in src.rglob("*"):
            if not source.is_file():
                continue
            rel = f"{category}/{source.relative_to(src).as_posix()}"
            target = destRoot / rel
            oldHash = previous.get(rel)
            if target.exists():
                if not isinstance(oldHash, str) or _fileHash(target) != oldHash:
                    # An untracked or locally edited file belongs to the user.
                    continue
                if not overwrite and not mirror:
                    current[rel] = oldHash
                    counts[category] += 1
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            current[rel] = _fileHash(source)
            counts[category] += 1

    if mirror:
        for rel, oldHash in previous.items():
            if (
                rel in current
                or not isinstance(rel, str)
                or Path(rel).is_absolute()
                or any(part in {"", ".", ".."} for part in Path(rel).parts)
                or not Path(rel).parts
                or Path(rel).parts[0] not in {"agents", "skills"}
                or not isinstance(oldHash, str)
            ):
                continue
            target = destRoot / rel
            if target.is_file() and _fileHash(target) == oldHash:
                target.unlink()
                logger.info("Pruned stale app-managed AI asset: %s", target)
    manifestPath.write_text(
        json.dumps({"version": 1, "files": current}, indent=2) + "\n",
        encoding="utf-8",
    )
    nAgents = counts["agents"]
    nSkills = counts["skills"]
    return nAgents, nSkills


def ensureKbRoots(project: NWProject) -> list[str]:
    """Create missing CHARACTER/WORLD/TIMELINE/OBJECT/PLOT roots.

    Returns the list of class names that were created.
    """
    created: list[str] = []
    for itemClass in KB_ROOT_CLASSES:
        if project.tree.findRoot(itemClass) is None:
            handle = project.newRoot(itemClass)
            if handle:
                created.append(itemClass.name)
                logger.info("Created kb root %s (%s)", itemClass.name, handle)
    return created


def writeHandleIndex(projectPath: Path, *, smart: bool | None = None) -> Path:
    """Write ``INDEX.md`` (smart wiki-link form by default).

    Parses ``nwProject.nwx`` + ``content/*.nwd``. Regenerated on Set up AI
    and each turn. When ``smart`` is None, uses ``CONFIG.aiSmartIndex``.
    """
    from novelwriter import CONFIG
    from novelwriter.ai.index import writeProjectIndex

    if smart is None:
        smart = bool(getattr(CONFIG, "aiSmartIndex", True))
    return writeProjectIndex(projectPath, smart=smart)


def writeProjectClaudeMd(projectPath: Path) -> Path:
    """Write project-level CLAUDE.md with novelWriter-specific agent rules."""
    projectPath = Path(projectPath)
    out = projectPath / "CLAUDE.md"
    if out.exists():
        try:
            with out.open(encoding="utf-8") as handle:
                marker = handle.readline().rstrip("\n")
                previousText = handle.read()
            previousHash = hashlib.sha256(previousText.encode("utf-8")).hexdigest()
            managed = marker == f"{_CLAUDE_MARKER}{previousHash} -->"
        except OSError:
            managed = False
        if not managed:
            logger.warning("Preserving user-owned project instructions: %s", out)
            return out
    body = _CLAUDE_MD_TEMPLATE.strip() + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    text = f"{_CLAUDE_MARKER}{digest} -->\n{body}"
    out.write_text(text, encoding="utf-8")
    return out


def listManuscriptHandles(projectPath: Path | str) -> list[str]:
    """Return handle ids for manuscript (NOVEL-class FILE) documents.

    Used later by the sync layer for per-turn deny rules. Broader than
    class alone: any FILE under NOVEL root (DOCUMENT layout included).
    """
    projectPath = Path(projectPath)
    nwx = projectPath / "nwProject.nwx"
    if not nwx.is_file():
        return []
    handles: list[str] = []
    tree = ET.parse(nwx)
    for item in tree.getroot().iter("item"):
        if item.get("class") == "NOVEL" and item.get("type") == "FILE":
            if h := item.get("handle"):
                handles.append(h)
    return handles


# =============================================================================
#  Internals
# =============================================================================


def _fileHash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_CLAUDE_MD_TEMPLATE = """
# novelWriter project — AI working conventions

You are running headless inside a **novelWriter project directory**. The project's notes and
manuscript live as `content/<handle>.nwd` files. Each `.nwd` is Markdown with a small header of
`%%~` comment lines (`name`, `path`, `kind`, `hash`, `date`) — **preserve those header lines
exactly** when you edit a file; edit only the Markdown body below them.

## Navigating (token-efficient)
- Start with **`INDEX.md`** (auto-generated). Entries look like `[[Title]] — short blurb` plus a
  `content/<handle>.nwd` path.
- Prefer the blurb over reading full notes. Only load a full note when you need detail.
- Ask the user to request `Expand [[Title]]` in a later message when you need a full note. You may
  also `Read` `content/<handle>.nwd` yourself when tools allow.
- Wiki links `[[Name]]` may appear in notes; resolve via INDEX or the handle path.
- Classes: `NOVEL` = manuscript (author-owned — **never edit**), `CHARACTER` / `WORLD` /
  `TIMELINE` / `OBJECT` / `PLOT` = kb notes you may update, `ARCHIVE` / `TRASH` / `TEMPLATE` =
  leave alone.

## Editing rules
- **Never edit or write** any `NOVEL`-class file, `nwProject.nwx`, or anything under `meta/`.
  (These are also blocked at the tool-permission layer — don't try to work around it.)
- Update existing kb notes by editing their `content/<handle>.nwd` in place, headers preserved.
- To create a **new** note, write a Markdown file under `_inbox/<Class>/<Title>.md` (e.g.
  `_inbox/CHARACTER/Marla.md`). Do not invent a handle or touch `nwProject.nwx`; the app imports
  `_inbox/` into the project after your turn.

Follow your agent instructions (muse never writes manuscript prose; critics are read-only, etc.).
""".strip()
