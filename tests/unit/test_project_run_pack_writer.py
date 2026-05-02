"""Unit tests for app.services.project_run_pack_writer."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.project_run_pack_writer import (
    DEFAULT_SECTION,
    RunPackProposal,
    render_pack,
    render_section,
    replace_or_append_section,
    write_run_pack_proposals,
)


def test_render_pack_includes_tag_line_summary_and_launch_prompt():
    pack = RunPackProposal(
        title="fix flaky channel scroll",
        summary="ResizeObserver fires twice on initial mount.",
        category="code_bug",
        confidence="high",
        launch_prompt="Investigate ChatMessageArea scroll race.",
    )
    out = render_pack(pack)
    assert out.startswith("### fix flaky channel scroll\n")
    assert "**category:** code_bug" in out
    assert "**confidence:** high" in out
    assert "**status:** proposed" in out
    assert "ResizeObserver fires twice on initial mount." in out
    assert "**launch_prompt:**" in out
    assert "```\nInvestigate ChatMessageArea scroll race.\n```" in out


def test_render_pack_normalizes_invalid_category_and_confidence():
    pack = RunPackProposal.from_dict({
        "title": "x", "summary": "", "category": "bogus", "confidence": "ultra"
    })
    assert pack.category == "other"
    assert pack.confidence == "medium"


def test_render_pack_emits_blueprint_impact_and_source_ids():
    pack = RunPackProposal(
        title="ship dep stack",
        category="config_issue",
        confidence="medium",
        blueprint_impact=True,
        source_item_ids=("a-1", "b-2"),
    )
    out = render_pack(pack)
    assert "**blueprint_impact:** yes" in out
    assert "**source_item_ids:** a-1, b-2" in out


def test_render_section_emits_heading_and_packs_in_order():
    packs = [
        RunPackProposal(title="first"),
        RunPackProposal(title="second"),
    ]
    section = render_section("Proposed Run Packs", packs)
    assert section.startswith("## Proposed Run Packs\n")
    assert section.index("### first") < section.index("### second")


def test_replace_or_append_section_creates_when_file_empty():
    rendered = "## Proposed Run Packs\n\n### x\n"
    assert replace_or_append_section("", "Proposed Run Packs", rendered) == rendered


def test_replace_or_append_section_appends_when_section_missing():
    existing = "# Audit\n\nSome prose.\n\n## Findings\n\nNothing.\n"
    rendered = "## Proposed Run Packs\n\n### x\n"
    out = replace_or_append_section(existing, "Proposed Run Packs", rendered)
    assert out.startswith("# Audit")
    assert out.endswith("## Proposed Run Packs\n\n### x\n")
    # Findings section preserved verbatim.
    assert "## Findings\n\nNothing.\n" in out


def test_replace_or_append_section_replaces_existing_section():
    existing = (
        "# Audit\n\n"
        "## Proposed Run Packs\n\n### old\n\n"
        "## Notes\n\nstuff\n"
    )
    rendered = "## Proposed Run Packs\n\n### new\n"
    out = replace_or_append_section(existing, "Proposed Run Packs", rendered)
    assert "### old" not in out
    assert "### new" in out
    # Notes preserved.
    assert "## Notes\n\nstuff\n" in out
    assert out.startswith("# Audit")


def test_write_run_pack_proposals_creates_file_with_section(tmp_path: Path):
    result = write_run_pack_proposals(
        str(tmp_path),
        "docs/tracks/foo.md",
        DEFAULT_SECTION,
        [{"title": "first", "summary": "do it", "category": "code_bug", "confidence": "low"}],
    )
    assert result.created_file is True
    assert result.pack_count == 1
    assert result.section == DEFAULT_SECTION
    assert result.relative_path == "docs/tracks/foo.md"
    body = (tmp_path / "docs/tracks/foo.md").read_text()
    assert body.startswith("## Proposed Run Packs\n")
    assert "### first" in body


def test_write_run_pack_proposals_replaces_existing_section(tmp_path: Path):
    target = tmp_path / "audit.md"
    target.write_text(
        "# Audit\n\n"
        "## Proposed Run Packs\n\n### old\n\n"
        "## Notes\n\nstuff\n"
    )
    result = write_run_pack_proposals(
        str(tmp_path),
        "audit.md",
        "Proposed Run Packs",
        [
            {"title": "p1", "summary": "", "category": "code_bug", "confidence": "low"},
            {"title": "p2", "summary": "", "category": "other", "confidence": "high"},
        ],
    )
    assert result.created_file is False
    assert result.pack_count == 2
    body = target.read_text()
    assert "### old" not in body
    assert "### p1" in body
    assert "### p2" in body
    assert "## Notes\n\nstuff" in body


def test_write_run_pack_proposals_creates_parent_directories(tmp_path: Path):
    write_run_pack_proposals(
        str(tmp_path),
        ".spindrel/audits/missing/dir/x.md",
        DEFAULT_SECTION,
        [{"title": "p", "summary": "", "category": "other", "confidence": "low"}],
    )
    assert (tmp_path / ".spindrel/audits/missing/dir/x.md").exists()
