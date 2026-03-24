"""Pre-turn context compression: summarise old conversation via a cheap model.

This is a **view-layer** optimisation — ephemeral, per-turn, no DB changes.
Coexists with compaction (which is storage-layer — permanent).
"""
import json
import logging
from typing import Any

from app.agent.bots import BotConfig
from app.config import settings
from app.db.models import Channel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config resolution: channel → bot → global
# ---------------------------------------------------------------------------

def _is_compression_enabled(bot: BotConfig, channel: Channel | None = None) -> bool:
    if channel is not None and channel.context_compression is not None:
        return channel.context_compression
    cc = bot.compression_config or {}
    if "enabled" in cc:
        return bool(cc["enabled"])
    return settings.CONTEXT_COMPRESSION_ENABLED


def _get_compression_model(bot: BotConfig, channel: Channel | None = None) -> str:
    if channel and channel.compression_model:
        return channel.compression_model
    cc = bot.compression_config or {}
    if cc.get("model"):
        return cc["model"]
    if settings.CONTEXT_COMPRESSION_MODEL:
        return settings.CONTEXT_COMPRESSION_MODEL
    return settings.COMPACTION_MODEL or bot.model


def _get_compression_threshold(bot: BotConfig, channel: Channel | None = None) -> int:
    if channel and channel.compression_threshold is not None:
        return channel.compression_threshold
    cc = bot.compression_config or {}
    if cc.get("threshold"):
        return int(cc["threshold"])
    return settings.CONTEXT_COMPRESSION_THRESHOLD


def _get_compression_keep_turns(bot: BotConfig, channel: Channel | None = None) -> int:
    if channel and channel.compression_keep_turns is not None:
        return channel.compression_keep_turns
    cc = bot.compression_config or {}
    if cc.get("keep_turns") is not None:
        return int(cc["keep_turns"])
    return settings.CONTEXT_COMPRESSION_KEEP_TURNS


# ---------------------------------------------------------------------------
# Message stringification (reuse compaction's helper when available)
# ---------------------------------------------------------------------------

def _stringify_content(content: Any) -> str:
    """Convert message content to plain text for the compression prompt."""
    from app.services.compaction import _stringify_message_content
    return _stringify_message_content(content)


def _stringify_tool_calls(tool_calls: list[dict]) -> str:
    parts: list[str] = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "?")
        args = fn.get("arguments", "")
        # Truncate very long arguments
        if len(args) > 300:
            args = args[:300] + "…"
        parts.append(f'[tool_call: {name}({args})]')
    return " ".join(parts)


def _format_message(idx: int, msg: dict) -> str:
    """Format a single message with its [msg:N] index prefix."""
    role = msg.get("role", "?")
    content = _stringify_content(msg.get("content"))

    if role == "assistant" and msg.get("tool_calls"):
        tc_text = _stringify_tool_calls(msg["tool_calls"])
        if content:
            return f"[msg:{idx}] {role}: {content} {tc_text}"
        return f"[msg:{idx}] {role}: {tc_text}"

    if role == "tool":
        tool_id = msg.get("tool_call_id", "")
        # Truncate long tool results
        if len(content) > 500:
            content = content[:500] + "…"
        return f"[msg:{idx}] tool({tool_id}): {content}"

    return f"[msg:{idx}] {role}: {content}"


# ---------------------------------------------------------------------------
# Compression prompt
# ---------------------------------------------------------------------------

