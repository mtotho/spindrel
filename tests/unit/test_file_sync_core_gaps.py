"""Phase B.6 targeted sweep of file_sync.py core gap #28 (sync_changed_file kind branches).

Covers the five `kind` branches of `sync_changed_file` plus the deletion path
(path.exists() is False) across all four tables, and the reload cascade for
carapaces and workflows. Uses real DB + real files on disk (chdir to tmp_path)
following the same pattern as `TestSyncAllFilesSkills` in test_file_sync.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import (
    Carapace as CarapaceRow,
    PromptTemplate,
    Skill as SkillRow,
    Workflow as WorkflowRow,
)
from app.services.file_sync import SOURCE_FILE


# ---------------------------------------------------------------------------
# Fixture — chdir to tmp_path + mock embedding + reload hooks
# ---------------------------------------------------------------------------


@pytest.fixture
def isolate_watch(tmp_path, monkeypatch):
    """Chdir into tmp + patch external touchpoints for sync_changed_file."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.services.file_sync._embed_skill_from_content", new_callable=AsyncMock
    ) as embed, patch(
        "app.agent.carapaces.reload_carapaces", new_callable=AsyncMock
    ) as reload_cap, patch(
        "app.services.workflows.reload_workflows", new_callable=AsyncMock
    ) as reload_wf:
        yield {
            "tmp_path": tmp_path,
            "embed": embed,
            "reload_carapaces": reload_cap,
            "reload_workflows": reload_wf,
        }


# ---------------------------------------------------------------------------
# Deletion path — path.exists() is False
# ---------------------------------------------------------------------------


