"""Shared task operations used by both bot tools and admin API."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task


async def spawn_child_run(
    parent_task_id: uuid.UUID,
    db: AsyncSession,
    params: dict | None = None,
    channel_id: uuid.UUID | None = None,
    bot_id: str | None = None,
) -> Task:
    """Spawn a concrete child task from a task definition.

    Resolves the latest prompt, clones all execution fields from the parent,
    and increments the parent's run_count.

    Args:
        parent_task_id: The definition's task id.
        db: Active async session.
        params: Optional runtime params merged into the child's
            ``execution_config['params']`` so step templates can reach them
            as ``{{params.*}}``.
        channel_id: Optional channel override. When provided, the child
            dispatches its anchor messages / step output to this channel
            instead of inheriting from the parent. Enables one pipeline
            definition to run against multiple channels.
        bot_id: Optional bot override. When provided, the child's agent
            steps (and any bot-scoped tool calls) run under this bot
            instead of inheriting from the parent.

    Raises:
        ValueError: If parent not found or not a valid definition.
    """
    parent = await db.get(Task, parent_task_id)
    if not parent:
        raise ValueError(f"Task {parent_task_id} not found.")

    # Validate this is a definition (schedule template, pipeline, or has trigger_config)
    is_definition = (
        parent.recurrence
        or parent.trigger_config
        or parent.task_type in ("scheduled", "pipeline")
    )
    if not is_definition:
        raise ValueError(
            f"Task {parent_task_id} is not a task definition "
            f"(type={parent.task_type}, no recurrence or trigger_config)."
        )

    # Resolve latest prompt content
    from app.services.prompt_resolution import resolve_prompt
    prompt = await resolve_prompt(
        workspace_id=str(parent.workspace_id) if parent.workspace_id else None,
        workspace_file_path=parent.workspace_file_path,
        template_id=str(parent.prompt_template_id) if parent.prompt_template_id else None,
        inline_prompt=parent.prompt,
        db=db,
    )

    exec_cfg = dict(parent.execution_config) if parent.execution_config else None
    if params:
        exec_cfg = exec_cfg or {}
        merged_params = dict(exec_cfg.get("params") or {})
        merged_params.update(params)
        exec_cfg["params"] = merged_params

    # Launch-time-required fields — a pipeline definition can declare that
    # the caller MUST supply bot_id and/or channel_id via its
    # ``execution_config.requires_*`` flags. This keeps system pipelines
    # channel-agnostic (one definition, many launch contexts) while still
    # validating loudly instead of silently spawning an undispatched run.
    requires_channel = bool((parent.execution_config or {}).get("requires_channel"))
    requires_bot = bool((parent.execution_config or {}).get("requires_bot"))
    effective_channel_id = channel_id if channel_id is not None else parent.channel_id
    effective_bot_id = bot_id or parent.bot_id
    missing: list[str] = []
    if requires_channel and effective_channel_id is None:
        missing.append("channel_id")
    if requires_bot and not effective_bot_id:
        missing.append("bot_id")
    if missing:
        raise ValueError(
            f"Task {parent_task_id} requires {', '.join(missing)} at launch time "
            f"(declared via execution_config.requires_* on the definition)."
        )

    concrete = Task(
        bot_id=effective_bot_id,
        client_id=parent.client_id,
        session_id=parent.session_id,
        channel_id=effective_channel_id,
        prompt=prompt,
        title=parent.title,
        prompt_template_id=parent.prompt_template_id,
        workspace_file_path=parent.workspace_file_path,
        workspace_id=parent.workspace_id,
        scheduled_at=datetime.now(timezone.utc),
        status="pending",
        task_type=parent.task_type,
        dispatch_type=parent.dispatch_type,
        dispatch_config=dict(parent.dispatch_config) if parent.dispatch_config else None,
        callback_config=dict(parent.callback_config) if parent.callback_config else None,
        execution_config=exec_cfg,
        recurrence=None,
        parent_task_id=parent.id,
        max_run_seconds=parent.max_run_seconds,
        workflow_id=parent.workflow_id,
        workflow_session_mode=parent.workflow_session_mode,
        steps=list(parent.steps) if parent.steps else None,
        # Inherit run_isolation from the definition so pipeline runs spawned
        # from a sub_session definition render as a sub-session anchor in
        # the parent channel (and route their step output to the run's
        # dedicated Session instead of the parent channel's chat).
        run_isolation=parent.run_isolation or "inline",
        created_at=datetime.now(timezone.utc),
    )
    db.add(concrete)
    parent.run_count = (parent.run_count or 0) + 1
    await db.flush()
    return concrete