_COMPRESSION_PROMPT = """\
You are a conversation summariser. You will receive a conversation between a user and an AI assistant, and the user's latest question.

Your task: produce a focused summary of the conversation that preserves all information the assistant would need to answer the current question well.

Rules:
- Include [msg:N] references throughout so the assistant can drill down later — e.g. "User configured webhooks with Bearer auth (see [msg:3]-[msg:5])."
- Preserve exact values: file paths, code snippets, IDs, URLs, config values, numbers.
- Note which message introduced key facts.
- Include outstanding tasks, open questions, and unresolved items.
- Structure your output as:
  **Key Context**: Core facts and decisions
  **Recent Actions**: What was just done (tool calls, results)
  **Open Items**: Pending tasks, unanswered questions
  **Relevant Details**: Specifics the assistant may need

Be concise but thorough. Do NOT invent information not in the conversation."""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def compress_context(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    channel_id: Any = None,
    provider_id: str | None = None,
) -> tuple[list[dict], list[dict]] | None:
    """Compress conversation context via a cheap model.

    Returns (compressed_messages, conversation_for_drilldown) or None if skipped.
    conversation_for_drilldown is the numbered conversation portion for get_message_detail.
    """
    # Load channel for config cascade
    channel: Channel | None = None
    if channel_id is not None:
        try:
            from sqlalchemy import select
            from app.db.engine import async_session
            async with async_session() as db:
                channel = (await db.execute(
                    select(Channel).where(Channel.id == channel_id)
                )).scalar_one_or_none()
        except Exception:
            pass  # Fall through to bot/global config

    if not _is_compression_enabled(bot, channel):
        return None

    threshold = _get_compression_threshold(bot, channel)
    keep_turns = _get_compression_keep_turns(bot, channel)
    model = _get_compression_model(bot, channel)

    # Split messages into: header (leading system msgs), conversation, tail (trailing system msgs + final user)
    header: list[dict] = []
    conversation: list[dict] = []
    tail: list[dict] = []

    # 1. Collect leading system messages as header
    i = 0
    while i < len(messages) and messages[i].get("role") == "system":
        header.append(messages[i])
        i += 1

    # 2. Collect conversation messages (everything between header and tail)
    # Tail = trailing system messages injected by assemble_context + final user message
    # Walk backwards to find the tail boundary
    j = len(messages) - 1
    tail_start = len(messages)

    # The final message should be the user message
    if j >= i and messages[j].get("role") == "user":
        tail_start = j
        j -= 1
        # Walk back over any trailing system messages (injected by context assembly)
        while j >= i and messages[j].get("role") == "system":
            tail_start = j
            j -= 1

    conversation = messages[i:tail_start]
    tail = messages[tail_start:]

    # Measure conversation char count
    conv_chars = sum(len(_stringify_content(m.get("content", ""))) for m in conversation)
    if conv_chars < threshold:
        return None

    # Separate keep_turns from conversation (count user turns from the end)
    kept: list[dict] = []
    older: list[dict] = list(conversation)
    if keep_turns > 0:
        user_turn_count = 0
        split_idx = len(older)
        for k in range(len(older) - 1, -1, -1):
            if older[k].get("role") == "user":
                user_turn_count += 1
                if user_turn_count >= keep_turns:
                    split_idx = k
                    break
        else:
            # Fewer user turns than keep_turns — keep everything
            split_idx = 0
        kept = older[split_idx:]
        older = older[:split_idx]

    if not older:
        return None  # Nothing to compress

    # Number each message in the older portion
    numbered_text_lines: list[str] = []
    for idx, msg in enumerate(older):
        numbered_text_lines.append(_format_message(idx, msg))

    numbered_text = "\n".join(numbered_text_lines)

    # Build compression prompt
    prompt_messages = [
        {"role": "system", "content": _COMPRESSION_PROMPT},
        {"role": "user", "content": (
            f"User's current question: {user_message}\n\n"
            f"Conversation to summarise ({len(older)} messages):\n\n{numbered_text}"
        )},
    ]

    try:
        from app.services.providers import get_llm_client
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=settings.CONTEXT_COMPRESSION_MAX_SUMMARY_TOKENS,
        )
        summary_text = response.choices[0].message.content or ""
    except Exception:
        logger.warning("Context compression failed, falling through to uncompressed", exc_info=True)
        return None

    if not summary_text.strip():
        return None

    # Build compressed message list: header + summary system msg + kept turns + tail
    summary_msg = {
        "role": "system",
        "content": (
            f"[Compressed conversation summary — {len(older)} messages summarised. "
            f"Use get_message_detail(start_index, end_index) to retrieve full message "
            f"content for any [msg:N] reference.]\n\n{summary_text}"
        ),
    }

    compressed = header + [summary_msg] + kept + tail

    # The drill-down history is the older conversation portion (numbered)
    return (compressed, older)
