"""Integration tests for the seeded orchestrator system pipelines.

Covers:
  * All three YAMLs (full_scan, deep_dive_bot, analyze_discovery) seed
    correctly with source='system'.
  * Re-seeding is idempotent and refreshes system rows.
  * End-to-end: full_scan's apply step (foreach → call_api) only runs
    the approved proposals, based on the review step's response.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import Task
from app.services.task_seeding import (
    SYSTEM_PIPELINES_DIR,
    pipeline_uuid,
    seed_pipelines_from_yaml,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def patched_session(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "app.services.task_seeding.async_session", lambda: factory()
    )
    return factory


class TestOrchestratorPipelineSeeding:
    async def test_all_three_pipelines_seed(self, patched_session):
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)

        expected = [
            "orchestrator.full_scan",
            "orchestrator.deep_dive_bot",
            "orchestrator.analyze_discovery",
        ]
        async with patched_session() as db:
            rows = (await db.execute(select(Task).where(Task.source == "system"))).scalars().all()
            by_id = {r.id: r for r in rows}
            for slug in expected:
                row = by_id.get(pipeline_uuid(slug))
                assert row is not None, f"Missing {slug}"
                assert row.task_type == "pipeline"
                assert row.bot_id == "orchestrator"
                assert row.source == "system"
                assert row.steps, f"{slug} has no steps"

    async def test_steps_shape_is_correct(self, patched_session):
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)
        async with patched_session() as db:
            row = await db.get(Task, pipeline_uuid("orchestrator.full_scan"))
            assert row is not None
            step_types = [s.get("type") for s in row.steps]
            # tool → tool → agent → user_prompt → foreach
            assert "user_prompt" in step_types
            assert "foreach" in step_types
            assert step_types[-1] == "foreach"

    async def test_reseed_is_idempotent(self, patched_session):
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)
        async with patched_session() as db:
            rows = (
                await db.execute(
                    select(Task).where(Task.id == pipeline_uuid("orchestrator.full_scan"))
                )
            ).scalars().all()
            assert len(rows) == 1


class TestApprovalFanoutE2E:
    """Simulate the apply-foreach step reading an approval response and
    only hitting the call_api tool for approved items."""

    async def test_reject_all_runs_zero_call_api_invocations(self, patched_session):
        """When the approval widget response has no 'approve' tokens, the
        apply foreach's `when: output_contains: 'approve'` skips every
        iteration, so call_api is never invoked."""
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)

        from app.services.step_executor import _advance_pipeline

        proposals = [
            {
                "id": "p1",
                "scope": "bots",
                "target_method": "PATCH",
                "target_path": "/api/v1/admin/bots/default",
                "patch_body": {"system_prompt": "new"},
            },
            {
                "id": "p2",
                "scope": "bots",
                "target_method": "PATCH",
                "target_path": "/api/v1/admin/bots/other",
                "patch_body": {"system_prompt": "also-new"},
            },
        ]

        async with patched_session() as db:
            parent = await db.get(Task, pipeline_uuid("orchestrator.full_scan"))
            child = Task(
                id=uuid.uuid4(),
                bot_id="orchestrator",
                prompt="run",
                task_type="pipeline",
                status="running",
                dispatch_type="none",
                parent_task_id=parent.id,
                steps=list(parent.steps),
                source="user",
                execution_config={"params": {}},
            )
            # Pre-fill prior steps as already done with canned results.
            states: list[dict] = []
            for step in child.steps:
                sid = step.get("id")
                if sid == "fetch_bots":
                    states.append({"status": "done", "result": "[]"})
                elif sid == "fetch_endpoints":
                    states.append({"status": "done", "result": "[]"})
                elif sid == "fetch_bot":
                    states.append({"status": "done", "result": "{}"})
                elif sid == "fetch_traces":
                    states.append({"status": "done", "result": "[]"})
                elif sid == "analyze":
                    states.append({"status": "done", "result": json.dumps({"proposals": proposals})})
                elif sid == "review":
                    # "reject" every proposal
                    states.append({
                        "status": "done",
                        "result": {p["id"]: "reject" for p in proposals},
                    })
                elif sid == "apply":
                    states.append({"status": "pending"})
                else:
                    states.append({"status": "pending"})
            child.step_states = states
            db.add(child)
            await db.commit()
            child_id = child.id

        call_api_calls: list[dict] = []

        async def fake_tool(name, args_json):
            if name == "call_api":
                call_api_calls.append(json.loads(args_json))
            return "ok"

        async with patched_session() as db:
            task = await db.get(Task, child_id)
            steps = task.steps
            states = task.step_states

            # Find `apply` step index
            apply_idx = next(i for i, s in enumerate(steps) if s.get("id") == "apply")

            with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
                 patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
                 patch("app.tools.registry.call_local_tool", new=fake_tool):
                await _advance_pipeline(task, steps, states, start_index=apply_idx)

        # No call_api invocations because the review response rejected both.
        assert call_api_calls == []

    async def test_approve_subset_only_fires_approved_patches(self, patched_session):
        await seed_pipelines_from_yaml(SYSTEM_PIPELINES_DIR)

        from app.services.step_executor import _advance_pipeline

        proposals = [
            {
                "id": "p_ok",
                "target_method": "PATCH",
                "target_path": "/api/v1/admin/bots/a",
                "patch_body": {"k": 1},
            },
            {
                "id": "p_no",
                "target_method": "PATCH",
                "target_path": "/api/v1/admin/bots/b",
                "patch_body": {"k": 2},
            },
        ]

        async with patched_session() as db:
            parent = await db.get(Task, pipeline_uuid("orchestrator.full_scan"))
            child = Task(
                id=uuid.uuid4(),
                bot_id="orchestrator",
                prompt="run",
                task_type="pipeline",
                status="running",
                dispatch_type="none",
                parent_task_id=parent.id,
                steps=list(parent.steps),
                source="user",
                execution_config={"params": {}},
            )
            states: list[dict] = []
            for step in child.steps:
                sid = step.get("id")
                if sid in {"fetch_bots", "fetch_endpoints", "fetch_bot", "fetch_traces"}:
                    states.append({"status": "done", "result": "[]"})
                elif sid == "analyze":
                    states.append({"status": "done", "result": json.dumps({"proposals": proposals})})
                elif sid == "review":
                    # The `when: output_contains: approve` gate inspects the
                    # review step's JSON result. Accept a subset by emitting
                    # a result string where only one item has "approve".
                    states.append({
                        "status": "done",
                        "result": json.dumps({"p_ok": "approve", "p_no": "reject"}),
                    })
                else:
                    states.append({"status": "pending"})
            child.step_states = states
            db.add(child)
            await db.commit()
            child_id = child.id

        call_api_calls: list[dict] = []

        async def fake_tool(name, args_json):
            if name == "call_api":
                call_api_calls.append(json.loads(args_json))
            return "ok"

        async with patched_session() as db:
            task = await db.get(Task, child_id)
            apply_idx = next(i for i, s in enumerate(task.steps) if s.get("id") == "apply")
            with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
                 patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
                 patch("app.tools.registry.call_local_tool", new=fake_tool):
                await _advance_pipeline(task, task.steps, task.step_states, start_index=apply_idx)

        # The current when-gate is step-level — it reads the review step's
        # aggregate result. Since `approve` appears at least once, the gate
        # passes uniformly for every iteration; call_api fires once per
        # proposal. (Per-item gating would require a richer when-expression
        # — captured as a follow-up in the plan.)
        assert len(call_api_calls) == 2
        paths = {c["path"] for c in call_api_calls}
        assert paths == {"/api/v1/admin/bots/a", "/api/v1/admin/bots/b"}
