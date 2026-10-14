"""
novelWriter – AI Backend Interface and Stream Parser
====================================================

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

import json
import logging

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class AiEventKind(Enum):
    """Normalised event kinds emitted by the stream parser.

    The Claude Code stream-json schema is not a stable public contract, so the
    parser maps known shapes into these kinds and reports everything else as
    UNKNOWN (never raises).
    """

    SESSION_STARTED = "session_started"
    TEXT_CHUNK = "text_chunk"
    TOOL_ACTIVITY = "tool_activity"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"
    STATUS = "status"
    UNKNOWN = "unknown"
    IGNORE = "ignore"  # recognised but not actionable (thinking deltas, etc.)


@dataclass(slots=True)
class AiEvent:
    """A single normalised stream event.

    Attributes:
        kind: Event classification.
        text: Human-facing text (chunk content, tool name, error message, …).
        data: Structured payload (result meta, session fields, …).
        raw:  The original JSON object when available.
    """

    kind: AiEventKind
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class UsageSummary:
    """Token / cost snapshot from a Claude Code result event.

    ``contextUsed`` approximates how full the context window is
    (uncached input + cache read + cache write). Auto-compact is handled
    by Claude Code itself when this approaches ``contextWindow``.
    """

    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadTokens: int = 0
    cacheCreateTokens: int = 0
    contextUsed: int = 0
    contextWindow: int = 0
    costUsd: float | None = None

    @property
    def hasData(self) -> bool:
        return bool(
            self.inputTokens or self.outputTokens or self.cacheReadTokens or self.cacheCreateTokens or self.contextUsed
        )

    @property
    def contextPercent(self) -> float | None:
        if self.contextWindow > 0 and self.contextUsed > 0:
            return min(100.0, 100.0 * self.contextUsed / self.contextWindow)
        return None


def _asInt(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def summarizeTurnUsage(meta: dict[str, Any] | None) -> UsageSummary:
    """Extract a :class:`UsageSummary` from turn-complete metadata."""
    meta = meta or {}
    summary = UsageSummary()
    cost = meta.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        summary.costUsd = float(cost)

    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    modelUsage = meta.get("modelUsage") if isinstance(meta.get("modelUsage"), dict) else {}

    # Prefer modelUsage (has contextWindow + camelCase counters).
    mu: dict[str, Any] = {}
    if modelUsage:
        first = next(iter(modelUsage.values()), None)
        if isinstance(first, dict):
            mu = first

    if mu:
        summary.inputTokens = _asInt(mu.get("inputTokens"))
        summary.outputTokens = _asInt(mu.get("outputTokens"))
        summary.cacheReadTokens = _asInt(mu.get("cacheReadInputTokens"))
        summary.cacheCreateTokens = _asInt(mu.get("cacheCreationInputTokens"))
        summary.contextWindow = _asInt(mu.get("contextWindow"))
    elif usage:
        summary.inputTokens = _asInt(usage.get("input_tokens"))
        summary.outputTokens = _asInt(usage.get("output_tokens"))
        summary.cacheReadTokens = _asInt(usage.get("cache_read_input_tokens"))
        summary.cacheCreateTokens = _asInt(usage.get("cache_creation_input_tokens"))

    # If modelUsage lacked some fields, fill from usage.
    if usage:
        if not summary.inputTokens:
            summary.inputTokens = _asInt(usage.get("input_tokens"))
        if not summary.outputTokens:
            summary.outputTokens = _asInt(usage.get("output_tokens"))
        if not summary.cacheReadTokens:
            summary.cacheReadTokens = _asInt(usage.get("cache_read_input_tokens"))
        if not summary.cacheCreateTokens:
            summary.cacheCreateTokens = _asInt(usage.get("cache_creation_input_tokens"))

    summary.contextUsed = summary.inputTokens + summary.cacheReadTokens + summary.cacheCreateTokens
    return summary


def formatTokenCount(n: int) -> str:
    """Compact human token count: 1234 → 1.2k, 45000 → 45k."""
    n = max(0, int(n))
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}M" if val < 10 else f"{int(round(val))}M"
    if n >= 10_000:
        return f"{int(round(n / 1000))}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class AiBackendSignals(QObject):
    """Signal hub for AI backends.

    Held as a separate QObject (same pattern as versioninfo._RetrieverSignal)
    so backends can be QRunnable-based later without signal ownership issues.
    """

    sessionStarted = pyqtSignal(str)  # session_id
    modelResolved = pyqtSignal(str)  # actual model id from stream init/result
    chunkReceived = pyqtSignal(str)  # streamed text delta
    toolActivity = pyqtSignal(str)  # tool name / short status
    turnComplete = pyqtSignal(str, dict)  # full result text, metadata
    errorOccurred = pyqtSignal(str)  # human-readable error


class AiBackend(QObject):
    """Abstract AI backend.

    Concrete backends (Claude Code via QProcess, future Anthropic API, …)
    implement startTurn/cancel/newConversation. The GUI only talks to this
    interface and its AiBackendSignals.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent=parent)
        self.signals = AiBackendSignals()
        self._busy = False
        self._sessionId: str | None = None
        self._agent = ""
        self._model = ""  # empty = honour agent frontmatter / CLI default
        self._effort = ""  # empty = CLI default
        self._resolvedModel = ""  # last model id reported by Claude Code
        self._projectPath: Path | None = None
        self._readOnly = True  # default to safe posture
        self._disallowedTools: list[str] = []
        self._allowedTools: list[str] = []

    ##
    #  Properties
    ##

    @property
    def busy(self) -> bool:
        """True while a turn is in flight."""
        return self._busy

    @property
    def sessionId(self) -> str | None:
        """Current Claude Code session id, or None before the first turn."""
        return self._sessionId

    @property
    def agent(self) -> str:
        return self._agent

    @property
    def model(self) -> str:
        return self._model

    @property
    def resolvedModel(self) -> str:
        """Last concrete model id from the stream (e.g. claude-sonnet-4-…)."""
        return self._resolvedModel

    @property
    def effort(self) -> str:
        return self._effort

    @property
    def projectPath(self) -> Path | None:
        return self._projectPath

    @property
    def readOnly(self) -> bool:
        """If True, use dontAsk (hard read-only). If False, acceptEdits + tool rules."""
        return self._readOnly

    ##
    #  Setters
    ##

    def setAgent(self, agent: str) -> None:
        """Set the --agent name (e.g. 'critic', 'muse'). Empty = CLI default."""
        self._agent = (agent or "").strip()

    def setModel(self, model: str) -> None:
        """Set --model. Empty leaves model unset so agent frontmatter wins."""
        self._model = (model or "").strip()

    def setEffort(self, effort: str) -> None:
        """Set --effort (low|medium|high|xhigh|max). Empty = CLI default."""
        self._effort = (effort or "").strip()

    def setProjectPath(self, path: Path | str | None) -> None:
        """Set the process working directory (open novelWriter project root)."""
        self._projectPath = Path(path) if path else None

    def setBinary(self, path: str | None) -> None:
        """Set a backend executable path when the backend supports one."""
        _ = path

    def setRemoteControl(self, enabled: bool, name: str = "") -> None:
        """Configure remote control when the backend supports it."""
        _ = (enabled, name)

    def shutdown(self) -> None:
        """Stop any active process before the application exits."""
        if self.busy:
            self.cancel()

    def setReadOnly(self, readOnly: bool) -> None:
        """Select a read-only or app-approved file editing tool surface."""
        self._readOnly = bool(readOnly)

    def setDisallowedTools(self, tools: list[str]) -> None:
        """Set per-turn --disallowedTools (manuscript handles, nwProject.nwx, …)."""
        self._disallowedTools = list(tools)

    def setAllowedTools(self, tools: list[str]) -> None:
        """Set --allowedTools for writing agents. Empty uses backend defaults."""
        self._allowedTools = list(tools)

    ##
    #  Abstract Interface
    ##

    @abstractmethod
    def startTurn(self, prompt: str) -> None:
        """Begin a turn with the given user prompt. Emits signals as events arrive."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the in-flight turn (terminate process). No-op if idle."""
        raise NotImplementedError

    def newConversation(self) -> None:
        """Drop the session id so the next startTurn opens a fresh conversation."""
        if self._busy:
            self.cancel()
        self._sessionId = None
        logger.debug("AI conversation reset")


