"""Daily system-health summary generator + scheduler gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.api_v1_system_health import (
    RECENT_ERRORS_SOURCE_ID,
    RECENT_ERRORS_TARGET_ID,
    PromoteRecentErrorsRequest,
    get_system_health_preflight,
    get_recent_errors,
    promote_recent_errors,
)
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
from app.services.system_health_preflight import build_system_health_preflight
from app.services.workspace_attention import place_attention_item


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
async def test_generate_daily_summary_counts_agent_quality_findings(db_session):
    period_end = _now_fixed()
    inside = period_end - timedelta(hours=2)

    db_session.add(TraceEvent(
        event_type="agent_quality_audit",
        created_at=inside,
        data={
            "audit_version": 1,
            "findings": [
                {"code": "current_inline_image_missed"},
                {"code": "tool_surface_mismatch"},
            ],
        },
    ))
    await db_session.commit()

    with patch(
        "app.tools.local.get_recent_server_errors.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        summary = await generate_daily_summary(db_session, period_hours=24, now=period_end)

    assert summary.source_counts["agent_quality"] == 2
    quality = next(f for f in summary.findings if f["service"] == "agent_quality")
    assert quality["count"] == 2
    assert "current_inline_image_missed" in quality["sample"]


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


@pytest.mark.asyncio
async def test_recent_errors_api_includes_matching_attention_state(db_session):
    finding = _make_finding(service="agent-server", count=2, severity="error", title="Boom")
    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Boom",
        severity="error",
        dedupe_key=finding.dedupe_key,
    )

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[finding]),
    ):
        payload = await get_recent_errors(
            since="2h",
            services=["agent-server"],
            limit=10,
            include_attention=True,
            auth=None,
            db=db_session,
        )

    assert payload["since"] == "2h"
    assert payload["total"] == 1
    assert payload["findings"][0]["dedupe_key"] == finding.dedupe_key
    assert payload["findings"][0]["attention"]["id"] == str(item.id)
    assert payload["findings"][0]["attention"]["status"] == "open"
    assert payload["findings"][0]["review_state"] == "open"


@pytest.mark.asyncio
async def test_system_health_preflight_no_findings_warns_on_unstamped_build(db_session):
    with patch(
        "app.services.system_health_preflight.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        payload = await build_system_health_preflight(
            db_session,
            since="2h",
            services=["agent-server"],
            limit=10,
        )

    assert payload["schema_version"] == "system-health-preflight.v1"
    assert payload["window"] == {
        "since": "2h",
        "services": ["agent-server"],
        "limit": 10,
    }
    assert payload["recent_errors"] == {"total": 0, "findings": []}
    assert payload["review_counts"] == {}
    assert payload["recommended_next_action"] == "no_current_errors"
    assert any(warning["code"] == "missing_build_sha" for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_system_health_preflight_recommends_triage_for_open_errors(db_session):
    finding = _make_finding(service="agent-server", count=2, severity="error", title="Boom")
    await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Boom",
        severity="error",
        dedupe_key=finding.dedupe_key,
    )

    with patch(
        "app.services.system_health_preflight.collect_findings",
        new=AsyncMock(return_value=[finding]),
    ):
        payload = await build_system_health_preflight(db_session, since="24h")

    assert payload["review_counts"] == {"open": 1}
    assert payload["severity_counts"] == {"error": 2}
    assert payload["recent_errors"]["findings"][0]["review_state"] == "open"
    assert payload["recommended_next_action"] == "triage_recent_errors"


@pytest.mark.asyncio
async def test_system_health_preflight_ignores_resolved_duplicates_for_action(db_session):
    root = _make_finding(service="agent-server", count=2, severity="error", title="Root")
    duplicate = _make_finding(service="agent-server", count=2, severity="error", title="Wrapper")
    duplicate.dedupe_key = "log-agent-server-wrapper"
    root_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Root",
        severity="error",
        dedupe_key=root.dedupe_key,
    )
    duplicate_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Wrapper",
        severity="error",
        dedupe_key=duplicate.dedupe_key,
    )
    from app.services.workspace_attention import resolve_attention_item

    await resolve_attention_item(
        db_session,
        root_item.id,
        resolved_by="api_key:ops",
        resolution="duplicate",
        duplicate_of=duplicate_item.id,
        note="Covered elsewhere.",
    )
    await resolve_attention_item(
        db_session,
        duplicate_item.id,
        resolved_by="api_key:ops",
        resolution="duplicate",
        duplicate_of=root_item.id,
        note="Covered by root.",
    )

    with patch(
        "app.services.system_health_preflight.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        payload = await build_system_health_preflight(db_session, since="24h")

    assert payload["review_counts"] == {"resolved_duplicate": 2}
    assert payload["recommended_next_action"] == "no_current_errors"


@pytest.mark.asyncio
async def test_system_health_preflight_route_returns_payload(db_session):
    with patch(
        "app.services.system_health_preflight.collect_findings",
        new=AsyncMock(return_value=[]),
    ):
        payload = await get_system_health_preflight(
            since="2h",
            services=["agent-server"],
            limit=20,
            auth=None,
            db=db_session,
        )

    assert payload["schema_version"] == "system-health-preflight.v1"
    assert payload["window"]["services"] == ["agent-server"]


@pytest.mark.asyncio
async def test_recent_errors_promote_defaults_to_error_and_critical(db_session):
    warning = _make_finding(service="agent-server", count=1, severity="warning", title="Warn")
    error = _make_finding(service="agent-server", count=3, severity="error", title="Err")
    critical = _make_finding(service="postgres", count=1, severity="critical", title="Crit")
    warning.dedupe_key = "log-agent-server-sig-warning"
    critical.dedupe_key = "log-postgres-sig-critical"

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[warning, error, critical]),
    ):
        payload = await promote_recent_errors(
            PromoteRecentErrorsRequest(since="24h"),
            auth=None,
            db=db_session,
        )

    promoted_keys = {
        item["attention"]["dedupe_key"]
        for item in payload["promoted"]
    }
    assert payload["selected"] == 2
    assert warning.dedupe_key not in promoted_keys
    assert promoted_keys == {error.dedupe_key, critical.dedupe_key}
    assert all(
        item["attention"]["evidence"]["kind"] == "recent_server_error"
        for item in payload["promoted"]
    )


@pytest.mark.asyncio
async def test_recent_errors_marks_resolved_duplicates_and_promote_skips_by_default(db_session):
    root = _make_finding(service="agent-server", count=2, severity="error", title="Root")
    duplicate = _make_finding(service="agent-server", count=2, severity="error", title="Wrapper")
    duplicate.dedupe_key = "log-agent-server-wrapper"
    root_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Root",
        severity="error",
        dedupe_key=root.dedupe_key,
    )
    duplicate_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title="Wrapper",
        severity="error",
        dedupe_key=duplicate.dedupe_key,
    )
    from app.services.workspace_attention import resolve_attention_item

    await resolve_attention_item(
        db_session,
        duplicate_item.id,
        resolved_by="api_key:ops",
        resolution="duplicate",
        duplicate_of=root_item.id,
        note="Covered by the root finding.",
    )

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        payload = await get_recent_errors(
            since="30m",
            services=None,
            limit=10,
            include_attention=True,
            auth=None,
            db=db_session,
        )

    by_key = {finding["dedupe_key"]: finding for finding in payload["findings"]}
    assert by_key[root.dedupe_key]["review_state"] == "open"
    assert by_key[duplicate.dedupe_key]["review_state"] == "resolved_duplicate"
    assert by_key[duplicate.dedupe_key]["attention"]["duplicate_of"] == str(root_item.id)
    assert by_key[duplicate.dedupe_key]["attention"]["note"] == "Covered by the root finding."

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        compact_payload = await get_recent_errors(
            since="30m",
            services=None,
            limit=10,
            include_attention=False,
            auth=None,
            db=db_session,
        )

    compact_by_key = {finding["dedupe_key"]: finding for finding in compact_payload["findings"]}
    assert compact_by_key[duplicate.dedupe_key]["review_state"] == "resolved_duplicate"
    assert compact_by_key[duplicate.dedupe_key]["attention"] is None

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        duplicate_only = await get_recent_errors(
            since="30m",
            services=None,
            limit=10,
            include_attention=True,
            review_state=["resolved_duplicate"],
            auth=None,
            db=db_session,
        )
    assert [finding["dedupe_key"] for finding in duplicate_only["findings"]] == [
        duplicate.dedupe_key
    ]

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        without_duplicates = await get_recent_errors(
            since="30m",
            services=None,
            limit=10,
            include_attention=True,
            exclude_review_state=["resolved_duplicate"],
            auth=None,
            db=db_session,
        )
    assert [finding["dedupe_key"] for finding in without_duplicates["findings"]] == [
        root.dedupe_key
    ]

    with patch(
        "app.routers.api_v1_system_health.collect_findings",
        new=AsyncMock(return_value=[root, duplicate]),
    ):
        promoted = await promote_recent_errors(
            PromoteRecentErrorsRequest(since="30m", min_severity="error"),
            auth=None,
            db=db_session,
        )

    promoted_keys = {row["finding"]["dedupe_key"] for row in promoted["promoted"]}
    assert promoted_keys == {root.dedupe_key}
    assert promoted["skipped"][0]["dedupe_key"] == duplicate.dedupe_key
    assert promoted["skipped"][0]["reason"] == "resolved_duplicate"
