"""Agent tools for bot-to-bot delegation and external harness execution."""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

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
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "delegate_to_agent",
        "description": (
            "Delegate work to another bot or carapace. Creates a background task that the child "
            "agent executes asynchronously. The child's result is automatically posted to the "
            "originating channel when complete. Do NOT use create_task for cross-bot work; use "
            "this tool instead.\n\n"
            "bot_id accepts either a bot ID or a carapace ID. When a carapace ID is given, "
            "the parent bot runs with that carapace's expertise applied."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bot_id": {
                    "type": "string",
                    "description": "The bot_id or carapace_id of the delegate agent to run.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The full prompt/instructions for the delegate agent.",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When to run. ISO 8601 datetime or relative offset: "
                        "+30m, +2h, +1d. Omit to run as soon as the task worker picks it up."
                    ),
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Post the child's result as a Slack thread reply (true) or new channel-level message "
                        "(false, default). No effect outside Slack."
                    ),
                },
                "notify_parent": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "When true (default), the parent agent automatically runs again "
                        "once the sub-agent completes, receiving the sub-agent's result as input so it can "
                        "synthesize or react. Set false for fire-and-forget tasks where the parent doesn't "
                        "need to react."
                    ),
                },
                "model_tier": {
                    "type": "string",
                    "enum": ["free", "fast", "standard", "capable", "frontier"],
                    "description": (
                        "Model tier for the delegate. Overrides the default tier from the "
                        "delegate entry. Tiers map to concrete models via admin settings. "
                        "free = zero-cost/rate-limited, fast = trivial extraction, "
                        "standard = routine work, capable = multi-step reasoning, "
                        "frontier = complex/high-stakes."
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
    scheduled_at: str | None = None,
    reply_in_thread: bool = False,
    notify_parent: bool = True,
    model_tier: str | None = None,
) -> str:
    # LLMs sometimes pass "true"/"false" strings instead of booleans
    if isinstance(reply_in_thread, str):
        reply_in_thread = reply_in_thread.strip().lower() not in ("false", "0", "no", "")
    # Normalize model_tier (LLMs may add whitespace)
    if model_tier:
        model_tier = model_tier.strip().lower() or None

    from app.agent.bots import get_bot, resolve_bot_id, list_bots
    from app.agent.carapaces import get_carapace, resolve_carapaces
    from app.services.delegation import delegation_service, DelegationError

    session_id = current_session_id.get()
    client_id = current_client_id.get()
    channel_id = current_channel_id.get()
    parent_bot_id = current_bot_id.get() or "default"
    dispatch_type = current_dispatch_type.get()
    dispatch_config = dict(current_dispatch_config.get() or {})

    try:
        parent_bot = get_bot(parent_bot_id)
    except Exception as exc:
        return json.dumps({"error": f"Could not load parent bot: {exc}"})

    # Try bot resolution first, then fall back to carapace
    resolved = resolve_bot_id(bot_id)
    carapace_delegate = False
    target_carapace_id: str | None = None

    if resolved is not None:
        # Bot found — standard bot delegation
        if resolved.id != bot_id:
            logger.info("delegate_to_agent: resolved %r → %r", bot_id, resolved.id)
            bot_id = resolved.id

        # Self-delegation guard: child gets a fresh session with none of the
        # parent's context, so delegating to yourself is always wrong.
        if resolved.id == parent_bot_id:
            return json.dumps({
                "error": "Cannot delegate to yourself — the child gets a fresh session "
                "with none of your current context. Execute directly or use exec_command."
            })

        # Permission check: delegate_bots must be configured for bot delegation
        if not parent_bot.delegate_bots:
            return json.dumps({"error": "Delegation is disabled. Configure delegate_bots for this bot."})
    else:
        # No bot found — try carapace resolution
        carapace = get_carapace(bot_id)
        if carapace is None:
            available_bots = ", ".join(b.id for b in list_bots())
            return json.dumps({"error": f"No bot or carapace matching {bot_id!r}. Available bots: {available_bots}"})

        # Permission check: carapace must appear in delegates of an active carapace the parent wears
        resolved_parent = resolve_carapaces(parent_bot.carapaces)
        authorized_carapace_delegates = {d.id for d in resolved_parent.delegates if d.type == "carapace"}
        if bot_id not in authorized_carapace_delegates:
            return json.dumps({
                "error": f"Carapace {bot_id!r} is not in the delegates list of any active carapace. "
                f"Authorized carapace delegates: {sorted(authorized_carapace_delegates) or 'none'}"
            })

        carapace_delegate = True
        target_carapace_id = bot_id
        # For carapace delegation, the task runs under the parent bot with the target carapace applied
        bot_id = parent_bot.id

    sched_dt: datetime | None = None
    if scheduled_at:
        try:
            from app.tools.local.tasks import _parse_scheduled_at
            sched_dt = _parse_scheduled_at(scheduled_at)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    # Resolve model tier: explicit param > delegate entry default > none
    effective_tier = model_tier
    if not effective_tier and parent_bot.carapaces:
        # Check if the target has a default model_tier in a carapace delegate entry
        lookup_id = target_carapace_id if carapace_delegate else bot_id
        resolved_parent = resolve_carapaces(parent_bot.carapaces)
        for d in resolved_parent.delegates:
            if d.id == lookup_id and d.model_tier:
                effective_tier = d.model_tier
                break

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
            channel_id=channel_id,
            reply_in_thread=reply_in_thread,
            notify_parent=notify_parent,
            carapace_ids=[target_carapace_id] if carapace_delegate else None,
            model_tier=effective_tier,
        )
        if carapace_delegate:
            return f"Carapace delegation task created: {task_id} (carapace: {target_carapace_id})"
        return f"Delegation task created: {task_id}"
    except DelegationError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("delegate_to_agent failed")
        return json.dumps({"error": str(exc)})


