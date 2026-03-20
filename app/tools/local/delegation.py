"""Agent tools for bot-to-bot delegation and external harness execution."""
import json
import logging
from datetime import datetime, timedelta, timezone

from app.agent.context import (
    current_bot_id,
    current_client_id,
    current_dispatch_config,
    current_dispatch_type,
    current_ephemeral_delegates,
    current_root_session_id,
    current_session_depth,
    current_session_id,
)
from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "delegate_to_agent",
        "description": (
            "Preferred way to run a sub-agent. Use mode=immediate (default) to run the child bot "
            "now and get its response back synchronously — use this unless you have a reason to defer. "
            "Use mode=deferred to schedule it as a background task. "
            "The child's result is automatically posted to the originating channel (e.g. Slack thread). "
            "Do NOT use create_task for cross-bot work; use this tool instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bot_id": {
                    "type": "string",
                    "description": "The bot_id of the delegate agent to run.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The full prompt/instructions for the delegate agent.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["immediate", "deferred"],
                    "default": "immediate",
                    "description": (
                        "immediate (default): run the child agent now and return its response synchronously. "
                        "deferred: create a scheduled task (use only when you explicitly want async/later execution)."
                    ),
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "Deferred mode only. When to run. ISO 8601 datetime or relative offset: "
                        "+30m, +2h, +1d. Omit to run immediately after task is picked up."
                    ),
                },
            },
            "required": ["bot_id", "prompt"],
        },
    },
})
async def delegate_to_agent(
    bot_id: str,
    prompt: str,
    mode: str = "immediate",
    scheduled_at: str | None = None,
) -> str:
    from app.agent.bots import get_bot, resolve_bot_id, list_bots
    from app.services.delegation import delegation_service, DelegationError

    session_id = current_session_id.get()
    client_id = current_client_id.get()
    parent_bot_id = current_bot_id.get() or "default"
    dispatch_type = current_dispatch_type.get()
    dispatch_config = dict(current_dispatch_config.get() or {})
    depth = current_session_depth.get()
    root_sid = current_root_session_id.get()

    # Root session is the current session if not already in a delegation chain
    if root_sid is None:
        root_sid = session_id

    try:
        parent_bot = get_bot(parent_bot_id)
    except Exception as exc:
        return json.dumps({"error": f"Could not load parent bot: {exc}"})

    # Global flag OR bot-level config (non-empty delegate_bots) enables delegation
    if not settings.DELEGATION_ENABLED and not parent_bot.delegate_bots:
        return json.dumps({"error": "Delegation is disabled. Set DELEGATION_ENABLED=true or configure delegate_bots for this bot."})

    # Fuzzy-resolve bot_id so partial names / aliases work
    resolved = resolve_bot_id(bot_id)
    if resolved is None:
        available = ", ".join(b.id for b in list_bots())
        return json.dumps({"error": f"No bot matching {bot_id!r}. Available: {available}"})
    if resolved.id != bot_id:
        logger.info("delegate_to_agent: resolved %r → %r", bot_id, resolved.id)
        bot_id = resolved.id

    # Check if bot_id was @-tagged in the user message (ephemeral override, bypasses allowlist)
    ephemeral = bot_id in (current_ephemeral_delegates.get() or [])

    if mode == "deferred":
        sched_dt: datetime | None = None
        if scheduled_at:
            try:
                from app.tools.local.tasks import _parse_scheduled_at
                sched_dt = _parse_scheduled_at(scheduled_at)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

        try:
            task_id = await delegation_service.run_deferred(
                parent_bot=parent_bot,
                delegate_bot_id=bot_id,
                prompt=prompt,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
                scheduled_at=sched_dt,
                client_id=client_id,
                parent_session_id=session_id,
            )
            return f"Deferred delegation task created: {task_id}"
        except DelegationError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            logger.exception("delegate_to_agent deferred failed")
            return json.dumps({"error": str(exc)})

    # Immediate mode
    try:
        response = await delegation_service.run_immediate(
            parent_session_id=session_id,
            parent_bot=parent_bot,
            delegate_bot_id=bot_id,
            prompt=prompt,
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            depth=depth,
            root_session_id=root_sid,
            client_id=client_id,
            ephemeral_delegate=ephemeral,
        )
        return response or "(child agent returned no response)"
    except DelegationError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("delegate_to_agent immediate failed")
        return json.dumps({"error": str(exc)})


@register({
    "type": "function",
    "function": {
        "name": "delegate_to_harness",
        "description": (
            "Run an external CLI harness (e.g. claude-code, cursor) as a subprocess with a prompt. "
            "Use mode=sync (default) to wait for the result. "
            "Use mode=deferred to run in the background — the result is posted back to the channel when done; "
            "the tool returns a task_id immediately. "
            "Harness must be configured in harnesses.yaml and the bot must have harness_access for it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "harness": {
                    "type": "string",
                    "description": "Name of the harness as defined in harnesses.yaml (e.g. claude-code, cursor).",
                },
                "prompt": {
                    "type": "string",
                    "description": "The prompt/instruction to pass to the harness.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the harness process. Must be in server allowlist if set.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["sync", "deferred"],
                    "default": "sync",
                    "description": (
                        "sync (default): wait for the harness to finish and return its output. "
                        "deferred: start the harness in the background, return a task_id immediately; "
                        "result is posted back to the originating channel when complete. "
                        "Use deferred for long-running harnesses (e.g. claude-code on large tasks)."
                    ),
                },
            },
            "required": ["harness", "prompt"],
        },
    },
})
async def delegate_to_harness(
    harness: str,
    prompt: str,
    working_directory: str | None = None,
    mode: str = "sync",
) -> str:
    from app.agent.bots import get_bot
    from app.services.harness import harness_service, HarnessError

    parent_bot_id = current_bot_id.get() or "default"
    try:
        bot = get_bot(parent_bot_id)
    except Exception as exc:
        return json.dumps({"error": f"Could not load bot: {exc}"})

    # Global flag OR bot-level harness_access config enables harness delegation
    if not settings.DELEGATION_ENABLED and not bot.harness_access:
        return json.dumps({"error": "Delegation is disabled. Set DELEGATION_ENABLED=true or configure harness_access for this bot."})

    if mode == "deferred":
        from app.db.engine import async_session
        from app.db.models import Task
        dispatch_type = current_dispatch_type.get()
        dispatch_config = dict(current_dispatch_config.get() or {})
        session_id = current_session_id.get()
        client_id = current_client_id.get()
        task = Task(
            bot_id=parent_bot_id,
            client_id=client_id,
            session_id=session_id,
            prompt=prompt,
            status="pending",
            dispatch_type="harness",
            dispatch_config={
                "harness_name": harness,
                "working_directory": working_directory,
                "output_dispatch_type": dispatch_type or "none",
                "output_dispatch_config": dispatch_config,
            },
        )
        async with async_session() as db:
            db.add(task)
            await db.commit()
            await db.refresh(task)
        logger.info("Deferred harness task created: %s (harness=%s)", task.id, harness)
        return json.dumps({"task_id": str(task.id), "status": "deferred", "harness": harness})

    # sync mode
    try:
        result = await harness_service.run(
            harness_name=harness,
            prompt=prompt,
            working_directory=working_directory,
            bot=bot,
        )
        output = {
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
        }
        if result.truncated:
            output["truncated"] = True
        if result.stdout:
            output["stdout"] = result.stdout
        if result.stderr:
            output["stderr"] = result.stderr
        return json.dumps(output)
    except HarnessError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("delegate_to_harness failed")
        return json.dumps({"error": str(exc)})
