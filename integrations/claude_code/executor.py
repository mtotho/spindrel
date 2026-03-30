"""Deferred task executor for claude_code tasks — called by the task worker."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def run_claude_code_task(task) -> None:
    """Execute a claude_code task: run SDK subprocess, store result, dispatch."""
    from app.agent import dispatchers
    from app.agent.bots import get_bot
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
    claude_session_id: str | None = None

    try:
        from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage
        from integrations.claude_code.config import settings as cc_settings

        # Use the larger of task-level timeout and Claude Code's configured timeout
        _timeout = max(_timeout, cc_settings.TIMEOUT)

        bot = get_bot(task.bot_id)

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

        # Resolve cwd
        from app.services.workspace import workspace_service
        ws_root = workspace_service.get_workspace_root(task.bot_id, bot)
        if not ws_root:
            raise ValueError(f"No workspace root configured for bot {task.bot_id}")
        cwd = ws_root
        if working_directory:
            cwd = os.path.normpath(os.path.join(ws_root, working_directory))
            ws_prefix = ws_root.rstrip(os.sep) + os.sep
            if cwd != ws_root and not cwd.startswith(ws_prefix):
                raise ValueError(f"working_directory escapes workspace: {working_directory}")

        effective_max_turns = max_turns if max_turns is not None else cc_settings.MAX_TURNS
        effective_allowed = allowed_tools if allowed_tools is not None else cc_settings.ALLOWED_TOOLS

        options = ClaudeAgentOptions(
            cwd=cwd,
            permission_mode=cc_settings.PERMISSION_MODE,
            max_turns=effective_max_turns,
            allowed_tools=effective_allowed,
        )
        if system_prompt:
            options.system_prompt = system_prompt
        if resume_session_id:
            options.resume = resume_session_id
        if cc_settings.MODEL:
            options.model = cc_settings.MODEL

        result_msg = None
        async with asyncio.timeout(_timeout):
            async for message in sdk_query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result_msg = message
                if hasattr(message, "session_id") and getattr(message, "session_id", None):
                    claude_session_id = message.session_id

        if result_msg is None:
            raise RuntimeError("No result message received from Claude Code")

        claude_session_id = result_msg.session_id

        # Build result text with metadata header
        parts = []
        if result_msg.result:
            parts.append(result_msg.result)
        if result_msg.is_error:
            parts.append("[claude-code reported error]")
        meta_parts = []
        if result_msg.num_turns is not None:
            meta_parts.append(f"turns={result_msg.num_turns}")
        if result_msg.total_cost_usd is not None:
            meta_parts.append(f"cost=${result_msg.total_cost_usd:.2f}")
        if result_msg.duration_ms is not None:
            meta_parts.append(f"{result_msg.duration_ms}ms")
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
                merged_ecfg["claude_session_id"] = claude_session_id
                if result_msg.total_cost_usd is not None:
                    merged_ecfg["claude_cost_usd"] = result_msg.total_cost_usd
                if result_msg.num_turns is not None:
                    merged_ecfg["claude_num_turns"] = result_msg.num_turns
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
            await _notify_parent(task, cfg, result_msg, result_text, output_dispatch_type, output_dispatch_config)

    except TimeoutError:
        logger.error("claude_code task %s timed out after %ds", task.id, _timeout)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = f"Timed out after {_timeout}s"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        try:
            _err_text = f"[Error: Claude Code task timed out after {_timeout}s]"
            output_task = Task(
                id=task.id, bot_id=task.bot_id,
                dispatch_type=output_dispatch_type, dispatch_config=output_dispatch_config,
            )
            dispatcher = dispatchers.get(output_dispatch_type)
            await dispatcher.deliver(output_task, _err_text)
        except Exception:
            logger.warning("Failed to dispatch timeout error for claude_code task %s", task.id)

    except Exception as exc:
        logger.exception("claude_code task %s failed", task.id)

        # Resume retry logic
        _resume_session_id = claude_session_id or ecfg.get("claude_session_id")
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


async def _notify_parent(task, cfg, result_msg, result_text, output_dispatch_type, output_dispatch_config):
    """Create a callback task so the parent bot can react to the result."""
    from app.db.engine import async_session
    from app.db.models import Task

    _parent_bot_id = cfg.get("parent_bot_id")
    _parent_session_str = cfg.get("parent_session_id")
    _parent_client_id = cfg.get("parent_client_id")
    if not (_parent_bot_id and _parent_session_str):
        return

    try:
        _parent_session_id = uuid.UUID(_parent_session_str)
        _cb_header = "[Claude Code completed"
        _meta = []
        if result_msg.num_turns is not None:
            _meta.append(f"turns={result_msg.num_turns}")
        if result_msg.total_cost_usd is not None:
            _meta.append(f"cost=${result_msg.total_cost_usd:.2f}")
        if result_msg.is_error:
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