def _parse_uuid_opt(raw: str | None) -> uuid.UUID | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return uuid.UUID(str(raw).strip())
    except (ValueError, TypeError):
        return None


@register({
    "type": "function",
    "function": {
        "name": "delegate_to_harness",
        "description": (
            "Run an external CLI harness (e.g. claude-code, cursor) with a prompt. "
            "Runs inside the bot's workspace container (docker workspace) by default. "
            "Pass sandbox_instance_id to target a specific sandbox instance instead. "
            "Use mode=sync (default) to wait for the result. "
            "Use mode=deferred for background execution; result posts to the channel when done. "
            "Harness must be in harnesses.yaml and the bot must have harness_access."
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
                    "description": (
                        "Working directory: on the host, must be in HARNESS_WORKING_DIR_ALLOWLIST when set. "
                        "With sandbox_instance_id, this is a path inside the container (e.g. /workspace/project)."
                    ),
                },
                "sandbox_instance_id": {
                    "type": "string",
                    "description": (
                        "Optional. UUID of a specific sandbox instance (from ensure_sandbox) to run in. "
                        "If omitted, falls back to the bot's workspace docker config when enabled. "
                        "Use this only when you need to target a specific sandbox instance."
                    ),
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
                "reply_in_thread": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Deferred mode only. Post the result as a Slack thread reply (true) or new "
                        "channel-level message (false, default). No effect outside Slack or in sync mode."
                    ),
                },
                "notify_parent": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Deferred mode only. When true (default), the parent agent automatically runs again "
                        "once the harness completes, receiving the harness output as input so it can "
                        "review, summarize, or react. Set false for fire-and-forget jobs where the parent "
                        "doesn't need to act on the result."
                    ),
                },
            },
            "required": ["harness", "prompt"],  # sandbox_instance_id optional; falls back to workspace docker
        },
    },
})
async def delegate_to_harness(
    harness: str,
    prompt: str,
    sandbox_instance_id: str | None = None,
    working_directory: str | None = None,
    mode: str = "sync",
    reply_in_thread: bool = False,
    notify_parent: bool = True,
) -> str:
    # LLMs sometimes pass "true"/"false" strings instead of booleans
    if isinstance(reply_in_thread, str):
        reply_in_thread = reply_in_thread.strip().lower() not in ("false", "0", "no", "")
    if isinstance(notify_parent, str):
        notify_parent = notify_parent.strip().lower() not in ("false", "0", "no", "")

    from app.agent.bots import get_bot
    from app.services.harness import harness_service, HarnessError

    parent_bot_id = current_bot_id.get() or "default"
    try:
        bot = get_bot(parent_bot_id)
    except Exception as exc:
        return json.dumps({"error": f"Could not load bot: {exc}"})

    # Global flag OR bot-level harness_access config enables harness delegation
    if not bot.harness_access:
        return json.dumps({"error": "Delegation is disabled. Configure harness_access for this bot."})

    if mode == "deferred":
        from app.db.engine import async_session
        from app.db.models import Task
        dispatch_type = current_dispatch_type.get()
        dispatch_config = dict(current_dispatch_config.get() or {})
        session_id = current_session_id.get()
        client_id = current_client_id.get()
        src_corr = current_correlation_id.get()
        delivery_config = dict(dispatch_config)
        delivery_config["reply_in_thread"] = reply_in_thread
        # execution_config: what to run
        exec_cfg: dict = {
            "harness_name": harness,
            "working_directory": working_directory,
            "output_dispatch_type": dispatch_type or "none",
            "output_dispatch_config": delivery_config,
        }
        sbx = _parse_uuid_opt(sandbox_instance_id)
        if sbx is not None:
            exec_cfg["sandbox_instance_id"] = str(sbx)
        if src_corr is not None:
            exec_cfg["source_correlation_id"] = str(src_corr)
        # callback_config: what happens after
        callback_cfg: dict = {}
        if notify_parent and session_id is not None:
            callback_cfg["notify_parent"] = True
            callback_cfg["parent_bot_id"] = parent_bot_id
            callback_cfg["parent_session_id"] = str(session_id)
            if client_id:
                callback_cfg["parent_client_id"] = client_id
            # Propagate the parent's effective model so the callback task uses the same model
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
            prompt=prompt,
            status="pending",
            task_type="harness",
            dispatch_type=dispatch_type or "none",
            dispatch_config=delivery_config,
            execution_config=exec_cfg,
            callback_config=callback_cfg or None,
        )
        async with async_session() as db:
            db.add(task)
            await db.commit()
            await db.refresh(task)
        logger.info("Deferred harness task created: %s (harness=%s)", task.id, harness)
        return json.dumps({"task_id": str(task.id), "status": "deferred", "harness": harness})

    # sync mode
    try:
        sbx = _parse_uuid_opt(sandbox_instance_id)
        result = await harness_service.run(
            harness_name=harness,
            prompt=prompt,
            working_directory=working_directory,
            bot=bot,
            sandbox_instance_id=sbx,
        )

        # Attempt to parse Claude Code JSON output for structured response
        from app.agent.tasks import _parse_claude_json_output
        claude_data = _parse_claude_json_output(result.stdout)

        if claude_data is not None:
            output = {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "result": claude_data.get("result", ""),
                "session_id": claude_data.get("session_id"),
                "is_error": claude_data.get("is_error", False),
                "cost_usd": claude_data.get("cost_usd"),
                "num_turns": claude_data.get("num_turns"),
            }
        else:
            output = {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }
            if result.stdout:
                output["stdout"] = result.stdout

        if result.truncated:
            output["truncated"] = True
        if result.stderr:
            output["stderr"] = result.stderr
        return json.dumps(output)
    except HarnessError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("delegate_to_harness failed")
        return json.dumps({"error": str(exc)})
