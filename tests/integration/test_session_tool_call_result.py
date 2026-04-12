"""Integration tests for the session-scoped tool call result endpoint.

GET /api/v1/sessions/{session_id}/tool-calls/{tool_call_id}/result is the
user-facing path for fetching full tool call output bodies that exceeded
the inline envelope cap. The web UI uses it for the rich tool result
"Show full output" affordance.

The existing admin endpoint at /api/v1/tool-calls/{id} requires `logs:read`
which UI users don't have. The session-scoped sibling uses `sessions:read`
plus a session-ownership check.
"""
import uuid

import pytest

from app.db.models import Session, ToolCall
from tests.integration.conftest import client, db_session, engine, _TEST_REGISTRY  # noqa: F401


@pytest.mark.asyncio
async def test_returns_full_body_for_owned_tool_call(client, db_session):
    sid = uuid.uuid4()
    tc_id = uuid.uuid4()

    db_session.add(Session(id=sid, client_id="c1", bot_id="test-bot"))
    db_session.add(
        ToolCall(
            id=tc_id,
            session_id=sid,
            client_id="c1",
            bot_id="test-bot",
            tool_name="file",
            tool_type="local",
            arguments={"operation": "read", "path": "foo.txt"},
            result="line1\nline2\nline3\n",
        )
    )
    await db_session.commit()

    res = await client.get(f"/api/v1/sessions/{sid}/tool-calls/{tc_id}/result")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(tc_id)
    assert body["tool_name"] == "file"
    assert body["body"] == "line1\nline2\nline3\n"
    assert body["byte_size"] == len(b"line1\nline2\nline3\n")
    assert body["content_type"] == "text/plain"


@pytest.mark.asyncio
async def test_returns_404_when_tool_call_belongs_to_other_session(client, db_session):
    sid = uuid.uuid4()
    other_sid = uuid.uuid4()
    tc_id = uuid.uuid4()

    db_session.add(Session(id=sid, client_id="c1", bot_id="test-bot"))
    db_session.add(Session(id=other_sid, client_id="c2", bot_id="test-bot"))
    db_session.add(
        ToolCall(
            id=tc_id,
            session_id=other_sid,
            client_id="c2",
            bot_id="test-bot",
            tool_name="file",
            tool_type="local",
            arguments={},
            result="leaked",
        )
    )
    await db_session.commit()

    # Path session is sid but the tool_call belongs to other_sid → 404
    res = await client.get(f"/api/v1/sessions/{sid}/tool-calls/{tc_id}/result")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_returns_404_for_nonexistent_tool_call(client):
    sid = uuid.uuid4()
    tc_id = uuid.uuid4()
    res = await client.get(f"/api/v1/sessions/{sid}/tool-calls/{tc_id}/result")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_empty_body_renders_as_empty_string(client, db_session):
    sid = uuid.uuid4()
    tc_id = uuid.uuid4()

    db_session.add(Session(id=sid, client_id="c1", bot_id="test-bot"))
    db_session.add(
        ToolCall(
            id=tc_id,
            session_id=sid,
            client_id="c1",
            bot_id="test-bot",
            tool_name="file",
            tool_type="local",
            arguments={},
            result=None,  # NULL result column
        )
    )
    await db_session.commit()

    res = await client.get(f"/api/v1/sessions/{sid}/tool-calls/{tc_id}/result")
    assert res.status_code == 200
    body = res.json()
    assert body["body"] == ""
    assert body["byte_size"] == 0
