"""Tests for ``app.tools.local.pipelines`` — list_pipelines + run_pipeline.

Mirror of ``test_system_pipelines.py``'s real-DB-first pattern. Both tools
wrap existing machinery (queries against Task, spawn_child_run), so we
exercise the real pieces end-to-end rather than mocking the session.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db.models import Task
from app.services.task_seeding import pipeline_uuid
from app.tools.local.pipelines import list_pipelines, run_pipeline


# ---------------------------------------------------------------------------
# list_pipelines
# ---------------------------------------------------------------------------


class TestListPipelines:
    @pytest.mark.asyncio
    async def test_returns_pipeline_definitions_only(
        self, db_session, patched_async_sessions
    ):
        # Definition — should appear
        definition = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            title="My Pipeline",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo hi"}],
            source="user",
        )
        # Concrete run (parent_task_id set) — should NOT appear
        run = Task(
            id=uuid.uuid4(),
            parent_task_id=definition.id,
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo hi"}],
            source="user",
        )
        # Plain agent task — should NOT appear
        plain = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="say hello",
            task_type="agent",
            source="user",
        )
        db_session.add_all([definition, run, plain])
        await db_session.commit()

        result = json.loads(await list_pipelines())
        ids = {p["id"] for p in result["pipelines"]}
        assert str(definition.id) in ids
        assert str(run.id) not in ids
        assert str(plain.id) not in ids

    @pytest.mark.asyncio
    async def test_surfaces_params_schema_and_requires(
        self, db_session, patched_async_sessions
    ):
        pipeline = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            title="Audit X",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "x"}],
            execution_config={
                "description": "audit stuff",
                "requires_channel": True,
                "params_schema": [
                    {"name": "bot_id", "required": True, "description": "Bot id"}
                ],
            },
            source="system",
        )
        db_session.add(pipeline)
        await db_session.commit()

        entry = next(
            p for p in json.loads(await list_pipelines())["pipelines"]
            if p["id"] == str(pipeline.id)
        )
        assert entry["description"] == "audit stuff"
        assert entry["requires_channel"] is True
        assert entry["params_schema"][0]["name"] == "bot_id"

    @pytest.mark.asyncio
    async def test_source_filter(self, db_session, patched_async_sessions):
        sys_p = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "x"}],
            source="system",
        )
        user_p = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "x"}],
            source="user",
        )
        db_session.add_all([sys_p, user_p])
        await db_session.commit()

        sys_only = json.loads(await list_pipelines(source="system"))
        assert all(p["source"] == "system" for p in sys_only["pipelines"])
        assert str(sys_p.id) in {p["id"] for p in sys_only["pipelines"]}
        assert str(user_p.id) not in {p["id"] for p in sys_only["pipelines"]}


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_accepts_uuid(self, db_session, patched_async_sessions):
        pipeline = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            title="X",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            source="system",
        )
        db_session.add(pipeline)
        await db_session.commit()

        result = json.loads(
            await run_pipeline(str(pipeline.id), params={"bot_id": "default"})
        )
        assert result["parent_task_id"] == str(pipeline.id)
        assert result["status"] == "pending"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_accepts_system_slug(self, db_session, patched_async_sessions):
        slug = "orchestrator.analyze_discovery"
        pipeline = Task(
            id=pipeline_uuid(slug),  # deterministic id for the slug
            bot_id="orchestrator",
            prompt="p",
            title="Analyze Discovery",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            source="system",
        )
        db_session.add(pipeline)
        await db_session.commit()

        result = json.loads(
            await run_pipeline(slug, params={"bot_id": "crumb"})
        )
        assert result["parent_task_id"] == str(pipeline.id)
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_id(
        self, db_session, patched_async_sessions
    ):
        result = json.loads(await run_pipeline("nonexistent.pipeline"))
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_params_land_in_execution_config(
        self, db_session, patched_async_sessions
    ):
        pipeline = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            source="system",
        )
        db_session.add(pipeline)
        await db_session.commit()

        result = json.loads(
            await run_pipeline(str(pipeline.id), params={"bot_id": "crumb"})
        )
        # Verify the child row actually has the params merged in.
        child = await db_session.get(Task, uuid.UUID(result["id"]))
        assert child.execution_config["params"] == {"bot_id": "crumb"}

    @pytest.mark.asyncio
    async def test_rejects_invalid_channel_id(
        self, db_session, patched_async_sessions
    ):
        pipeline = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            task_type="pipeline",
            steps=[{"id": "s1", "type": "exec", "prompt": "echo x"}],
            source="system",
        )
        db_session.add(pipeline)
        await db_session.commit()

        result = json.loads(
            await run_pipeline(
                str(pipeline.id),
                params={"bot_id": "x"},
                channel_id="not-a-uuid",
            )
        )
        assert "error" in result
        assert "Invalid channel_id" in result["error"]