# =============================================================================
#  Permission helpers (shared with argv builder and sync layer)
# =============================================================================

# Tools writing agents are allowed to use. Note: Agent (not Task) is the
# subagent-spawn tool used by muse's frontmatter.
DEFAULT_WRITER_ALLOWED_TOOLS: tuple[str, ...] = (
    "Read",
    "Glob",
    "Grep",
    "Skill",
    "Agent",
    "Edit",
    "Write",
)
READ_ONLY_AVAILABLE_TOOLS: tuple[str, ...] = ("Read", "Glob", "Grep", "Skill")

# Always denied for writing agents, on top of per-handle manuscript denies.
BASE_DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash",
    "WebSearch",
    "WebFetch",
    "Edit(nwProject.nwx)",
    "Write(nwProject.nwx)",
    "Edit(meta/**)",
    "Write(meta/**)",
)

# Agents that should run under dontAsk (hard read-only).
READ_ONLY_AGENTS: frozenset[str] = frozenset({
    "critic",
    "editor",
    "reader-sim",
    "character-sim",
    "continuity-checker",
})


def isReadOnlyAgent(agent: str) -> bool:
    """Return True if the named agent should use dontAsk permission mode."""
    return (agent or "").strip().lower() in READ_ONLY_AGENTS


def manuscriptDenyRules(handles: list[str]) -> list[str]:
    """Build Edit/Write deny rules for every manuscript document handle.

    Handles may be bare ids (`bb2c23b3c42cc`) or already path-like
    (`content/bb2c23b3c42cc.nwd`). Output always uses the
    `Edit(content/<h>.nwd)` / `Write(content/<h>.nwd)` spelling verified in
    Phase 0.
    """
    rules: list[str] = []
    for raw in handles:
        h = raw.strip()
        if not h:
            continue
        if h.endswith(".nwd"):
            # Accept full relative paths or bare filenames.
            rel = h if h.startswith("content/") else f"content/{h.split('/')[-1]}"
        else:
            # Bare handle id.
            stem = h.split("/")[-1]
            rel = f"content/{stem}.nwd"
        rules.append(f"Edit({rel})")
        rules.append(f"Write({rel})")
    return rules


