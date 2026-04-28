"""Admin context-preview adapter over the runtime assembly result."""
from __future__ import annotations

import json
from typing import Any

from app.config import settings


_CURRENT_TURN_MARKER_PREFIXES = (
    "Everything above is context and conversation history.",
    "Everything above is background context.",
)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _split_base_system_message(content: str) -> list[dict[str, str]]:
    parts = [part.rstrip() for part in content.split("\n\n") if part.strip()]
    if not parts:
        return []

    labels: list[str | None] = [None] * len(parts)
    start = 0
    if settings.GLOBAL_BASE_PROMPT:
        labels[0] = "Global Base Prompt"
        start = 1

    memory_indices = [
        idx
        for idx, part in enumerate(parts[start:], start=start)
        if _looks_like_memory_scheme(part)
    ]
    for idx in memory_indices:
        labels[idx] = "Memory Scheme Prompt"

    non_memory = [
        idx
        for idx in range(start, len(parts))
        if labels[idx] is None
    ]
    if non_memory:
        labels[non_memory[-1]] = "Bot System Prompt"
        for idx in non_memory[:-1]:
            labels[idx] = "Workspace Base Prompt"

    return [
        {"label": label, "role": "system", "content": part}
        for label, part in zip(labels, parts, strict=False)
        if label is not None
    ]


def _looks_like_memory_scheme(content: str) -> bool:
    return (
        "persistent memory lives" in content
        or "Memory Tools" in content
        or "search_memory(query)" in content
    )


def _label_system_message(content: str, index: int) -> str:
    stripped = content.strip()
    if stripped.startswith("[PERSONA]"):
        return "Persona"
    if stripped.startswith("Current time:") or stripped.startswith("Current local time:"):
        return "Date/Time"
    if stripped.startswith("Available skills"):
        return "Skill Index"
    if stripped.startswith("Available sub-agents"):
        return "Delegation Index"
    if stripped.startswith("--- BEGIN RECENT CONVERSATION HISTORY ---"):
        return "Recent Conversation History Start"
    if stripped.startswith("--- END RECENT CONVERSATION HISTORY ---"):
        return "Recent Conversation History End"
    if "pinned widget" in stripped.lower():
        return "Pinned Widget Context"
    if "section index" in stripped.lower():
        return "Section Index"
    if stripped.startswith("## Channel workspace context"):
        return "Workspace Files"
    if stripped.startswith("## Bot knowledge base"):
        return "Bot Knowledge Base"
    if stripped.startswith("Current context profile:"):
        return "Context Profile"
    return f"System Message {index}"


def _is_current_turn_marker(content: str) -> bool:
    return any(content.startswith(prefix) for prefix in _CURRENT_TURN_MARKER_PREFIXES)


def _budget_dict(budget: Any) -> dict[str, Any]:
    return {
        "total_tokens": getattr(budget, "total_tokens", None),
        "reserve_tokens": getattr(budget, "reserve_tokens", None),
        "used_tokens": getattr(budget, "used_tokens", None),
        "remaining_tokens": getattr(budget, "remaining_tokens", None),
    }


def _pinned_widget_context(decisions: dict[str, str]) -> dict[str, Any]:
    decision = decisions.get("pinned_widgets")
    if decision == "skipped_by_channel_config":
        return {"enabled": False, "decision": decision}
    return {"enabled": True, "decision": decision or "unknown"}


def build_context_preview_response(preview: Any, *, include_history: bool) -> dict[str, Any]:
    """Shape a runtime ``PreviewResult`` into the legacy admin response.

    The first system message is already composed by the same session-loading
    path used for live turns. This adapter may split that display-only block
    into labels, but it never rebuilds prompt content.
    """
    blocks: list[dict[str, str]] = []
    conversation: list[dict[str, str]] = []
    seen_system = 0

    for message in preview.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = _text_content(message.get("content"))
        if role == "system":
            if _is_current_turn_marker(content):
                continue
            if seen_system == 0:
                split_blocks = _split_base_system_message(content)
                if split_blocks:
                    blocks.extend(split_blocks)
                else:
                    blocks.append({"label": "Bot System Prompt", "role": "system", "content": content})
            else:
                blocks.append({
                    "label": _label_system_message(content, seen_system + 1),
                    "role": "system",
                    "content": content,
                })
            seen_system += 1
        elif include_history:
            conversation.append({
                "label": role.capitalize() if role else "Message",
                "role": role,
                "content": content[:10000],
            })

    total_chars = sum(len(block["content"]) for block in blocks + conversation)
    assembly = preview.assembly
    decisions = getattr(assembly, "inject_decisions", {}) or {}
    context_policy = getattr(assembly, "context_policy", {}) or {}

    return {
        "blocks": blocks,
        "conversation": conversation,
        "pinned_widget_context": _pinned_widget_context(decisions),
        "total_chars": total_chars,
        "total_tokens_approx": max(1, total_chars // 4) if total_chars > 0 else 0,
        "history_mode": getattr(preview, "history_mode", None) or "unknown",
        "runtime": {
            "bot_id": preview.bot_id,
            "model": preview.model,
            "context_profile": getattr(assembly, "context_profile", None),
            "inject_chars": dict(getattr(preview, "inject_chars", {}) or {}),
            "inject_decisions": dict(decisions),
            "budget": _budget_dict(preview.budget),
        },
    }
