"""Unit tests for tool audit API response schemas and helpers."""
import uuid
from datetime import datetime, timezone

import pytest

from app.routers.api_v1_tool_calls import ToolCallOut, ToolCallStatGroup


class TestToolCallOutSchema:
    def test_result_truncation_in_model(self):
        """ToolCallOut can be constructed with normal fields."""
        tc = ToolCallOut(
            id=uuid.uuid4(),
            tool_name="exec_command",
            tool_type="local",
            arguments={"command": "ls"},
            result="short result",
            created_at=datetime.now(timezone.utc),
        )
        assert tc.tool_name == "exec_command"
        assert tc.result == "short result"

    def test_optional_fields_default_none(self):
        tc = ToolCallOut(
            id=uuid.uuid4(),
            tool_name="web_search",
            tool_type="mcp",
            arguments={},
            error="timeout",
            error_code="tool_dispatch_timeout",
            error_kind="timeout",
            retryable=True,
            retry_after_seconds=3,
            fallback="Retry later.",
            created_at=datetime.now(timezone.utc),
        )
        assert tc.session_id is None
        assert tc.bot_id is None
        assert tc.error == "timeout"
        assert tc.error_code == "tool_dispatch_timeout"
        assert tc.error_kind == "timeout"
        assert tc.retryable is True
        assert tc.retry_after_seconds == 3
        assert tc.fallback == "Retry later."
        assert tc.duration_ms is None


class TestToolCallStatGroup:
    def test_construction(self):
        sg = ToolCallStatGroup(
            key="exec_command",
            count=42,
            total_duration_ms=10000,
            avg_duration_ms=238,
            error_count=3,
        )
        assert sg.count == 42
        assert sg.error_count == 3