def appendPermissionPolicy(
    argv: list[str],
    *,
    readOnly: bool,
    allowedTools: list[str] | None = None,
    disallowedTools: list[str] | None = None,
) -> None:
    """Add a closed Claude tool and permission policy to a command line."""
    argv.extend([
        "--restricted",
        "--strict-mcp-config",
        "--permission-prompts",
        "none",
        "--permission-mode",
        "dontAsk",
        "--tools",
        *(READ_ONLY_AVAILABLE_TOOLS if readOnly else DEFAULT_WRITER_ALLOWED_TOOLS),
    ])
    if not readOnly:
        allowed = allowedTools or list(DEFAULT_WRITER_ALLOWED_TOOLS)
        argv.append("--allowedTools")
        argv.extend(allowed)
        denied = disallowedTools or buildDisallowedTools()
        argv.append("--disallowedTools")
        argv.extend(denied)


def buildDisallowedTools(manuscriptHandles: list[str] | None = None) -> list[str]:
    """Combine base denies with per-handle manuscript protection rules."""
    rules = list(BASE_DISALLOWED_TOOLS)
    if manuscriptHandles:
        rules.extend(manuscriptDenyRules(manuscriptHandles))
    return rules


# =============================================================================
#  NDJSON stream parser (pure functions — no Qt / QProcess)
# =============================================================================


def parseStreamLine(line: str) -> AiEvent | None:
    """Parse one NDJSON line from Claude Code stream-json output.

    Returns:
        An AiEvent, or None if the line is blank.

    Never raises on unknown or malformed content — returns AiEvent(ERROR) or
    AiEvent(UNKNOWN) instead. Callers can ignore IGNORE/UNKNOWN events.
    """
    text = line.strip()
    if not text:
        return None

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("AI stream: non-JSON line ignored: %s", exc)
        return AiEvent(kind=AiEventKind.ERROR, text=f"Malformed stream line: {exc}", data={"line": text[:200]})

    if not isinstance(obj, dict):
        return AiEvent(kind=AiEventKind.UNKNOWN, text=str(obj), raw={"value": obj})

    return _classifyEvent(obj)


