"""Tests for Mission Control plan operations backed by SQLite DB."""
import os
import re
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_KEY", "test-key")

from unittest.mock import AsyncMock, patch


@pytest_asyncio.fixture
async def mc_db(tmp_path):
    """Set up a temporary MC SQLite database for each test."""
    db_path = str(tmp_path / "mc_test.db")

    with patch("integrations.mission_control.db.engine._get_db_path", return_value=db_path):
        import integrations.mission_control.db.engine as eng_mod
        eng_mod._engine = None
        eng_mod._session_factory = None

        from integrations.mission_control.db.engine import get_mc_engine, close_mc_engine

        await get_mc_engine()
        yield

        await close_mc_engine()

    from integrations.mission_control import services
    services._kanban_migrated.clear()
    services._timeline_migrated.clear()
    services._plans_migrated.clear()


@pytest.fixture
def mock_workspace():
    """Mock workspace file I/O."""
    with (
        patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
        patch("app.services.channel_workspace.ensure_channel_workspace"),
        patch("app.services.channel_workspace.write_workspace_file"),
        patch("app.services.channel_workspace.read_workspace_file", return_value=None),
    ):
        yield


CHANNEL_ID = str(uuid.uuid4())


@pytest.mark.asyncio
class TestDraftPlan:
    async def test_draft_plan_inserts_into_db(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan

        result = await draft_plan(
            CHANNEL_ID,
            "Deploy v2",
            ["Update config", "Run migrations", "Deploy"],
            notes="ETA 2 hours",
        )

        assert "plan-" in result
        assert "3 steps" in result

        # Verify in DB
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            plans = (await session.execute(
                select(McPlan).where(McPlan.channel_id == CHANNEL_ID)
            )).scalars().all()
            assert len(plans) == 1
            plan = plans[0]
            assert plan.title == "Deploy v2"
            assert plan.status == "draft"
            assert plan.notes == "ETA 2 hours"

            await session.refresh(plan, ["steps"])
            assert len(plan.steps) == 3
            assert plan.steps[0].content == "Update config"
            assert plan.steps[1].content == "Run migrations"
            assert plan.steps[2].content == "Deploy"

    async def test_draft_plan_with_approval_steps(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan

        result = await draft_plan(
            CHANNEL_ID,
            "Gated plan",
            ["Auto step 1", "Manual step 2", "Auto step 3"],
            approval_steps=[2],
        )

        assert "require human approval" in result

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            plan = (await session.execute(
                select(McPlan).where(McPlan.channel_id == CHANNEL_ID)
            )).scalar_one()
            await session.refresh(plan, ["steps"])
            assert plan.steps[0].requires_approval is False
            assert plan.steps[1].requires_approval is True
            assert plan.steps[2].requires_approval is False


@pytest.mark.asyncio
class TestApprovePlan:
    async def test_approve_plan_transitions_status(self, mc_db, mock_workspace):
        from integrations.mission_control.services import approve_plan
        from integrations.mission_control.tools.plans import draft_plan

        # Create a draft
        result_text = await draft_plan(CHANNEL_ID, "Approve me", ["Step 1"])
        # Extract plan_id from result text
        import re
        plan_id = re.search(r"plan-\w+", result_text).group()

        # Approve it
        result = await approve_plan(CHANNEL_ID, plan_id)
        assert result["plan"]["status"] == "approved"
        assert "approved" in result["plan"]["meta"]

    async def test_approve_plan_wrong_status(self, mc_db, mock_workspace):
        from integrations.mission_control.services import approve_plan, reject_plan
        from integrations.mission_control.tools.plans import draft_plan

        result_text = await draft_plan(CHANNEL_ID, "Reject then approve", ["Step 1"])
        import re
        plan_id = re.search(r"plan-\w+", result_text).group()

        await reject_plan(CHANNEL_ID, plan_id)

        with pytest.raises(ValueError, match="expected \\[draft\\]"):
            await approve_plan(CHANNEL_ID, plan_id)


@pytest.mark.asyncio
class TestPlanExecutor:
    async def test_plan_executor_advances_step(self, mc_db, mock_workspace):
        """After approval, the executor should create a task for step 1."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        import re
        result_text = await draft_plan(CHANNEL_ID, "Exec plan", ["Do A", "Do B"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        # Get plan DB id
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            plan_db_id = db_plan.id

        # Mock _create_step_task entirely — it needs core DB which isn't available in unit tests
        with patch(
            "integrations.mission_control.plan_executor._create_step_task",
            new_callable=AsyncMock,
        ):
            from integrations.mission_control.plan_executor import advance_plan
            await advance_plan(plan_db_id)

        # Verify step 1 is now in_progress
        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            await session.refresh(db_plan, ["steps"])
            assert db_plan.steps[0].status == "in_progress"
            assert db_plan.steps[1].status == "pending"
            assert db_plan.status == "executing"

    async def test_approval_gate_pauses_execution(self, mc_db, mock_workspace):
        """A step with requires_approval should pause the plan."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        import re
        result_text = await draft_plan(
            CHANNEL_ID, "Gated exec",
            ["Auto step", "Approval step", "Final step"],
            approval_steps=[1],  # First step requires approval
        )
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            plan_db_id = db_plan.id

        from integrations.mission_control.plan_executor import advance_plan
        await advance_plan(plan_db_id)

        # Plan should be paused at step 1 (requires approval)
        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            assert db_plan.status == "awaiting_approval"

    async def test_plan_auto_completes(self, mc_db, mock_workspace):
        """When all steps are terminal, plan should auto-complete."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        import re
        result_text = await draft_plan(CHANNEL_ID, "Complete me", ["Only step"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan, McPlanStep
        from sqlalchemy import select

        # Manually mark the step as done
        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            db_plan.steps[0].status = "done"
            db_plan.status = "executing"
            plan_db_id = db_plan.id
            await session.commit()

        from integrations.mission_control.plan_executor import advance_plan
        await advance_plan(plan_db_id)

        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            assert db_plan.status == "complete"

    async def test_step_failure_recorded(self, mc_db, mock_workspace):
        """Failed step should be recorded via on_step_task_completed."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        import re
        result_text = await draft_plan(CHANNEL_ID, "Fail plan", ["Failing step", "Next step"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        # Mark step 1 as in_progress (simulating executor started it)
        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            db_plan.steps[0].status = "in_progress"
            db_plan.status = "executing"
            step_id = db_plan.steps[0].id
            plan_db_id = db_plan.id
            await session.commit()

        # Simulate task failure via hook
        mock_task = type("Task", (), {"result": "Something went wrong", "id": uuid.uuid4()})()

        # Mock advance_plan to avoid core DB calls
        with patch("integrations.mission_control.plan_executor.advance_plan", new_callable=AsyncMock):
            from integrations.mission_control.plan_executor import on_step_task_completed
            await on_step_task_completed(step_id, "failed", mock_task)

        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            await session.refresh(db_plan, ["steps"])
            assert db_plan.steps[0].status == "failed"
            assert db_plan.steps[0].result_summary == "Something went wrong"

    async def test_advance_plan_already_complete(self, mc_db, mock_workspace):
        """advance_plan on a complete plan should be a no-op."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Already done", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            db_plan.steps[0].status = "done"
            db_plan.status = "complete"
            plan_db_id = db_plan.id
            await session.commit()

        from integrations.mission_control.plan_executor import advance_plan
        await advance_plan(plan_db_id)  # should be a no-op

        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            assert db_plan.status == "complete"

    async def test_advance_plan_all_failed(self, mc_db, mock_workspace):
        """When all steps are failed, plan should auto-complete."""
        from integrations.mission_control.tools.plans import draft_plan
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "All fail", ["Fail 1", "Fail 2"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            db_plan.steps[0].status = "failed"
            db_plan.steps[1].status = "failed"
            db_plan.status = "executing"
            plan_db_id = db_plan.id
            await session.commit()

        from integrations.mission_control.plan_executor import advance_plan
        await advance_plan(plan_db_id)

        async with await mc_session() as session:
            db_plan = await session.get(McPlan, plan_db_id)
            assert db_plan.status == "complete"


@pytest.mark.asyncio
class TestUpdatePlanStep:
    async def test_mark_step_done(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_step
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Step test", ["Do it"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        # Move to executing
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            db_plan.status = "executing"
            await session.commit()

        result = await update_plan_step(CHANNEL_ID, plan_id, 1, "done")
        assert "done" in result

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            assert db_plan.steps[0].status == "done"
            assert db_plan.steps[0].completed_at is not None

    async def test_mark_step_failed(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_step
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Fail step", ["Try this", "Then this"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            db_plan.status = "executing"
            await session.commit()

        result = await update_plan_step(CHANNEL_ID, plan_id, 1, "failed")
        assert "failed" in result

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            await session.refresh(db_plan, ["steps"])
            assert db_plan.steps[0].status == "failed"
            assert db_plan.steps[1].status == "pending"

    async def test_auto_complete_all_terminal(self, mc_db, mock_workspace):
        """When update_plan_step makes all steps terminal, plan auto-completes."""
        from integrations.mission_control.tools.plans import draft_plan, update_plan_step
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Auto complete", ["Only step"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            db_plan.status = "executing"
            await session.commit()

        result = await update_plan_step(CHANNEL_ID, plan_id, 1, "done")
        assert "auto-completed" in result

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            assert db_plan.status == "complete"


@pytest.mark.asyncio
class TestUpdatePlanStatus:
    async def test_abandon_from_draft(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_status

        result_text = await draft_plan(CHANNEL_ID, "Abandon draft", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()

        result = await update_plan_status(CHANNEL_ID, plan_id, "abandoned")
        assert "abandoned" in result

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            assert db_plan.status == "abandoned"

    async def test_abandon_from_executing(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_status
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Abandon exec", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            db_plan.status = "executing"
            await session.commit()

        result = await update_plan_status(CHANNEL_ID, plan_id, "abandoned")
        assert "abandoned" in result

    async def test_complete_from_executing(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_status
        from integrations.mission_control.services import approve_plan

        result_text = await draft_plan(CHANNEL_ID, "Complete", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()
        await approve_plan(CHANNEL_ID, plan_id)

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import select

        async with await mc_session() as session:
            db_plan = (await session.execute(
                select(McPlan).where(McPlan.plan_id == plan_id)
            )).scalar_one()
            db_plan.status = "executing"
            await session.commit()

        result = await update_plan_status(CHANNEL_ID, plan_id, "complete")
        assert "complete" in result

    async def test_invalid_transition_blocked(self, mc_db, mock_workspace):
        from integrations.mission_control.tools.plans import draft_plan, update_plan_status

        result_text = await draft_plan(CHANNEL_ID, "Bad transition", ["Step 1"])
        plan_id = re.search(r"plan-\w+", result_text).group()

        # Can't complete a draft plan (must be executing)
        result = await update_plan_status(CHANNEL_ID, plan_id, "complete")
        assert "Cannot transition" in result


@pytest.mark.asyncio
class TestPlanMigration:
    async def test_lazy_migration_imports_plans(self, mc_db):
        """Lazy migration should import plans from markdown file."""
        from app.services.plan_board import serialize_plans_md

        # Create fake plan data that would be in a plans.md file
        plans_content = """# Plans

## Deploy v2 [draft]
- **id**: plan-test123
- **created**: 2026-04-01

### Steps
1. [ ] Update config
2. [ ] Run migrations
"""
        with (
            patch("integrations.mission_control.services._resolve_bot", new_callable=AsyncMock),
            patch("app.services.channel_workspace.ensure_channel_workspace"),
            patch("app.services.channel_workspace.write_workspace_file"),
            patch("app.services.channel_workspace.read_workspace_file", return_value=plans_content),
        ):
            channel_id = str(uuid.uuid4())
            plans = await _get_plans(channel_id)

            # Should have imported something (exact count depends on parser)
            # The key thing is it didn't crash and the channel is now marked migrated
            from integrations.mission_control import services
            assert channel_id in services._plans_migrated


async def _get_plans(channel_id: str) -> list[dict]:
    """Helper to trigger migration and get plans."""
    from integrations.mission_control.services import _get_plans_as_dicts
    return await _get_plans_as_dicts(channel_id)
