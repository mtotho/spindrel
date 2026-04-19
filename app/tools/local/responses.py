"""Response-delivery tools — ways an agent can target its reply.

Today: ``respond_privately`` — deliver a reply visible only to one user
on integrations that support ephemeral messages (Slack ``chat.post
Ephemeral`` is the only implementation). Strict-deliver: the reply is
routed to exactly one bound integration on the channel, or the tool
returns ``unsupported`` and the agent should ask conversationally
instead. There is no channel-broadcast fallback.
"""
from __future__ import annotations

import json

from app.agent.context import current_bot_id, current_channel_id
from app.domain.capability import Capability
from app.services.ephemeral_dispatch import deliver_ephemeral
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "respond_privately",
        "description": (
            "Send a reply that is visible ONLY to one specific user in the current "
            "channel. Use when the output is personal (credentials, private debug "
            "info, long diagnostics meant for the asker only) and should not be "
            "visible to everyone. The recipient is specified by their integration-"
            "native user id (Slack 'U...' format, Discord snowflake, etc.). "
            "If no bound integration on this channel can deliver privately to "
            "that user, this tool returns unsupported — you should then ask the "
            "user conversationally instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {
                    "type": "string",
                    "description": (
                        "Integration-native user id for the recipient. On Slack, "
                        "this looks like 'U01ABC'. You can read it from the "
                        "'<@U...>' token in the user's message attribution."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "The message body to deliver privately.",
                },
            },
            "required": ["to_user", "text"],
        },
    },
}, safety_tier="readonly", required_capabilities=frozenset({Capability.EPHEMERAL}), requires_bot_context=True, requires_channel_context=True)
async def respond_privately(to_user: str, text: str) -> str:
    bot_id = current_bot_id.get() or ""
    channel_id = current_channel_id.get()
    if channel_id is None:
        return json.dumps({"ok": False, "error": "no channel in current context"})

    result = await deliver_ephemeral(
        channel_id=channel_id,
        bot_id=bot_id,
        recipient_user_id=to_user,
        text=text,
    )
    mode = result.get("mode")
    if mode == "ephemeral":
        return json.dumps({"ok": True, **result})
    # error / unsupported both surface as ok=False so the calling agent
    # reads the error field and reframes — no silent success on degraded paths.
    return json.dumps({"ok": False, **result})
