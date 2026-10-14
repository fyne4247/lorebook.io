"""
novelWriter – AI Project Setup Tests
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

from pathlib import Path

import pytest

from novelwriter.ai.agents import isProjectAiReady, scanProjectAgents
from novelwriter.ai.setup import (
    defaultAiAssetsRoot,
    installClaudeTree,
    listManuscriptHandles,
    setupProjectAi,
    writeHandleIndex,
    writeProjectClaudeMd,
)
from novelwriter.core.project import NWProject
from novelwriter.enum import nwItemClass

from tests.helpers import buildTestProject


class TestInstallClaudeTree:
    def test_default_assets_exist(self):
        root = defaultAiAssetsRoot()
        packagedRoot = Path(__file__).resolve().parents[2] / "novelwriter" / "assets" / "ai" / "claude"
        assert root.resolve() == packagedRoot.resolve()
        assert root.resolve().is_relative_to(Path(__file__).resolve().parents[2])
        assert (root / "agents").is_dir()
        assert (root / "skills").is_dir()
        assert any((root / "agents").glob("*.md"))

    def test_install_into_project(self, tmp_path: Path):
        src = defaultAiAssetsRoot()
        nAgents, nSkills = installClaudeTree(src, tmp_path, overwrite=True)
        assert nAgents >= 10
        assert nSkills > 0
        assert (tmp_path / ".claude" / "agents" / "critic.md").is_file()
        assert isProjectAiReady(tmp_path) is True
        agents = scanProjectAgents(tmp_path)
        names = {a.name for a in agents}
        assert "critic" in names
        assert "muse" in names

    def test_refresh_prunes_stale_and_overwrites(self, tmp_path: Path):
        src = tmp_path / "source"
        (src / "agents").mkdir(parents=True)
        (src / "skills" / "writing").mkdir(parents=True)
        museSource = src / "agents" / "muse.md"
        retiredSource = src / "agents" / "retired.md"
        museSource.write_text("bundled muse v1", encoding="utf-8")
        retiredSource.write_text("bundled retired", encoding="utf-8")
        (src / "skills" / "writing" / "SKILL.md").write_text("bundled skill", encoding="utf-8")

        installClaudeTree(src, tmp_path, overwrite=False)
        agentsDir = tmp_path / ".claude" / "agents"
        stale = agentsDir / "retired.md"
        customAgent = agentsDir / "my-agent.md"
        customSkill = tmp_path / ".claude" / "skills" / "writing" / "custom" / "SKILL.md"
        customAgent.write_text("mine", encoding="utf-8")
        customSkill.parent.mkdir(parents=True)
        customSkill.write_text("mine", encoding="utf-8")
        muse = agentsDir / "muse.md"
        museSource.write_text("bundled muse v2", encoding="utf-8")
        retiredSource.unlink()

        installClaudeTree(src, tmp_path, overwrite=True, mirror=True)

        assert not stale.exists()  # pruned
        assert muse.read_text(encoding="utf-8") == "bundled muse v2"  # updated
        assert customAgent.read_text(encoding="utf-8") == "mine"
        assert customSkill.read_text(encoding="utf-8") == "mine"


class TestIndexAndClaudeMd:
    def test_write_claude_md_preserves_custom_and_edited_files(self, tmp_path: Path, monkeypatch):
        from novelwriter.ai import setup

        path = tmp_path / "CLAUDE.md"
        path.write_text("My project instructions\n", encoding="utf-8")
        writeProjectClaudeMd(tmp_path)
        assert path.read_text(encoding="utf-8") == "My project instructions\n"

        path.unlink()
        writeProjectClaudeMd(tmp_path)
        generated = path.read_text(encoding="utf-8")
        monkeypatch.setattr(setup, "_CLAUDE_MD_TEMPLATE", "Updated app instructions")
        writeProjectClaudeMd(tmp_path)
        assert "Updated app instructions" in path.read_text(encoding="utf-8")

        path.write_text(path.read_text(encoding="utf-8") + "\nMy additions\n", encoding="utf-8")
        monkeypatch.setattr(setup, "_CLAUDE_MD_TEMPLATE", "Later app instructions")
        writeProjectClaudeMd(tmp_path)
        assert "My additions" in path.read_text(encoding="utf-8")
        assert "Later app instructions" not in path.read_text(encoding="utf-8")
        assert generated != path.read_text(encoding="utf-8")

    def test_write_index_from_nwx(self, tmp_path: Path):
        # Minimal nwx + content
        content = tmp_path / "content"
        content.mkdir()
        (content / "abc123.nwd").write_text(
            "%%~name: Jane Smith\n%%~path: x/abc123\n%%~kind: CHARACTER/NOTE\n# Jane\n",
            encoding="utf-8",
        )
        (tmp_path / "nwProject.nwx").write_text(
            '<?xml version="1.0"?>\n'
            "<novelWriterXML>\n"
            '  <content count="1">\n'
            '    <item handle="abc123" class="CHARACTER" type="FILE" layout="NOTE">\n'
            "      <name>Jane Smith</name>\n"
            "    </item>\n"
            '    <item handle="novel1" class="NOVEL" type="FILE" layout="DOCUMENT">\n'
            "      <name>Chapter 1</name>\n"
            "    </item>\n"
            "  </content>\n"
            "</novelWriterXML>\n",
            encoding="utf-8",
        )
        (content / "novel1.nwd").write_text("%%~name: Chapter 1\n# Chapter 1\n", encoding="utf-8")

        path = writeHandleIndex(tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "Jane Smith" in text
        assert "content/abc123.nwd" in text
        # Smart index uses "Manuscript" section; legacy used "NOVEL"
        assert "NOVEL" in text or "Manuscript" in text
        assert "[[Jane Smith]]" in text or "Jane Smith" in text

        handles = listManuscriptHandles(tmp_path)
        assert "novel1" in handles
        assert "abc123" not in handles

    def test_write_claude_md(self, tmp_path: Path):
        path = writeProjectClaudeMd(tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "novelWriter managed AI instructions sha256:" in text.splitlines()[0]
        assert "novelWriter" in text
        assert "_inbox/" in text
        assert "%%~" in text
        assert "INDEX.md" in text


@pytest.mark.core
def testSetupPreservesCustomRootFilesOnInstallAndRefresh(projPath, mockGUI, mockRnd):
    project = NWProject()
    buildTestProject(project, projPath)
    claudePath = projPath / "CLAUDE.md"
    indexPath = projPath / "INDEX.md"
    claudePath.write_text("Custom project instructions\n", encoding="utf-8")
    indexPath.write_text("Custom project index\n", encoding="utf-8")

    first = setupProjectAi(project)
    second = setupProjectAi(project, refresh=True)

    assert first.ok and second.ok
    assert claudePath.read_text(encoding="utf-8") == "Custom project instructions\n"
    assert indexPath.read_text(encoding="utf-8") == "Custom project index\n"


@pytest.mark.core
def testSetupReportsEveryRequiredStepFailure(projPath, mockGUI, mockRnd, monkeypatch):
    from novelwriter.ai import setup

    project = NWProject()
    buildTestProject(project, projPath)
    (projPath / "_inbox").write_text("block directory creation", encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise OSError("injected setup failure")

    monkeypatch.setattr(setup, "ensureKbRoots", fail)
    monkeypatch.setattr(setup, "writeHandleIndex", fail)
    monkeypatch.setattr(setup, "writeProjectClaudeMd", fail)

    result = setupProjectAi(project)

    assert result.ok is False
    assert result.agentsInstalled > 0
    assert len(result.errors) == 4
    assert result.message.startswith("AI setup incomplete:")


@pytest.mark.core
def testSetupProjectAi_Full(projPath, mockGUI, mockRnd):
    """End-to-end setup against a real NWProject."""
    project = NWProject()
    buildTestProject(project, projPath)

    # Initially no AI
    assert isProjectAiReady(projPath) is False

    result = setupProjectAi(project)
    assert result.ok is True
    assert result.agentsInstalled >= 10
    assert result.claudeMdWritten is True
    assert result.indexWritten is True
    assert isProjectAiReady(projPath) is True
    assert (projPath / "CLAUDE.md").is_file()
    assert (projPath / "INDEX.md").is_file()
    assert (projPath / "_inbox").is_dir()
    assert (projPath / ".claude" / "agents" / "muse.md").is_file()

    # Kb roots that were missing should now exist
    for cls in (nwItemClass.CHARACTER, nwItemClass.WORLD, nwItemClass.TIMELINE, nwItemClass.OBJECT, nwItemClass.PLOT):
        assert project.tree.findRoot(cls) is not None

    # Second run without refresh still succeeds
    result2 = setupProjectAi(project, refresh=False)
    assert result2.ok is True