def parseStreamLines(text: str) -> list[AiEvent]:
    """Parse a multi-line NDJSON blob; skip blank lines and None results."""
    events: list[AiEvent] = []
    for line in text.splitlines():
        if ev := parseStreamLine(line):
            events.append(ev)
    return events


def _classifyEvent(obj: dict[str, Any]) -> AiEvent:
    """Map a raw stream-json object onto an AiEvent."""
    etype = obj.get("type")

    if etype == "system":
        return _classifySystem(obj)

    if etype == "stream_event":
        return _classifyStreamEvent(obj)

    if etype == "result":
        return _classifyResult(obj)

    if etype == "assistant":
        return _classifyAssistant(obj)

    if etype == "user":
        # Tool results arrive as user messages; surface errors as tool activity.
        return _classifyUser(obj)

    if etype == "rate_limit_event":
        info = obj.get("rate_limit_info") or {}
        return AiEvent(
            kind=AiEventKind.STATUS,
            text="rate_limit",
            data={"rate_limit_info": info},
            raw=obj,
        )

    # Unknown top-level type — tolerate (Phase 0: more types exist than docs list).
    return AiEvent(
        kind=AiEventKind.UNKNOWN,
        text=str(etype or ""),
        data={"type": etype},
        raw=obj,
    )


def _classifySystem(obj: dict[str, Any]) -> AiEvent:
    """Handle system/* events (init, status, thinking_tokens, …)."""
    subtype = obj.get("subtype")

    if subtype == "init":
        sid = str(obj.get("session_id") or "")
        data = {
            "session_id": sid,
            "model": obj.get("model"),
            "cwd": obj.get("cwd"),
            "permissionMode": obj.get("permissionMode"),
            "agents": obj.get("agents") or [],
            "tools": obj.get("tools") or [],
            "claude_code_version": obj.get("claude_code_version"),
        }
        return AiEvent(kind=AiEventKind.SESSION_STARTED, text=sid, data=data, raw=obj)

    if subtype == "status":
        status = str(obj.get("status") or "")
        return AiEvent(kind=AiEventKind.STATUS, text=status, data={"status": status}, raw=obj)

    if subtype == "thinking_tokens":
        return AiEvent(kind=AiEventKind.IGNORE, text="thinking_tokens", raw=obj)

    return AiEvent(
        kind=AiEventKind.UNKNOWN,
        text=f"system/{subtype or ''}",
        data={"subtype": subtype},
        raw=obj,
    )


def _classifyStreamEvent(obj: dict[str, Any]) -> AiEvent:
    """Handle stream_event wrappers around raw Anthropic API events."""
    event = obj.get("event")
    if not isinstance(event, dict):
        return AiEvent(kind=AiEventKind.UNKNOWN, text="stream_event", raw=obj)

    evType = event.get("type")

    if evType == "content_block_delta":
        delta = event.get("delta") or {}
        if not isinstance(delta, dict):
            return AiEvent(kind=AiEventKind.IGNORE, raw=obj)
        dType = delta.get("type")
        if dType == "text_delta":
            chunk = delta.get("text") or ""
            return AiEvent(kind=AiEventKind.TEXT_CHUNK, text=str(chunk), raw=obj)
        # thinking_delta, signature_delta, input_json_delta — ignore for UI
        return AiEvent(kind=AiEventKind.IGNORE, text=str(dType or ""), raw=obj)

    if evType == "content_block_start":
        block = event.get("content_block") or {}
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = str(block.get("name") or "tool")
            return AiEvent(
                kind=AiEventKind.TOOL_ACTIVITY,
                text=name,
                data={
                    "tool_name": name,
                    "tool_id": block.get("id"),
                    "phase": "start",
                },
                raw=obj,
            )
        return AiEvent(kind=AiEventKind.IGNORE, text=str((block or {}).get("type") or ""), raw=obj)

    # message_start / message_delta / message_stop / content_block_stop
    return AiEvent(kind=AiEventKind.IGNORE, text=str(evType or ""), raw=obj)


