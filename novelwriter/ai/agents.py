"""
novelWriter – AI Agent Scanner
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
import re

from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Frontmatter: YAML-like block between --- markers. We only parse name + description
# (including folded `>` scalars). No PyYAML dependency.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
_NAME_RE = re.compile(r"(?m)^name:\s*(.+?)\s*$")
_DESC_INLINE_RE = re.compile(r"(?m)^description:\s*(.+?)\s*$")
_DESC_FOLDED_RE = re.compile(
    r"(?m)^description:\s*>\s*\n((?:[ \t]+.+\n?)*)",
)


@dataclass(frozen=True, slots=True)
class AiAgentInfo:
    """Minimal agent metadata for the UI combo box."""

    name: str
    description: str
    path: Path


def agentsDir(projectPath: Path | str) -> Path:
    """Return ``<project>/.claude/agents``."""
    return Path(projectPath) / ".claude" / "agents"


def isProjectAiReady(projectPath: Path | str | None) -> bool:
    """Check whether the project has at least one agent definition installed."""
    if not projectPath:
        return False
    d = agentsDir(projectPath)
    if not d.is_dir():
        return False
    return any(d.glob("*.md"))


def scanProjectAgents(projectPath: Path | str | None) -> list[AiAgentInfo]:
    """Scan ``<project>/.claude/agents/*.md`` for name/description.

    Returns agents sorted by name. Malformed files are skipped with a log
    warning. Empty list if the directory is missing.
    """
    if not projectPath:
        return []
    root = agentsDir(projectPath)
    if not root.is_dir():
        return []

    agents: list[AiAgentInfo] = []
    for path in sorted(root.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read agent file %s: %s", path, exc)
            continue
        name, desc = parseAgentFrontmatter(text)
        if not name:
            # Fall back to file stem if frontmatter name is missing.
            name = path.stem
        agents.append(AiAgentInfo(name=name, description=desc, path=path))
    return agents


def parseAgentFrontmatter(text: str) -> tuple[str, str]:
    """Extract ``(name, description)`` from agent markdown frontmatter.

    Supports:
      * ``name: critic``
      * ``description: single line``
      * ``description: >`` folded multi-line scalars (indent-stripped, joined)
    """
    match = _FRONTMATTER_RE.search(text)
    if not match:
        return "", ""
    block = match.group(1)

    name = ""
    if m := _NAME_RE.search(block):
        name = m.group(1).strip().strip("\"'")

    description = ""
    if m := _DESC_FOLDED_RE.search(block):
        lines = [raw.strip() for raw in m.group(1).splitlines()]
        description = " ".join(line for line in lines if line)
    elif m := _DESC_INLINE_RE.search(block):
        val = m.group(1).strip()
        # Ignore a bare `>` that would be handled by the folded matcher.
        if val != ">":
            description = val.strip("\"'")

    return name, description
