"""
novelWriter – Claude Code QProcess Backend
==========================================

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
import os
import shutil
import sys
import uuid

from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSlot

from novelwriter import CONFIG
from novelwriter.ai.backend import (
    AiBackend,
    AiEventKind,
    appendPermissionPolicy,
    emitEventToSignals,
    isReadOnlyAgent,
    parseStreamLine,
)

logger = logging.getLogger(__name__)

# Fallback locations checked when shutil.which fails (macOS GUI apps get a
# minimal PATH that often omits Homebrew / user-local bins).
_BINARY_FALLBACKS: tuple[str, ...] = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    str(Path.home() / ".local" / "bin" / "claude"),
    str(Path.home() / ".claude" / "local" / "claude"),
)

# Grace period before escalate terminate → kill (ms).
_KILL_GRACE_MS = 2000


def resolveClaudeBinary(explicit: str | None = None) -> str | None:
    """Locate the Claude Code CLI binary.

    Resolution order:
      1. explicit argument (non-empty)
      2. CONFIG.aiClaudeBin (if set; "" means auto)
      3. shutil.which("claude") / which("claude.cmd") on Windows
      4. well-known fallback paths (Homebrew, ~/.local/bin, ~/.claude/local)

    Returns an absolute path string, or None if nothing is found.
    """
    candidates: list[str] = []

    if explicit and explicit.strip():
        candidates.append(explicit.strip())

    confBin = str(getattr(CONFIG, "aiClaudeBin", "") or "").strip()
    if confBin:
        candidates.append(confBin)

    whichName = "claude.cmd" if sys.platform == "win32" else "claude"
    if found := shutil.which(whichName):
        candidates.append(found)
    if whichName != "claude" and (found := shutil.which("claude")):
        candidates.append(found)

    candidates.extend(_BINARY_FALLBACKS)

    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        path = Path(cand).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        # On Windows, .cmd may not report as executable via os.access the same way.
        if sys.platform == "win32" and path.is_file():
            return str(path.resolve())

    return None


def isClaudeAvailable(explicit: str | None = None) -> bool:
    """Return True if a Claude Code binary can be resolved."""
    return resolveClaudeBinary(explicit) is not None


def missingBinaryMessage() -> str:
    """Actionable message when the Claude Code CLI cannot be found."""
    if sys.platform == "darwin":
        paths = "/opt/homebrew/bin/claude, /usr/local/bin/claude, ~/.local/bin/claude, ~/.claude/local/claude"
        tip = (
            "macOS GUI apps often have a minimal PATH. Set the full path in "
            f"Preferences → AI Assistant, or install so one of these exists: {paths}."
        )
    elif sys.platform == "win32":
        tip = "On Windows, set Preferences → AI Assistant to claude.cmd (or the full path from `where claude`)."
    else:
        tip = "Ensure `claude` is on PATH, or set the full path in Preferences → AI Assistant."
    return f"Claude Code CLI not found. Install Claude Code, run it once from a terminal, then retry.\n\n{tip}"


def classifyClaudeError(
    *,
    exitCode: int | None = None,
    stderr: str = "",
    stdoutHint: str = "",
    processError: str = "",
) -> str:
    """Map process failure signals to a short, actionable user message.

    Inspects stderr/stdout fragments for common Claude Code failures
    (auth, not found, network) before falling back to a generic exit message.
    """
    blob = f"{stderr}\n{stdoutHint}\n{processError}".lower()

    # Auth / login
    if any(
        needle in blob
        for needle in (
            "not logged in",
            "please run /login",
            "please run 'claude login'",
            "claude login",
            "authentication",
            "unauthorized",
            "invalid api key",
            "api key",
        )
    ):
        return (
            "Claude Code is not logged in (or credentials expired). "
            "Open a terminal and run: claude login\n"
            "Then return here and try again."
        )

    # Binary / start failures
    if any(
        needle in blob
        for needle in (
            "no such file",
            "not found",
            "cannot find",
            "failed to start",
            "exec format error",
            "permission denied",
        )
    ) and ("claude" in blob or "process" in blob or processError):
        if "permission denied" in blob:
            return (
                "Cannot execute the Claude Code binary (permission denied). "
                "Check that the file is executable, or pick another path in Preferences."
            )
        return missingBinaryMessage()

    # Network
    if any(
        needle in blob
        for needle in (
            "network",
            "connection refused",
            "timed out",
            "timeout",
            "could not resolve",
            "ssl",
            "unreachable",
        )
    ):
        return "Claude Code could not reach the API (network error). Check your connection and try again."

    # Rate limit
    if "rate limit" in blob or "429" in blob:
        return "Claude Code hit a rate limit. Wait a moment and try again."

    # Generic non-zero exit
    if exitCode is not None and exitCode != 0:
        detail = (stderr or processError or "").strip()
        if detail:
            # Keep it short for the status line
            first = detail.splitlines()[0][:200]
            return f"Claude Code exited with code {exitCode}: {first}"
        return (
            f"Claude Code exited with code {exitCode}. "
            "Check that you are logged in (`claude login`) and the project path is valid."
        )

    if processError:
        return f"Could not start Claude Code: {processError}"

    return "Claude Code produced no result."


class ClaudeCodeBackend(AiBackend):
    """Drive Claude Code headless via QProcess.

    Each turn spawns:
        claude -p <prompt> --output-format stream-json --include-partial-messages
               --verbose [--agent …] [--model …] [--effort …]
               --session-id <uuid> | --resume <uuid>
               --permission-mode dontAsk|acceptEdits
               [--allowedTools …] [--disallowedTools …]

    Stdin is redirected to the null device (Phase 0: avoids a ~3 s hang).
    stdout NDJSON lines are parsed and mapped onto AiBackendSignals.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent=parent)
        self._binary: str | None = None
        self._process: QProcess | None = None
        self._stdoutBuffer = ""
        self._stderrBuffer = ""
        self._accumulatedText = ""
        self._pendingSessionId: str | None = None  # uuid we pass on first turn
        self._finishedCleanly = False
        self._cancelRequested = False
        self._killTimer: QTimer | None = None

    ##
    #  Public API
    ##

    def setBinary(self, path: str | None) -> None:
        """Override binary path (empty/None → re-resolve on next turn)."""
        self._binary = path.strip() if path else None

    def resolveBinary(self) -> str | None:
        """Resolve and cache the binary path."""
        if self._binary and Path(self._binary).is_file():
            return self._binary
        resolved = resolveClaudeBinary(self._binary)
        self._binary = resolved
        return resolved

    def startTurn(self, prompt: str) -> None:
        """Spawn claude -p for one turn. Refuses if already busy."""
        if self._busy:
            self.signals.errorOccurred.emit("A turn is already in progress.")
            return

        binary = self.resolveBinary()
        if not binary:
            self.signals.errorOccurred.emit(missingBinaryMessage())
            return

        if not self._projectPath or not Path(self._projectPath).is_dir():
            self.signals.errorOccurred.emit(
                "No project directory set for the AI backend. Open a novelWriter project first."
            )
            return

        if not (prompt or "").strip():
            self.signals.errorOccurred.emit("Cannot start a turn with an empty prompt.")
            return

        argv = self.buildArgv(prompt)
        logger.info(
            "AI turn start: bin=%s agent=%s resume=%s cwd=%s",
            binary,
            self._agent or "(default)",
            bool(self._sessionId),
            self._projectPath,
        )
        logger.debug("AI argv: %s", _redactArgv(argv))

        self._busy = True
        self._cancelRequested = False
        self._finishedCleanly = False
        self._stdoutBuffer = ""
        self._stderrBuffer = ""
        self._accumulatedText = ""

        proc = QProcess(self)
        proc.setProgram(binary)
        proc.setArguments(argv[1:])  # program is set separately
        proc.setWorkingDirectory(str(self._projectPath))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        # Phase 0 gotcha: without null stdin, -p waits ~3 s for input.
        proc.setStandardInputFile(QProcess.nullDevice())

        env = QProcessEnvironment.systemEnvironment()
        # Ensure the process does not think it is nested inside Claude Code.
        for key in (
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_CODE_BRIDGE_SESSION_ID",
            "CLAUDE_CODE_EXECPATH",
            "AI_AGENT",
        ):
            env.remove(key)
        proc.setProcessEnvironment(env)

        proc.readyReadStandardOutput.connect(self._onReadyReadStdout)
        proc.readyReadStandardError.connect(self._onReadyReadStderr)
        proc.finished.connect(self._onFinished)
        proc.errorOccurred.connect(self._onProcessError)

        self._process = proc
        # Non-blocking start: FailedToStart is reported via _onProcessError so
        # the GUI event loop stays responsive.
        proc.start()

    def cancel(self) -> None:
        """Terminate the running process without blocking the UI.

        Sends ``terminate()`` immediately, then schedules ``kill()`` after a
        grace period if the process is still alive (Phase-4: Stop must not
        freeze the event loop).
        """
        proc = self._process
        if proc is None or proc.state() == QProcess.ProcessState.NotRunning:
            self._busy = False
            self._stopKillTimer()
            return

        self._cancelRequested = True
        logger.info("AI turn cancel requested")
        proc.terminate()
        self._stopKillTimer()
        self._killTimer = QTimer(self)
        self._killTimer.setSingleShot(True)
        self._killTimer.timeout.connect(self._escalateKill)
        self._killTimer.start(_KILL_GRACE_MS)

    def newConversation(self) -> None:
        """Reset session so the next turn gets a fresh --session-id."""
        super().newConversation()
        self._pendingSessionId = None
        self._stopKillTimer()

    ##
    #  Argv builder (also unit-tested)
    ##

    def buildArgv(self, prompt: str) -> list[str]:
        """Build the full argv list (including binary as argv[0]).

        Permission posture (Phase 0 verified):
          * Read-only agents → --permission-mode dontAsk
          * Writing agents   → --permission-mode acceptEdits
            + --allowedTools (Read Glob Grep Skill Agent Edit Write)
            + --disallowedTools (base + per-handle manuscript denies)
        """
        binary = self._binary or "claude"
        argv: list[str] = [
            binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
        ]

        # Session: resume existing, or open a new one with a stable uuid we track.
        if self._sessionId:
            argv.extend(["--resume", self._sessionId])
        else:
            if not self._pendingSessionId:
                self._pendingSessionId = str(uuid.uuid4())
            argv.extend(["--session-id", self._pendingSessionId])

        # Agent — only needed on first turn; harmless on resume.
        if self._agent:
            argv.extend(["--agent", self._agent])

        # Model: leave unset unless the user overrides (honour agent frontmatter).
        if self._model:
            argv.extend(["--model", self._model])

        if self._effort:
            argv.extend(["--effort", self._effort])

        # Keep file access within this project and ignore inherited tools/MCP.
        readOnly = self._readOnly or isReadOnlyAgent(self._agent)
        appendPermissionPolicy(
            argv,
            readOnly=readOnly,
            allowedTools=self._allowedTools,
            disallowedTools=self._disallowedTools,
        )

        return argv

    ##
    #  Process slots
    ##

    @pyqtSlot()
    def _onReadyReadStdout(self) -> None:
        """Read and parse NDJSON lines from stdout."""
        proc = self._process
        if proc is None:
            return
        raw = proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        if not raw:
            return
        self._stdoutBuffer += raw
        self._drainStdoutBuffer(final=False)

    @pyqtSlot()
    def _onReadyReadStderr(self) -> None:
        """Capture stderr for error reporting (do not treat as stream events)."""
        proc = self._process
        if proc is None:
            return
        raw = proc.readAllStandardError().data().decode("utf-8", errors="replace")
        if raw:
            self._stderrBuffer += raw
            # Log but do not spam the UI with every stderr fragment.
            for line in raw.splitlines():
                if line.strip():
                    logger.debug("claude stderr: %s", line[:300])

    @pyqtSlot()
    def _escalateKill(self) -> None:
        """Kill the process if it ignored terminate()."""
        proc = self._process
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            logger.warning("AI process did not terminate; killing")
            proc.kill()

    def _stopKillTimer(self) -> None:
        """Cancel a pending kill-escalation timer."""
        if self._killTimer is not None:
            self._killTimer.stop()
            self._killTimer.deleteLater()
            self._killTimer = None

    @pyqtSlot(int, QProcess.ExitStatus)
    def _onFinished(self, exitCode: int, exitStatus: QProcess.ExitStatus) -> None:
        """Handle process exit: flush buffers, emit completion/error if needed."""
        self._stopKillTimer()
        # Drain any remaining stdout that lacked a trailing newline.
        self._drainStdoutBuffer(final=True)

        wasCancel = self._cancelRequested
        self._busy = False
        proc = self._process
        self._process = None

        stderrTail = self._stderrBuffer.strip()[-500:] if self._stderrBuffer else ""

        if wasCancel:
            logger.info("AI turn cancelled (exit=%s)", exitCode)
            self.signals.errorOccurred.emit("Turn cancelled.")
            return

        if exitStatus == QProcess.ExitStatus.CrashExit:
            self.signals.errorOccurred.emit(
                classifyClaudeError(
                    exitCode=exitCode,
                    stderr=stderrTail,
                    processError="process crashed",
                )
            )
            return

        if not self._finishedCleanly:
            # No result event was parsed — surface a classified error or synthesise.
            if exitCode != 0:
                self.signals.errorOccurred.emit(classifyClaudeError(exitCode=exitCode, stderr=stderrTail))
            elif self._accumulatedText:
                # Process exited 0 without a result event — synthesise completion.
                self.signals.turnComplete.emit(
                    self._accumulatedText,
                    {
                        "session_id": self._sessionId,
                        "synthesized": True,
                    },
                )
            else:
                self.signals.errorOccurred.emit(
                    classifyClaudeError(exitCode=0, stderr=stderrTail)
                    if stderrTail
                    else "Claude Code produced no result."
                )

        logger.info(
            "AI turn finished: exit=%s session=%s cost_done=%s",
            exitCode,
            self._sessionId,
            self._finishedCleanly,
        )
        # Silence unused-local for optional future use of proc handle.
        del proc

    @pyqtSlot(QProcess.ProcessError)
    def _onProcessError(self, error: QProcess.ProcessError) -> None:
        """Handle QProcess-level errors (FailedToStart, Crashed, …)."""
        # finished() also fires after most errors; only report FailedToStart here
        # because those never reach a useful finished path for our purposes.
        if error == QProcess.ProcessError.FailedToStart:
            self._busy = False
            proc = self._process
            detail = proc.errorString() if proc else "unknown"
            self._process = None
            self.signals.errorOccurred.emit(classifyClaudeError(processError=detail, stderr=self._stderrBuffer))
            logger.error("QProcess FailedToStart: %s", detail)

    ##
    #  Internal helpers
    ##

    def _drainStdoutBuffer(self, final: bool) -> None:
        """Split the stdout buffer on newlines and dispatch complete lines."""
        while True:
            idx = self._stdoutBuffer.find("\n")
            if idx < 0:
                break
            line = self._stdoutBuffer[:idx]
            self._stdoutBuffer = self._stdoutBuffer[idx + 1 :]
            self._handleLine(line)

        if final and self._stdoutBuffer.strip():
            self._handleLine(self._stdoutBuffer)
            self._stdoutBuffer = ""

    def _handleLine(self, line: str) -> None:
        """Parse one NDJSON line and emit the corresponding signals."""
        event = parseStreamLine(line)
        if event is None:
            return

        if event.kind == AiEventKind.SESSION_STARTED:
            sid = event.text or str(event.data.get("session_id") or "")
            if sid:
                self._sessionId = sid
                self._pendingSessionId = None
            model = str(event.data.get("model") or "").strip()
            if model:
                self._resolvedModel = model

        elif event.kind == AiEventKind.TEXT_CHUNK:
            self._accumulatedText += event.text

        elif event.kind == AiEventKind.TURN_COMPLETE:
            self._finishedCleanly = True
            sid = event.data.get("session_id")
            if sid:
                self._sessionId = str(sid)
            # Prefer the full result text over accumulated deltas (they match
            # in practice; result is authoritative for cost/usage metadata).
            if event.text:
                self._accumulatedText = event.text
            model = str(event.data.get("model") or "").strip()
            if not model:
                usage = event.data.get("modelUsage") or {}
                if isinstance(usage, dict) and usage:
                    model = str(next(iter(usage.keys())))
            if model:
                self._resolvedModel = model

        elif event.kind == AiEventKind.ERROR:
            # Result-level is_error still counts as a clean parse of the stream.
            if event.data.get("is_error") is not None or event.data.get("session_id"):
                self._finishedCleanly = True
                sid = event.data.get("session_id")
                if sid:
                    self._sessionId = str(sid)

        emitEventToSignals(event, self.signals)


