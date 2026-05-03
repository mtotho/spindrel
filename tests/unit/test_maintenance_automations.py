"""Maintenance automation read-model and task policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Task
from tests.factories import build_bot


class TestMaintenanceAutomationReadModel:
    def test_builds_definition_from_bot_columns_without_db_round_trip(self):
        from app.services.maintenance_automations import build_maintenance_job

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="pure-maint-bot",
            name="Pure Maint Bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=18,
            memory_hygiene_model="gpt-4.1-mini",
            memory_hygiene_extra_instructions="compact old logs",
            last_hygiene_run_at=now - timedelta(hours=18),
            next_hygiene_run_at=now + timedelta(hours=6),
        )
        task = Task(
            bot_id=bot.id,
            task_type="memory_hygiene",
            status="complete",
            run_at=now - timedelta(hours=18),
        )

        job = build_maintenance_job(bot, "memory_hygiene", last_task=task)

        assert job.bot_id == "pure-maint-bot"
        assert job.bot_name == "Pure Maint Bot"
        assert job.title == "Memory maintenance"
        assert job.enabled is True
        assert job.interval_hours == 18
        assert job.model == "gpt-4.1-mini"
        assert job.extra_instructions == "compact old logs"
        assert job.last_run_at == bot.last_hygiene_run_at
        assert job.next_run_at == bot.next_hygiene_run_at
        assert job.last_task_status == "complete"

    @pytest.mark.asyncio
    async def test_lists_both_bot_scoped_maintenance_jobs_with_last_task_state(
        self, db_session,
    ):
        from app.services.maintenance_automations import list_maintenance_jobs

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="maint-bot",
            name="Maintenance Bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=24,
            next_hygiene_run_at=now + timedelta(hours=1),
            skill_review_enabled=True,
            skill_review_interval_hours=72,
            skill_review_model="gpt-4.1",
            next_skill_review_run_at=now + timedelta(hours=2),
        )
        db_session.add(bot)
        db_session.add(Task(
            bot_id=bot.id,
            title="old memory run",
            task_type="memory_hygiene",
            status="complete",
            run_at=now - timedelta(hours=1),
            completed_at=now - timedelta(minutes=55),
        ))
        db_session.add(Task(
            bot_id=bot.id,
            title="latest skill run",
            task_type="skill_review",
            status="failed",
            run_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=25),
        ))
        await db_session.commit()

        jobs = await list_maintenance_jobs(db_session)

        by_type = {job.job_type: job for job in jobs}
        assert set(by_type) == {"memory_hygiene", "skill_review"}
        assert by_type["memory_hygiene"].title == "Memory maintenance"
        assert by_type["memory_hygiene"].enabled is True
        assert by_type["memory_hygiene"].interval_hours == 24
        assert by_type["memory_hygiene"].last_task_status == "complete"
        assert by_type["memory_hygiene"].next_run_at == bot.next_hygiene_run_at
        assert by_type["skill_review"].title == "Skill review"
        assert by_type["skill_review"].model == "gpt-4.1"
        assert by_type["skill_review"].last_task_status == "failed"
        assert by_type["skill_review"].next_run_at == bot.next_skill_review_run_at

    @pytest.mark.asyncio
    async def test_upcoming_items_include_each_enabled_job_type(self, db_session):
        from app.services.maintenance_automations import list_upcoming_maintenance_items

        now = datetime.now(timezone.utc)
        bot = build_bot(
            id="upcoming-maint-bot",
            name="Upcoming Maint Bot",
            memory_scheme="workspace-files",
            memory_hygiene_enabled=True,
            memory_hygiene_interval_hours=12,
            next_hygiene_run_at=now + timedelta(hours=1),
            skill_review_enabled=True,
            skill_review_interval_hours=48,
            next_skill_review_run_at=now + timedelta(hours=3),
        )
        db_session.add(bot)
        await db_session.commit()

        items = await list_upcoming_maintenance_items(db_session)

        assert [item["task_type"] for item in items] == ["memory_hygiene", "skill_review"]
        assert [item["title"] for item in items] == ["Memory maintenance", "Skill review"]
        assert {item["type"] for item in items} == {"maintenance"}


class TestTaskKindPolicy:
    @pytest.mark.parametrize(
        ("task_type", "profile", "hard_cap"),
        [("memory_hygiene", "memory_hygiene", 12), ("skill_review", "skill_review", 8)],
    )
    def test_maintenance_tasks_use_hygiene_runtime_policy(self, task_type, profile, hard_cap):
        from app.services.task_run_policy import resolve_task_run_policy

        policy = resolve_task_run_policy(task_type)

        assert policy.context_profile == profile
        assert policy.origin == "hygiene"
        assert policy.skip_skill_inject is True
        assert policy.run_control_policy["tool_surface"] == "strict"
        assert policy.run_control_policy["hard_max_llm_calls"] == hard_cap

    def test_heartbeat_and_default_task_policies_remain_distinct(self):
        from app.services.task_run_policy import resolve_task_run_policy

        heartbeat = resolve_task_run_policy("heartbeat")
        scheduled = resolve_task_run_policy("scheduled")

        assert heartbeat.context_profile == "heartbeat"
        assert heartbeat.origin == "heartbeat"
        assert scheduled.context_profile is None
        assert scheduled.origin == "task"
        assert scheduled.skip_skill_inject is False

    def test_task_run_control_policy_applies_maintenance_caps(self):
        from app.agent.task_run_host import _task_run_control_policy

        policy = _task_run_control_policy({}, task_type="memory_hygiene")

        assert policy["tool_surface"] == "strict"
        assert policy["hard_max_llm_calls"] == 12
        assert policy["soft_max_llm_calls"] == 8

    def test_task_run_control_policy_allows_explicit_overrides(self):
        from app.agent.task_run_host import _task_run_control_policy

        policy = _task_run_control_policy(
            {"run_control_policy": {"hard_max_llm_calls": 2}},
            task_type="memory_hygiene",
        )

        assert policy["tool_surface"] == "strict"
        assert policy["hard_max_llm_calls"] == 2
