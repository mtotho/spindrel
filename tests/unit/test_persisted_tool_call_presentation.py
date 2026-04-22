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
                    "body": "{\"id\":\"widgets\",\"name\":\"Widgets\",\"content\":\"...\"}",
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
                "target_label": "widgets/INDEX.md",
            },
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "file", "arguments": "{\"operation\":\"edit\",\"path\":\"index.html\"}"},
            "name": "file",
            "arguments": "{\"operation\":\"edit\",\"path\":\"index.html\"}",
            "surface": "transcript",
            "summary": {
                "kind": "diff",
                "subject_type": "file",
                "label": "Edited index.html: +1 -1 lines (1 replacement)",
                "path": "index.html",
                "diff_stats": {"additions": 1, "deletions": 1},
            },
        },
    ]
