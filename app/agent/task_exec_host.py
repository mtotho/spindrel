"""Host orchestration for deferred exec task execution."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.db.models import Task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskExecHostDeps:
    """Patchable dependencies supplied by app.agent.tasks at run time."""

    async_session: Callable[[], Any]
    settings: Any
    get_bot: Callable[[str], Any]
    build_exec_script: Callable[[str, list[str] | None, str | None, str | None], str]
    sandbox_service: Any
    workspace_service: Any
    resolve_task_timeout: Callable[[Task], int]
    fire_task_complete: Callable[[Task, str], Awaitable[None]]
    mark_task_failed_in_db: Callable[..., Awaitable[None]]
    publish_turn_ended: Callable[..., Awaitable[None]]
    publish_turn_ended_safe: Callable[..., Awaitable[None]]
    schedule_exec_completion_record: Callable[..., None]
    sleep: Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class _ExecConfig:
    command: str
    args: list[str] | None
    working_directory: str | None
    stream_to: str | None
    output_dispatch_type: str
    output_dispatch_config: dict
    source_correlation_id: uuid.UUID | None
    sandbox_instance_id: uuid.UUID | None
    callback_config: dict


@dataclass(frozen=True)
class _WorkspaceExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int


def _parse_uuid_opt(config: dict, key: str) -> uuid.UUID | None:
    raw = config.get(key)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_exec_config(task: Task) -> _ExecConfig:
    execution_config = task.execution_config or task.callback_config or {}
    callback_config = task.callback_config or {}
    return _ExecConfig(
        command=execution_config.get("command", ""),
        args=execution_config.get("args", []),
        working_directory=execution_config.get("working_directory"),
        stream_to=execution_config.get("stream_to"),
        output_dispatch_type=execution_config.get("output_dispatch_type", task.dispatch_type or "none"),
        output_dispatch_config=execution_config.get("output_dispatch_config")
        or dict(task.dispatch_config or {}),
        source_correlation_id=_parse_uuid_opt(execution_config, "source_correlation_id"),
        sandbox_instance_id=_parse_uuid_opt(execution_config, "sandbox_instance_id"),
        callback_config=callback_config,
    )


async def run_exec_task(task: Task, *, deps: TaskExecHostDeps) -> None:
    """Execute a raw exec task, persist the result, and publish completion."""
    logger.info("Running exec task %s", task.id)
    now = datetime.now(timezone.utc)
    turn_id = uuid.uuid4()

    async with deps.async_session() as db:
        fresh_task = await db.get(Task, task.id)
        if fresh_task is None:
            return
        fresh_task.status = "running"
        fresh_task.run_at = now
        await db.commit()

    config = _resolve_exec_config(task)
    exec_timeout: int | None = None

    try:
        bot = deps.get_bot(task.bot_id)
        script = deps.build_exec_script(
            config.command,
            config.args,
            config.working_directory,
            config.stream_to,
        )
        exec_timeout = deps.resolve_task_timeout(task)

        result = await asyncio.wait_for(
            _execute_script(task, bot, script, config, deps=deps),
            timeout=exec_timeout,
        )
        result_text = _format_exec_result(result)

        async with deps.async_session() as db:
            fresh_task = await db.get(Task, task.id)
            if fresh_task:
                fresh_task.status = "complete"
                fresh_task.result = result_text
                fresh_task.completed_at = datetime.now(timezone.utc)
                await db.commit()

        await deps.fire_task_complete(task, "complete")
        await _record_success(task, result, result_text, config, deps=deps)
        await _publish_success(task, result_text, config, turn_id, deps=deps)
        await _create_parent_callback_if_requested(task, result_text, config, deps=deps)

    except asyncio.TimeoutError:
        timeout = exec_timeout if exec_timeout is not None else deps.resolve_task_timeout(task)
        logger.error("Exec task %s timed out after %ds", task.id, timeout)
        timeout_msg = f"Timed out after {timeout}s"
        await deps.mark_task_failed_in_db(task.id, error=timeout_msg)
        await deps.fire_task_complete(task, "failed")
        output_task = _output_task(task, config)
        await deps.publish_turn_ended_safe(
            output_task,
            turn_id=turn_id,
            error=timeout_msg,
            log_label="timeout error for exec task",
        )

    except Exception as exc:
        logger.exception("Exec task %s failed", task.id)
        await deps.mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        await deps.fire_task_complete(task, "failed")
        try:
            deps.schedule_exec_completion_record(
                command=config.command or "unknown",
                task_id=task.id,
                session_id=task.session_id,
                client_id=task.client_id,
                bot_id=task.bot_id,
                correlation_id=config.source_correlation_id,
                exit_code=-1,
                duration_ms=0,
                truncated=False,
                result_text="",
                error=str(exc)[:4000],
            )
            await deps.sleep(0)
        except Exception:
            logger.exception("Failed to schedule exec failure record for task %s", task.id)


async def _execute_script(
    task: Task,
    bot: Any,
    script: str,
    config: _ExecConfig,
    *,
    deps: TaskExecHostDeps,
) -> Any:
    if config.sandbox_instance_id is not None:
        if not deps.settings.DOCKER_SANDBOX_ENABLED:
            raise RuntimeError("DOCKER_SANDBOX_ENABLED is false")
        allowed = bot.docker_sandbox_profiles or None
        instance = await deps.sandbox_service.get_instance_for_bot(
            config.sandbox_instance_id,
            bot.id,
            allowed_profiles=allowed,
        )
        if instance is None:
            raise RuntimeError("Sandbox instance not found or not allowed")
        return await deps.sandbox_service.exec(instance, script)

    if bot.workspace.enabled or bot.shared_workspace_id:
        workspace_result = await deps.workspace_service.exec(
            bot.id,
            script,
            bot.workspace,
            config.working_directory or "",
            bot=bot,
        )
        return _WorkspaceExecResult(
            stdout=workspace_result.stdout,
            stderr=workspace_result.stderr,
            exit_code=workspace_result.exit_code,
            truncated=workspace_result.truncated,
            duration_ms=workspace_result.duration_ms,
        )

    if bot.bot_sandbox.enabled:
        return await deps.sandbox_service.exec_bot_local(bot.id, script, bot.bot_sandbox)

    raise RuntimeError("No sandbox available for exec task")


def _format_exec_result(result: Any) -> str:
    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr}")
    if result.truncated:
        parts.append("[output truncated]")
    parts.append(f"[exit {result.exit_code}, {result.duration_ms}ms]")
    return "\n".join(parts)


async def _record_success(
    task: Task,
    result: Any,
    result_text: str,
    config: _ExecConfig,
    *,
    deps: TaskExecHostDeps,
) -> None:
    error: str | None = None
    if result.exit_code != 0:
        error = ((result.stderr or "").strip()[:500] or f"non-zero exit {result.exit_code}")
    deps.schedule_exec_completion_record(
        command=config.command,
        task_id=task.id,
        session_id=task.session_id,
        client_id=task.client_id,
        bot_id=task.bot_id,
        correlation_id=config.source_correlation_id,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        truncated=result.truncated,
        result_text=result_text,
        error=error,
    )
    await deps.sleep(0)


async def _publish_success(
    task: Task,
    result_text: str,
    config: _ExecConfig,
    turn_id: uuid.UUID,
    *,
    deps: TaskExecHostDeps,
) -> None:
    await deps.publish_turn_ended(
        _output_task(task, config),
        turn_id=turn_id,
        result=result_text,
    )


async def _create_parent_callback_if_requested(
    task: Task,
    result_text: str,
    config: _ExecConfig,
    *,
    deps: TaskExecHostDeps,
) -> None:
    if not (config.callback_config.get("notify_parent") and result_text):
        return

    parent_bot_id = config.callback_config.get("parent_bot_id")
    parent_session_str = config.callback_config.get("parent_session_id")
    parent_client_id = config.callback_config.get("parent_client_id")
    if not (parent_bot_id and parent_session_str):
        return

    try:
        parent_session_id = uuid.UUID(parent_session_str)
        callback_task = Task(
            bot_id=parent_bot_id,
            client_id=parent_client_id,
            session_id=parent_session_id,
            channel_id=task.channel_id,
            prompt=f"[Exec task completed: {config.command}]\n\n{result_text}",
            status="pending",
            task_type="callback",
            dispatch_type=config.output_dispatch_type,
            dispatch_config=dict(config.output_dispatch_config),
            parent_task_id=task.id,
            created_at=datetime.now(timezone.utc),
        )
        async with deps.async_session() as db:
            db.add(callback_task)
            await db.commit()
            await db.refresh(callback_task)
        logger.info(
            "Exec task %s: created parent callback task %s (bot=%s, session=%s)",
            task.id,
            callback_task.id,
            parent_bot_id,
            parent_session_id,
        )
    except Exception:
        logger.exception("Failed to create parent callback task for exec task %s", task.id)


def _output_task(task: Task, config: _ExecConfig) -> Task:
    return Task(
        id=task.id,
        bot_id=task.bot_id,
        channel_id=task.channel_id,
        dispatch_type=config.output_dispatch_type,
        dispatch_config=config.output_dispatch_config,
    )
