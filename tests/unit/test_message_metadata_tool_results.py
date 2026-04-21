"""Tests for the persist_turn → metadata.tool_results carry-forward.

The agent loop attaches `_tool_envelopes` (a list of compact envelope dicts
in tool-call order) to the final assistant message in the turn. persist_turn
in app/services/sessions.py picks up this private field and writes it to
`Message.metadata.tool_results` so the web UI can render rich tool results
on persisted messages without per-tool knowledge.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import Message, Session
from app.services.sessions import persist_turn
from tests.integration.conftest import engine, db_session  # noqa: F401


@pytest.fixture
def bot():
    return BotConfig(
        id="test-bot",
        name="Test Bot",
        model="test/model",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(enabled=False),
    )


@pytest.mark.asyncio
async def test_persist_turn_writes_tool_results_to_metadata(db_session, bot):
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    envelopes = [
        {
            "content_type": "text/markdown",
            "body": "# Hello",
            "plain_body": "Read hello.txt",
            "display": "inline",
            "truncated": False,
            "record_id": None,
            "byte_size": 7,
        },
        {
            "content_type": "application/vnd.spindrel.diff+text",
            "body": "+new line\n",
            "plain_body": "Wrote out.txt (+1 line)",
            "display": "inline",
            "truncated": False,
            "record_id": None,
            "byte_size": 10,
        },
    ]

    messages = [
        {"role": "user", "content": "do file ops"},
        {
            "role": "assistant",
            "content": "Done.",
            "_tools_used": ["file", "file"],
            "_tool_envelopes": envelopes,
        },
    ]

    with patch("app.services.sessions.get_bot", return_value=bot):
        await persist_turn(
            db_session,
            session_id=sid,
            bot=bot,
            messages=messages,
            from_index=0,
        )

    # Pull back the persisted assistant message via ORM
    from sqlalchemy import select
    row = (
        await db_session.execute(
            select(Message).where(
                Message.session_id == sid,
                Message.role == "assistant",
            )
        )
    ).scalar_one()
    assert row is not None
    metadata = dict(row.metadata_) if row.metadata_ else {}
    assert metadata.get("tools_used") == ["file", "file"]
    assert metadata.get("tool_results") == envelopes


@pytest.mark.asyncio
async def test_persist_turn_writes_thinking_to_metadata(db_session, bot):
    """`_thinking_content` on the assistant dict should land on Message.metadata.thinking."""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    messages = [
        {"role": "user", "content": "reason about this"},
        {
            "role": "assistant",
            "content": "The answer is 42.",
            "_thinking_content": "Step 1: consider the question.\nStep 2: recall prior context.",
        },
    ]

    with patch("app.services.sessions.get_bot", return_value=bot):
        await persist_turn(
            db_session,
            session_id=sid,
            bot=bot,
            messages=messages,
            from_index=0,
        )

    from sqlalchemy import select
    row = (
        await db_session.execute(
            select(Message).where(
                Message.session_id == sid,
                Message.role == "assistant",
            )
        )
    ).scalar_one()
    metadata = dict(row.metadata_) if row.metadata_ else {}
    assert metadata.get("thinking") == "Step 1: consider the question.\nStep 2: recall prior context."


@pytest.mark.asyncio
async def test_persist_turn_omits_tool_results_when_empty(db_session, bot):
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},  # no _tool_envelopes
    ]

    with patch("app.services.sessions.get_bot", return_value=bot):
        await persist_turn(
            db_session,
            session_id=sid,
            bot=bot,
            messages=messages,
            from_index=0,
        )

    from sqlalchemy import select
    row = (
        await db_session.execute(
            select(Message).where(
                Message.session_id == sid,
                Message.role == "assistant",
            )
        )
    ).scalar_one()
    metadata = dict(row.metadata_) if row.metadata_ else {}
    assert "tool_results" not in metadata
