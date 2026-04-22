from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers.api_v1_sessions import MessageOut


def test_message_out_from_orm_includes_tool_calls():
    correlation_id = uuid.uuid4()
    tool_calls = [{
        "id": "call_1",
        "name": "file",
        "arguments": "{\"path\":\"notes.md\"}",
        "surface": "transcript",
        "summary": {
            "kind": "diff",
            "subject_type": "file",
            "label": "Edited notes.md",
            "path": "notes.md",
            "diff_stats": {"additions": 1, "deletions": 0},
        },
    }]
    row = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="Done.",
        tool_calls=tool_calls,
        tool_call_id="call_1",
        correlation_id=correlation_id,
        created_at=datetime.now(timezone.utc),
        metadata_={"tools_used": ["file"]},
        attachments=[],
    )

    out = MessageOut.from_orm(row)

    assert out.tool_calls == tool_calls
    assert out.tool_call_id == "call_1"
    assert out.correlation_id == correlation_id
