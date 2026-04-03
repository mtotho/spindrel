"""Unit tests for app.services.file_sync — prompt template collection and path classification."""
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.services.file_sync import (
    SOURCE_FILE,
    SOURCE_INTEGRATION,
    _classify_path,
    _collect_prompt_template_files,
)

# All workspace schema template files shipped via mission_control integration
_MC_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "integrations" / "mission_control" / "prompts"

# Templates organized by category subfolder
_EXPECTED_TEMPLATES = {
    "core": [
        "mission-control",
        "general-project",
        "research-analysis",
        "creative-project",
    ],
    "technical": [
        "software-development",
        "software-testing-qa",
        "sprint-agile",
        "incident-response",
    ],
    "business": [
        "project-management-hub",
        "product-roadmap",
        "content-editorial",
        "consulting-engagement",
    ],
    "personal": [
        "life-goals",
        "learning-track",
        "budget-financial",
    ],
    "operations": [
        "restaurant-manager",
        "home-property",
    ],
}

# Flat list for parametrize
_ALL_TEMPLATES = [
    (category, stem)
    for category, stems in _EXPECTED_TEMPLATES.items()
    for stem in stems
]


class TestCollectPromptTemplateFiles:
    """Tests for _collect_prompt_template_files() scanning logic."""

    def test_includes_integration_dirs(self, tmp_path):
        """Integration prompts are discovered alongside top-level prompts."""
        # Set up top-level prompts/
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "base.md").write_text("# base")

        # Set up integrations/mission_control/prompts/
        intg_prompts = tmp_path / "integrations" / "mission_control" / "prompts"
        intg_prompts.mkdir(parents=True)
        (intg_prompts / "life-goals.md").write_text("# life goals")

        with patch("app.services.file_sync._integration_dirs", return_value=[tmp_path / "integrations"]):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                items = _collect_prompt_template_files()
            finally:
                os.chdir(old_cwd)

        names = [(name, src) for _, name, src in items]
        assert ("base", SOURCE_FILE) in names
        assert ("life-goals", SOURCE_INTEGRATION) in names

    def test_empty_dirs_returns_empty(self, tmp_path):
        """No prompts dirs → empty list."""
        with patch("app.services.file_sync._integration_dirs", return_value=[tmp_path / "integrations"]):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                items = _collect_prompt_template_files()
            finally:
                os.chdir(old_cwd)

        assert items == []

    def test_only_integration_prompts(self, tmp_path):
        """Integration prompts are found even without top-level prompts/."""
        intg_prompts = tmp_path / "integrations" / "foo" / "prompts"
        intg_prompts.mkdir(parents=True)
        (intg_prompts / "bar.md").write_text("# bar")

        with patch("app.services.file_sync._integration_dirs", return_value=[tmp_path / "integrations"]):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                items = _collect_prompt_template_files()
            finally:
                os.chdir(old_cwd)

        assert len(items) == 1
        assert items[0][1] == "bar"
        assert items[0][2] == SOURCE_INTEGRATION

    def test_recursive_discovery_top_level(self, tmp_path):
        """prompts/**/*.md finds files in subdirectories."""
        prompts_dir = tmp_path / "prompts"
        sub = prompts_dir / "technical"
        sub.mkdir(parents=True)
        (sub / "dev.md").write_text("# dev")
        (prompts_dir / "base.md").write_text("# base")

        with patch("app.services.file_sync._integration_dirs", return_value=[]):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                items = _collect_prompt_template_files()
            finally:
                os.chdir(old_cwd)

        names = [name for _, name, _ in items]
        assert "base" in names
        assert "dev" in names

    def test_recursive_discovery_integration(self, tmp_path):
        """integrations/*/prompts/**/*.md finds files in subdirectories."""
        intg_prompts = tmp_path / "integrations" / "mc" / "prompts"
        sub = intg_prompts / "business"
        sub.mkdir(parents=True)
        (sub / "roadmap.md").write_text("# roadmap")
        (intg_prompts / "base.md").write_text("# base")

        with patch("app.services.file_sync._integration_dirs", return_value=[tmp_path / "integrations"]):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                items = _collect_prompt_template_files()
            finally:
                os.chdir(old_cwd)

        names = [name for _, name, _ in items]
        assert "base" in names
        assert "roadmap" in names
        # Both should be SOURCE_INTEGRATION
        for _, _, src in items:
            assert src == SOURCE_INTEGRATION


