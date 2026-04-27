"""Daily system-health summary generator + scheduler gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import (
    SystemHealthSummary,
    ToolCall,
    TraceEvent,
    WorkspaceAttentionItem,
)
from app.services.error_log_parser import LogFinding
from app.services.system_health_summary import (
    DAILY_SUMMARY_SOURCE_ID,
    _date_dedupe_key,
    generate_daily_summary,
    latest_summary,
)


def _now_fixed() -> datetime:
    return datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)


def _make_finding(*, service: str, count: int, severity: str = "error", title: str = "x") -> LogFinding:
    return LogFinding(
        service=service,
        severity=severity,
        signature="sig-x",
        title=title,
        sample=title,
        first_seen=_now_fixed(),
        last_seen=_now_fixed(),
        count=count,
        dedupe_key=f"log-{service}-sig-x",
        extra={"kind": "level_line"},
    )


@pytest.mark.asyncio
async def test_generate_daily_summary_persists_row_and_attention_item(db_session):
    findings = [
        _make_finding(service="agent-server", count=3, severity="error"),
        _make_finding(service="postgres", count=1, severity="critical"),
    ]
    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=findings),
    ):
        summary = await generate_daily_summary(db_session, period_hours=24, now=_now_fixed())

    assert isinstance(summary, SystemHealthSummary)
    assert summary.error_count == 4
    assert summary.critical_count == 1
    assert summary.source_counts == {"agent-server": 3, "postgres": 1}
    assert summary.attention_item_id is not None

    item = await db_session.get(WorkspaceAttentionItem, summary.attention_item_id)
    assert item is not None
    assert item.source_type == "system"
    assert item.source_id == DAILY_SUMMARY_SOURCE_ID
    assert item.target_kind == "system"
    assert item.severity == "error"
    assert item.dedupe_key == _date_dedupe_key(_now_fixed())
    assert item.evidence["summary_id"] == str(summary.id)


@pytest.mark.asyncio
async def test_generate_daily_summary_clean_path_uses_info_severity(db_session):
    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        summary = await generate_daily_summary(db_session, period_hours=24, now=_now_fixed())

    assert summary.error_count == 0
    assert summary.critical_count == 0
    item = await db_session.get(WorkspaceAttentionItem, summary.attention_item_id)
    assert item.severity == "info"
    assert "clean" in item.title.lower()


@pytest.mark.asyncio
async def test_generate_daily_summary_counts_structured_sources(db_session):
    """trace_events + tool_calls within the window should be counted."""
    period_end = _now_fixed()
    inside = period_end - timedelta(hours=2)
    outside = period_end - timedelta(hours=48)

    db_session.add_all([
        TraceEvent(event_type="error", event_name="boom", created_at=inside),
        TraceEvent(event_type="llm_error", event_name="rate", created_at=inside),
        TraceEvent(event_type="error", event_name="old", created_at=outside),
        ToolCall(
            bot_id="bot-a",
            tool_name="x",
            tool_type="local",
            arguments={},
            status="error",
            error="exploded",
            created_at=inside,
        ),
        ToolCall(
            bot_id="bot-a",
            tool_name="x",
            tool_type="local",
            arguments={},
            status="error",
            error="ancient",
            created_at=outside,
        ),
    ])
    await db_session.commit()

    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        summary = await generate_daily_summary(db_session, period_hours=24, now=period_end)

    assert summary.trace_event_count == 2
    assert summary.tool_error_count == 1


@pytest.mark.asyncio
async def test_dedupe_key_per_day(db_session):
    """Two summaries on different dates produce different attention items."""
    day_one = datetime(2026, 4, 26, 3, 30, tzinfo=timezone.utc)
    day_two = datetime(2026, 4, 27, 3, 30, tzinfo=timezone.utc)
    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        s1 = await generate_daily_summary(db_session, period_hours=24, now=day_one)
        s2 = await generate_daily_summary(db_session, period_hours=24, now=day_two)
    assert s1.attention_item_id != s2.attention_item_id


@pytest.mark.asyncio
async def test_latest_summary_returns_most_recent(db_session):
    older = datetime(2026, 4, 25, 3, 30, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 26, 3, 30, tzinfo=timezone.utc)
    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        await generate_daily_summary(db_session, period_hours=24, now=older)
        new_summary = await generate_daily_summary(db_session, period_hours=24, now=newer)

    most_recent = await latest_summary(db_session)
    assert most_recent is not None
    assert most_recent.id == new_summary.id
