"""Local tool: activate_capability — discover and activate capabilities for this session."""

import json
import logging

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "activate_capability",
        "description": (
            "Activate an available capability for this conversation. "
            "Capabilities provide specialized expertise (skills, tools, behavioral instructions). "
            "Call this when the user's request matches an available capability listed in your context. "
            "The activation lasts for the current session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The capability ID to activate (from the available capabilities index).",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why this capability is needed for the current request.",
                },
            },
            "required": ["id"],
        },
    },
}, safety_tier="mutating")
async def activate_capability(id: str, reason: str = "") -> str:
    """Activate a capability for this conversation session.

    Flow:
    1. Validate capability exists and is not disabled
    2. Check if already active (bot config / integration / session)
    3. Record activation in session store
    4. Return the capability's instructions as immediate inline context
    """
    from app.agent.capability_session import activate, is_activated
    from app.agent.carapaces import get_carapace, list_carapaces
    from app.agent.context import current_correlation_id, current_bot_id
    from app.config import settings

    carapace_id = id.strip()
    if not carapace_id:
        return json.dumps({"error": "Capability ID is required."}, ensure_ascii=False)

    # Get session context
    correlation_id = current_correlation_id.get(None)
    session_id = str(correlation_id) if correlation_id else None
    bot_id = current_bot_id.get(None)

    # Validate carapace exists
    carapace = get_carapace(carapace_id)
    if carapace is None:
        available = [c["id"] for c in list_carapaces()]
        return json.dumps({
            "error": f"Capability '{carapace_id}' not found.",
            "available": available[:20],
        }, ensure_ascii=False)

    # Check global disable list
    _disabled_raw = getattr(settings, "CAPABILITIES_DISABLED", "") or ""
    _globally_disabled = {s.strip() for s in _disabled_raw.split(",") if s.strip()}
    if carapace_id in _globally_disabled:
        return json.dumps({"error": f"Capability '{carapace_id}' is globally disabled."}, ensure_ascii=False)

    # Check channel disable list (via context var)
    from app.agent.context import current_channel_id
    channel_id = current_channel_id.get(None)
    if channel_id:
        try:
            from app.db.engine import async_session
            from app.db.models import Channel
            async with async_session() as db:
                ch = await db.get(Channel, channel_id)
                if ch:
                    ch_disabled = set(getattr(ch, "carapaces_disabled", None) or [])
                    if carapace_id in ch_disabled:
                        return json.dumps({"error": f"Capability '{carapace_id}' is disabled on this channel."}, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to check channel disabled list for capability activation", exc_info=True)

    # Check if already active in session
    if session_id and is_activated(session_id, carapace_id):
        fragment = carapace.get("system_prompt_fragment", "")
        return json.dumps({
            "status": "already_active",
            "id": carapace_id,
            "name": carapace.get("name", carapace_id),
            "message": f"Capability '{carapace.get('name', carapace_id)}' is already active in this session.",
            "fragment": fragment or "",
        }, ensure_ascii=False)

    # Activate in session store and record approval for this session
    if session_id:
        activate(session_id, carapace_id)
        from app.agent.capability_session import approve
        approve(session_id, carapace_id)
    else:
        logger.warning("No session_id for capability activation of %s — activation is ephemeral", carapace_id)

    # Build response with the fragment for immediate use
    fragment = carapace.get("system_prompt_fragment", "")
    tools = carapace.get("local_tools", [])

    result = {
        "status": "activated",
        "id": carapace_id,
        "name": carapace.get("name", carapace_id),
        "message": (
            f"Capability '{carapace.get('name', carapace_id)}' activated for this session. "
            "Full tools will be available on the next turn."
        ),
    }

    # Return fragment so LLM can use behavioral instructions THIS turn
    if fragment:
        result["instructions"] = fragment

    # Inform about tools that will be available next turn
    if tools:
        result["tools_next_turn"] = tools

    if reason:
        logger.info("Capability '%s' activated by %s: %s", carapace_id, bot_id or "unknown", reason)

    return json.dumps(result, ensure_ascii=False)
