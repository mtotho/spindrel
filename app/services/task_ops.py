"""Shared task operations used by both bot tools and admin API."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task


async def spawn_child_run(parent_task_id: uuid.UUID, db: AsyncSession) -> Task:
    """Spawn a concrete child task from a task definition.

    Resolves the latest prompt, clones all execution fields from the parent,
    and increments the parent's run_count.

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

    concrete = Task(
        bot_id=parent.bot_id,
        client_id=parent.client_id,
        session_id=parent.session_id,
        channel_id=parent.channel_id,
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
        execution_config=dict(parent.execution_config) if parent.execution_config else None,
        recurrence=None,
        parent_task_id=parent.id,
        max_run_seconds=parent.max_run_seconds,
        workflow_id=parent.workflow_id,
        workflow_session_mode=parent.workflow_session_mode,
        steps=list(parent.steps) if parent.steps else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(concrete)
    parent.run_count = (parent.run_count or 0) + 1
    await db.flush()
    return concrete
