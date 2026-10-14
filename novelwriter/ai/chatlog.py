"""
novelWriter – AI Chat Session Log
=================================

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

from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# App-owned (agents cannot write meta/)
CHAT_LOG_SUBDIR = Path("meta") / "ai-chat"


def chatLogDir(projectPath: Path | str) -> Path:
    """Return ``<project>/meta/ai-chat`` (created on demand)."""
    path = Path(projectPath) / CHAT_LOG_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safeSlug(text: str, fallback: str = "chat") -> str:
    slug = re.sub(r"[^\w\-]+", "-", (text or "").strip(), flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug[:40] or fallback


class AiChatLog:
    """Markdown conversation log for one chat session.

    Auto-save path: ``meta/ai-chat/YYYY-MM-DD_HHMMSS_<agent>.md``
    One file per conversation (until ``newSession`` / project close).
    """

    def __init__(self) -> None:
        self._projectPath: Path | None = None
        self._path: Path | None = None
        self._agent = ""
        self._sessionId = ""
        self._started = ""
        self._turnCount = 0

    ##
    #  Properties
    ##

    @property
    def path(self) -> Path | None:
        """Current log file path, or None if not started."""
        return self._path

    @property
    def turnCount(self) -> int:
        return self._turnCount

    ##
    #  Public API
    ##

    def setProjectPath(self, projectPath: Path | str | None) -> None:
        """Bind to a project root. Closes the current session file handle state."""
        self.close()
        self._projectPath = Path(projectPath) if projectPath else None

    def newSession(self, agent: str = "", sessionId: str = "") -> Path | None:
        """Start a fresh log file for a new conversation."""
        self._agent = (agent or "agent").strip() or "agent"
        self._sessionId = (sessionId or "").strip()
        self._turnCount = 0
        self._path = None
        self._started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._projectPath is None:
            return None
        # File is created lazily on first message so empty "New conversation"
        # clicks don't leave blank files.
        return None

    def close(self) -> None:
        """Forget the current session (does not delete the file)."""
        self._path = None
        self._sessionId = ""
        self._turnCount = 0
        self._started = ""

    def ensureFile(self, agent: str = "", sessionId: str = "") -> Path | None:
        """Create the session file if needed; return its path."""
        if self._projectPath is None:
            return None
        if agent:
            self._agent = agent.strip() or self._agent
        if sessionId:
            self._sessionId = sessionId.strip() or self._sessionId
        if self._path is not None and self._path.is_file():
            return self._path

        if not self._started:
            self._started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        agentSlug = _safeSlug(self._agent, "agent")
        sid = self._sessionId[:8] if self._sessionId else "local"
        baseName = f"{stamp}_{agentSlug}_{sid}"
        logDir = chatLogDir(self._projectPath)
        collision = 1
        while True:
            suffix = "" if collision == 1 else f"_{collision}"
            path = logDir / f"{baseName}{suffix}.md"
            header = (
                f"# AI Chat — {self._agent}\n\n"
                f"- Started: {self._started}\n"
                f"- Agent: `{self._agent}`\n"
                f"- Session: `{self._sessionId or 'n/a'}`\n"
                f"- Log file: `{path.name}`\n\n"
                f"---\n\n"
            )
            try:
                with path.open("x", encoding="utf-8") as out:
                    out.write(header)
            except FileExistsError:
                collision += 1
                continue
            except OSError:
                logger.exception("Could not create AI chat log %s", path)
                self._path = None
                return None
            self._path = path
            logger.info("AI chat log started: %s", path)
            return self._path

    def appendUser(self, text: str, agent: str = "", sessionId: str = "") -> None:
        """Append a user message."""
        if not (text or "").strip():
            return
        if self.ensureFile(agent=agent, sessionId=sessionId) is None:
            return
        self._appendBlock("You", text.strip())

    def appendAssistant(
        self,
        text: str,
        *,
        model: str = "",
        costUsd: float | None = None,
        agent: str = "",
        sessionId: str = "",
        usage: object | None = None,
    ) -> None:
        """Append an assistant reply with optional model/cost/token meta."""
        if not (text or "").strip():
            return
        if self.ensureFile(agent=agent, sessionId=sessionId) is None:
            return
        bits: list[str] = []
        if model:
            bits.append(f"model: `{model}`")
        if isinstance(costUsd, (int, float)):
            bits.append(f"cost: ${float(costUsd):.4f}")
        # Optional UsageSummary-like object from the AI backend.
        if usage is not None:
            try:
                ctx = int(getattr(usage, "contextUsed", 0) or 0)
                window = int(getattr(usage, "contextWindow", 0) or 0)
                outTok = int(getattr(usage, "outputTokens", 0) or 0)
                if window > 0 and ctx > 0:
                    bits.append(f"ctx: {ctx:,}/{window:,}")
                elif outTok:
                    bits.append(f"out: {outTok:,} tok")
            except (TypeError, ValueError):
                pass
        meta = (" · ".join(bits)) if bits else ""
        self._appendBlock("Assistant", text.strip(), meta=meta)
        self._turnCount += 1

    def appendNote(self, text: str) -> None:
        """Append a free-form note (errors, cancel, etc.)."""
        if not (text or "").strip() or self._path is None:
            return
        self._appendBlock("Note", text.strip())

    def exportMarkdown(self, dest: Path | str) -> bool:
        """Copy the current session log (or rebuild from nothing) to dest."""
        dest = Path(dest)
        if self._path is not None and self._path.is_file():
            try:
                dest.write_text(self._path.read_text(encoding="utf-8"), encoding="utf-8")
                return True
            except OSError:
                logger.exception("Could not export chat log to %s", dest)
                return False
        return False

    def renderMarkdown(
        self,
        messages: list[tuple[str, str]],
        *,
        agent: str = "",
        sessionId: str = "",
        model: str = "",
    ) -> str:
        """Build a full markdown document from in-memory messages (for export)."""
        started = self._started or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        agent = agent or self._agent or "agent"
        sessionId = sessionId or self._sessionId or "n/a"
        lines = [
            f"# AI Chat — {agent}",
            "",
            f"- Started: {started}",
            f"- Agent: `{agent}`",
            f"- Session: `{sessionId}`",
        ]
        if model:
            lines.append(f"- Last model: `{model}`")
        lines += ["", "---", ""]
        for role, text in messages:
            label = "You" if role == "user" else "Assistant" if role == "assistant" else role.title()
            lines.append(f"## {label}")
            lines.append("")
            lines.append((text or "").rstrip())
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def exportMessages(
        self,
        dest: Path | str,
        messages: list[tuple[str, str]],
        *,
        agent: str = "",
        sessionId: str = "",
        model: str = "",
    ) -> bool:
        """Write messages to dest (used when no auto-log file exists yet)."""
        dest = Path(dest)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                self.renderMarkdown(messages, agent=agent, sessionId=sessionId, model=model),
                encoding="utf-8",
            )
            return True
        except OSError:
            logger.exception("Could not export chat to %s", dest)
            return False

    ##
    #  Internals
    ##

    def _appendBlock(self, heading: str, body: str, meta: str = "") -> None:
        if self._path is None:
            return
        now = datetime.now().strftime("%H:%M:%S")
        title = f"## {heading} ({now})"
        if meta:
            title = f"{title} · {meta}"
        block = f"{title}\n\n{body.rstrip()}\n\n---\n\n"
        try:
            with open(self._path, mode="a", encoding="utf-8") as out:
                out.write(block)
        except OSError:
            logger.exception("Could not append to AI chat log %s", self._path)
