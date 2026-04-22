import uuid

import pytest

from app.db.models import Message, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


class TestSessionMessagesRouter:
    async def test_get_session_messages_hides_internal_rows_but_keeps_pipeline_steps(self, client, db_session):
        session_id = uuid.uuid4()
        db_session.add(Session(id=session_id, client_id=f"router-client-{uuid.uuid4().hex[:8]}", bot_id="test-bot"))
        await db_session.flush()

        hidden_intermediate = Message(
            session_id=session_id,
            role="assistant",
            content="intermediate tool row",
            metadata_={"hidden": True},
        )
        visible_final = Message(
            session_id=session_id,
            role="assistant",
            content="final assistant row",
            tool_calls=[{
                "id": "call-1",
                "name": "file",
                "arguments": "{\"operation\":\"edit\",\"path\":\"notes.md\"}",
                "surface": "transcript",
                "summary": {
                    "kind": "diff",
                    "subject_type": "file",
                    "label": "Edited notes.md",
                    "path": "notes.md",
                    "diff_stats": {"additions": 1, "deletions": 1},
                },
            }],
            metadata_={
                "transcript_entries": [
                    {"id": "text:1", "kind": "text", "text": "Before edit.\n"},
                    {"id": "tool:call-1", "kind": "tool_call", "toolCallId": "call-1"},
                    {"id": "text:2", "kind": "text", "text": "Done.\n"},
                ],
                "tool_results": [{
                    "content_type": "application/vnd.spindrel.diff+text",
                    "body": "@@ -1 +1 @@\n-old\n+new",
                    "plain_body": "Edited notes.md",
                    "display": "inline",
                    "truncated": False,
                    "record_id": "result-edit",
                    "byte_size": 24,
                }],
            },
        )
        visible_pipeline_step = Message(
            session_id=session_id,
            role="assistant",
            content="pipeline child row",
            metadata_={"hidden": True, "pipeline_step": True},
        )
        db_session.add_all([hidden_intermediate, visible_final, visible_pipeline_step])
        await db_session.commit()

        resp = await client.get(f"/sessions/{session_id}/messages", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        messages = body["messages"]
        assert body["has_more"] is False
        assert [message["content"] for message in messages if message["role"] == "assistant"] == [
            "final assistant row",
            "pipeline child row",
        ]
        final_row = next(message for message in messages if message["content"] == "final assistant row")
        assert final_row["tool_calls"][0]["id"] == "call-1"
        assert final_row["metadata"]["transcript_entries"][1]["toolCallId"] == "call-1"
        assert final_row["metadata"]["tool_results"][0]["content_type"] == "application/vnd.spindrel.diff+text"
