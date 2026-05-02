import uuid
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import Message, Session
from app.services.sessions import persist_turn
from tests.integration.conftest import db_session  # noqa: F401


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
async def test_persist_turn_normalizes_assistant_tool_calls_with_surface_and_summary(db_session, bot):
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    diff_body = "\n".join([
        "--- a/index.html",
        "+++ b/index.html",
        "@@ -1,2 +1,2 @@",
        "-old line",
        "+new line",
        " same line",
    ])
    messages = [
        {"role": "user", "content": "edit the widget"},
        {
            "role": "assistant",
            "content": "Done.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_skill",
                        "arguments": "{\"skill_id\":\"widgets\"}",
                    },
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "file",
                        "arguments": "{\"operation\":\"edit\",\"path\":\"index.html\"}",
                    },
                },
            ],
            "_tool_envelopes": [
                {
                    "content_type": "application/json",
                    "body": "{\"id\":\"widgets\",\"name\":\"Widgets\",\"description\":\"How to build widgets\",\"content\":\"# Widgets\"}",
                    "plain_body": "Loaded skill widgets",
                    "display": "badge",
                    "truncated": False,
                    "record_id": None,
                    "byte_size": 32,
                },
                {
                    "content_type": "application/vnd.spindrel.diff+text",
                    "body": diff_body,
                    "plain_body": "Edited index.html: +1 -1 lines (1 replacement)",
                    "display": "inline",
                    "truncated": False,
                    "record_id": None,
                    "byte_size": len(diff_body),
                },
            ],
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

    assert row.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_skill", "arguments": "{\"skill_id\":\"widgets\"}"},
            "name": "get_skill",
            "arguments": "{\"skill_id\":\"widgets\"}",
            "surface": "transcript",
            "summary": {
                "kind": "read",
                "subject_type": "skill",
                "label": "Loaded skill",
                "target_id": "widgets",
                "target_label": "Widgets",
                "preview_text": "How to build widgets",
            },
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "file", "arguments": "{\"operation\":\"edit\",\"path\":\"index.html\"}"},
            "name": "file",
            "arguments": "{\"operation\":\"edit\",\"path\":\"index.html\"}",
            "surface": "rich_result",
            "summary": {
                "kind": "diff",
                "subject_type": "file",
                "label": "Edited index.html: +1 -1 lines (1 replacement)",
                "path": "index.html",
                "diff_stats": {"additions": 1, "deletions": 1},
            },
        },
    ]


@pytest.mark.asyncio
async def test_persist_turn_matches_tool_envelopes_by_tool_call_id_before_position(db_session, bot):
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    messages = [
        {"role": "user", "content": "search the web"},
        {
            "role": "assistant",
            "content": "Found it.",
            "tool_calls": [
                {
                    "id": "call_skill",
                    "type": "function",
                    "function": {
                        "name": "get_skill",
                        "arguments": "{\"skill_id\":\"workspace_files\"}",
                    },
                },
                {
                    "id": "call_search",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": "{\"query\":\"latest OpenAI news\",\"num_results\":5}",
                    },
                },
            ],
            "_tool_envelopes": [
                {
                    "tool_call_id": "call_search",
                    "content_type": "application/vnd.spindrel.html+interactive",
                    "body": "<html><body>widget</body></html>",
                    "plain_body": "Widget: web_search",
                    "display": "inline",
                    "truncated": False,
                    "record_id": None,
                    "byte_size": 32,
                    "display_label": "Web search",
                },
            ],
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

    assert row.tool_calls[0]["id"] == "call_skill"
    assert row.tool_calls[0]["surface"] == "transcript"
    assert row.tool_calls[1]["id"] == "call_search"
    assert row.tool_calls[1]["surface"] == "widget"
    assert row.tool_calls[1]["summary"] == {
        "kind": "result",
        "subject_type": "widget",
        "label": "Widget available",
        "target_label": "Web search",
    }
    assert row.metadata_["tool_results"][0]["tool_call_id"] == "call_search"


@pytest.mark.asyncio
async def test_persist_turn_repairs_redacted_tool_result_ids_from_tool_calls(db_session, bot):
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, client_id="c1", bot_id=bot.id))
    await db_session.commit()

    raw_id = "toolu_016dAm8mvA8hFZAbpDiNdMBk"
    messages = [
        {"role": "user", "content": "run the selected bridge tool"},
        {
            "role": "assistant",
            "content": "Done.",
            "tool_calls": [
                {
                    "id": raw_id,
                    "type": "function",
                    "function": {
                        "name": "spindrel__manage_task",
                        "arguments": "{\"action\":\"status\"}",
                    },
                },
                {
                    "id": f"auto:{raw_id}",
                    "type": "function",
                    "function": {
                        "name": "auto-approved",
                        "arguments": "{}",
                    },
                    "name": "auto-approved",
                },
            ],
            "_tool_envelopes": [
                {
                    "tool_call_id": "toolu_0[REDACTED]6dAm8mvA8hFZAbpDiNdMBk",
                    "content_type": "application/json",
                    "body": "{\"ok\":true}",
                    "plain_body": "Task status loaded",
                    "display": "inline",
                    "truncated": False,
                    "record_id": None,
                    "byte_size": 11,
                },
            ],
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

    assert row.tool_calls[0]["id"] == raw_id
    assert row.metadata_["tool_results"][0]["tool_call_id"] == raw_id


def test_message_out_repairs_redacted_tool_result_ids_from_tool_calls():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.schemas.messages import MessageOut

    raw_id = "toolu_0132CKeCpSjTvXEDHroN1cBq"
    msg = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="Done.",
        tool_calls=[
            {
                "id": raw_id,
                "name": "mcp__spindrel__list_channels",
                "function": {"name": "mcp__spindrel__list_channels"},
            }
        ],
        tool_call_id=None,
        correlation_id=None,
        created_at=datetime.now(timezone.utc),
        metadata_={
            "tool_results": [
                {
                    "tool_call_id": "toolu_0[REDACTED]32CKeCpSjTvXEDHroN[REDACTED]cBq",
                    "content_type": "application/json",
                    "body": "{}",
                }
            ]
        },
        attachments=[],
    )

    out = MessageOut.from_orm(msg)

    assert out.metadata["tool_results"][0]["tool_call_id"] == raw_id
