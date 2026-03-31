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
_EXPECTED_TEMPLATES = [
    "software-development",
    "research-analysis",
    "creative-project",
    "general-project",
    "project-management-hub",
    "mission-control",
    "software-testing-qa",
    "life-goals",
    "restaurant-manager",
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

    @pytest.mark.parametrize("stem", _EXPECTED_TEMPLATES)
    def test_template_file_exists(self, stem):
        """Each expected template file exists on disk."""
        path = _MC_PROMPTS_DIR / f"{stem}.md"
        assert path.exists(), f"Missing template file: {path}"

    @pytest.mark.parametrize("stem", _EXPECTED_TEMPLATES)
    def test_template_has_valid_frontmatter(self, stem):
        """Each template has YAML frontmatter with category=workspace_schema."""
        path = _MC_PROMPTS_DIR / f"{stem}.md"
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

    def test_no_extra_template_files(self):
        """No unexpected .md files in prompts dir (catch accidental additions)."""
        actual_stems = {p.stem for p in _MC_PROMPTS_DIR.glob("*.md")}
        expected_stems = set(_EXPECTED_TEMPLATES)
        extra = actual_stems - expected_stems
        assert not extra, f"Unexpected template files: {extra}"
