"""Slack adapter for SDK-normalized rich tool-result presentation."""
from __future__ import annotations

from integrations.sdk import (
    ToolBadge,
    ToolOutputDisplay,
    ToolResultCard,
    ToolResultPresentation,
    ToolResultRenderingSupport,
    build_tool_result_presentation,
    extract_tool_badges,
)
from integrations.slack.formatting import markdown_to_slack_mrkdwn

_SLOT_EMOJI = {
    "success": ":white_check_mark:",
    "warning": ":warning:",
    "danger": ":x:",
    "error": ":x:",
    "info": ":information_source:",
}


def build_tool_result_blocks(
    tool_results: list[dict],
    *,
    display_mode: str,
    support: ToolResultRenderingSupport | None,
) -> list[dict]:
    """Render tool-result envelopes to Slack Block Kit blocks.

    The shared SDK function decides which envelopes become portable cards
    and which degrade to badges. This adapter only maps that portable model
    to Slack's read-only blocks.
    """
    mode = ToolOutputDisplay.normalize(display_mode)
    presentation = build_tool_result_presentation(
        tool_results,
        display_mode=mode,
        support=support,
    )
    if mode == ToolOutputDisplay.NONE:
        return []
    if mode == ToolOutputDisplay.COMPACT:
        block = badges_to_context_block(list(presentation.badges))
        return [block] if block is not None else []

    blocks: list[dict] = []
    for card in presentation.cards:
        blocks.extend(_card_to_blocks(card))
    fallback = badges_to_context_block(list(presentation.unsupported_badges))
    if fallback is not None:
        blocks.append(fallback)
    limit = (support.limits.get("max_blocks") if support else None) or 50
    if len(blocks) > limit:
        blocks = blocks[: max(0, limit - 1)]
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "_Additional tool result blocks omitted._"}],
        })
    return blocks[:limit]


def badges_to_context_block(badges: list[ToolBadge]) -> dict | None:
    """Render compact tool badges into one Slack context block."""
    if not badges:
        return None
    elements = []
    for badge in badges[:10]:
        name = _escape_mrkdwn(badge.tool_name) or "tool"
        text = f":wrench:  *{name}*"
        if badge.display_label:
            text += f"  —  {_escape_mrkdwn(badge.display_label)}"
        elements.append({"type": "mrkdwn", "text": text})
    return {"type": "context", "elements": elements}


def _card_to_blocks(card: ToolResultCard) -> list[dict]:
    blocks: list[dict] = []
    if card.title:
        text = _escape_mrkdwn(card.title)[:150]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}})
    if card.status:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*{_escape_mrkdwn(card.status)}*"}],
        })
    if card.summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": markdown_to_slack_mrkdwn(card.summary)[:3000]},
        })
    if card.fields:
        fields = [
            {"type": "mrkdwn", "text": f"*{_escape_mrkdwn(f.label)}*\n{_escape_mrkdwn(f.value)}"}
            for f in card.fields[:10]
            if f.label or f.value
        ]
        if fields:
            blocks.append({"type": "section", "fields": fields})
    if card.table:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _table_to_mrkdwn(card.table.columns, card.table.rows, card.table.truncated)},
        })
    if card.links:
        lines = []
        for link in card.links[:10]:
            line = f":link: <{link.url}|{_escape_mrkdwn(link.title or link.url)}>"
            if link.subtitle:
                line += f"\n    {_escape_mrkdwn(link.subtitle[:160])}"
            lines.append(line)
        if lines:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    if card.code:
        label = f"_{_escape_mrkdwn(card.code.language)}_\n" if card.code.language else ""
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{label}```\n{card.code.content[:2900]}\n```"},
        })
    if card.image:
        blocks.append({"type": "image", "image_url": card.image.url, "alt_text": card.image.alt or "image"})
    if card.truncated:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "_Tool result truncated._"}],
        })
    return blocks


def _table_to_mrkdwn(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...], truncated: bool) -> str:
    widths = [len(c) for c in columns]
    for row in rows:
        for idx, cell in enumerate(row[:len(widths)]):
            widths[idx] = max(widths[idx], len(str(cell)))
    header = " | ".join(columns[idx].ljust(widths[idx]) for idx in range(len(columns)))
    sep = "-+-".join("-" * width for width in widths)
    lines = [header, sep]
    for row in rows:
        lines.append(" | ".join(
            str(row[idx] if idx < len(row) else "").ljust(widths[idx])
            for idx in range(len(columns))
        ))
    if truncated:
        lines.append("... [truncated]")
    return f"```\n{chr(10).join(lines)}\n```"


def _escape_mrkdwn(text: str | None) -> str:
    text = text or ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "badges_to_context_block",
    "build_tool_result_blocks",
    "extract_tool_badges",
]
