import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig, get_bot
from app.agent.persona import get_persona
from app.db.models import Message, Session
from app.services.compaction import maybe_compact


logger = logging.getLogger(__name__)


def _effective_system_prompt(bot: BotConfig) -> str:
    """System prompt plus optional memory guidelines when memory is enabled."""
    out = bot.system_prompt.rstrip()
    if bot.memory.enabled and bot.memory.prompt:
        out += "\n\n" + bot.memory.prompt.strip()
    return out


async def load_or_create(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    client_id: str,
    bot_id: str,
) -> tuple[uuid.UUID, list[dict]]:
    if session_id is not None:
        existing = await db.get(Session, session_id)
        if existing is not None:
            messages = await _load_messages(db, existing)
            return session_id, messages

    if session_id is None:
        session_id = uuid.uuid4()

    bot = get_bot(bot_id)
    session = Session(id=session_id, client_id=client_id, bot_id=bot_id)
    db.add(session)

    system_content = _effective_system_prompt(bot)
    system_msg = Message(
        session_id=session_id,
        role="system",
        content=system_content,
    )
    db.add(system_msg)
    await db.commit()

    # Build initial message list with persona if enabled
    messages = [{"role": "system", "content": system_content}]
    if bot.persona:
        persona_layer = await get_persona(bot.id)
        if persona_layer:
            messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})

    return session_id, messages



async def _load_messages(db: AsyncSession, session: Session) -> list[dict]:
    """Load messages for a session, using compacted summary when available."""
    bot = get_bot(session.bot_id)

    persona_layer = None
    if bot.persona:
        persona_layer = await get_persona(bot.id)

    def _base_messages() -> list[dict]:
        msgs = [{"role": "system", "content": _effective_system_prompt(bot)}]
        if persona_layer:
            msgs.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
        return msgs

    if session.summary and session.summary_message_id and bot.context_compaction:
        watermark_msg = await db.get(Message, session.summary_message_id)
        if watermark_msg is not None:
            recent_result = await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .where(Message.created_at > watermark_msg.created_at)
                .order_by(Message.created_at)
            )
            recent = [_message_to_dict(m) for m in recent_result.scalars().all()]
            messages = _base_messages()
            messages.append({"role": "system", "content": f"Summary of the conversation so far:\n\n{session.summary}"})
            messages.extend(recent)
            return _sanitize_tool_messages(messages)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at)
    )
    all_msgs = [_message_to_dict(m) for m in result.scalars().all()]
    non_system_msgs = [m for m in all_msgs if m["role"] != "system"]
    return _sanitize_tool_messages(_base_messages() + non_system_msgs)

async def persist_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    bot: BotConfig,
    messages: list[dict],
    from_index: int,
) -> None:
    new_messages = messages[from_index:]
    now = datetime.now(timezone.utc)
    for i, msg in enumerate(new_messages):
        record = Message(
            session_id=session_id,
            role=msg["role"],
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id"),
            created_at=now + timedelta(microseconds=i),
        )
        db.add(record)

    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_active=now)
    )
    await db.commit()

    await maybe_compact(session_id, bot, messages)


def _sanitize_tool_messages(messages: list[dict]) -> list[dict]:
    """Fix tool message ordering and strip orphans.

    LLMs (especially Gemini via LiteLLM) require strict ordering:
    assistant(tool_calls) must come before its tool(results), and every
    tool result must have a matching tool_call.  DB round-trips can break
    ordering (same-timestamp inserts) and compaction can orphan messages.

    Strategy: extract tool call/result groups, reinsert them in the
    correct position, and strip anything that can't be matched.
    """
    # Pass 1: find where each tool_call ID is offered (assistant) and
    # answered (tool result), by position in the message list.
    call_positions: dict[str, int] = {}   # tc_id → index of assistant msg
    result_positions: dict[str, int] = {} # tc_id → index of tool msg

    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") or ""
                if tc_id:
                    call_positions[tc_id] = i
        elif msg.get("role") == "tool" and msg.get("tool_call_id"):
            result_positions[msg["tool_call_id"]] = i

    # Pass 2: identify problems
    all_call_ids = set(call_positions.keys())
    all_result_ids = set(result_positions.keys())
    orphan_results = all_result_ids - all_call_ids
    orphan_calls = all_call_ids - all_result_ids
    misordered = {
        tc_id for tc_id in (all_call_ids & all_result_ids)
        if call_positions[tc_id] >= result_positions[tc_id]
    }

    if not orphan_results and not orphan_calls and not misordered:
        return messages

    if orphan_results:
        logger.warning("Stripping %d orphaned tool result(s)", len(orphan_results))
    if orphan_calls:
        logger.warning("Stripping %d unanswered tool call(s)", len(orphan_calls))
    if misordered:
        logger.warning("Reordering %d misordered tool sequence(s)", len(misordered))

    # Pass 3: rebuild.  Pull out misordered tool results, strip orphans,
    # then reinsert tool results right after their tool_call source.
    displaced: dict[str, dict] = {}  # tc_id → tool result msg (pulled out)
    result_indices_to_skip: set[int] = set()

    for tc_id in misordered:
        idx = result_positions[tc_id]
        displaced[tc_id] = messages[idx]
        result_indices_to_skip.add(idx)

    cleaned: list[dict] = []
    for i, msg in enumerate(messages):
        if i in result_indices_to_skip:
            continue

        if msg.get("role") == "tool" and msg.get("tool_call_id") in orphan_results:
            continue

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            kept = [tc for tc in msg["tool_calls"]
                    if (tc.get("id") or "") not in orphan_calls]
            if not kept:
                if msg.get("content"):
                    cleaned.append({"role": "assistant", "content": msg["content"]})
                continue
            if len(kept) != len(msg["tool_calls"]):
                msg = {**msg, "tool_calls": kept}

        cleaned.append(msg)

        # Reinsert any displaced tool results right after their source
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") or ""
                if tc_id in displaced:
                    cleaned.append(displaced.pop(tc_id))

    return cleaned


def _message_to_dict(msg: Message) -> dict:
    d: dict = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls is not None:
        d["tool_calls"] = msg.tool_calls
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    return d
