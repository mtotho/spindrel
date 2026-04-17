"""Agent tools for bot-to-bot delegation."""
import json
import logging
from datetime import datetime

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_client_id,
    current_dispatch_config,
    current_dispatch_type,
    current_session_id,
    task_creation_count,
)
from app.tools.registry import register

_MAX_TASK_CREATIONS_PER_REQUEST = 20

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
}, safety_tier="control_plane")
async def delegate_to_agent(
    bot_id: str,
    prompt: str,
    scheduled_at: str | None = None,
    reply_in_thread: bool = False,
    notify_parent: bool = True,
    model_tier: str | None = None,
) -> str:
    # Rate limit: cap task creation per agent loop iteration
    count = task_creation_count.get(0)
    if count >= _MAX_TASK_CREATIONS_PER_REQUEST:
        return json.dumps({"error": f"Task creation limit reached for this request (max {_MAX_TASK_CREATIONS_PER_REQUEST})."}, ensure_ascii=False)
    task_creation_count.set(count + 1)

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
        return json.dumps({"error": f"Could not load parent bot: {exc}"}, ensure_ascii=False)

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
            }, ensure_ascii=False)

        # Permission check: delegate_bots must be configured for bot delegation
        if not parent_bot.delegate_bots:
            return json.dumps({"error": "Delegation is disabled. Configure delegate_bots for this bot."}, ensure_ascii=False)

        # Allowlist check: target must be in delegate_bots, wildcard, or ephemeral @-tag
        from app.agent.context import current_ephemeral_delegates
        ephemeral = current_ephemeral_delegates.get() or []
        allowed = parent_bot.delegate_bots
        if "*" not in allowed and bot_id not in allowed and bot_id not in ephemeral:
            return json.dumps({
                "error": f"Bot {bot_id!r} is not in your delegate_bots allowlist. "
                f"Authorized delegates: {allowed}"
            }, ensure_ascii=False)
    else:
        # No bot found — try carapace resolution
        carapace = get_carapace(bot_id)
        if carapace is None:
            available_bots = ", ".join(b.id for b in list_bots())
            return json.dumps({"error": f"No bot or carapace matching {bot_id!r}. Available bots: {available_bots}"}, ensure_ascii=False)

        # Permission check: carapace must appear in delegates of an active carapace the parent wears
        resolved_parent = resolve_carapaces(parent_bot.carapaces)
        authorized_carapace_delegates = {d.id for d in resolved_parent.delegates if d.type == "carapace"}
        if bot_id not in authorized_carapace_delegates:
            return json.dumps({
                "error": f"Carapace {bot_id!r} is not in the delegates list of any active carapace. "
                f"Authorized carapace delegates: {sorted(authorized_carapace_delegates) or 'none'}"
            }, ensure_ascii=False)

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
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

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
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("delegate_to_agent failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


