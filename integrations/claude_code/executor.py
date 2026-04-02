"""Deferred task executor for claude_code tasks — called by the task worker."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def run_claude_code_task(task) -> None:
    """Execute a claude_code task: run CLI in Docker container, store result, dispatch."""
    from app.agent import dispatchers
    from app.agent.tasks import resolve_task_timeout
    from app.db.engine import async_session
    from app.db.models import Task

    logger.info("Running claude_code task %s", task.id)
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    ecfg = task.execution_config or {}
    cfg = task.callback_config or {}
    working_directory = ecfg.get("working_directory")
    output_dispatch_type = ecfg.get("output_dispatch_type", task.dispatch_type or "none")
    output_dispatch_config = ecfg.get("output_dispatch_config") or dict(task.dispatch_config or {})
    system_prompt = ecfg.get("system_prompt")
    max_turns = ecfg.get("max_turns")
    resume_session_id = ecfg.get("resume_session_id")
    allowed_tools = ecfg.get("allowed_tools")

    _timeout = resolve_task_timeout(task)

    try:
        from integrations.claude_code.config import settings as cc_settings
        from integrations.claude_code.runner import run_in_container

        # Use the larger of task-level timeout and Claude Code's configured timeout
        _timeout = max(_timeout, cc_settings.TIMEOUT)

        # Resolve prompt (supports template/workspace-file-linked tasks)
        from app.services.prompt_resolution import resolve_prompt
        async with async_session() as resolve_db:
            prompt = await resolve_prompt(
                workspace_id=str(task.workspace_id) if task.workspace_id else None,
                workspace_file_path=task.workspace_file_path,
                template_id=str(task.prompt_template_id) if task.prompt_template_id else None,
                inline_prompt=task.prompt,
                db=resolve_db,
            )

        result = await run_in_container(
            bot_id=task.bot_id,
            prompt=prompt,
            working_directory=working_directory,
            max_turns=max_turns,
            system_prompt=system_prompt,
            resume_session_id=resume_session_id,
            allowed_tools=allowed_tools,
            timeout=_timeout,
        )

        # Build result text with metadata header
        parts = []
        if result.result:
            parts.append(result.result)
        if result.is_error:
            parts.append("[claude-code reported error]")
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        meta_parts = []
        if result.num_turns is not None:
            meta_parts.append(f"turns={result.num_turns}")
        if result.cost_usd is not None:
            meta_parts.append(f"cost=${result.cost_usd:.2f}")
        if result.duration_ms is not None:
            meta_parts.append(f"{result.duration_ms}ms")
        meta_parts.append(f"exit={result.exit_code}")
        if meta_parts:
            parts.append(f"[{', '.join(meta_parts)}]")
        result_text = "\n".join(parts)

        # Store result
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                merged_ecfg = dict(t.execution_config or {})
                if result.session_id:
                    merged_ecfg["claude_session_id"] = result.session_id
                if result.cost_usd is not None:
                    merged_ecfg["claude_cost_usd"] = result.cost_usd
                if result.num_turns is not None:
                    merged_ecfg["claude_num_turns"] = result.num_turns
                t.execution_config = merged_ecfg
                await db.commit()

        # Dispatch result to output channel
        output_task = Task(
            id=task.id,
            bot_id=task.bot_id,
            dispatch_type=output_dispatch_type,
            dispatch_config=output_dispatch_config,
        )
        dispatcher = dispatchers.get(output_dispatch_type)
        await dispatcher.deliver(output_task, result_text)

        # Notify parent bot
        if cfg.get("notify_parent") and result_text:
            await _notify_parent(task, cfg, result, result_text, output_dispatch_type, output_dispatch_config)

    except Exception as exc:
        logger.exception("claude_code task %s failed", task.id)

        # Resume retry logic — try to extract session_id from ecfg
        _resume_session_id = ecfg.get("claude_session_id") or ecfg.get("resume_session_id")
        _resume_retries = ecfg.get("resume_retries", 0)
        from integrations.claude_code.config import settings as cc_settings
        _can_resume = (
            _resume_session_id
            and _resume_retries < cc_settings.MAX_RESUME_RETRIES
        )

        if _can_resume:
            logger.info(
                "claude_code task %s: scheduling resume (session=%s, attempt %d/%d)",
                task.id, _resume_session_id, _resume_retries + 1, cc_settings.MAX_RESUME_RETRIES,
            )
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    merged_ecfg = dict(t.execution_config or {})
                    merged_ecfg["resume_session_id"] = str(_resume_session_id)
                    merged_ecfg["resume_retries"] = _resume_retries + 1
                    merged_ecfg.setdefault("original_prompt", t.prompt)
                    t.execution_config = merged_ecfg
                    t.status = "pending"
                    t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                    t.error = f"resuming (attempt {_resume_retries + 1}): {str(exc)[:200]}"
                    t.prompt = "continue from where you left off"
                    await db.commit()
        else:
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    t.status = "failed"
                    t.error = str(exc)[:4000]
                    t.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            # Dispatch error to output channel
            try:
                _err_text = f"[Error: Claude Code task failed: {str(exc)[:500]}]"
                output_task = Task(
                    id=task.id, bot_id=task.bot_id,
                    dispatch_type=output_dispatch_type, dispatch_config=output_dispatch_config,
                )
                dispatcher = dispatchers.get(output_dispatch_type)
                await dispatcher.deliver(output_task, _err_text)
            except Exception:
                logger.warning("Failed to dispatch error for claude_code task %s", task.id)


async def _notify_parent(task, cfg, result, result_text, output_dispatch_type, output_dispatch_config):
    """Create a callback task so the parent bot can react to the result."""
    from app.db.engine import async_session
    from app.db.models import Task
    from integrations.claude_code.runner import ClaudeCodeResult

    _parent_bot_id = cfg.get("parent_bot_id")
    _parent_session_str = cfg.get("parent_session_id")
    _parent_client_id = cfg.get("parent_client_id")
    if not (_parent_bot_id and _parent_session_str):
        return

    try:
        _parent_session_id = uuid.UUID(_parent_session_str)
        _cb_header = "[Claude Code completed"
        _meta = []
        if result.num_turns is not None:
            _meta.append(f"turns={result.num_turns}")
        if result.cost_usd is not None:
            _meta.append(f"cost=${result.cost_usd:.2f}")
        if result.is_error:
            _meta.append("error=true")
        if _meta:
            _cb_header += f" ({', '.join(_meta)})"
        _cb_header += "]"

        _cb_exec_cfg: dict = {}
        if cfg.get("parent_model_override"):
            _cb_exec_cfg["model_override"] = cfg["parent_model_override"]
        if cfg.get("parent_provider_id_override"):
            _cb_exec_cfg["model_provider_id_override"] = cfg["parent_provider_id_override"]

        _cb_task = Task(
            bot_id=_parent_bot_id,
            client_id=_parent_client_id,
            session_id=_parent_session_id,
            channel_id=task.channel_id,
            prompt=f"{_cb_header}\n\n{result_text}",
            status="pending",
            task_type="callback",
            dispatch_type=output_dispatch_type,
            dispatch_config=dict(output_dispatch_config),
            execution_config=_cb_exec_cfg or None,
            parent_task_id=task.id,
            created_at=datetime.now(timezone.utc),
        )
        async with async_session() as db:
            db.add(_cb_task)
            await db.commit()
            await db.refresh(_cb_task)
        logger.info(
            "claude_code task %s: created parent callback task %s (bot=%s)",
            task.id, _cb_task.id, _parent_bot_id,
        )
    except Exception:
        logger.exception("Failed to create parent callback task for claude_code task %s", task.id)
