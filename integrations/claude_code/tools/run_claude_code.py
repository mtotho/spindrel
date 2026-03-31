"""run_claude_code — Claude Code CLI tool executed in Docker workspace (sync + deferred paths)."""
from __future__ import annotations

import json
import logging
import os

from integrations import _register as reg

logger = logging.getLogger(__name__)


def _parse_bool(val, default: bool = False) -> bool:
    """Handle LLMs passing 'true'/'false' strings instead of booleans."""
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip().lower() not in ("false", "0", "no", "")
    return bool(val)


@reg.register({
    "type": "function",
    "function": {
        "name": "run_claude_code",
        "description": (
            "Run Claude Code (AI coding agent) inside the bot's Docker workspace container. "
            "Claude Code can read, write, and edit files, run shell commands, search code, "
            "and perform complex multi-step coding tasks autonomously. "
            "Use mode=sync (default) to wait for the result. "
            "Use mode=deferred for long-running tasks; result posts to the channel when done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Instructions for Claude Code — what to build, fix, refactor, or investigate.",
                },
                "working_directory": {
                    "type": "string",
                    "description": (
                        "Relative subdirectory within the bot's workspace to use as cwd. "
                        "Must be a relative path (no .. traversal, no absolute paths). "
                        "Omit to use the workspace root."
                    ),
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Custom system prompt override for this invocation.",
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Override the default max agent turns for this run.",
                },
                "resume_session_id": {
                    "type": "string",
                    "description": "Session ID from a previous run to resume (continues the conversation).",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Override the default pre-approved tool list (e.g. ['Read', 'Write', 'Bash']).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["sync", "deferred"],
                    "default": "sync",
                    "description": (
                        "sync: wait for completion and return the result. "
                        "deferred: create a background task, return task_id immediately; "
                        "result is posted to the channel when complete."
                    ),
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Deferred mode only. Post result as a thread reply (true) or "
                        "channel-level message (false). No effect outside Slack or in sync mode."
                    ),
                },
                "notify_parent": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Deferred mode only. When true (default), the parent agent runs again "
                        "with the result so it can react. Set false for fire-and-forget."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
})
async def run_claude_code(
    prompt: str,
    working_directory: str | None = None,
    system_prompt: str | None = None,
    max_turns: int | None = None,
    resume_session_id: str | None = None,
    allowed_tools: list[str] | None = None,
    mode: str = "sync",
    reply_in_thread: bool = False,
    notify_parent: bool = True,
) -> str:
    reply_in_thread = _parse_bool(reply_in_thread, default=False)
    notify_parent = _parse_bool(notify_parent, default=True)

    # Validate working_directory (no traversal, no absolute paths)
    if working_directory:
        working_directory = working_directory.strip()
        if os.path.isabs(working_directory) or ".." in working_directory.split(os.sep):
            return json.dumps({"error": "working_directory must be a relative path with no '..' traversal"})

    # -----------------------------------------------------------------------
    # Deferred mode: create a Task and return immediately
    # -----------------------------------------------------------------------
    if mode == "deferred":
        return await _create_deferred_task(
            prompt=prompt,
            working_directory=working_directory,
            system_prompt=system_prompt,
            max_turns=max_turns,
            resume_session_id=resume_session_id,
            allowed_tools=allowed_tools,
            reply_in_thread=reply_in_thread,
            notify_parent=notify_parent,
        )

    # -----------------------------------------------------------------------
    # Sync mode: run Claude Code CLI in Docker container
    # -----------------------------------------------------------------------
    from app.agent.context import current_bot_id
    from integrations.claude_code.runner import run_in_container

    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context — cannot resolve workspace."})

    try:
        result = await run_in_container(
            bot_id=bot_id,
            prompt=prompt,
            working_directory=working_directory,
            max_turns=max_turns,
            system_prompt=system_prompt,
            resume_session_id=resume_session_id,
            allowed_tools=allowed_tools,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        err_type = type(exc).__name__
        return json.dumps({"error": f"{err_type}: {exc}"})

    return json.dumps({
        "result": result.result,
        "session_id": result.session_id,
        "is_error": result.is_error,
        "cost_usd": result.cost_usd,
        "num_turns": result.num_turns,
        "duration_ms": result.duration_ms,
        "duration_api_ms": result.duration_api_ms,
    })


async def _create_deferred_task(
    *,
    prompt: str,
    working_directory: str | None,
    system_prompt: str | None,
    max_turns: int | None,
    resume_session_id: str | None,
    allowed_tools: list[str] | None,
    reply_in_thread: bool,
    notify_parent: bool,
) -> str:
    """Create a deferred task for the task worker to execute."""
    from app.agent.context import (
        current_bot_id,
        current_channel_id,
        current_client_id,
        current_correlation_id,
        current_dispatch_config,
        current_dispatch_type,
        current_model_override,
        current_provider_id_override,
        current_session_id,
    )
    from app.db.engine import async_session
    from app.db.models import Task

    parent_bot_id = current_bot_id.get() or "default"
    session_id = current_session_id.get()
    client_id = current_client_id.get()
    channel_id = current_channel_id.get()
    dispatch_type = current_dispatch_type.get()
    dispatch_config = dict(current_dispatch_config.get() or {})

    delivery_config = dict(dispatch_config)
    delivery_config["reply_in_thread"] = reply_in_thread

    # execution_config: what to run
    exec_cfg: dict = {
        "working_directory": working_directory,
        "output_dispatch_type": dispatch_type or "none",
        "output_dispatch_config": delivery_config,
    }
    if system_prompt:
        exec_cfg["system_prompt"] = system_prompt
    if max_turns is not None:
        exec_cfg["max_turns"] = max_turns
    if resume_session_id:
        exec_cfg["resume_session_id"] = resume_session_id
    if allowed_tools:
        exec_cfg["allowed_tools"] = allowed_tools

    src_corr = current_correlation_id.get()
    if src_corr is not None:
        exec_cfg["source_correlation_id"] = str(src_corr)

    # callback_config: what happens after completion
    callback_cfg: dict = {}
    if notify_parent and session_id is not None:
        callback_cfg["notify_parent"] = True
        callback_cfg["parent_bot_id"] = parent_bot_id
        callback_cfg["parent_session_id"] = str(session_id)
        if client_id:
            callback_cfg["parent_client_id"] = client_id
        _mo = current_model_override.get()
        _po = current_provider_id_override.get()
        if _mo:
            callback_cfg["parent_model_override"] = _mo
        if _po:
            callback_cfg["parent_provider_id_override"] = _po

    task = Task(
        bot_id=parent_bot_id,
        client_id=client_id,
        session_id=session_id,
        channel_id=channel_id,
        prompt=prompt,
        status="pending",
        task_type="claude_code",
        dispatch_type=dispatch_type or "none",
        dispatch_config=delivery_config,
        execution_config=exec_cfg,
        callback_config=callback_cfg or None,
    )
    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)

    logger.info("Deferred claude_code task created: %s", task.id)
    return json.dumps({"task_id": str(task.id), "status": "deferred"})
