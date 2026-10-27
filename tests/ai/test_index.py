"""
novelWriter – Smart Index (Phase 7) Tests
=========================================

This file is a part of novelWriter
Copyright (C) 2026 novelWriter contributors
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from novelwriter.ai.index import (
    buildExpandBlocks,
    expandWikiTarget,
    extractBlurb,
    generateHandleIndex,
    generateSmartIndex,
    parseExpandRequests,
    resolveWikiLink,
    scanWikiLinks,
    stripNwdMeta,
    writeProjectIndex,
)
from novelwriter.ai.setup import setupProjectAi
from novelwriter.core.project import NWProject
from novelwriter.enum import nwItemClass

from tests.helpers import buildTestProject


class TestWikiParse:
    def test_scan_links(self):
        text = "See [[Marla Vance]] and [[The Warren|bar]] plus [[Marla Vance]] again."
        assert scanWikiLinks(text) == ["Marla Vance", "The Warren"]

    def test_parse_expand(self):
        assert parseExpandRequests("Expand [[Marla Vance]] please") == ["Marla Vance"]
        assert parseExpandRequests("expand [[Fish]]") == ["Fish"]
        assert parseExpandRequests("Just chatting about [[Fish]]") == []  # not expand

    def test_strip_meta_and_blurb(self):
        raw = (
            "%%~name: Jane\n%%~path: a/b\n%%~kind: CHARACTER/NOTE\n"
            "%Short: A heroine with a secret.\n\n# Jane\n\nProse here.\n"
        )
        body = stripNwdMeta(raw)
        assert not body.startswith("%%~")
        assert extractBlurb(body) == "A heroine with a secret."

    def test_parse_expand_variants_and_clip(self):
        assert parseExpandRequests("Expand [[One]]\nExpand [[Two|alias]] and [[One]]") == ["One", "Two"]
        assert parseExpandRequests("Expand\n[[Later]]") == ["Later"]
        assert parseExpandRequests("Expand the note [[Later]]") == ["Later"]
        assert parseExpandRequests("no request here") == []
        assert extractBlurb("%Synopsis: A long summary.") == "A long summary."
        assert extractBlurb("# heading\n@tag: one\n%%~meta\nProse line") == "Prose line"
        assert extractBlurb("%Short: " + "x" * 200, maxLen=20).endswith("…")


class TestGenerateIndex:
    def test_collect_fallbacks_and_legacy_dispatch(self, tmp_path: Path, monkeypatch):
        from novelwriter.ai import index

        content = tmp_path / "content"
        content.mkdir()
        (tmp_path / "nwProject.nwx").write_text(
            "<novelWriterXML><content>"
            '<item handle="missing" class="WORLD" type="FILE"><name>Fallback title</name></item>'
            '<item handle="blank" class="PLOT" type="FILE"/>'
            '<item handle="skip" class="PLOT" type="FOLDER"/>'
            '<item class="PLOT" type="FILE"/>'
            "</content></novelWriterXML>",
            encoding="utf-8",
        )
        entries = index.collectProjectEntries(tmp_path)
        assert [(entry.handle, entry.title) for entry in entries] == [
            ("missing", "Fallback title"),
            ("blank", "blank"),
        ]
        assert index.writeProjectIndex(tmp_path, smart=False).is_file()
        assert index.collectProjectEntries(tmp_path / "absent") == []

        missing = content / "broken.nwd"
        missing.write_text("%%~name: Broken\nBody", encoding="utf-8")
        nwx = tmp_path / "nwProject.nwx"
        nwx.write_text(
            '<novelWriterXML><item handle="broken" class="WORLD" type="FILE">'
            "<name>Named</name></item></novelWriterXML>",
            encoding="utf-8",
        )
        originalReadText = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == missing:
                raise OSError("read failed")
            return originalReadText(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
        assert index.collectProjectEntries(tmp_path)[0].title == "Named"

    def test_resolver_fallbacks_and_unreadable_expansion(self, tmp_path: Path, monkeypatch):

        content = tmp_path / "content"
        content.mkdir()
        (content / "h.nwd").write_text("%%~name: Alpha Beta\n# Alpha Beta\n", encoding="utf-8")
        (tmp_path / "nwProject.nwx").write_text(
            '<novelWriterXML><item handle="h" class="WORLD" type="FILE">'
            "<name>Alpha Beta</name></item></novelWriterXML>",
            encoding="utf-8",
        )
        assert resolveWikiLink(tmp_path, " ") is None
        assert resolveWikiLink(tmp_path, "Alpha") is not None
        assert resolveWikiLink(tmp_path, "h").handle == "h"
        assert expandWikiTarget(tmp_path, "missing") is None
        assert expandWikiTarget(tmp_path, "Alpha Beta")[2] == "# Alpha Beta"

        target = content / "h.nwd"
        originalReadText = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == target:
                raise OSError("read failed")
            return originalReadText(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
        assert expandWikiTarget(tmp_path, "Alpha Beta")[2] == ""

        target.unlink()
        assert expandWikiTarget(tmp_path, "Alpha Beta")[2] == ""

    def test_index_ownership_preserves_custom_and_edited_files(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "one.nwd").write_text("%%~name: First\n# First\n", encoding="utf-8")
        nwx = tmp_path / "nwProject.nwx"
        nwx.write_text(
            '<novelWriterXML><content count="1">'
            '<item handle="one" class="CHARACTER" type="FILE"><name>First</name></item>'
            "</content></novelWriterXML>",
            encoding="utf-8",
        )
        path = tmp_path / "INDEX.md"
        path.write_text("My index\n", encoding="utf-8")

        generateSmartIndex(tmp_path)
        assert path.read_text(encoding="utf-8") == "My index\n"

        path.unlink()
        generateSmartIndex(tmp_path)
        generated = path.read_text(encoding="utf-8")
        assert "novelWriter managed AI index sha256:" in generated.splitlines()[0]
        nwx.write_text(
            '<novelWriterXML><content count="1">'
            '<item handle="one" class="CHARACTER" type="FILE"><name>Updated</name></item>'
            "</content></novelWriterXML>",
            encoding="utf-8",
        )
        (content / "one.nwd").write_text("%%~name: Updated\n# Updated\n", encoding="utf-8")
        generateSmartIndex(tmp_path)
        assert "Updated" in path.read_text(encoding="utf-8")

        path.write_text(path.read_text(encoding="utf-8") + "\nMy additions\n", encoding="utf-8")
        nwx.write_text(
            '<novelWriterXML><content count="1">'
            '<item handle="one" class="CHARACTER" type="FILE"><name>Later</name></item>'
            "</content></novelWriterXML>",
            encoding="utf-8",
        )
        (content / "one.nwd").write_text("%%~name: Later\n# Later\n", encoding="utf-8")
        generateSmartIndex(tmp_path)
        assert "My additions" in path.read_text(encoding="utf-8")
        assert "Later" not in path.read_text(encoding="utf-8")

    def test_index_unreadable_custom_file_is_preserved(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "INDEX.md"
        path.write_text("Custom index\n", encoding="utf-8")
        originalOpen = Path.open

        def failRead(target: Path, *args, **kwargs):
            if target == path:
                raise OSError("injected read failure")
            return originalOpen(target, *args, **kwargs)

        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "open", failRead)
            generateHandleIndex(tmp_path)

        assert path.read_text(encoding="utf-8") == "Custom index\n"

    def test_smart_index_shape(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "abc.nwd").write_text(
            "%%~name: Marla Vance\n%%~kind: CHARACTER/NOTE\n"
            "%Short: Sarcastic raccoon bartender.\n\n# Marla\n\n@tag: Marla\n",
            encoding="utf-8",
        )
        (tmp_path / "nwProject.nwx").write_text(
            '<?xml version="1.0"?>\n<novelWriterXML>\n'
            '  <content count="1">\n'
            '    <item handle="abc" class="CHARACTER" type="FILE" layout="NOTE">'
            "<name>Marla Vance</name></item>\n"
            "  </content>\n</novelWriterXML>\n",
            encoding="utf-8",
        )
        path = generateSmartIndex(tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "[[Marla Vance]]" in text
        assert "Sarcastic raccoon" in text
        assert "content/abc.nwd" in text
        assert "## Characters" in text

    def test_legacy_handle_index(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "xyz.nwd").write_text("%%~name: Spot\n# Spot\n", encoding="utf-8")
        (tmp_path / "nwProject.nwx").write_text(
            '<?xml version="1.0"?>\n<novelWriterXML>\n'
            '  <content count="1">\n'
            '    <item handle="xyz" class="CHARACTER" type="FILE" layout="NOTE">'
            "<name>Spot</name></item>\n"
            "  </content>\n</novelWriterXML>\n",
            encoding="utf-8",
        )
        text = generateHandleIndex(tmp_path).read_text(encoding="utf-8")
        assert "[[Spot]]" not in text
        assert "`content/xyz.nwd`" in text


class TestResolveExpand:
    def test_resolve_and_expand(self, tmp_path: Path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "h1.nwd").write_text(
            "%%~name: The Warren\n%%~kind: WORLD/NOTE\n# The Warren\n\n@tag: Warren\n\nAn underground bar.\n",
            encoding="utf-8",
        )
        (tmp_path / "nwProject.nwx").write_text(
            '<?xml version="1.0"?>\n<novelWriterXML>\n'
            '  <content count="1">\n'
            '    <item handle="h1" class="WORLD" type="FILE" layout="NOTE">'
            "<name>The Warren</name></item>\n"
            "  </content>\n</novelWriterXML>\n",
            encoding="utf-8",
        )
        e = resolveWikiLink(tmp_path, "The Warren")
        assert e is not None
        assert e.handle == "h1"
        assert resolveWikiLink(tmp_path, "Warren") is not None  # via @tag

        title, handle, body = expandWikiTarget(tmp_path, "The Warren")
        assert title == "The Warren"
        assert handle == "h1"
        assert "underground bar" in body
        assert "%%~" not in body

        blocks = buildExpandBlocks(tmp_path, ["The Warren", "Missing"])
        assert '<document title="The Warren"' in blocks
        assert "expand failed" in blocks


@pytest.mark.core
def testSetupWritesSmartIndex(projPath, mockGUI, mockRnd):
    """Write the generated project index during AI setup."""
    project = NWProject()
    buildTestProject(project, projPath)
    # Add a character with short blurb
    root = project.tree.findRoot(nwItemClass.CHARACTER)
    h = project.newFile("Hero", root)
    project.writeNewFile(h, 1, False, "%Short: Brave and tired.\n\n@tag: Hero\n")
    project.saveProject()

    result = setupProjectAi(project)
    assert result.ok
    text = (projPath / "INDEX.md").read_text(encoding="utf-8")
    # Default CONFIG.aiSmartIndex is True
    assert "[[Hero]]" in text or "Hero" in text
    assert "INDEX.md" in (projPath / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Expand" in (projPath / "CLAUDE.md").read_text(encoding="utf-8")


@pytest.mark.gui
def testExpandInjectedInPrompt(qtbot, mockGUIwithTheme, tmp_path, mockGUI, mockRnd):
    """Expand [[Name]] is injected as <document> before the user question."""
    from tests.gui.test_gui_aichat import _makePanel

    content = tmp_path / "content"
    content.mkdir()
    (content / "c1.nwd").write_text(
        "%%~name: Marla Vance\n# Marla Vance\n\nFull character bible here.\n",
        encoding="utf-8",
    )
    (tmp_path / "nwProject.nwx").write_text(
        '<?xml version="1.0"?>\n<novelWriterXML>\n'
        '  <content count="1">\n'
        '    <item handle="c1" class="CHARACTER" type="FILE" layout="NOTE">'
        "<name>Marla Vance</name></item>\n"
        "  </content>\n</novelWriterXML>\n",
        encoding="utf-8",
    )
    writeProjectIndex(tmp_path, smart=True)

    panel, fake, dialog = _makePanel(qtbot, mockGUIwithTheme, tmp_path=tmp_path)
    panel.includeSelection.setChecked(False)
    panel.inputEdit.setPlainText("Expand [[Marla Vance]] and summarise her.")
    with qtbot.waitSignal(fake.signals.turnComplete, timeout=2000):
        panel.btnSend.click()
    prompt = fake.prompts[0]
    assert '<document title="Marla Vance"' in prompt
    assert "Full character bible" in prompt
    assert "summarise her" in prompt
    dialog.close()
