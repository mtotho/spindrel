"""Tests for the system pipeline seeder + /run params plumbing.

Covers:
  * seed_pipelines_from_yaml inserts fresh rows
  * reseed overwrites source='system' rows
  * reseed refuses to clobber source='user' rows (logs warning)
  * spawn_child_run(params=...) merges into execution_config['params']
  * render_prompt resolves {{params.*}} dotted references
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import Task
from app.services.step_executor import render_prompt
from app.services.task_seeding import (
    pipeline_uuid,
    seed_pipelines_from_yaml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data))
    return path


@pytest_asyncio.fixture
async def patched_session(engine, monkeypatch):
    """Route ``app.services.task_seeding.async_session`` to the in-memory test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _session_cm():
        return factory()

    monkeypatch.setattr(
        "app.services.task_seeding.async_session", _session_cm
    )
    yield factory


def _pipeline_yaml(slug: str, title: str, steps: list[dict] | None = None) -> dict:
    return {
        "id": slug,
        "bot_id": "orchestrator",
        "title": title,
        "prompt": f"[system pipeline: {slug}]",
        "task_type": "pipeline",
        "steps": steps
        or [
            {"id": "s1", "type": "exec", "prompt": "echo hello"},
        ],
    }


# ---------------------------------------------------------------------------
# seed_pipelines_from_yaml
# ---------------------------------------------------------------------------

class TestSeedPipelinesFromYaml:
    @pytest.mark.asyncio
    async def test_inserts_fresh_row_with_source_system(self, patched_session, tmp_path):
        _write_yaml(tmp_path / "full_scan.yaml", _pipeline_yaml("full_scan", "Full Scan"))

        await seed_pipelines_from_yaml(tmp_path)

        async with patched_session() as db:
            row = await db.get(Task, pipeline_uuid("full_scan"))
            assert row is not None
            assert row.source == "system"
            assert row.title == "Full Scan"
            assert row.task_type == "pipeline"
            assert row.bot_id == "orchestrator"
            assert row.steps == [{"id": "s1", "type": "exec", "prompt": "echo hello"}]

    @pytest.mark.asyncio
    async def test_reseed_is_idempotent_and_refreshes_content(self, patched_session, tmp_path):
        path = _write_yaml(tmp_path / "x.yaml", _pipeline_yaml("x", "First"))
        await seed_pipelines_from_yaml(tmp_path)

        # Rewrite YAML with a new title; reseed should overwrite
        _write_yaml(path, _pipeline_yaml("x", "Second"))
        await seed_pipelines_from_yaml(tmp_path)

        async with patched_session() as db:
            rows = (await db.execute(select(Task).where(Task.id == pipeline_uuid("x")))).scalars().all()
            assert len(rows) == 1
            assert rows[0].title == "Second"
            assert rows[0].source == "system"

    @pytest.mark.asyncio
    async def test_user_row_collision_preserved(self, patched_session, tmp_path, caplog):
        slug = "x"
        row_id = pipeline_uuid(slug)

        # Pre-insert a user-owned row at the same id.
        async with patched_session() as db:
            db.add(Task(
                id=row_id,
                bot_id="orchestrator",
                prompt="my custom prompt",
                title="My Custom Pipeline",
                task_type="pipeline",
                steps=[{"id": "custom", "type": "exec", "prompt": "echo custom"}],
                source="user",
            ))
            await db.commit()

        _write_yaml(tmp_path / "x.yaml", _pipeline_yaml(slug, "System Pipeline"))

        with caplog.at_level(logging.WARNING, logger="app.services.task_seeding"):
            await seed_pipelines_from_yaml(tmp_path)

        async with patched_session() as db:
            row = await db.get(Task, row_id)
            assert row.source == "user"
            assert row.title == "My Custom Pipeline"
            assert row.prompt == "my custom prompt"

        assert any("user-owned" in rec.message for rec in caplog.records), (
            "expected a warning about user-owned collision"
        )

    @pytest.mark.asyncio
    async def test_missing_id_is_skipped(self, patched_session, tmp_path):
        (tmp_path / "bad.yaml").write_text(yaml.safe_dump({"title": "no id"}))
        await seed_pipelines_from_yaml(tmp_path)
        async with patched_session() as db:
            rows = (await db.execute(select(Task))).scalars().all()
            assert rows == []

    @pytest.mark.asyncio
    async def test_missing_directory_is_noop(self, patched_session, tmp_path):
        await seed_pipelines_from_yaml(tmp_path / "does-not-exist")
        async with patched_session() as db:
            rows = (await db.execute(select(Task))).scalars().all()
            assert rows == []


# ---------------------------------------------------------------------------
# /run endpoint params → spawn_child_run → execution_config['params']
# ---------------------------------------------------------------------------

class TestSpawnChildRunParams:
    @pytest.mark.asyncio
    async def test_params_populate_execution_config(self, db_session):
        from app.services.task_ops import spawn_child_run

        parent = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="system pipeline",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo {{params.bot_id}}"}],
            execution_config={"something_else": True},
            source="system",
        )
        db_session.add(parent)
        await db_session.commit()

        child = await spawn_child_run(parent.id, db_session, params={"bot_id": "default"})
        assert child.execution_config == {"something_else": True, "params": {"bot_id": "default"}}
        assert child.parent_task_id == parent.id
        assert child.status == "pending"

    @pytest.mark.asyncio
    async def test_params_merge_over_existing(self, db_session):
        from app.services.task_ops import spawn_child_run

        parent = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            execution_config={"params": {"a": 1, "b": 2}},
            source="system",
        )
        db_session.add(parent)
        await db_session.commit()

        child = await spawn_child_run(parent.id, db_session, params={"b": 99, "c": 3})
        assert child.execution_config["params"] == {"a": 1, "b": 99, "c": 3}

    @pytest.mark.asyncio
    async def test_no_params_leaves_execution_config_alone(self, db_session):
        from app.services.task_ops import spawn_child_run

        parent = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            execution_config=None,
            source="system",
        )
        db_session.add(parent)
        await db_session.commit()

        child = await spawn_child_run(parent.id, db_session)
        assert child.execution_config is None


# ---------------------------------------------------------------------------
# render_prompt: {{params.*}} dotted access
# ---------------------------------------------------------------------------

class TestRenderPromptParamsDotted:
    def test_flat_param_still_works(self):
        assert render_prompt("hi {{name}}", {"name": "ada"}, [], []) == "hi ada"

    def test_dotted_params_access(self):
        out = render_prompt("target={{params.bot_id}}", {"bot_id": "default"}, [], [])
        assert out == "target=default"

    def test_deep_dotted_params_access(self):
        out = render_prompt(
            "{{params.nested.key}}",
            {"nested": {"key": "val"}},
            [],
            [],
        )
        assert out == "val"

    def test_missing_params_key_left_intact(self):
        assert render_prompt("{{params.missing}}", {}, [], []) == "{{params.missing}}"

    def test_dict_value_serialized_as_json(self):
        out = render_prompt("{{params.obj}}", {"obj": {"a": 1}}, [], [])
        assert out == '{"a": 1}'

    def test_list_value_serialized_as_json(self):
        out = render_prompt("{{params.xs}}", {"xs": [1, 2]}, [], [])
        assert out == "[1, 2]"
