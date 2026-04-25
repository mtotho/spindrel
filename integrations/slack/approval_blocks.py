"""Slack Block Kit presenters for approval requests.

The renderer owns delivery orchestration; this module owns the approval
message shape so policy/button presentation can evolve without widening
the renderer.
"""
from __future__ import annotations

import json

from integrations.sdk import build_suggestions


def build_capability_approval_blocks(
    approval_id: str, bot_id: str, cap: dict,
) -> list:
    """Block Kit layout for legacy capability activation approvals."""
    cap_name = cap.get("name", "Unknown")
    cap_desc = cap.get("description", "")
    tools_count = cap.get("tools_count", 0)
    skills_count = cap.get("skills_count", 0)

    header_lines = [f":sparkles: *Capability activation — {cap_name}*"]
    if cap_desc:
        header_lines.append(cap_desc)
    header_lines.append(
        f"Provides: {tools_count} tool"
        f"{'s' if tools_count != 1 else ''}, "
        f"{skills_count} skill{'s' if skills_count != 1 else ''}"
    )
    header_lines.append(f"Bot: `{bot_id}`")

    primary_actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Allow"},
            "action_id": "approve_tool_call",
            "value": approval_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Deny"},
            "style": "danger",
            "action_id": "deny_tool_call",
            "value": approval_id,
        },
    ]

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(header_lines)},
        },
        {"type": "actions", "elements": primary_actions},
    ]


def build_tool_approval_blocks(
    approval_id: str,
    bot_id: str,
    tool_name: str,
    arguments: dict,
    reason: str | None,
) -> list:
    """Block Kit layout for regular tool approvals."""
    args_preview = json.dumps(arguments, indent=2)[:500]
    suggestions = build_suggestions(tool_name, arguments)

    primary_actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"Allow {tool_name}"},
            "style": "primary",
            "action_id": "allow_rule_always",
            "value": json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": tool_name,
                "conditions": {},
                "scope": "bot",
                "label": f"Allow {tool_name} always",
            }),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Approve this run"},
            "action_id": "approve_tool_call",
            "value": approval_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Deny"},
            "style": "danger",
            "action_id": "deny_tool_call",
            "value": approval_id,
        },
    ]

    suggestion_actions: list = []
    if suggestions and suggestions[0].scope == "global":
        sug = suggestions[0]
        suggestion_actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": sug.label[:75]},
            "action_id": "allow_rule_0",
            "value": json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": sug.tool_name,
                "conditions": sug.conditions,
                "scope": sug.scope,
                "label": sug.label,
            }),
        })
    narrow_start = next(
        (i for i, suggestion in enumerate(suggestions) if suggestion.conditions),
        len(suggestions),
    )
    for i, sug in enumerate(suggestions[narrow_start:narrow_start + 4]):
        if len(suggestion_actions) >= 5:
            break
        suggestion_actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": sug.label[:75]},
            "action_id": f"allow_rule_{narrow_start + i}",
            "value": json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": sug.tool_name,
                "conditions": sug.conditions,
                "scope": getattr(sug, "scope", "bot"),
                "label": sug.label,
            }),
        })

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":lock: *Tool approval required*\n"
                    f"*Bot:* `{bot_id}` | *Tool:* `{tool_name}`\n"
                    f"*Reason:* {reason or 'Policy requires approval'}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n{args_preview}\n```"},
        },
        {"type": "actions", "elements": primary_actions},
    ]
    if suggestion_actions:
        blocks.append({"type": "actions", "elements": suggestion_actions})
    return blocks
