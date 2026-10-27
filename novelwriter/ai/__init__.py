"""
novelWriter – AI Assistant Package
==================================

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

from novelwriter.ai.agents import (
    AiAgentInfo,
    isProjectAiReady,
    parseAgentFrontmatter,
    scanProjectAgents,
)
from novelwriter.ai.backend import (
    BASE_DISALLOWED_TOOLS,
    DEFAULT_WRITER_ALLOWED_TOOLS,
    READ_ONLY_AGENTS,
    AiBackend,
    AiBackendSignals,
    AiEvent,
    AiEventKind,
    buildDisallowedTools,
    isReadOnlyAgent,
    manuscriptDenyRules,
    parseStreamLine,
    parseStreamLines,
)
from novelwriter.ai.chatlog import AiChatLog, chatLogDir
from novelwriter.ai.claudecode import (
    ClaudeCodeBackend,
    classifyClaudeError,
    isClaudeAvailable,
    missingBinaryMessage,
    resolveClaudeBinary,
)
from novelwriter.ai.index import (
    buildExpandBlocks,
    expandWikiTarget,
    generateSmartIndex,
    parseExpandRequests,
    resolveWikiLink,
    scanWikiLinks,
    writeProjectIndex,
)
from novelwriter.ai.setup import (
    AiSetupResult,
    ensureKbRoots,
    listManuscriptHandles,
    setupProjectAi,
    writeHandleIndex,
    writeProjectClaudeMd,
)
from novelwriter.ai.sync import (
    AiTurnSync,
    AiTurnSyncResult,
    backupManuscriptFiles,
    detectManuscriptTouches,
    diffContentHashes,
    importInboxNotes,
    isKbHandle,
    snapshotContentHashes,
)


def isAiAvailable() -> bool:
    """Return True if the Claude Code CLI can be resolved on this machine."""
    return isClaudeAvailable()


__all__ = [
    "BASE_DISALLOWED_TOOLS",
    "DEFAULT_WRITER_ALLOWED_TOOLS",
    "READ_ONLY_AGENTS",
    "AiAgentInfo",
    "AiBackend",
    "AiBackendSignals",
    "AiChatLog",
    "AiEvent",
    "AiEventKind",
    "AiSetupResult",
    "AiTurnSync",
    "AiTurnSyncResult",
    "ClaudeCodeBackend",
    "backupManuscriptFiles",
    "buildDisallowedTools",
    "buildExpandBlocks",
    "chatLogDir",
    "classifyClaudeError",
    "detectManuscriptTouches",
    "diffContentHashes",
    "ensureKbRoots",
    "expandWikiTarget",
    "generateSmartIndex",
    "importInboxNotes",
    "isAiAvailable",
    "isClaudeAvailable",
    "isKbHandle",
    "isProjectAiReady",
    "isReadOnlyAgent",
    "listManuscriptHandles",
    "manuscriptDenyRules",
    "missingBinaryMessage",
    "parseAgentFrontmatter",
    "parseExpandRequests",
    "parseStreamLine",
    "parseStreamLines",
    "resolveClaudeBinary",
    "resolveWikiLink",
    "scanProjectAgents",
    "scanWikiLinks",
    "setupProjectAi",
    "snapshotContentHashes",
    "writeHandleIndex",
    "writeProjectClaudeMd",
    "writeProjectIndex",
]
