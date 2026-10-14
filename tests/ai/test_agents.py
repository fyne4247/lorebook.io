"""
novelWriter – AI Agent Scanner Tests
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

import re

from pathlib import Path

from novelwriter.ai import agents
from novelwriter.ai.agents import (
    isProjectAiReady,
    parseAgentFrontmatter,
    scanProjectAgents,
)


class TestParseAgentFrontmatter:
    def test_inline_description(self):
        text = "---\nname: critic\ndescription: A sharp critic\nmodel: sonnet\n---\n\n# Body\n"
        name, desc = parseAgentFrontmatter(text)
        assert name == "critic"
        assert desc == "A sharp critic"

    def test_folded_description(self):
        text = (
            "---\n"
            "name: critic\n"
            "description: >\n"
            "  Adversarial prose critic: provides structured critique\n"
            "  across the four reader reward channels.\n"
            "model: sonnet\n"
            "---\n\n# Critic\n"
        )
        name, desc = parseAgentFrontmatter(text)
        assert name == "critic"
        assert "Adversarial prose critic" in desc
        assert "reward channels" in desc
        assert "\n" not in desc  # folded to one line

    def test_missing_frontmatter(self):
        assert parseAgentFrontmatter("# just a heading\n") == ("", "")

    def test_name_only(self):
        text = "---\nname: muse\n---\n"
        name, desc = parseAgentFrontmatter(text)
        assert name == "muse"
        assert desc == ""

    def test_description_without_name_and_bare_fold_marker(self, monkeypatch):
        assert parseAgentFrontmatter("---\ndescription: Helpful\n---\n") == ("", "Helpful")
        monkeypatch.setattr(agents, "_DESC_FOLDED_RE", re.compile(r"never matches"))
        assert parseAgentFrontmatter("---\ndescription: >\n---\n") == ("", "")


class TestScanProjectAgents:
    def test_empty_project(self, tmp_path: Path):
        assert scanProjectAgents(tmp_path) == []
        assert scanProjectAgents(None) == []
        assert isProjectAiReady(tmp_path) is False
        assert isProjectAiReady(None) is False

    def test_scan_agent_files(self, tmp_path: Path):
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "critic.md").write_text(
            "---\nname: critic\ndescription: >\n  Hard-hitting critique.\n---\n# Critic\n",
            encoding="utf-8",
        )
        (agents / "muse.md").write_text(
            "---\nname: muse\ndescription: Editorial lead\n---\n",
            encoding="utf-8",
        )
        (agents / "notes.txt").write_text("ignored", encoding="utf-8")

        result = scanProjectAgents(tmp_path)
        assert isProjectAiReady(tmp_path) is True
        names = [a.name for a in result]
        assert names == ["critic", "muse"]  # sorted
        assert "Hard-hitting" in result[0].description
        assert result[1].description == "Editorial lead"

    def test_fallback_to_stem(self, tmp_path: Path):
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "mystery.md").write_text("# no frontmatter\n", encoding="utf-8")
        result = scanProjectAgents(tmp_path)
        assert len(result) == 1
        assert result[0].name == "mystery"

    def test_unreadable_agent_is_skipped(self, tmp_path: Path, monkeypatch):
        agentsDir = tmp_path / ".claude" / "agents"
        agentsDir.mkdir(parents=True)
        broken = agentsDir / "broken.md"
        broken.write_text("unreadable", encoding="utf-8")
        (agentsDir / "good.md").write_text("---\nname: good\n---\n", encoding="utf-8")
        readText = Path.read_text

        def readAgent(path: Path, *args, **kwargs):
            if path == broken:
                raise OSError("read denied")
            return readText(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", readAgent)
        result = scanProjectAgents(tmp_path)
        assert [agent.name for agent in result] == ["good"]
