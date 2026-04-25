"""Unit tests for app.services.file_sync — prompt template collection and path classification."""
import os
from unittest.mock import patch

import pytest

from app.services.file_sync import (
    SOURCE_FILE,
    SOURCE_INTEGRATION,
    _classify_path,
    _collect_prompt_template_files,
)


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


# ---------------------------------------------------------------------------
# sync_all_files — real DB + real files on disk (chdir to tmp_path)
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock
from sqlalchemy import select

from app.db.models import Skill as SkillRow, PromptTemplate


@pytest.fixture
def isolate_file_sync(tmp_path, monkeypatch):
    """Chdir into an empty tmp dir and mock embeddings + reload hooks.

    ``sync_all_files`` scans relative paths (``skills/``, ``prompts/``,
    ``integrations/``, ``packages/``) and opens its own
    ``async_session`` blocks. We chdir so the scan sees only what the test
    created, and mock the external/embedding touchpoints (E.1).
    """
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.services.file_sync._embed_skill_from_content",
        new_callable=AsyncMock,
    ) as embed, patch(
        "app.services.workflows.collect_workflow_files", return_value=[]
    ), patch(
        "app.services.workflows.reload_workflows", new_callable=AsyncMock
    ), patch(
        "app.services.integration_settings.inactive_integration_ids", return_value=set()
    ), patch(
        "app.services.paths.effective_integration_dirs", return_value=[]
    ):
        yield {"tmp_path": tmp_path, "embed": embed}


class TestSyncAllFilesSkills:
    """Real-DB coverage of sync_all_files's skill synchronization path."""

    @pytest.mark.asyncio
    async def test_when_new_skill_file_then_row_added_and_embedded(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        embed = isolate_file_sync["embed"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        content = "---\nname: Deploy Helper\ncategory: devops\n---\n\n# body\n"
        (skills_dir / "deploy_helper.md").write_text(content)

        from app.services.file_sync import sync_all_files
        result = await sync_all_files()

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "deploy_helper"))
        ).scalar_one()
        assert result["added"] == 1
        assert row.name == "Deploy Helper"
        assert row.category == "devops"
        assert row.source_type == SOURCE_FILE
        embed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_when_file_unchanged_then_row_not_updated(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        (skills_dir / "stable.md").write_text("---\nname: Stable\n---\n\nbody\n")

        from app.services.file_sync import sync_all_files
        await sync_all_files()
        result = await sync_all_files()

        assert result["unchanged"] == 1
        assert result["updated"] == 0
        assert result["added"] == 0

    @pytest.mark.asyncio
    async def test_when_content_changed_then_row_updated(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        path = skills_dir / "mutable.md"
        path.write_text("---\nname: Initial\n---\n\noriginal\n")

        from app.services.file_sync import sync_all_files
        await sync_all_files()
        path.write_text("---\nname: Updated\n---\n\nrevised content\n")
        result = await sync_all_files()

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "mutable"))
        ).scalar_one()
        assert result["updated"] == 1
        assert row.name == "Updated"
        assert "revised content" in row.content

    @pytest.mark.asyncio
    async def test_when_file_removed_then_orphan_deleted(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        (skills_dir / "keeper.md").write_text("---\nname: Keeper\n---\nbody\n")
        (skills_dir / "doomed.md").write_text("---\nname: Doomed\n---\nbody\n")

        from app.services.file_sync import sync_all_files
        await sync_all_files()
        (skills_dir / "doomed.md").unlink()
        result = await sync_all_files()

        ids = {
            r.id
            for r in (
                await db_session.execute(select(SkillRow))
            ).scalars().all()
        }
        assert ids == {"keeper"}
        assert result["deleted"] == 1

    @pytest.mark.asyncio
    async def test_when_zero_files_on_disk_then_orphan_deletion_skipped(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        from datetime import datetime, timezone
        db_session.add(SkillRow(
            id="legacy",
            name="Legacy",
            content="x",
            content_hash="h",
            source_type=SOURCE_FILE,
            source_path="/gone",
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        from app.services.file_sync import sync_all_files
        result = await sync_all_files()

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "legacy"))
        ).scalar_one()
        assert row.id == "legacy"
        assert result["deleted"] == 0
        assert any("mount issue" in err for err in result["errors"])

    @pytest.mark.asyncio
    async def test_when_bot_skill_file_then_id_is_prefixed(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        (tmp / "bots" / "alpha" / "skills").mkdir(parents=True)
        (tmp / "bots" / "alpha" / "skills" / "private.md").write_text(
            "---\nname: Private\n---\nsecret sauce\n"
        )

        from app.services.file_sync import sync_all_files
        result = await sync_all_files()

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "bots/alpha/private"))
        ).scalar_one()
        assert result["added"] == 1
        assert row.source_type == SOURCE_FILE


class TestSyncAllFilesPromptTemplates:
    @pytest.mark.asyncio
    async def test_when_new_prompt_file_then_template_row_added(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        prompts_dir = tmp / "prompts"
        prompts_dir.mkdir()
        content = (
            "---\nname: Onboarding Kickoff\ncategory: core\ntags: [intro, onboarding]\n"
            "---\n\ntemplate body\n"
        )
        (prompts_dir / "onboarding.md").write_text(content)

        from app.services.file_sync import sync_all_files
        result = await sync_all_files()

        row = (
            await db_session.execute(
                select(PromptTemplate).where(PromptTemplate.name == "Onboarding Kickoff")
            )
        ).scalar_one()
        assert result["added"] == 1
        assert row.category == "core"
        assert sorted(row.tags) == ["intro", "onboarding"]
        assert row.source_type == SOURCE_FILE

    @pytest.mark.asyncio
    async def test_when_prompt_file_removed_then_template_orphan_deleted(
        self, db_session, patched_async_sessions, isolate_file_sync
    ):
        tmp = isolate_file_sync["tmp_path"]
        prompts_dir = tmp / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "keep.md").write_text("---\nname: Keep\n---\nbody\n")
        (prompts_dir / "remove.md").write_text("---\nname: Remove\n---\nbody\n")

        from app.services.file_sync import sync_all_files
        await sync_all_files()
        (prompts_dir / "remove.md").unlink()
        result = await sync_all_files()

        names = {
            r.name
            for r in (
                await db_session.execute(select(PromptTemplate))
            ).scalars().all()
        }
        assert names == {"Keep"}
        assert result["deleted"] == 1
