"""
novelWriter – Smart Project Index (Phase 7)
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

import hashlib
import logging
import re
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
_INDEX_MARKER = "<!-- novelWriter managed AI index sha256:"

# Obsidian-style [[Wiki Link]] or [[Wiki Link|alias]]
_WIKI_LINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")
_NAME_HEADER_RE = re.compile(r"(?m)^%%~name:\s*(.+)$")
_SHORT_RE = re.compile(r"(?mi)^%Short:\s*(.+)$")
_SYNOPSIS_RE = re.compile(r"(?mi)^%Synopsis:\s*(.+)$")
_TAG_RE = re.compile(r"(?m)^@tag:\s*([^\s|#]+)")
_EXPAND_RE = re.compile(r"(?i)\bexpand\s+\[\[([^\]]+?)\]\]|\[\[\s*expand:\s*([^\]]+?)\]\]")

# Human section titles for INDEX.md (class → heading)
_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("CHARACTER", "Characters"),
    ("WORLD", "Locations / World"),
    ("TIMELINE", "Timeline"),
    ("OBJECT", "Objects"),
    ("PLOT", "Plot / Outline"),
    ("ENTITY", "Entities"),
    ("CUSTOM", "Notes"),
    ("NOVEL", "Manuscript"),
    ("ARCHIVE", "Archive"),
    ("TEMPLATE", "Templates"),
)


def _isManagedIndex(path: Path) -> bool:
    """Return whether an existing index carries the novelWriter marker."""
    try:
        with path.open(encoding="utf-8") as handle:
            marker = handle.readline().rstrip("\n")
            content = handle.read()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return marker == f"{_INDEX_MARKER}{digest} -->"
    except OSError:
        return False


def _managedIndexText(content: str) -> str:
    """Add an ownership marker that detects local edits before refresh."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{_INDEX_MARKER}{digest} -->\n{content}"


_BLURB_MAX = 120


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One row in the smart project index."""

    handle: str
    title: str
    itemClass: str
    itemType: str
    layout: str
    blurb: str
    tags: tuple[str, ...] = ()


def scanWikiLinks(text: str) -> list[str]:
    """Return unique wiki-link targets from text (display name, not alias)."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _WIKI_LINK_RE.finditer(text or ""):
        raw = m.group(1).strip()
        # [[Name|alias]] → Name
        name = raw.split("|", 1)[0].strip()
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    return found


def parseExpandRequests(text: str) -> list[str]:
    """Detect ``Expand [[Name]]`` requests in user or assistant text."""
    names: list[str] = []
    seen: set[str] = set()
    for m in _EXPAND_RE.finditer(text or ""):
        name = (m.group(1) or m.group(2) or "").strip()
        name = name.split("|", 1)[0].strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    # Also treat bare Expand requests that list links on following lines
    for name in scanWikiLinks(text or ""):
        # Only auto-include if the message looks like an expand request
        if re.search(rf"(?i)expand.*\[\[{re.escape(name)}\]\]", text or "") and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def stripNwdMeta(text: str) -> str:
    """Remove leading ``%%~`` header lines from an .nwd body."""
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith("%%~"):
        i += 1
    return "\n".join(lines[i:]).lstrip("\n")


def extractBlurb(body: str, maxLen: int = _BLURB_MAX) -> str:
    """One-line summary from %Short, %Synopsis, or first prose line."""
    if m := _SHORT_RE.search(body or ""):
        return _clip(m.group(1).strip(), maxLen)
    if m := _SYNOPSIS_RE.search(body or ""):
        return _clip(m.group(1).strip(), maxLen)
    for line in (body or "").splitlines():
        s = line.strip()
        if not s or s.startswith(("%", "@", "#", "%%~")):
            continue
        return _clip(s, maxLen)
    return ""


def extractTags(body: str) -> list[str]:
    """Return @tag keywords from document body."""
    return [m.group(1).strip() for m in _TAG_RE.finditer(body or "")]


def collectProjectEntries(projectPath: Path | str) -> list[IndexEntry]:
    """Scan nwProject.nwx + content/*.nwd into index entries."""
    projectPath = Path(projectPath)
    nwx = projectPath / "nwProject.nwx"
    content = projectPath / "content"
    entries: list[IndexEntry] = []
    if not nwx.is_file():
        return entries

    tree = ET.parse(nwx)
    for item in tree.getroot().iter("item"):
        handle = item.get("handle") or ""
        if not handle or item.get("type") != "FILE":
            continue
        cls = item.get("class") or "UNKNOWN"
        itype = item.get("type") or ""
        layout = item.get("layout") or ""
        title = ""
        body = ""
        nwd = content / f"{handle}.nwd"
        if nwd.is_file():
            try:
                raw = nwd.read_text(encoding="utf-8", errors="replace")
                if m := _NAME_HEADER_RE.search(raw[:500]):
                    title = m.group(1).strip()
                body = stripNwdMeta(raw)
            except OSError:
                pass
        if not title:
            nameEl = item.find("name")
            if nameEl is not None and nameEl.text:
                title = nameEl.text.strip()
        if not title:
            title = handle
        blurb = extractBlurb(body)
        tags = tuple(extractTags(body))
        entries.append(
            IndexEntry(
                handle=handle,
                title=title,
                itemClass=cls,
                itemType=itype,
                layout=layout,
                blurb=blurb,
                tags=tags,
            )
        )
    return entries


