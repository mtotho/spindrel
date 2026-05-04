"""Project coding-run schedule lifecycle.

Owns the scheduled-task surface for Project coding runs: CRUD, firing, listing.
The single allowed cross-lifecycle dependency is on
``project_coding_run_orchestration.create_project_coding_run`` from
``fire_project_coding_run_schedule`` (a schedule fire spawns a fresh coding run).

Imports go: schedule → orchestration → lib. Never the reverse.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow
from app.db.models import Channel, Project, Task
from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_SCHEDULE_PRESET_ID,
    ProjectCodingRunCreate,
    ProjectCodingRunScheduleCreate,
    ProjectCodingRunScheduleUpdate,
    ProjectMachineTargetGrant,
    _attach_task_machine_grant,
    _machine_target_grant_summary,
    _utcnow,
    _uuid_from_config,
    normalize_work_surface_mode,
)
from app.services.project_run_environment_profiles import validate_project_run_environment_profile_or_raise
from app.services.project_run_model_selection import (
    PROJECT_RUN_MODEL_SELECTION_KEY,
    normalize_project_run_model_selection,
    project_run_model_selection_from_config,
    project_run_model_selection_summary,
)


def _schedule_execution_config(
    *,
    project_id: uuid.UUID,
    request: str,
    repo_path: str | None,
    work_surface_mode: str,
    run_environment_profile: str | None,
    machine_target_grant: ProjectMachineTargetGrant | None,
    loop_policy: dict[str, Any] | None,
    model_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "run_preset_id": PROJECT_CODING_RUN_SCHEDULE_PRESET_ID,
        "project_coding_run_schedule": {
            "project_id": str(project_id),
            "request": request.strip(),
            "repo_path": repo_path,
            "work_surface_mode": normalize_work_surface_mode(work_surface_mode),
            "run_environment_profile": run_environment_profile,
            "machine_target_grant": _machine_target_grant_summary(machine_target_grant),
            "loop_policy": dict(loop_policy or {}),
            PROJECT_RUN_MODEL_SELECTION_KEY: dict(model_selection or {}),
        },
    }


def _project_schedule_config(task: Task) -> dict[str, Any]:
    if not isinstance(task.execution_config, dict):
        return {}
    cfg = task.execution_config.get("project_coding_run_schedule")
    return cfg if isinstance(cfg, dict) else {}


def _validate_schedule_channel(project: Project, channel: Channel | None) -> Channel:
    if channel is None:
        raise ValueError("channel not found")
    if channel.project_id != project.id:
        raise ValueError("channel does not belong to this Project")
    return channel


def _validate_schedule_request(request: str) -> str:
    text = (request or "").strip()
    if len(text) < 20:
        raise ValueError("Project coding-run schedules require a concrete run brief")
    if text.startswith(("docs/", ".spindrel/", "/")) and "\n" not in text and len(text.split()) == 1:
        raise ValueError("Project coding-run schedule request cannot be only a file path")
    return text


def _is_project_coding_run_schedule(project: Project, task: Task) -> bool:
    if not isinstance(task.execution_config, dict):
        return False
    if task.execution_config.get("run_preset_id") != PROJECT_CODING_RUN_SCHEDULE_PRESET_ID:
        return False
    cfg = _project_schedule_config(task)
    return cfg.get("project_id") == str(project.id)


async def create_project_coding_run_schedule(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunScheduleCreate,
) -> Task:
    from app.agent.tasks import validate_recurrence

    channel = _validate_schedule_channel(project, await db.get(Channel, body.channel_id))
    recurrence = validate_recurrence(body.recurrence) or None
    scheduled_at = body.scheduled_at or _utcnow()
    title = body.title.strip() or "Scheduled Project coding run"
    request = _validate_schedule_request(body.request)
    work_surface_mode = normalize_work_surface_mode(body.work_surface_mode)
    await validate_project_run_environment_profile_or_raise(
        project,
        profile_id=body.run_environment_profile,
        repo_path=body.repo_path,
        work_surface_mode=work_surface_mode,
    )
    model_selection = await normalize_project_run_model_selection(
        db,
        channel,
        model_override=body.model_override,
        model_provider_id_override=body.model_provider_id_override,
        harness_effort=body.harness_effort,
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id=channel.bot_id,
        client_id=channel.client_id,
        session_id=channel.active_session_id,
        channel_id=channel.id,
        prompt=request,
        title=title,
        scheduled_at=scheduled_at,
        status="active",
        task_type="scheduled",
        dispatch_type=channel.integration if channel.integration and channel.dispatch_config else "none",
        dispatch_config=dict(channel.dispatch_config) if channel.integration and channel.dispatch_config else None,
        execution_config=_schedule_execution_config(
            project_id=project.id,
            request=request,
            repo_path=body.repo_path,
            work_surface_mode=work_surface_mode,
            run_environment_profile=body.run_environment_profile,
            machine_target_grant=body.machine_target_grant,
            loop_policy=body.loop_policy,
            model_selection=model_selection.to_persisted(),
        ),
        recurrence=recurrence,
        source="project_coding_run_schedule",
        created_at=_utcnow(),
    )
    db.add(task)
    await db.flush()
    await _attach_task_machine_grant(
        db,
        task=task,
        grant=body.machine_target_grant,
        granted_by_user_id=body.granted_by_user_id,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def update_project_coding_run_schedule(
    db: AsyncSession,
    project: Project,
    schedule_id: uuid.UUID,
    body: ProjectCodingRunScheduleUpdate,
) -> Task:
    from app.agent.tasks import validate_recurrence
    from app.services.machine_task_grants import revoke_task_machine_grant

    task = await db.get(Task, schedule_id)
    if task is None or not _is_project_coding_run_schedule(project, task):
        raise ValueError("coding-run schedule not found")

    cfg = dict(_project_schedule_config(task))
    channel = await db.get(Channel, task.channel_id) if task.channel_id else None
    if body.channel_id is not None and body.channel_id != task.channel_id:
        channel = _validate_schedule_channel(project, await db.get(Channel, body.channel_id))
        task.channel_id = channel.id
        task.bot_id = channel.bot_id
        task.client_id = channel.client_id
        task.session_id = channel.active_session_id
        task.dispatch_type = channel.integration if channel.integration and channel.dispatch_config else "none"
        task.dispatch_config = dict(channel.dispatch_config) if channel.integration and channel.dispatch_config else None
    if channel is None:
        channel = _validate_schedule_channel(project, None)

    if body.title is not None:
        task.title = body.title.strip() or task.title
    if body.request is not None:
        request = _validate_schedule_request(body.request)
        cfg["request"] = request
        task.prompt = request
    if body.repo_path_set:
        cfg["repo_path"] = body.repo_path
    if body.work_surface_mode is not None:
        cfg["work_surface_mode"] = normalize_work_surface_mode(body.work_surface_mode)
    if body.run_environment_profile_set:
        cfg["run_environment_profile"] = body.run_environment_profile
    if body.scheduled_at_set:
        task.scheduled_at = body.scheduled_at
    if body.recurrence is not None:
        task.recurrence = validate_recurrence(body.recurrence) or None
    if body.enabled is not None:
        task.status = "active" if body.enabled else "cancelled"
    if body.machine_target_grant_set:
        cfg["machine_target_grant"] = _machine_target_grant_summary(body.machine_target_grant) if body.machine_target_grant else None
        await revoke_task_machine_grant(db, task.id)
        if body.machine_target_grant is not None:
            await _attach_task_machine_grant(
                db,
                task=task,
                grant=body.machine_target_grant,
                granted_by_user_id=body.granted_by_user_id,
            )
    if body.loop_policy is not None:
        cfg["loop_policy"] = dict(body.loop_policy or {})
    current_selection = project_run_model_selection_from_config(cfg.get(PROJECT_RUN_MODEL_SELECTION_KEY))
    model_override = body.model_override if body.model_override_set else current_selection.model_override
    provider_override = (
        body.model_provider_id_override
        if body.model_provider_id_override_set
        else current_selection.model_provider_id_override
    )
    harness_effort = body.harness_effort if body.harness_effort_set else current_selection.harness_effort
    model_selection = await normalize_project_run_model_selection(
        db,
        channel,
        model_override=model_override,
        model_provider_id_override=provider_override,
        harness_effort=harness_effort,
    )
    cfg[PROJECT_RUN_MODEL_SELECTION_KEY] = model_selection.to_persisted()
    await validate_project_run_environment_profile_or_raise(
        project,
        profile_id=cfg.get("run_environment_profile"),
        repo_path=str(cfg.get("repo_path") or "") or None,
        work_surface_mode=normalize_work_surface_mode(cfg.get("work_surface_mode")),
    )
    task.execution_config = {
        **dict(task.execution_config or {}),
        "run_preset_id": PROJECT_CODING_RUN_SCHEDULE_PRESET_ID,
        "project_coding_run_schedule": cfg,
    }
    await db.commit()
    await db.refresh(task)
    return task


async def disable_project_coding_run_schedule(
    db: AsyncSession,
    project: Project,
    schedule_id: uuid.UUID,
) -> Task:
    task = await db.get(Task, schedule_id)
    if task is None or not _is_project_coding_run_schedule(project, task):
        raise ValueError("coding-run schedule not found")
    task.status = "cancelled"
    await db.commit()
    await db.refresh(task)
    return task


async def fire_project_coding_run_schedule(
    db: AsyncSession,
    schedule: Task,
    *,
    interval: timedelta | None = None,
    advance: bool = True,
) -> Task | None:
    from app.services.project_coding_run_orchestration import create_project_coding_run

    cfg = _project_schedule_config(schedule)
    project_id = _uuid_from_config(cfg.get("project_id"))
    if project_id is None:
        raise ValueError("coding-run schedule missing Project")
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    if not _is_project_coding_run_schedule(project, schedule):
        raise ValueError("coding-run schedule not found")
    if schedule.status != "active":
        return None
    channel_id = _uuid_from_config(schedule.channel_id)
    if channel_id is None:
        raise ValueError("coding-run schedule missing channel")
    run_number = int((schedule.run_count or 0) + 1)
    model_selection = (
        cfg.get(PROJECT_RUN_MODEL_SELECTION_KEY)
        if isinstance(cfg.get(PROJECT_RUN_MODEL_SELECTION_KEY), dict)
        else {}
    )
    grant = None
    grant_cfg = cfg.get("machine_target_grant")
    if isinstance(grant_cfg, dict) and grant_cfg.get("provider_id") and grant_cfg.get("target_id"):
        grant = ProjectMachineTargetGrant(
            provider_id=str(grant_cfg["provider_id"]),
            target_id=str(grant_cfg["target_id"]),
            capabilities=list(grant_cfg.get("capabilities") or []),
            allow_agent_tools=bool(grant_cfg.get("allow_agent_tools", True)),
            expires_at=grant_cfg.get("expires_at"),
        )
    task = await create_project_coding_run(
        db,
        project,
        ProjectCodingRunCreate(
            channel_id=channel_id,
            request=str(cfg.get("request") or schedule.prompt or ""),
            repo_path=str(cfg.get("repo_path") or "") or None,
            work_surface_mode=normalize_work_surface_mode(cfg.get("work_surface_mode")),
            run_environment_profile=str(cfg.get("run_environment_profile") or "") or None,
            machine_target_grant=grant,
            schedule_task_id=schedule.id,
            schedule_run_number=run_number,
            loop_policy=cfg.get("loop_policy") if isinstance(cfg.get("loop_policy"), dict) else None,
            model_override=model_selection.get("model_override"),
            model_provider_id_override=model_selection.get("model_provider_id_override"),
            harness_effort=model_selection.get("harness_effort"),
        ),
    )
    schedule = await db.get(Task, schedule.id)
    if schedule is not None:
        if advance and interval is not None:
            base = schedule.scheduled_at or _utcnow()
            schedule.scheduled_at = base + interval
        schedule.run_count = run_number
        await db.commit()
    return task


async def list_project_coding_run_schedules(
    db: AsyncSession,
    project: Project,
) -> list[dict[str, Any]]:
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    if not channel_ids:
        return []
    candidates = list((await db.execute(
        select(Task)
        .where(Task.channel_id.in_(channel_ids))
        .order_by(Task.created_at.desc())
    )).scalars().all())
    schedules = [task for task in candidates if _is_project_coding_run_schedule(project, task)]
    recent_runs: dict[str, list[dict[str, Any]]] = {}
    if schedules:
        run_candidates = list((await db.execute(
            select(Task)
            .where(Task.parent_task_id.in_([item.id for item in schedules]))
            .order_by(Task.created_at.desc())
        )).scalars().all())
        for run in run_candidates:
            sid = str(run.parent_task_id)
            rows = recent_runs.setdefault(sid, [])
            if len(rows) >= 3 or not isinstance(run.execution_config, dict):
                continue
            cfg = run.execution_config.get("project_coding_run") or {}
            rows.append({
                "id": str(run.id),
                "task_id": str(run.id),
                "channel_id": str(run.channel_id) if run.channel_id else None,
                "session_id": str(run.session_id) if run.session_id else None,
                "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "branch": cfg.get("branch") if isinstance(cfg, dict) else None,
            })
    return [await _coding_run_schedule_row(db, task, recent_runs.get(str(task.id), [])) for task in schedules]


async def _coding_run_schedule_row(db: AsyncSession, task: Task, recent_runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from app.services.machine_task_grants import task_machine_grant_payload

    cfg = _project_schedule_config(task)
    channel = await db.get(Channel, task.channel_id) if task.channel_id else None
    bot = await db.get(BotRow, task.bot_id) if task.bot_id else None
    return {
        "id": str(task.id),
        "project_id": cfg.get("project_id"),
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "title": task.title or "Scheduled Project coding run",
        "request": cfg.get("request") or task.prompt or "",
        "status": task.status,
        "enabled": task.status == "active",
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "recurrence": task.recurrence,
        "run_count": task.run_count or 0,
        "last_run": (recent_runs or [None])[0],
        "recent_runs": recent_runs or [],
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "machine_target_grant": await task_machine_grant_payload(db, task),
        "repo_path": cfg.get("repo_path"),
        "work_surface_mode": normalize_work_surface_mode(cfg.get("work_surface_mode")),
        "run_environment_profile": cfg.get("run_environment_profile"),
        "loop_policy": cfg.get("loop_policy") if isinstance(cfg.get("loop_policy"), dict) else None,
        "model_selection": project_run_model_selection_summary(
            execution_config=dict(task.execution_config or {}),
            run_config=cfg,
            channel=channel,
            bot=bot,
        ),
    }