def _classifyResult(obj: dict[str, Any]) -> AiEvent:
    """Handle the terminal result event."""
    resultText = obj.get("result")
    if resultText is None:
        resultText = ""
    isError = bool(obj.get("is_error"))
    meta: dict[str, Any] = {
        "session_id": obj.get("session_id"),
        "subtype": obj.get("subtype"),
        "is_error": isError,
        "total_cost_usd": obj.get("total_cost_usd"),
        "usage": obj.get("usage") or {},
        "stop_reason": obj.get("stop_reason"),
        "permission_denials": obj.get("permission_denials") or [],
        "duration_ms": obj.get("duration_ms"),
        "num_turns": obj.get("num_turns"),
        "modelUsage": obj.get("modelUsage"),
        "api_error_status": obj.get("api_error_status"),
    }
    if isError:
        errMsg = str(resultText) or str(obj.get("subtype") or "turn failed")
        return AiEvent(kind=AiEventKind.ERROR, text=errMsg, data=meta, raw=obj)
    return AiEvent(kind=AiEventKind.TURN_COMPLETE, text=str(resultText), data=meta, raw=obj)


def _classifyAssistant(obj: dict[str, Any]) -> AiEvent:
    """Handle complete assistant messages (non-streaming summaries).

    Prefer stream_event text deltas for live UI; assistant messages are useful
    for tool_use blocks when partial messages are off.
    """
    msg = obj.get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return AiEvent(kind=AiEventKind.IGNORE, raw=obj)

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            name = str(block.get("name") or "tool")
            return AiEvent(
                kind=AiEventKind.TOOL_ACTIVITY,
                text=name,
                data={"tool_name": name, "tool_id": block.get("id"), "phase": "assistant"},
                raw=obj,
            )

    return AiEvent(kind=AiEventKind.IGNORE, text="assistant", raw=obj)


def _classifyUser(obj: dict[str, Any]) -> AiEvent:
    """Handle user/tool-result messages; surface tool errors as activity."""
    result = obj.get("tool_use_result")
    if result is None:
        return AiEvent(kind=AiEventKind.IGNORE, text="user", raw=obj)

    # tool_use_result can be a string error or a structured object.
    if isinstance(result, str):
        lowered = result.lower()
        if "error" in lowered or "denied" in lowered or "permission" in lowered:
            return AiEvent(
                kind=AiEventKind.TOOL_ACTIVITY,
                text=result[:200],
                data={"phase": "error", "tool_use_result": result},
                raw=obj,
            )
        return AiEvent(kind=AiEventKind.IGNORE, text="tool_result", raw=obj)

    if isinstance(result, dict):
        # Some builds put an error flag on the result object.
        if result.get("error") or result.get("is_error"):
            msg = str(result.get("error") or result.get("message") or "tool error")
            return AiEvent(
                kind=AiEventKind.TOOL_ACTIVITY,
                text=msg[:200],
                data={"phase": "error", "tool_use_result": result},
                raw=obj,
            )

    return AiEvent(kind=AiEventKind.IGNORE, text="tool_result", raw=obj)


def emitEventToSignals(event: AiEvent, signals: AiBackendSignals) -> None:
    """Dispatch a parsed AiEvent onto an AiBackendSignals hub.

    Shared by ClaudeCodeBackend and tests/FakeBackend so the mapping lives in
    one place.
    """
    if event.kind == AiEventKind.SESSION_STARTED:
        signals.sessionStarted.emit(event.text or str(event.data.get("session_id") or ""))
        model = str(event.data.get("model") or "").strip()
        if model:
            signals.modelResolved.emit(model)
    elif event.kind == AiEventKind.TEXT_CHUNK:
        if event.text:
            signals.chunkReceived.emit(event.text)
    elif event.kind == AiEventKind.TOOL_ACTIVITY:
        signals.toolActivity.emit(event.text)
    elif event.kind == AiEventKind.TURN_COMPLETE:
        # Prefer explicit model field; fall back to first key in modelUsage.
        model = str(event.data.get("model") or "").strip()
        if not model:
            usage = event.data.get("modelUsage") or {}
            if isinstance(usage, dict) and usage:
                model = str(next(iter(usage.keys())))
        if model:
            signals.modelResolved.emit(model)
        signals.turnComplete.emit(event.text, event.data)
    elif event.kind == AiEventKind.ERROR:
        signals.errorOccurred.emit(event.text)
    # STATUS / UNKNOWN / IGNORE — not forwarded to the panel by default
