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

from app.db.models import Channel, Project, Task
from app.services.run_presets import get_run_preset

from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_PRESET_ID,
    ProjectCodingRunContinue,
    ProjectCodingRunCreate,
    ProjectMachineTargetGrant,
    ProjectTaskExecutionContext,
    _attach_task_machine_grant,
    _latest_run_receipts_by_task,
    _lineage_config,
    _load_project_coding_task,
    _machine_access_prompt_block,
    _prior_evidence_context,
    _safe_dependency_stack_target,
    _utcnow,
)


def _project_coding_run_prompt(
    *,
    base_prompt: str,
    project: Project,
    request: str,
    defaults: dict[str, Any],
    runtime_target: dict[str, Any],
    dev_targets: list[dict[str, Any]] | None = None,
    machine_target_grant: ProjectMachineTargetGrant | None = None,
    continuation: dict[str, Any] | None = None,
) -> str:
    base_branch = defaults.get("base_branch") or "the repository default branch"
    branch = defaults.get("branch")
    repo = defaults.get("repo") or {}
    repo_path = repo.get("path") or "the Project root"
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
    return (
        f"{base_prompt}\n\n"
        "Project coding-run handoff configuration:\n"
        f"- Project: {project.name} (/{project.root_path})\n"
        f"- Repository path: {repo_path}\n"
        f"- Base branch: {base_branch}\n"
        f"- Work branch: {branch}\n"
        f"- Runtime/dev/dependency configured keys: {configured_keys}\n"
        f"- Missing runtime secret bindings: {missing_secrets}\n\n"
        "Project Dependency Stack:\n"
        f"- {dependency_stack_line}\n"
        "- If configured, use get_project_dependency_stack and manage_project_dependency_stack for Docker-backed databases/dependencies, logs, restarts, rebuilds, service exec, and dependency health.\n"
        "- Start any app/dev server yourself with native bash on your own unused or assigned port; do not restart another agent's server process.\n"
        "- Do not run raw docker or docker compose in a harness shell; edit the Project compose file and call manage_project_dependency_stack(action=\"reload\") when stack shape changes.\n"
        "- Do not wrap unit tests in Docker, Dockerfile.test, docker compose, or dependency stacks. Run repo-local tests with the native Project shell/runtime env.\n\n"
        "Project-run boundary:\n"
        "- Do not bootstrap, restart, or reconfigure the host Spindrel API/e2e server for ordinary Project work.\n"
        "- Do not run repo-dev bootstrap helpers such as scripts/agent_e2e_dev.py prepare, start-api, or prepare-harness-parity unless this task explicitly asks you to change that infrastructure.\n"
        "- Use the runtime env, Dependency Stack tools, and your own source-run dev process instead.\n\n"
        f"{dev_target_block}\n"
        f"{_machine_access_prompt_block(machine_target_grant)}\n"
        "Guided handoff requirements:\n"
        "1. Before editing, inspect git status and update from the base branch when safe.\n"
        f"2. Create or switch to the work branch `{branch}` before making changes.\n"
        "3. Use the Project runtime env, dependency stack env, and assigned dev targets for repo-local tests, app/dev servers, and screenshots.\n"
        "4. If GitHub credentials and gh are available, push the branch and open a draft PR. "
        "If not, publish a blocked or needs_review receipt with the exact blocker.\n"
        "5. publish_project_run_receipt must include branch, base_branch, changed files, tests, screenshots, dev target status, and handoff URL when available.\n\n"
        f"Project task request:\n{request_text}"
        f"{continuation_block}"
    )


async def create_project_coding_run(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunCreate,
) -> Task:
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
        machine_grant=body.machine_target_grant,
        source_work_pack_id=body.source_work_pack_id,
        schedule_task_id=body.schedule_task_id,
        schedule_run_number=body.schedule_run_number,
    )
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=body.request,
        defaults={"branch": ctx.branch, "base_branch": ctx.base_branch, "repo": ctx.repo},
        runtime_target=ctx.runtime_target.to_persisted(),
        dev_targets=[t.to_persisted() for t in ctx.dev_targets],
        machine_target_grant=body.machine_target_grant,
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
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=ctx.request,
        defaults={"branch": ctx.branch, "base_branch": ctx.base_branch, "repo": ctx.repo},
        runtime_target=ctx.runtime_target.to_persisted(),
        dev_targets=[t.to_persisted() for t in ctx.dev_targets],
        machine_target_grant=None,
        continuation=continuation_context,
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
    task.title = f"{preset.task_defaults.title} follow-up {continuation_index}"
    parent_ecfg = parent.execution_config if isinstance(parent.execution_config, dict) else {}
    if isinstance(parent_ecfg.get("session_target"), dict):
        task.execution_config["session_target"] = dict(parent_ecfg["session_target"])
    if isinstance(parent_ecfg.get("project_instance"), dict):
        task.execution_config["project_instance"] = dict(parent_ecfg["project_instance"])
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task