class TestClassifyPath:
    """Tests for _classify_path() — mapping filesystem paths to sync types."""

    def test_integration_prompt(self, tmp_path):
        """integrations/{id}/prompts/*.md → prompt_template with SOURCE_INTEGRATION."""
        intg_prompts = tmp_path / "integrations" / "mission_control" / "prompts"
        intg_prompts.mkdir(parents=True)
        md = intg_prompts / "life-goals.md"
        md.write_text("# life goals")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = _classify_path(md)
        finally:
            os.chdir(old_cwd)

        assert result is not None
        kind, name, bot_id, source_type = result
        assert kind == "prompt_template"
        assert name == "life-goals"
        assert bot_id is None
        assert source_type == SOURCE_INTEGRATION

    def test_integration_prompt_in_subfolder(self, tmp_path):
        """integrations/{id}/prompts/{category}/*.md → prompt_template."""
        sub = tmp_path / "integrations" / "mc" / "prompts" / "technical"
        sub.mkdir(parents=True)
        md = sub / "sprint-agile.md"
        md.write_text("# sprint")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = _classify_path(md)
        finally:
            os.chdir(old_cwd)

        assert result is not None
        kind, name, bot_id, source_type = result
        assert kind == "prompt_template"
        assert name == "sprint-agile"
        assert source_type == SOURCE_INTEGRATION

    def test_top_level_prompt_regression(self, tmp_path):
        """prompts/*.md still works after adding the integration rule."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        md = prompts_dir / "base.md"
        md.write_text("# base")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = _classify_path(md)
        finally:
            os.chdir(old_cwd)

        assert result is not None
        kind, name, bot_id, source_type = result
        assert kind == "prompt_template"
        assert name == "base"
        assert bot_id is None
        assert source_type == SOURCE_FILE

    def test_top_level_prompt_in_subfolder(self, tmp_path):
        """prompts/{category}/*.md → prompt_template with SOURCE_FILE."""
        sub = tmp_path / "prompts" / "personal"
        sub.mkdir(parents=True)
        md = sub / "goals.md"
        md.write_text("# goals")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = _classify_path(md)
        finally:
            os.chdir(old_cwd)

        assert result is not None
        kind, name, bot_id, source_type = result
        assert kind == "prompt_template"
        assert name == "goals"
        assert source_type == SOURCE_FILE

    def test_unrelated_path_returns_none(self, tmp_path):
        """Random paths are not classified."""
        random_file = tmp_path / "random" / "file.md"
        random_file.parent.mkdir(parents=True)
        random_file.write_text("# random")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = _classify_path(random_file)
        finally:
            os.chdir(old_cwd)

        assert result is None


class TestMissionControlTemplateFiles:
    """Verify all shipped workspace schema templates exist with valid frontmatter."""

    @pytest.mark.parametrize("category,stem", _ALL_TEMPLATES)
    def test_template_file_exists(self, category, stem):
        """Each expected template file exists on disk in its category subfolder."""
        path = _MC_PROMPTS_DIR / category / f"{stem}.md"
        assert path.exists(), f"Missing template file: {path}"

    @pytest.mark.parametrize("category,stem", _ALL_TEMPLATES)
    def test_template_has_valid_frontmatter(self, category, stem):
        """Each template has YAML frontmatter with required fields."""
        path = _MC_PROMPTS_DIR / category / f"{stem}.md"
        content = path.read_text()

        # Parse YAML frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        assert match, f"{stem}.md missing YAML frontmatter"
        fm = yaml.safe_load(match.group(1))

        assert fm.get("name"), f"{stem}.md missing 'name' in frontmatter"
        assert fm.get("description"), f"{stem}.md missing 'description' in frontmatter"
        assert fm.get("category") == "workspace_schema", (
            f"{stem}.md category should be 'workspace_schema', got {fm.get('category')!r}"
        )
        assert fm.get("tags"), f"{stem}.md missing 'tags' in frontmatter"
        assert fm.get("group"), f"{stem}.md missing 'group' in frontmatter"

    @pytest.mark.parametrize("category,stem", _ALL_TEMPLATES)
    def test_template_group_matches_folder(self, category, stem):
        """The group frontmatter field matches the category subfolder name."""
        path = _MC_PROMPTS_DIR / category / f"{stem}.md"
        content = path.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        fm = yaml.safe_load(match.group(1))

        # Group should match the folder name (title-cased)
        assert fm.get("group", "").lower() == category.lower(), (
            f"{stem}.md group '{fm.get('group')}' doesn't match folder '{category}'"
        )

    def test_no_stale_flat_template_files(self):
        """No .md files should remain at the prompts root (all should be in subfolders)."""
        flat_files = list(_MC_PROMPTS_DIR.glob("*.md"))
        assert not flat_files, f"Template files should be in subfolders, found at root: {[p.name for p in flat_files]}"

    def test_no_unexpected_category_folders(self):
        """Only expected category folders exist."""
        actual_folders = {p.name for p in _MC_PROMPTS_DIR.iterdir() if p.is_dir()}
        expected_folders = set(_EXPECTED_TEMPLATES.keys())
        extra = actual_folders - expected_folders
        assert not extra, f"Unexpected category folders: {extra}"

    def test_all_templates_have_mc_compatibility(self):
        """All templates should declare mission_control compatibility."""
        for category, stems in _EXPECTED_TEMPLATES.items():
            for stem in stems:
                path = _MC_PROMPTS_DIR / category / f"{stem}.md"
                content = path.read_text()
                match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                fm = yaml.safe_load(match.group(1))
                compat = fm.get("compatible_integrations", [])
                assert "mission_control" in compat, (
                    f"{stem}.md should have 'mission_control' in compatible_integrations"
                )


class TestRecommendedHeartbeat:
    """Verify recommended_heartbeat frontmatter on templates that have it."""

    # All templates except mission-control (core) should have recommended_heartbeat
    _TEMPLATES_WITH_HEARTBEAT = [
        (cat, stem)
        for cat, stems in _EXPECTED_TEMPLATES.items()
        for stem in stems
        if not (cat == "core" and stem == "mission-control")
    ]

    @pytest.mark.parametrize("category,stem", _TEMPLATES_WITH_HEARTBEAT)
    def test_heartbeat_has_required_fields(self, category, stem):
        """recommended_heartbeat must include prompt and interval."""
        path = _MC_PROMPTS_DIR / category / f"{stem}.md"
        content = path.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        fm = yaml.safe_load(match.group(1))

        hb = fm.get("recommended_heartbeat")
        assert hb is not None, f"{stem}.md should have recommended_heartbeat"
        assert isinstance(hb, dict), f"{stem}.md recommended_heartbeat should be a dict"
        assert hb.get("prompt"), f"{stem}.md recommended_heartbeat missing 'prompt'"
        assert hb.get("interval") in ("hourly", "daily", "weekly", "monthly"), (
            f"{stem}.md recommended_heartbeat interval should be hourly/daily/weekly/monthly, "
            f"got {hb.get('interval')!r}"
        )

    def test_mission_control_has_no_heartbeat(self):
        """The base mission-control template doesn't recommend a heartbeat."""
        path = _MC_PROMPTS_DIR / "core" / "mission-control.md"
        content = path.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        fm = yaml.safe_load(match.group(1))
        assert fm.get("recommended_heartbeat") is None
