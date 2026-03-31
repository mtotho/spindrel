"""Discord button interaction handlers for tool approval.

Handles button clicks from Discord messages sent by
DiscordDispatcher.request_approval().

Custom ID format (compact, stays under Discord's 100-char limit):
  - "ap:{approval_id}"   — approve this run
  - "dn:{approval_id}"   — deny
  - "aa:{approval_id}"   — allow always (bot-scoped, no conditions)
  - "ar:{approval_id}:N" — allow rule suggestion N (0-indexed)

The approval record in the DB has bot_id, tool_name, and arguments,
so we look those up server-side rather than encoding them in the custom_id.
"""
import logging
import re

import discord
import httpx

logger = logging.getLogger(__name__)

# Pattern: prefix:uuid or prefix:uuid:index
_APPROVAL_PATTERN = re.compile(r"^(ap|dn|aa|ar):([0-9a-f\-]{36})(?::(\d+))?$")


def is_approval_custom_id(custom_id: str) -> bool:
    """Check if a custom_id is one of our approval button IDs."""
    return bool(_APPROVAL_PATTERN.match(custom_id))


async def handle_approval_interaction(interaction: discord.Interaction) -> None:
    """Handle a button click on an approval message."""
    custom_id = interaction.data.get("custom_id", "")
    m = _APPROVAL_PATTERN.match(custom_id)
    if not m:
        return

    action_prefix = m.group(1)
    approval_id = m.group(2)
    suggestion_index = int(m.group(3)) if m.group(3) else None

    await interaction.response.defer()
    user_id = str(interaction.user.id)

    if action_prefix == "ap":
        # Approve this run
        ok = await _decide(approval_id, approved=True, decided_by=f"discord:{user_id}")
        if ok:
            await _update_message(interaction, f"\u2705 **Approved** (this run) by <@{user_id}>")
        elif ok is None:
            await _update_message(interaction, "\u26a0\ufe0f Approval already resolved.")
        else:
            await _update_message(interaction, "\u274c Failed to process approval.")

    elif action_prefix == "dn":
        # Deny
        ok = await _decide(approval_id, approved=False, decided_by=f"discord:{user_id}")
        if ok:
            await _update_message(interaction, f"\U0001f6ab **Denied** by <@{user_id}>")
        elif ok is None:
            await _update_message(interaction, "\u26a0\ufe0f Approval already resolved.")
        else:
            await _update_message(interaction, "\u274c Failed to process approval.")

    elif action_prefix == "aa":
        # Allow always — look up tool_name from approval record, create bot-scoped rule
        approval_data = await _fetch_approval(approval_id)
        if not approval_data:
            await _update_message(interaction, "\u274c Approval not found.")
            return
        tool_name = approval_data.get("tool_name", "?")
        bot_id = approval_data.get("bot_id", "?")
        ok = await _decide_with_rule(
            approval_id,
            decided_by=f"discord:{user_id}",
            create_rule={
                "tool_name": tool_name,
                "conditions": {},
                "scope": "bot",
            },
        )
        if ok:
            await _update_message(interaction, f"\u2705 **Allowed** `{tool_name}` for `{bot_id}` by <@{user_id}>")
        elif ok is None:
            await _update_message(interaction, "\u26a0\ufe0f Approval already resolved.")
        else:
            await _update_message(interaction, "\u274c Failed to process approval.")

    elif action_prefix == "ar" and suggestion_index is not None:
        # Allow rule suggestion — regenerate suggestions and pick by index
        approval_data = await _fetch_approval(approval_id)
        if not approval_data:
            await _update_message(interaction, "\u274c Approval not found.")
            return
        tool_name = approval_data.get("tool_name", "?")
        bot_id = approval_data.get("bot_id", "?")
        arguments = approval_data.get("arguments", {})

        from approval_suggestions_helper import build_suggestion_rule
        rule, label = build_suggestion_rule(tool_name, arguments, suggestion_index)
        if not rule:
            await _update_message(interaction, "\u274c Suggestion no longer available.")
            return

        scope = rule.get("scope", "bot")
        ok = await _decide_with_rule(
            approval_id,
            decided_by=f"discord:{user_id}",
            create_rule=rule,
        )
        scope_text = " (all bots)" if scope == "global" else f" for `{bot_id}`"
        if ok:
            await _update_message(interaction, f"\u2705 **Approved** + rule: **{label}**{scope_text} by <@{user_id}>")
        elif ok is None:
            await _update_message(interaction, "\u26a0\ufe0f Approval already resolved.")
        else:
            await _update_message(interaction, "\u274c Failed to process approval.")


async def _fetch_approval(approval_id: str) -> dict | None:
    """Fetch approval record from the agent server."""
    from discord_settings import AGENT_BASE_URL, API_KEY

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}",
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return r.json()
            return None
    except Exception:
        logger.exception("Failed to fetch approval %s", approval_id)
        return None


async def _decide(approval_id: str, *, approved: bool, decided_by: str) -> bool | None:
    """Call the agent server's approval decide endpoint.
    Returns True on success, None on 409, False on error.
    """
    from discord_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {"approved": approved, "decided_by": decided_by}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return True
            elif r.status_code == 409:
                return None
            else:
                logger.error("Approval decide failed: %d %s", r.status_code, r.text)
                return False
    except Exception:
        logger.exception("Failed to decide approval %s", approval_id)
        return False


async def _decide_with_rule(
    approval_id: str, *, decided_by: str, create_rule: dict,
) -> bool | None:
    """Approve + create an allow rule in a single call."""
    from discord_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {
        "approved": True,
        "decided_by": decided_by,
        "create_rule": create_rule,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return True
            elif r.status_code == 409:
                return None
            else:
                logger.error("Approval decide+rule failed: %d %s", r.status_code, r.text)
                return False
    except Exception:
        logger.exception("Failed to decide+rule approval %s", approval_id)
        return False


async def _update_message(interaction: discord.Interaction, text: str) -> None:
    """Replace the original approval message — keep embeds, remove buttons, add verdict."""
    try:
        original = interaction.message
        embeds = list(original.embeds) if original else []
        embeds.append(discord.Embed(description=text, color=0x00FF00 if "\u2705" in text else 0xFF0000))
        await interaction.edit_original_response(
            embeds=embeds,
            view=None,  # Remove all buttons
        )
    except Exception:
        logger.exception("Failed to update approval message")
