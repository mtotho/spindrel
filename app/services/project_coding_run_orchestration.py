"""Project coding-run orchestration lifecycle.

Owns the create + continue surface for Project coding runs, plus the per-run
prompt rendering, the task→machine-grant attach helper, and the continuation
index lookup. Imports go orchestration → lib. Schedule fires by importing
``create_project_coding_run`` from here, the single allowed cross-lifecycle
direction.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Project, Session, Task
from app.services.run_presets import get_run_preset

from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_PRESET_ID,
    ProjectCodingRunContinue,
    ProjectCodingRunCreate,
    ProjectConcurrencyCapExceeded,
    ProjectMachineTargetGrant,
    ProjectTaskExecutionContext,
    WORK_SURFACE_FRESH_PROJECT_INSTANCE,
    WORK_SURFACE_ISOLATED_WORKTREE,
    WORK_SURFACE_SHARED_REPO,
    _attach_task_machine_grant,
    count_active_project_coding_implementations,
    _latest_run_receipts_by_task,
    _lineage_config,
    _load_project_coding_task,
    _machine_access_prompt_block,
    _prior_evidence_context,
    _safe_dependency_stack_target,
    _utcnow,
    initial_project_run_loop_state,
    normalize_project_run_loop_policy,
    normalize_work_surface_mode,
)
from app.services.project_runtime import project_snapshot


def _session_environment_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(payload.get("session_id")) if payload.get("session_id") else None,
        "mode": payload.get("mode"),
        "status": payload.get("status"),
        "cwd": payload.get("cwd"),
        "docker_status": payload.get("docker_status"),
        "docker_endpoint": payload.get("docker_endpoint"),
        "worktree": payload.get("worktree"),
        "error": (payload.get("metadata") or {}).get("error") if isinstance(payload.get("metadata"), dict) else None,
    }


async def _ensure_project_run_execution_environment(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    branch: str | None,
    base_branch: str | None,
    repo_path: str | None,
) -> None:
    if task.session_id is None:
        return
    from app.services.session_execution_environments import (
        ensure_isolated_session_environment,
        record_failed_session_execution_environment,
        session_execution_environment_out,
    )

    cfg = dict(task.execution_config or {})
    run_cfg = dict(cfg.get("project_coding_run") or {})
    run_cfg["session_environment"] = {
        "session_id": str(task.session_id),
        "mode": "isolated",
        "status": "preparing",
    }
    cfg["project_coding_run"] = run_cfg
    task.execution_config = cfg
    await db.flush()

    try:
        env = await ensure_isolated_session_environment(
            db,
            session_id=task.session_id,
            project=project,
            branch=branch,
            base_branch=base_branch,
            repo_path=repo_path,
        )
        payload = session_execution_environment_out(env, session_id=env.session_id)
    except Exception as exc:
        env = await record_failed_session_execution_environment(
            db,
            session_id=task.session_id,
            project=project,
            error=str(exc),
            branch=branch,
            base_branch=base_branch,
            repo_path=repo_path,
        )
        payload = session_execution_environment_out(env, session_id=env.session_id)

    cfg = dict(task.execution_config or {})
    run_cfg = dict(cfg.get("project_coding_run") or {})
    run_cfg["session_environment"] = _session_environment_run_summary(payload)
    cfg["project_coding_run"] = run_cfg
    task.execution_config = cfg
    await db.flush()


def _apply_work_surface_mode(task: Task, mode: str) -> None:
    normalized = normalize_work_surface_mode(mode)
    ecfg = dict(task.execution_config or {})
    ecfg["work_surface_mode"] = normalized
    if normalized == WORK_SURFACE_FRESH_PROJECT_INSTANCE:
        ecfg["project_instance"] = {"mode": "fresh"}
    else:
        ecfg["project_instance"] = {"mode": "shared"}
    task.execution_config = ecfg


async def _attach_visible_project_run_session(
    db: AsyncSession,
    *,
    channel: Channel,
    task: Task,
    project: Project,
    prompt: str,
    source: str,
) -> None:
    """Create the visible channel session that operators use to inspect a run."""
    now = _utcnow()
    session_id = uuid.uuid4()
    pre_user_msg_id = uuid.uuid4()
    title = task.title or "Project coding run"
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=task.bot_id,
        channel_id=channel.id,
        title=title,
        locked=channel.integration is not None,
        source_task_id=task.id,
        metadata_={
            "created_by": "project_coding_run",
            "source": source,
            "project_id": str(project.id),
            "source_task_id": str(task.id),
        },
        created_at=now,
        last_active=now,
    )
    message = Message(
        id=pre_user_msg_id,
        session_id=session_id,
        role="user",
        content=prompt,
        correlation_id=task.correlation_id,
        metadata_={
            "sender_type": "project_run_launcher",
            "sender_display_name": "Project run launcher",
            "source": source,
            "task_id": str(task.id),
            "project_id": str(project.id),
            "context_visibility": "session",
        },
        created_at=now,
    )
    db.add(session)
    db.add(message)
    task.session_id = session_id
    task.execution_config = {
        **dict(task.execution_config or {}),
        "session_scoped": True,
        "session_target": {"mode": "existing", "session_id": str(session_id)},
        "pre_user_msg_id": str(pre_user_msg_id),
    }
    channel.updated_at = now


def _project_coding_run_prompt(
    *,
    base_prompt: str,
    project: Project,
    request: str,
    defaults: dict[str, Any],
    runtime_target: dict[str, Any],
    dev_targets: list[dict[str, Any]] | None = None,
    machine_target_grant: ProjectMachineTargetGrant | None = None,
    work_surface_mode: str = WORK_SURFACE_ISOLATED_WORKTREE,
    continuation: dict[str, Any] | None = None,
    loop_policy: dict[str, Any] | None = None,
    loop_iteration: int = 1,
) -> str:
    base_branch = defaults.get("base_branch") or "the repository default branch"
    branch = defaults.get("branch")
    repo = defaults.get("repo") or {}
    repo_path = repo.get("path") or "the Project root"
    cwd_line = repo.get("path") or "the Project root"
    configured_keys = ", ".join(runtime_target.get("configured_keys") or []) or "none"
    missing_secrets = ", ".join(runtime_target.get("missing_secrets") or []) or "none"
    dependency_stack = _safe_dependency_stack_target(project)
    dependency_stack_line = (
        f"Configured from {dependency_stack.get('source_path') or 'inline spec'}"
        if dependency_stack.get("configured")
        else "Not configured"
    )
    dev_target_lines = []
    for target in dev_targets or []:
        dev_target_lines.append(
            f"- {target.get('label') or target.get('key')}: {target.get('url')} "
            f"({target.get('port_env')}={target.get('port')}, {target.get('url_env')}={target.get('url')})"
        )
    dev_target_block = (
        "Assigned dev targets:\n"
        + ("\n".join(dev_target_lines) if dev_target_lines else "- No assigned dev targets; choose an unused port and report it in the run receipt.")
        + "\n"
    )
    request_text = request.strip() or "Use the Project task request from the run title and Project context."
    continuation_block = ""
    if continuation:
        feedback = str(continuation.get("feedback") or "").strip() or "Continue from the reviewer feedback on the existing PR."
        parent_task_id = continuation.get("parent_task_id") or "unknown"
        root_task_id = continuation.get("root_task_id") or parent_task_id
        handoff_url = continuation.get("handoff_url") or "not recorded"
        prior_evidence = continuation.get("prior_evidence") or {}
        evidence_line = (
            f"{prior_evidence.get('tests_count', 0)} tests, "
            f"{prior_evidence.get('screenshots_count', 0)} screenshots, "
            f"{prior_evidence.get('changed_files_count', 0)} files"
        )
        continuation_block = (
            "\n\nReview continuation context:\n"
            "- This is a follow-up run for an existing Project coding run, not a fresh branch.\n"
            f"- Parent task: {parent_task_id}\n"
            f"- Root task: {root_task_id}\n"
            f"- Existing handoff/PR: {handoff_url}\n"
            f"- Prior evidence: {evidence_line}\n"
            "- Update the same work branch and existing PR. Do not create a replacement PR unless the handoff tool reports that reuse is impossible.\n"
            "- Address the reviewer feedback, rerun relevant tests/screenshots, and publish a new Project run receipt.\n\n"
            f"Reviewer feedback:\n{feedback}"
        )
    loop_block = ""
    if loop_policy:
        max_iterations = int(loop_policy.get("max_iterations") or 1)
        stop_condition = str(loop_policy.get("stop_condition") or "").strip()
        loop_block = (
            "\n\nBounded Project run loop:\n"
            f"- Loop iteration: {loop_iteration} of {max_iterations}.\n"
            f"- Stop condition: {stop_condition}\n"
            "- This loop reuses the same branch, PR/handoff, Project instance, dependency stack, and continuation lineage.\n"
            "- At the end of this turn, publish_project_run_receipt must include loop_decision.\n"
            "- Use loop_decision=\"continue\" only when there is concrete remaining implementation or verification work and another iteration should start automatically.\n"
            "- Use loop_decision=\"done\" when the work satisfies the stop condition and is ready for human review.\n"
            "- Use loop_decision=\"needs_review\" when a human should decide instead of another automatic iteration.\n"
            "- Use loop_decision=\"blocked\" when progress requires external input or unavailable access.\n"
            "- Include loop_reason and remaining_work when loop_decision is continue, blocked, or needs_review.\n"
        )
    return (
        f"{base_prompt}\n\n"
        "Project coding-run handoff configuration:\n"
        f"- Project: {project.name} (/{project.root_path})\n"
        f"- Repository path: {repo_path}\n"
        f"- Base branch: {base_branch}\n"
        f"- Work branch: {branch}\n"
        f"- Work surface mode: {normalize_work_surface_mode(work_surface_mode)}\n"
        f"- Effective CWD: {cwd_line}\n"
        f"- Runtime/dev/dependency configured keys: {configured_keys}\n"
        f"- Missing runtime secret bindings: {missing_secrets}\n\n"
        "Execution environment:\n"
        "- Scheduled and Project coding runs use the configured work surface from the run launcher.\n"
        "- Use ordinary shell, test, Docker, and docker compose commands from the current working directory. In isolated runs, Docker commands are routed to this session's private Docker daemon.\n"
        "- Start any app/dev server yourself with native bash on your own unused or assigned port; do not restart another agent's server process.\n\n"
        "Project-run boundary:\n"
        "- Do not bootstrap, restart, or reconfigure the host Spindrel API/e2e server for ordinary Project work.\n"
        "- Do not run repo-dev bootstrap helpers such as scripts/agent_e2e_dev.py prepare, start-api, or prepare-harness-parity unless this task explicitly asks you to change that infrastructure.\n"
        "- Use the runtime env, the session Docker daemon, and your own source-run dev process instead.\n\n"
        f"{dev_target_block}\n"
        f"{_machine_access_prompt_block(machine_target_grant)}\n"
        "Guided handoff requirements:\n"
        "1. Before editing, confirm the current directory is the repo root, inspect git status, and update from the base branch when safe.\n"
        f"2. Create or switch to the work branch `{branch}` before making changes.\n"
        "3. Use the Project runtime env, dependency stack env, and assigned dev targets for repo-local tests, app/dev servers, and screenshots.\n"
        "4. If GitHub credentials and gh are available, push the branch and open a draft PR. "
        "If not, publish a blocked or needs_review receipt with the exact blocker.\n"
        "5. publish_project_run_receipt must include branch, base_branch, changed files, tests, screenshots, dev target status, and handoff URL when available.\n\n"
        f"Project task request:\n{request_text}"
        f"{loop_block}"
        f"{continuation_block}"
    )


async def create_project_coding_run(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunCreate,
    *,
    commit: bool = True,
) -> Task:
    snapshot = project_snapshot(project)
    if not snapshot:
        raise ValueError("Project coding runs require an applied Blueprint snapshot. Create a Blueprint from this Project first.")
    cap_raw = snapshot.get("max_concurrent_runs")
    cap = int(cap_raw) if isinstance(cap_raw, int) and cap_raw > 0 else None
    if cap is not None:
        in_flight = await count_active_project_coding_implementations(db, project)
        if in_flight >= cap:
            raise ProjectConcurrencyCapExceeded(cap=cap, in_flight=in_flight)
    channel = await db.get(Channel, body.channel_id)
    if channel is None:
        raise ValueError("channel not found")
    if channel.project_id != project.id:
        raise ValueError("channel does not belong to this Project")
    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    if preset is None:
        raise ValueError("Project coding-run preset is not registered")

    task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.fresh(
        db,
        project,
        task_id=task_id,
        request=body.request,
        repo_path=body.repo_path,
        machine_grant=body.machine_target_grant,
        source_artifact=body.source_artifact,
        schedule_task_id=body.schedule_task_id,
        schedule_run_number=body.schedule_run_number,
    )
    work_surface_mode = normalize_work_surface_mode(body.work_surface_mode)
    loop_policy = normalize_project_run_loop_policy(body.loop_policy)
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=body.request,
        defaults={"branch": ctx.branch, "base_branch": ctx.base_branch, "repo": ctx.repo},
        runtime_target=ctx.runtime_target.to_persisted(),
        dev_targets=[t.to_persisted() for t in ctx.dev_targets],
        machine_target_grant=body.machine_target_grant,
        work_surface_mode=work_surface_mode,
        loop_policy=loop_policy,
    )
    task = Task(
        id=task_id,
        prompt=prompt,
        scheduled_at=None,
        status="pending",
        recurrence=None,
        parent_task_id=body.schedule_task_id,
        created_at=_utcnow(),
    )
    ctx.apply_to_task(task, channel=channel)
    _apply_work_surface_mode(task, work_surface_mode)
    run_cfg = task.execution_config.setdefault("project_coding_run", {})
    run_cfg["loop_policy"] = loop_policy
    run_cfg["loop_state"] = initial_project_run_loop_state(loop_policy)
    await _attach_visible_project_run_session(
        db,
        channel=channel,
        task=task,
        project=project,
        prompt=prompt,
        source="manual" if body.schedule_task_id is None else "schedule",
    )
    db.add(task)
    await db.flush()
    if work_surface_mode != WORK_SURFACE_SHARED_REPO:
        await _ensure_project_run_execution_environment(
            db,
            task=task,
            project=project,
            branch=ctx.branch,
            base_branch=ctx.base_branch,
            repo_path=ctx.repo.get("path") if isinstance(ctx.repo, dict) else body.repo_path,
        )
    await _attach_task_machine_grant(
        db,
        task=task,
        grant=body.machine_target_grant,
        granted_by_user_id=body.granted_by_user_id,
    )
    if commit:
        await db.commit()
        await db.refresh(task)
    return task


async def _next_continuation_index(db: AsyncSession, project: Project, root_task_id: uuid.UUID) -> int:
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    if not channel_ids:
        return 1
    candidates = list((await db.execute(
        select(Task).where(Task.channel_id.in_(channel_ids))
    )).scalars().all())
    max_index = 0
    for task in candidates:
        if not isinstance(task.execution_config, dict):
            continue
        cfg = task.execution_config.get("project_coding_run")
        if not isinstance(cfg, dict):
            continue
        lineage = _lineage_config(task, cfg)
        if lineage["root_task_id"] == str(root_task_id):
            max_index = max(max_index, int(lineage["continuation_index"] or 0))
    return max_index + 1


async def continue_project_coding_run(
    db: AsyncSession,
    project: Project,
    task_id: uuid.UUID,
    body: ProjectCodingRunContinue,
) -> Task:
    parent = await _load_project_coding_task(db, project, task_id)
    channel = await db.get(Channel, parent.channel_id) if parent.channel_id else None
    if channel is None or channel.project_id != project.id:
        raise ValueError("coding run not found")
    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    if preset is None:
        raise ValueError("Project coding-run preset is not registered")

    parent_ctx = ProjectTaskExecutionContext.from_task(parent)
    root_task_id = uuid.UUID(parent_ctx.lineage.root_task_id)
    continuation_index = await _next_continuation_index(db, project, root_task_id)
    receipt = (await _latest_run_receipts_by_task(db, project.id, [parent.id])).get(parent.id)
    prior_evidence = _prior_evidence_context(receipt)
    feedback = body.feedback.strip()

    new_task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.from_parent(
        db,
        project,
        parent,
        new_task_id=new_task_id,
        feedback=feedback,
        prior_evidence=prior_evidence,
        continued_from_handoff_url=prior_evidence.get("handoff_url"),
        continuation_index=continuation_index,
    )
    continuation_context = {
        "feedback": feedback,
        "parent_task_id": str(parent.id),
        "root_task_id": str(root_task_id),
        "handoff_url": prior_evidence.get("handoff_url"),
        "prior_evidence": prior_evidence,
    }
    parent_cfg = parent.execution_config if isinstance(parent.execution_config, dict) else {}
    parent_run_cfg = parent_cfg.get("project_coding_run") if isinstance(parent_cfg.get("project_coding_run"), dict) else {}
    loop_policy = normalize_project_run_loop_policy(parent_run_cfg.get("loop_policy") if isinstance(parent_run_cfg.get("loop_policy"), dict) else None)
    work_surface_mode = normalize_work_surface_mode(parent_cfg.get("work_surface_mode"))
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=ctx.request,
        defaults={"branch": ctx.branch, "base_branch": ctx.base_branch, "repo": ctx.repo},
        runtime_target=ctx.runtime_target.to_persisted(),
        dev_targets=[t.to_persisted() for t in ctx.dev_targets],
        machine_target_grant=None,
        work_surface_mode=work_surface_mode,
        continuation=continuation_context,
        loop_policy=loop_policy,
        loop_iteration=continuation_index + 1,
    )
    task = Task(
        id=new_task_id,
        prompt=prompt,
        scheduled_at=None,
        status="pending",
        recurrence=None,
        created_at=_utcnow(),
    )
    ctx.apply_to_task(task, channel=channel)
    _apply_work_surface_mode(task, work_surface_mode)
    task.title = f"{preset.task_defaults.title} follow-up {continuation_index}"
    parent_ecfg = parent.execution_config if isinstance(parent.execution_config, dict) else {}
    task_run_cfg = task.execution_config.setdefault("project_coding_run", {})
    task_run_cfg["loop_policy"] = loop_policy
    task_run_cfg["loop_state"] = {
        **initial_project_run_loop_state(loop_policy),
        "iteration": continuation_index + 1,
        "state": "running" if loop_policy else "disabled",
    }
    if isinstance(parent_ecfg.get("session_target"), dict):
        task.execution_config["session_target"] = dict(parent_ecfg["session_target"])
    if isinstance(parent_ecfg.get("project_instance"), dict):
        task.execution_config["project_instance"] = dict(parent_ecfg["project_instance"])
    task.execution_config["work_surface_mode"] = work_surface_mode
    await _attach_visible_project_run_session(
        db,
        channel=channel,
        task=task,
        project=project,
        prompt=prompt,
        source="continuation",
    )
    parent.execution_config = {
        **parent_ecfg,
        "latest_continuation_task_id": str(task.id),
    }
    db.add(task)
    await db.flush()
    if work_surface_mode != WORK_SURFACE_SHARED_REPO:
        await _ensure_project_run_execution_environment(
            db,
            task=task,
            project=project,
            branch=ctx.branch,
            base_branch=ctx.base_branch,
            repo_path=ctx.repo.get("path") if isinstance(ctx.repo, dict) else None,
        )
    await db.commit()
    await db.refresh(task)
    return task