class ClaudeCodePersistentBackend(AiBackend):
    """Drive Claude Code as ONE long-lived stream-json session.

    Unlike :class:`ClaudeCodeBackend` (a fresh ``claude -p`` per turn), this
    keeps a single process alive with **stdin held open**::

        claude --print --input-format stream-json --output-format stream-json
               --include-partial-messages --verbose --replay-user-messages
               [--remote-control [name]] [--agent …] [--model …] [--effort …]
               --permission-mode dontAsk|acceptEdits
               [--allowedTools …] [--disallowedTools …]
               --session-id <uuid> | --resume <uuid>

    Each turn writes one user-message JSON line to stdin; the process stays warm
    between turns (no cold restart, live prompt cache, same session id). When
    ``remoteControl`` is enabled the same session is registered for Remote
    Control so it can also be driven from claude.ai / the Claude mobile app.

    The stdout NDJSON schema is identical to the one-shot backend, so the shared
    :func:`parseStreamLine` / :func:`emitEventToSignals` layer is reused as-is.
    Turn boundaries are the ``result`` event (not process exit).
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        remoteControl: bool = False,
        remoteControlName: str = "",
    ) -> None:
        super().__init__(parent=parent)
        self._binary: str | None = None
        self._process: QProcess | None = None
        self._stdoutBuffer = ""
        self._stderrBuffer = ""
        self._accumulatedText = ""
        self._pendingSessionId: str | None = None
        self._finishedCleanly = False
        self._cancelRequested = False
        self._expectedExit = False  # teardown/newConversation → suppress error on finish
        self._dirty = False  # config changed → respawn (with --resume) next turn
        self._killTimer: QTimer | None = None
        self._remoteControl = bool(remoteControl)
        self._remoteControlName = (remoteControlName or "").strip()

    ##
    #  Public API
    ##

    def setBinary(self, path: str | None) -> None:
        """Override binary path (empty/None → re-resolve on next spawn)."""
        new = path.strip() if path else None
        if new != self._binary:
            self._binary = new
            self._dirty = True

    def resolveBinary(self) -> str | None:
        """Resolve and cache the binary path."""
        if self._binary and Path(self._binary).is_file():
            return self._binary
        resolved = resolveClaudeBinary(self._binary)
        self._binary = resolved
        return resolved

    def setRemoteControl(self, enabled: bool, name: str = "") -> None:
        """Toggle Remote Control (and its optional session name)."""
        enabled = bool(enabled)
        name = (name or "").strip()
        if enabled != self._remoteControl or name != self._remoteControlName:
            self._remoteControl = enabled
            self._remoteControlName = name
            self._dirty = True

    @property
    def remoteControl(self) -> bool:
        return self._remoteControl

    ##
    #  Change-detecting setters (config is fixed at spawn → respawn on change)
    ##

    def setAgent(self, agent: str) -> None:
        """Set the selected agent and mark the backend for respawning if it changed."""
        new = (agent or "").strip()
        if new != self._agent:
            self._agent = new
            self._dirty = True

    def setModel(self, model: str) -> None:
        """Set the model override and mark the backend for respawning if it changed."""
        new = (model or "").strip()
        if new != self._model:
            self._model = new
            self._dirty = True

    def setEffort(self, effort: str) -> None:
        """Set the effort override and mark the backend for respawning if it changed."""
        new = (effort or "").strip()
        if new != self._effort:
            self._effort = new
            self._dirty = True

    def setReadOnly(self, readOnly: bool) -> None:
        """Set whether the selected agent runs with read-only permissions."""
        new = bool(readOnly)
        if new != self._readOnly:
            self._readOnly = new
            self._dirty = True

    def setAllowedTools(self, tools: list[str]) -> None:
        """Set the allowed tool list and mark the backend for respawning if changed."""
        new = list(tools)
        if new != self._allowedTools:
            self._allowedTools = new
            self._dirty = True

    def setDisallowedTools(self, tools: list[str]) -> None:
        """Set the denied tool list and mark the backend for respawning if changed."""
        new = list(tools)
        if new != self._disallowedTools:
            self._disallowedTools = new
            self._dirty = True

    def setProjectPath(self, path: Path | str | None) -> None:
        """Set the project path and start a fresh session when it changes."""
        new = Path(path) if path else None
        if new != self._projectPath:
            self._projectPath = new
            # A different project is a different conversation: drop the session
            # so the next spawn starts fresh rather than --resume-ing elsewhere.
            self._sessionId = None
            self._pendingSessionId = None
            self._dirty = True

    ##
    #  Turn lifecycle
    ##

    def startTurn(self, prompt: str) -> None:
        """Write one user message to the live session (spawning it if needed)."""
        if self._busy:
            self.signals.errorOccurred.emit("A turn is already in progress.")
            return

        if not (prompt or "").strip():
            self.signals.errorOccurred.emit("Cannot start a turn with an empty prompt.")
            return

        # (Re)spawn if there is no live process or the config changed.
        needsSpawn = self._process is None or self._process.state() == QProcess.ProcessState.NotRunning or self._dirty
        if needsSpawn:
            if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
                # Config changed mid-conversation: restart with new flags but keep
                # context via --resume (session id is preserved across teardown).
                self._teardownProcess()
            if not self._spawn():
                return

        self._busy = True
        self._cancelRequested = False
        self._finishedCleanly = False
        self._accumulatedText = ""

        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        })
        self._writeLine(msg)

    def cancel(self) -> None:
        """Interrupt the in-flight turn without killing the session.

        Sends a stream-json ``interrupt`` control request; if the turn does not
        end within a grace period, the process is terminated (the next turn
        respawns and recovers context via ``--resume``).
        """
        proc = self._process
        if proc is None or proc.state() == QProcess.ProcessState.NotRunning or not self._busy:
            self._busy = False
            self._stopKillTimer()
            return

        self._cancelRequested = True
        logger.info("AI turn interrupt requested")
        self._writeLine(
            json.dumps({
                "type": "control_request",
                "request_id": str(uuid.uuid4()),
                "request": {"subtype": "interrupt"},
            })
        )

        self._stopKillTimer()
        self._killTimer = QTimer(self)
        self._killTimer.setSingleShot(True)
        self._killTimer.timeout.connect(self._escalateCancel)
        self._killTimer.start(_KILL_GRACE_MS * 2)

    def newConversation(self) -> None:
        """Reset the session: tear down the live process so the next turn is fresh."""
        self._expectedExit = True
        self._sessionId = None
        self._pendingSessionId = None
        self._cancelRequested = False
        self._teardownProcess()
        self._busy = False
        logger.debug("AI persistent conversation reset")

    def shutdown(self) -> None:
        """Terminate the live session (call on app/panel close)."""
        self._expectedExit = True
        self._teardownProcess()
        self._busy = False

    ##
    #  Argv builder (also unit-tested)
    ##

    def buildArgv(self) -> list[str]:
        """Build the persistent-session argv (prompt is delivered via stdin)."""
        binary = self._binary or "claude"
        argv: list[str] = [
            binary,
            "--print",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--replay-user-messages",
        ]

        if self._remoteControl:
            argv.append("--remote-control")
            if self._remoteControlName:
                argv.append(self._remoteControlName)

        # Session: resume an existing conversation (recover context on respawn),
        # otherwise open a new one with a stable uuid we track.
        if self._sessionId:
            argv.extend(["--resume", self._sessionId])
        else:
            if not self._pendingSessionId:
                self._pendingSessionId = str(uuid.uuid4())
            argv.extend(["--session-id", self._pendingSessionId])

        if self._agent:
            argv.extend(["--agent", self._agent])
        if self._model:
            argv.extend(["--model", self._model])
        if self._effort:
            argv.extend(["--effort", self._effort])

        readOnly = self._readOnly or isReadOnlyAgent(self._agent)
        appendPermissionPolicy(
            argv,
            readOnly=readOnly,
            allowedTools=self._allowedTools,
            disallowedTools=self._disallowedTools,
        )

        return argv

    ##
    #  Process management
    ##

    def _spawn(self) -> bool:
        """Start the long-lived process. Returns False (and emits) on failure."""
        binary = self.resolveBinary()
        if not binary:
            self.signals.errorOccurred.emit(missingBinaryMessage())
            return False

        if not self._projectPath or not Path(self._projectPath).is_dir():
            self.signals.errorOccurred.emit(
                "No project directory set for the AI backend. Open a novelWriter project first."
            )
            return False

        argv = self.buildArgv()
        logger.info(
            "AI persistent session start: bin=%s agent=%s resume=%s remote=%s cwd=%s",
            binary,
            self._agent or "(default)",
            bool(self._sessionId),
            self._remoteControl,
            self._projectPath,
        )
        logger.debug("AI persistent argv: %s", _redactArgv(argv))

        proc = QProcess(self)
        proc.setProgram(binary)
        proc.setArguments(argv[1:])
        proc.setWorkingDirectory(str(self._projectPath))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        env = QProcessEnvironment.systemEnvironment()
        for key in (
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_CODE_BRIDGE_SESSION_ID",
            "CLAUDE_CODE_EXECPATH",
            "AI_AGENT",
        ):
            env.remove(key)
        proc.setProcessEnvironment(env)

        proc.readyReadStandardOutput.connect(self._onReadyReadStdout)
        proc.readyReadStandardError.connect(self._onReadyReadStderr)
        proc.finished.connect(self._onFinished)
        proc.errorOccurred.connect(self._onProcessError)

        self._process = proc
        self._stdoutBuffer = ""
        self._stderrBuffer = ""
        self._expectedExit = False
        proc.start()
        # QProcess queues writes made before the process is fully up, so a turn
        # can be written immediately after start() returns.
        self._dirty = False
        return True

    def _teardownProcess(self) -> None:
        """Stop the live process (graceful EOF → terminate → kill), blocking briefly.

        Only called on rare user-initiated events (new conversation, config
        change, shutdown), so a short synchronous wait is acceptable.
        """
        self._stopKillTimer()
        proc = self._process
        self._process = None
        if proc is None:
            return
        try:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.closeWriteChannel()  # EOF → claude exits promptly
                proc.terminate()
                if not proc.waitForFinished(1500):
                    proc.kill()
                    proc.waitForFinished(500)
        finally:
            proc.deleteLater()

    def _writeLine(self, line: str) -> None:
        """Write a single NDJSON line to the process stdin."""
        proc = self._process
        if proc is None:
            self.signals.errorOccurred.emit("AI session is not running.")
            self._busy = False
            return
        try:
            proc.write((line + "\n").encode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("AI stdin write failed: %s", exc)
            self.signals.errorOccurred.emit(f"Could not send to Claude Code: {exc}")
            self._busy = False

    ##
    #  Process slots
    ##

    @pyqtSlot()
    def _onReadyReadStdout(self) -> None:
        proc = self._process
        if proc is None:
            return
        raw = proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        if not raw:
            return
        self._stdoutBuffer += raw
        self._drainStdoutBuffer(final=False)

    @pyqtSlot()
    def _onReadyReadStderr(self) -> None:
        proc = self._process
        if proc is None:
            return
        raw = proc.readAllStandardError().data().decode("utf-8", errors="replace")
        if raw:
            self._stderrBuffer += raw
            for line in raw.splitlines():
                if line.strip():
                    logger.debug("claude stderr: %s", line[:300])

    @pyqtSlot()
    def _escalateCancel(self) -> None:
        """Interrupt did not land in time — terminate (context recovered on next turn)."""
        if self._busy and self._process is not None:
            logger.warning("AI interrupt timed out; terminating session (will --resume)")
            self._expectedExit = True
            self._teardownProcess()
            self._busy = False
            self._dirty = True
            self.signals.errorOccurred.emit("Turn cancelled.")
            self._cancelRequested = False

    def _stopKillTimer(self) -> None:
        if self._killTimer is not None:
            self._killTimer.stop()
            self._killTimer.deleteLater()
            self._killTimer = None

    @pyqtSlot(int, QProcess.ExitStatus)
    def _onFinished(self, exitCode: int, exitStatus: QProcess.ExitStatus) -> None:
        """Handle process exit (crash, EOF, or intentional teardown)."""
        self._stopKillTimer()
        self._drainStdoutBuffer(final=True)

        wasBusy = self._busy
        wasCancel = self._cancelRequested
        expected = self._expectedExit
        self._expectedExit = False
        self._busy = False
        self._process = None
        self._dirty = True  # force a respawn on the next turn
        self._pendingSessionId = None

        if expected:
            return

        stderrTail = self._stderrBuffer.strip()[-500:] if self._stderrBuffer else ""

        if wasCancel:
            logger.info("AI session ended after interrupt (exit=%s)", exitCode)
            self.signals.errorOccurred.emit("Turn cancelled.")
            self._cancelRequested = False
            return

        # Unexpected death mid-turn: surface a classified error. The session id
        # is retained so the next turn respawns with --resume and recovers.
        if wasBusy and not self._finishedCleanly:
            self.signals.errorOccurred.emit(
                classifyClaudeError(
                    exitCode=exitCode,
                    stderr=stderrTail,
                    processError="session ended unexpectedly",
                )
            )
        logger.info("AI persistent session finished: exit=%s session=%s", exitCode, self._sessionId)

    @pyqtSlot(QProcess.ProcessError)
    def _onProcessError(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._busy = False
            proc = self._process
            detail = proc.errorString() if proc else "unknown"
            self._process = None
            self._dirty = True
            self.signals.errorOccurred.emit(classifyClaudeError(processError=detail, stderr=self._stderrBuffer))
            logger.error("QProcess FailedToStart (persistent): %s", detail)

    ##
    #  Internal helpers
    ##

    def _drainStdoutBuffer(self, final: bool) -> None:
        while True:
            idx = self._stdoutBuffer.find("\n")
            if idx < 0:
                break
            line = self._stdoutBuffer[:idx]
            self._stdoutBuffer = self._stdoutBuffer[idx + 1 :]
            self._handleLine(line)
        if final and self._stdoutBuffer.strip():
            self._handleLine(self._stdoutBuffer)
            self._stdoutBuffer = ""

    def _handleLine(self, line: str) -> None:
        """Parse one NDJSON line; a ``result`` event ends the turn (process lives on)."""
        event = parseStreamLine(line)
        if event is None:
            return

        if event.kind == AiEventKind.SESSION_STARTED:
            sid = event.text or str(event.data.get("session_id") or "")
            if sid:
                self._sessionId = sid
                self._pendingSessionId = None
            model = str(event.data.get("model") or "").strip()
            if model:
                self._resolvedModel = model

        elif event.kind == AiEventKind.TEXT_CHUNK:
            self._accumulatedText += event.text

        elif event.kind == AiEventKind.TURN_COMPLETE:
            self._finishedCleanly = True
            self._busy = False
            self._stopKillTimer()
            sid = event.data.get("session_id")
            if sid:
                self._sessionId = str(sid)
            if event.text:
                self._accumulatedText = event.text
            model = str(event.data.get("model") or "").strip()
            if not model:
                usage = event.data.get("modelUsage") or {}
                if isinstance(usage, dict) and usage:
                    model = str(next(iter(usage.keys())))
            if model:
                self._resolvedModel = model
            if self._cancelRequested:
                # Turn ended as a result of our interrupt — report as cancelled.
                self._cancelRequested = False
                self.signals.errorOccurred.emit("Turn cancelled.")
                return

        elif event.kind == AiEventKind.ERROR:
            # Terminal result errors carry session_id / is_error; malformed-line
            # errors do not and must not clear busy.
            if event.data.get("is_error") is not None or event.data.get("session_id"):
                self._busy = False
                self._stopKillTimer()
                sid = event.data.get("session_id")
                if sid:
                    self._sessionId = str(sid)
                if self._cancelRequested:
                    self._cancelRequested = False
                    self.signals.errorOccurred.emit("Turn cancelled.")
                    return

        emitEventToSignals(event, self.signals)


def _redactArgv(argv: list[str]) -> list[str]:
    """Return argv safe for debug logs (truncate long prompt argument)."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-p" and i + 1 < len(argv):
            prompt = argv[i + 1]
            if len(prompt) > 80:
                prompt = prompt[:77] + "..."
            out.extend([a, prompt])
            i += 2
            continue
        out.append(a)
        i += 1
    return out