class TestSyncChangedFileDeletion:
    """Verify deleted-file cleanup across all four tables + reload cascade."""

    @pytest.mark.asyncio
    async def test_when_deleted_skill_file_then_skill_row_removed(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        gone = tmp / "skills" / "gone.md"
        db_session.add(SkillRow(
            id="gone", name="Gone", content="x", content_hash="h",
            source_type=SOURCE_FILE, source_path=str(gone.resolve()),
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(gone)

        remaining = (await db_session.execute(select(SkillRow))).scalars().all()
        assert remaining == []

    @pytest.mark.asyncio
    async def test_when_deleted_prompt_file_then_template_row_removed(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        """Exposes NameError at file_sync.py:686 — `rows2` referenced but never defined.

        When a deleted prompt file has zero Skill rows but non-empty PromptTemplate
        rows, the `if rows or rows2 or ...` line raises NameError because `rows`
        (SkillRow hits) is empty so Python evaluates `rows2` which doesn't exist.
        """
        tmp = isolate_watch["tmp_path"]
        gone = tmp / "prompts" / "gone.md"
        db_session.add(PromptTemplate(
            name="Gone Template", content="x", source_type=SOURCE_FILE,
            source_path=str(gone.resolve()), content_hash="h",
        ))
        await db_session.commit()

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(gone)

        remaining = (await db_session.execute(select(PromptTemplate))).scalars().all()
        assert remaining == []

    @pytest.mark.asyncio
    async def test_when_deleted_carapace_file_then_row_removed_and_reload_fired(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        gone = tmp / "carapaces" / "gone.yaml"
        db_session.add(CarapaceRow(
            id="gone", name="Gone", source_type=SOURCE_FILE,
            source_path=str(gone.resolve()), content_hash="h",
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(gone)

        remaining = (await db_session.execute(select(CarapaceRow))).scalars().all()
        assert remaining == []
        isolate_watch["reload_carapaces"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_when_deleted_workflow_file_then_row_removed_and_reload_fired(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        gone = tmp / "workflows" / "gone.yaml"
        db_session.add(WorkflowRow(
            id="gone", name="Gone", source_type=SOURCE_FILE,
            source_path=str(gone.resolve()), content_hash="h",
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(gone)

        remaining = (await db_session.execute(select(WorkflowRow))).scalars().all()
        assert remaining == []
        isolate_watch["reload_workflows"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_when_deleted_file_has_no_rows_then_reload_not_fired(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        ghost = tmp / "carapaces" / "never_existed.yaml"

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(ghost)

        isolate_watch["reload_carapaces"].assert_not_awaited()
        isolate_watch["reload_workflows"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Skill branch
# ---------------------------------------------------------------------------


class TestSyncChangedFileSkill:
    @pytest.mark.asyncio
    async def test_when_new_skill_file_then_row_added_and_embedded(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        path = skills_dir / "fresh.md"
        path.write_text("---\nname: Fresh Skill\ncategory: dev\n---\n\nbody\n")

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "fresh"))
        ).scalar_one()
        assert row.name == "Fresh Skill"
        assert row.category == "dev"
        isolate_watch["embed"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_when_skill_content_changes_then_row_updated(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        path = skills_dir / "mutable.md"
        path.write_text("---\nname: V1\n---\nold\n")

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)
        path.write_text("---\nname: V2\n---\nnew body\n")
        await sync_changed_file(path)

        row = (
            await db_session.execute(select(SkillRow).where(SkillRow.id == "mutable"))
        ).scalar_one()
        assert row.name == "V2"
        assert "new body" in row.content


# ---------------------------------------------------------------------------
# Prompt-template branch
# ---------------------------------------------------------------------------


class TestSyncChangedFilePromptTemplate:
    @pytest.mark.asyncio
    async def test_when_new_prompt_file_then_template_row_added(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        prompts_dir = tmp / "prompts"
        prompts_dir.mkdir()
        path = prompts_dir / "onboard.md"
        path.write_text(
            "---\nname: Onboarding\ncategory: core\ntags: [intro]\n---\n\nbody\n"
        )

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)

        row = (
            await db_session.execute(
                select(PromptTemplate).where(PromptTemplate.name == "Onboarding")
            )
        ).scalar_one()
        assert row.category == "core"
        assert row.tags == ["intro"]


# ---------------------------------------------------------------------------
# Carapace branch
# ---------------------------------------------------------------------------


class TestSyncChangedFileCarapace:
    @pytest.mark.asyncio
    async def test_when_new_carapace_file_then_row_added_and_reload_fired(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        cdir = tmp / "carapaces"
        cdir.mkdir()
        path = cdir / "helper.yaml"
        path.write_text(
            "id: helper\nname: Helper Cap\nlocal_tools: [foo, bar]\n"
        )

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)

        row = (
            await db_session.execute(select(CarapaceRow).where(CarapaceRow.id == "helper"))
        ).scalar_one()
        assert row.name == "Helper Cap"
        assert row.local_tools == ["foo", "bar"]
        isolate_watch["reload_carapaces"].assert_awaited_once()


# ---------------------------------------------------------------------------
# Workflow branch
# ---------------------------------------------------------------------------


class TestSyncChangedFileWorkflow:
    @pytest.mark.asyncio
    async def test_when_new_workflow_file_then_row_added_and_reload_fired(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        wdir = tmp / "workflows"
        wdir.mkdir()
        path = wdir / "nightly.yaml"
        path.write_text(
            "id: nightly\nname: Nightly Job\nsteps:\n  - tool: exec\n    args: {}\n"
        )

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)

        row = (
            await db_session.execute(select(WorkflowRow).where(WorkflowRow.id == "nightly"))
        ).scalar_one()
        assert row.name == "Nightly Job"
        assert row.steps == [{"tool": "exec", "args": {}}]
        isolate_watch["reload_workflows"].assert_awaited_once()


# ---------------------------------------------------------------------------
# Unclassified / non-managed paths
# ---------------------------------------------------------------------------


class TestSyncChangedFileNonManaged:
    @pytest.mark.asyncio
    async def test_when_unrelated_path_then_noop(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        random = tmp / "random" / "note.md"
        random.parent.mkdir()
        random.write_text("---\nname: Random\n---\n\nunmanaged\n")

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(random)

        assert (await db_session.execute(select(SkillRow))).scalars().all() == []
        assert (await db_session.execute(select(PromptTemplate))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_when_non_md_yaml_suffix_then_noop(
        self, db_session, patched_async_sessions, isolate_watch
    ):
        tmp = isolate_watch["tmp_path"]
        skills_dir = tmp / "skills"
        skills_dir.mkdir()
        path = skills_dir / "notes.txt"
        path.write_text("plain text, not managed")

        from app.services.file_sync import sync_changed_file
        await sync_changed_file(path)

        assert (await db_session.execute(select(SkillRow))).scalars().all() == []