def generateSmartIndex(projectPath: Path | str) -> Path:
    """Write a human- and agent-friendly INDEX.md with [[WikiLinks]]."""
    projectPath = Path(projectPath)
    entries = collectProjectEntries(projectPath)

    byClass: dict[str, list[IndexEntry]] = {}
    for e in entries:
        byClass.setdefault(e.itemClass, []).append(e)

    lines = [
        "# Project Index",
        "",
        "_Auto-generated for AI + navigation. Prefer this over loading full notes._",
        (
            "Agents: start here. To load a full note, ask the user or request "
            "`Expand [[Title]]` (the app injects the file). Or Read `content/<handle>.nwd`."
        ),
        "",
    ]

    # Known sections first, then leftovers
    orderedClasses = [c for c, _ in _SECTION_ORDER if c in byClass]
    orderedClasses += sorted(c for c in byClass if c not in orderedClasses)

    sectionTitle = dict(_SECTION_ORDER)

    for cls in orderedClasses:
        heading = sectionTitle.get(cls, cls.title())
        lines.append(f"## {heading}")
        lines.append("")
        items = sorted(byClass[cls], key=lambda e: e.title.lower())
        for e in items:
            blurb = f" — {e.blurb}" if e.blurb else ""
            tagBit = f"  `@tag: {e.tags[0]}`" if e.tags else ""
            lines.append(f"- [[{e.title}]]{blurb}  (`content/{e.handle}.nwd`){tagBit}")
        lines.append("")

    out = projectPath / "INDEX.md"
    if out.exists() and not _isManagedIndex(out):
        logger.warning("Preserving user-owned project index: %s", out)
        return out
    content = "\n".join(lines).rstrip() + "\n"
    out.write_text(_managedIndexText(content), encoding="utf-8")
    logger.info("Smart INDEX.md written (%d entries) → %s", len(entries), out)
    return out


def generateHandleIndex(projectPath: Path | str) -> Path:
    """Legacy handle-oriented INDEX (no wiki links). Used when smart index is off."""
    projectPath = Path(projectPath)
    entries = collectProjectEntries(projectPath)
    lines = [
        "# Project handle index (auto-generated — do not edit by hand)",
        "",
        "Use this index to find a note by title, then Read/Edit `content/<handle>.nwd`.",
        "",
    ]
    byClass: dict[str, list[IndexEntry]] = {}
    for e in entries:
        byClass.setdefault(e.itemClass, []).append(e)
    for cls in sorted(byClass):
        lines.append(f"## {cls}")
        for e in sorted(byClass[cls], key=lambda x: x.title.lower()):
            kind = e.itemType
            if e.layout:
                kind = f"{e.itemType}/{e.layout}"
            lines.append(f"- `content/{e.handle}.nwd` — {e.title}  [{kind}]")
        lines.append("")
    out = projectPath / "INDEX.md"
    if out.exists() and not _isManagedIndex(out):
        logger.warning("Preserving user-owned project index: %s", out)
        return out
    content = "\n".join(lines).rstrip() + "\n"
    out.write_text(_managedIndexText(content), encoding="utf-8")
    return out


def writeProjectIndex(projectPath: Path | str, *, smart: bool = True) -> Path:
    """Write INDEX.md using smart or legacy format."""
    if smart:
        return generateSmartIndex(projectPath)
    return generateHandleIndex(projectPath)


def resolveWikiLink(projectPath: Path | str, name: str) -> IndexEntry | None:
    """Resolve a [[Name]] to an index entry (title, then @tag, then stem match)."""
    name = (name or "").strip()
    if not name:
        return None
    key = name.casefold()
    entries = collectProjectEntries(projectPath)

    # Exact title
    for e in entries:
        if e.title.casefold() == key:
            return e
    # @tag
    for e in entries:
        if any(t.casefold() == key for t in e.tags):
            return e
    # Title contains / stem
    for e in entries:
        if key in e.title.casefold():
            return e
    # Handle as last resort
    for e in entries:
        if e.handle.casefold() == key:
            return e
    return None


def expandWikiTarget(projectPath: Path | str, name: str) -> tuple[str, str, str] | None:
    """Load full note body for a wiki name.

    Returns ``(title, handle, body)`` without ``%%~`` headers, or None if unresolved.
    """
    entry = resolveWikiLink(projectPath, name)
    if entry is None:
        return None
    nwd = Path(projectPath) / "content" / f"{entry.handle}.nwd"
    if not nwd.is_file():
        return entry.title, entry.handle, ""
    try:
        raw = nwd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entry.title, entry.handle, ""
    return entry.title, entry.handle, stripNwdMeta(raw)


def buildExpandBlocks(projectPath: Path | str, names: list[str]) -> str:
    """Build ``<document>`` blocks for Expand [[Name]] injection."""
    parts: list[str] = []
    for name in names:
        resolved = expandWikiTarget(projectPath, name)
        if not resolved:
            parts.append(f"<!-- expand failed: [[{name}]] not found -->")
            continue
        title, handle, body = resolved
        parts.append(f'<document title="{title}" handle="{handle}">\n{body.rstrip()}\n</document>')
    return "\n\n".join(parts)


def _clip(text: str, maxLen: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= maxLen:
        return text
    return text[: maxLen - 1].rstrip() + "…"
