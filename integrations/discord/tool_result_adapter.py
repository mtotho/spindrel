"""Discord adapter for SDK-normalized rich tool-result presentation."""
from __future__ import annotations

from integrations.sdk import (
    ToolBadge,
    ToolOutputDisplay,
    ToolResultCard,
    ToolResultRenderingSupport,
    build_tool_result_presentation,
)

_STATUS_COLORS = {
    "success": 0x2ECC71,
    "warning": 0xF1C40F,
    "danger": 0xE74C3C,
    "error": 0xE74C3C,
    "info": 0x3498DB,
}


def build_tool_result_payload(
    tool_results: list[dict],
    *,
    display_mode: str,
    support: ToolResultRenderingSupport | None,
) -> tuple[str, list[dict]]:
    """Render tool-result envelopes to Discord suffix text + embeds."""
    mode = ToolOutputDisplay.normalize(display_mode)
    presentation = build_tool_result_presentation(
        tool_results,
        display_mode=mode,
        support=support,
    )
    if mode == ToolOutputDisplay.NONE:
        return "", []
    if mode == ToolOutputDisplay.COMPACT:
        return _badges_to_text(list(presentation.badges)), []

    embeds = [_card_to_embed(card) for card in presentation.cards]
    embeds = [embed for embed in embeds if embed]
    fallback = _badges_to_text(list(presentation.unsupported_badges))
    return fallback, embeds[:10]


def _badges_to_text(badges: list[ToolBadge]) -> str:
    if not badges:
        return ""
    parts = []
    for badge in badges[:10]:
        text = f"`{badge.tool_name or 'tool'}`"
        if badge.display_label:
            text += f" - {badge.display_label}"
        parts.append(text)
    return "Tools: " + ", ".join(parts)


def _card_to_embed(card: ToolResultCard) -> dict:
    embed: dict = {}
    if card.title:
        embed["title"] = card.title[:256]
    description_parts: list[str] = []
    if card.status:
        description_parts.append(f"**{card.status[:180]}**")
    if card.summary:
        description_parts.append(card.summary[:1800])
    if card.table:
        description_parts.append(_table_to_code(card.table.columns, card.table.rows, card.table.truncated))
    if card.code:
        language = card.code.language or ""
        description_parts.append(f"```{language}\n{card.code.content[:1700]}\n```")
    if card.truncated:
        description_parts.append("_Tool result truncated._")
    if description_parts:
        embed["description"] = "\n\n".join(description_parts)[:4096]
    fields = []
    for field in card.fields[:10]:
        fields.append({
            "name": (field.label or "Field")[:256],
            "value": (field.value or "-")[:1024],
            "inline": True,
        })
    for link in card.links[:10]:
        value = f"[{link.title or link.url}]({link.url})"
        if link.subtitle:
            value += f"\n{link.subtitle[:180]}"
        fields.append({
            "name": "Link",
            "value": value[:1024],
            "inline": False,
        })
    if fields:
        embed["fields"] = fields[:25]
    if card.image:
        embed["image"] = {"url": card.image.url}
    if card.source_tool:
        embed["footer"] = {"text": card.source_tool[:2048]}
    if card.status:
        lowered = card.status.lower()
        for key, color in _STATUS_COLORS.items():
            if key in lowered:
                embed["color"] = color
                break
    return embed


def _table_to_code(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...], truncated: bool) -> str:
    widths = [len(c) for c in columns]
    for row in rows:
        for idx, cell in enumerate(row[:len(widths)]):
            widths[idx] = max(widths[idx], len(str(cell)))
    lines = [
        " | ".join(columns[idx].ljust(widths[idx]) for idx in range(len(columns))),
        "-+-".join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(" | ".join(
            str(row[idx] if idx < len(row) else "").ljust(widths[idx])
            for idx in range(len(columns))
        ))
    if truncated:
        lines.append("... [truncated]")
    return f"```\n{chr(10).join(lines)[:1800]}\n```"


__all__ = ["build_tool_result_payload"]
