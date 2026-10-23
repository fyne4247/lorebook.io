"""
novelWriter – AI Backend / Stream Parser Tests
==============================================

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

from pathlib import Path

import pytest

from novelwriter.ai.backend import (
    BASE_DISALLOWED_TOOLS,
    DEFAULT_WRITER_ALLOWED_TOOLS,
    AiBackendSignals,
    AiEventKind,
    buildDisallowedTools,
    emitEventToSignals,
    formatTokenCount,
    isReadOnlyAgent,
    manuscriptDenyRules,
    parseStreamLine,
    parseStreamLines,
    summarizeTurnUsage,
)

FIXTURES = Path(__file__).parent / "fixtures"


##
#  Helpers
##


def _load_ndjson(name: str) -> list[dict]:
    path = FIXTURES / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events_from_fixture(name: str) -> list:
    path = FIXTURES / name
    return parseStreamLines(path.read_text(encoding="utf-8"))


##
#  parseStreamLine — unit cases
##


class TestParseStreamLine:
    def test_blank_returns_none(self):
        assert parseStreamLine("") is None
        assert parseStreamLine("   \n") is None

    def test_malformed_json_is_error(self):
        ev = parseStreamLine("{not json")
        assert ev is not None
        assert ev.kind == AiEventKind.ERROR
        assert "Malformed" in ev.text

    def test_unknown_type_tolerated(self):
        ev = parseStreamLine(json.dumps({"type": "future_event_type", "foo": 1}))
        assert ev is not None
        assert ev.kind == AiEventKind.UNKNOWN
        assert ev.text == "future_event_type"

    def test_non_object_json(self):
        ev = parseStreamLine("[1, 2, 3]")
        assert ev is not None
        assert ev.kind == AiEventKind.UNKNOWN

    def test_session_init(self):
        line = json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": "abc-123",
            "model": "claude-haiku-4-5",
            "cwd": "/tmp/proj",
            "permissionMode": "dontAsk",
            "agents": ["critic", "muse"],
            "tools": ["Read", "Edit"],
            "claude_code_version": "2.1.206",
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.SESSION_STARTED
        assert ev.text == "abc-123"
        assert ev.data["model"] == "claude-haiku-4-5"
        assert "muse" in ev.data["agents"]

    def test_text_delta_chunk(self):
        line = json.dumps({
            "type": "stream_event",
            "session_id": "s",
            "event": {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.TEXT_CHUNK
        assert ev.text == "Hello"

    def test_thinking_delta_ignored(self):
        line = json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "hmm"},
            },
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.IGNORE

    def test_tool_use_start(self):
        line = json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "Read",
                    "input": {},
                },
            },
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.TOOL_ACTIVITY
        assert ev.text == "Read"
        assert ev.data["phase"] == "start"

    def test_result_success(self):
        line = json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Final answer.",
            "session_id": "sid",
            "total_cost_usd": 0.0123,
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "stop_reason": "end_turn",
            "permission_denials": [],
            "duration_ms": 1500,
            "num_turns": 2,
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.TURN_COMPLETE
        assert ev.text == "Final answer."
        assert ev.data["total_cost_usd"] == 0.0123
        assert ev.data["session_id"] == "sid"
        assert ev.data["usage"]["output_tokens"] == 20

    def test_summarize_turn_usage_model_usage(self):
        meta = {
            "total_cost_usd": 0.0278,
            "usage": {
                "input_tokens": 18,
                "output_tokens": 446,
                "cache_read_input_tokens": 32375,
                "cache_creation_input_tokens": 10828,
            },
            "modelUsage": {
                "claude-haiku-4-5-20251001": {
                    "inputTokens": 565,
                    "outputTokens": 465,
                    "cacheReadInputTokens": 32375,
                    "cacheCreationInputTokens": 10828,
                    "contextWindow": 200000,
                }
            },
        }
        u = summarizeTurnUsage(meta)
        assert u.costUsd == pytest.approx(0.0278)
        assert u.inputTokens == 565
        assert u.outputTokens == 465
        assert u.cacheReadTokens == 32375
        assert u.contextWindow == 200000
        assert u.contextUsed == 565 + 32375 + 10828
        assert u.contextPercent is not None
        assert 20 < u.contextPercent < 25
        assert formatTokenCount(43768).endswith("k")

    def test_summarize_turn_usage_usage_only(self):
        u = summarizeTurnUsage({
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "total_cost_usd": 0.01,
        })
        assert u.inputTokens == 100
        assert u.outputTokens == 50
        assert u.contextUsed == 100
        assert u.contextWindow == 0

    def test_result_error(self):
        line = json.dumps({
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": "something broke",
            "session_id": "sid",
            "permission_denials": [],
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.ERROR
        assert "broke" in ev.text

    def test_rate_limit_status(self):
        line = json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed"},
            "session_id": "s",
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.STATUS
        assert ev.text == "rate_limit"

    def test_system_status(self):
        line = json.dumps({
            "type": "system",
            "subtype": "status",
            "status": "compacting",
            "session_id": "s",
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.STATUS
        assert ev.text == "compacting"

    def test_user_tool_error_activity(self):
        line = json.dumps({
            "type": "user",
            "tool_use_result": "Error: Permission to use Edit has been denied",
            "session_id": "s",
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.TOOL_ACTIVITY
        assert "denied" in ev.text.lower() or "Permission" in ev.text

    def test_assistant_tool_use(self):
        line = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Agent", "id": "x"},
                ],
            },
        })
        ev = parseStreamLine(line)
        assert ev is not None
        assert ev.kind == AiEventKind.TOOL_ACTIVITY
        assert ev.text == "Agent"


##
#  Phase-0 fixture integration
##


class TestPhase0Fixtures:
    def test_sample_events_fixture(self):
        events = _events_from_fixture("sample_events.ndjson")
        kinds = [e.kind for e in events]
        assert AiEventKind.SESSION_STARTED in kinds
        assert AiEventKind.TEXT_CHUNK in kinds
        assert AiEventKind.TURN_COMPLETE in kinds
        # Unknown type must not raise
        assert AiEventKind.UNKNOWN in kinds

        session = next(e for e in events if e.kind == AiEventKind.SESSION_STARTED)
        assert session.text  # non-empty session id

        chunks = [e.text for e in events if e.kind == AiEventKind.TEXT_CHUNK]
        assert "".join(chunks)  # some streamed text

        result = next(e for e in events if e.kind == AiEventKind.TURN_COMPLETE)
        assert result.data.get("total_cost_usd") is not None

    def test_t1_full_fixture(self):
        """Full Phase-0 t1.ndjson: init → tools → text → result."""
        events = _events_from_fixture("t1.ndjson")
        assert events

        # Never raises; every line produces something or None (already filtered).
        kinds = {e.kind for e in events}
        assert AiEventKind.SESSION_STARTED in kinds
        assert AiEventKind.TURN_COMPLETE in kinds
        assert AiEventKind.TEXT_CHUNK in kinds
        assert AiEventKind.TOOL_ACTIVITY in kinds

        session = next(e for e in events if e.kind == AiEventKind.SESSION_STARTED)
        assert len(session.text) > 10

        result = next(e for e in events if e.kind == AiEventKind.TURN_COMPLETE)
        assert "Alice" in result.text or result.text  # t1 asked about Alice note
        assert result.data.get("is_error") is False
        assert isinstance(result.data.get("permission_denials"), list)

        # Accumulated text deltas should be a prefix/subset of the final result.
        streamed = "".join(e.text for e in events if e.kind == AiEventKind.TEXT_CHUNK)
        assert streamed
        # Final result contains the streamed content (may equal or be the full text).
        assert streamed in result.text or result.text.startswith(streamed[:20])

    def test_t8_accept_edits_fixture(self):
        """t8: writing-agent style run with tool activity and a result."""
        events = _events_from_fixture("t8.ndjson")
        tools = [e.text for e in events if e.kind == AiEventKind.TOOL_ACTIVITY]
        # Should have seen Read and/or Edit
        assert any(t in ("Read", "Edit", "Write") for t in tools)

        result = next(e for e in events if e.kind == AiEventKind.TURN_COMPLETE)
        assert result.data.get("total_cost_usd") is not None
        assert result.data.get("session_id")

    def test_every_fixture_line_parseable(self):
        """Every line in every Phase-0 fixture must parse without raising."""
        for path in FIXTURES.glob("*.ndjson"):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    ev = parseStreamLine(line)
                except Exception as exc:  # pragma: no cover
                    pytest.fail(f"{path.name}:{i} raised {exc}")
                assert ev is not None


##
#  Permission helpers
##


class TestPermissionHelpers:
    def test_read_only_agents(self):
        assert isReadOnlyAgent("critic") is True
        assert isReadOnlyAgent("editor") is True
        assert isReadOnlyAgent("reader-sim") is True
        assert isReadOnlyAgent("character-sim") is True
        assert isReadOnlyAgent("continuity-checker") is True
        assert isReadOnlyAgent("muse") is False
        assert isReadOnlyAgent("chronicler") is False
        assert isReadOnlyAgent("brainstormer") is False
        assert isReadOnlyAgent("") is False
        assert isReadOnlyAgent("CRITIC") is True  # case-insensitive

    def test_writer_allowed_includes_agent_not_task(self):
        assert "Agent" in DEFAULT_WRITER_ALLOWED_TOOLS
        assert "Task" not in DEFAULT_WRITER_ALLOWED_TOOLS
        assert "Edit" in DEFAULT_WRITER_ALLOWED_TOOLS
        assert "Write" in DEFAULT_WRITER_ALLOWED_TOOLS

    def test_base_disallowed(self):
        assert "Bash" in BASE_DISALLOWED_TOOLS
        assert "Edit(nwProject.nwx)" in BASE_DISALLOWED_TOOLS
        assert "Write(nwProject.nwx)" in BASE_DISALLOWED_TOOLS
        assert "Edit(meta/**)" in BASE_DISALLOWED_TOOLS

    def test_manuscript_deny_rules_bare_handle(self):
        rules = manuscriptDenyRules(["bb2c23b3c42cc", "ae7339df26ded"])
        assert "Edit(content/bb2c23b3c42cc.nwd)" in rules
        assert "Write(content/bb2c23b3c42cc.nwd)" in rules
        assert "Edit(content/ae7339df26ded.nwd)" in rules
        assert "Write(content/ae7339df26ded.nwd)" in rules

    def test_manuscript_deny_rules_path_forms(self):
        rules = manuscriptDenyRules([
            "content/abc.nwd",
            "abc.nwd",
            "  ",  # skipped
        ])
        assert rules.count("Edit(content/abc.nwd)") == 2
        assert rules.count("Write(content/abc.nwd)") == 2

    def test_build_disallowed_tools_combines(self):
        rules = buildDisallowedTools(["deadbeef"])
        assert "Bash" in rules
        assert "Edit(content/deadbeef.nwd)" in rules
        assert "Write(content/deadbeef.nwd)" in rules


##
#  Signal dispatch
##


class TestEmitEventToSignals:
    def test_dispatch_mapping(self, qtbot):
        hub = AiBackendSignals()
        sessions: list[str] = []
        chunks: list[str] = []
        tools: list[str] = []
        completes: list[tuple] = []
        errors: list[str] = []

        hub.sessionStarted.connect(sessions.append)
        hub.chunkReceived.connect(chunks.append)
        hub.toolActivity.connect(tools.append)
        hub.turnComplete.connect(lambda t, d: completes.append((t, d)))
        hub.errorOccurred.connect(errors.append)

        for line in (FIXTURES / "sample_events.ndjson").read_text().splitlines():
            if ev := parseStreamLine(line):
                emitEventToSignals(ev, hub)

        assert sessions
        assert sessions[0]
        assert chunks
        assert completes
        text, meta = completes[0]
        assert isinstance(text, str)
        assert "total_cost_usd" in meta or meta.get("session_id")
        assert not errors  # sample fixture is a success path
