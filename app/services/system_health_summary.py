"""Daily system-health summary generator.

Runs deterministically from ``task_worker`` once per day. Aggregates:

- Unstructured stderr/JSONL findings via ``error_log_parser`` (durable log
  file for the app, ``docker logs`` for sibling containers).
- Structured ``trace_event`` rows where ``event_type in ('error', 'llm_error')``.
- Failed ``tool_call`` rows.
- Cross-references ``workspace_attention_items`` opened in the period via
  matching ``_error_signature``.

Persists one ``SystemHealthSummary`` row plus a single rollup
``WorkspaceAttentionItem`` so the canvas landmark has a stable target
to point at.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import (
    SystemHealthSummary,
    ToolCall,
    TraceEvent,
    WorkspaceAttentionItem,
)
from app.services.agent_quality_audit import AGENT_QUALITY_AUDIT_EVENT
from app.services.error_log_parser import LogFinding
from app.services.workspace_attention import (
    STRUCTURED_ERROR_DETECTOR_ID,
    derive_dedupe_key,
    place_attention_item,
)

logger = logging.getLogger(__name__)

DAILY_SUMMARY_SOURCE_ID = "system:daily-health-summary"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _date_dedupe_key(generated_at: datetime) -> str:
    return derive_dedupe_key(
        "daily-health-summary",
        generated_at.date().isoformat(),
    )


def _finding_payload(f: LogFinding) -> dict:
    return {
        "service": f.service,
        "severity": f.severity,
        "signature": f.signature,
        "dedupe_key": f.dedupe_key,
        "title": f.title,
        "sample": f.sample,
        "first_seen": f.first_seen.isoformat(),
        "last_seen": f.last_seen.isoformat(),
        "count": f.count,
        "kind": f.extra.get("kind"),
    }


async def _count_trace_errors(db: AsyncSession, *, since: datetime) -> int:
    row = (await db.execute(
        select(func.count(TraceEvent.id)).where(
            TraceEvent.created_at >= since,
            TraceEvent.event_type.in_(("error", "llm_error")),
        )
    )).scalar()
    return int(row or 0)


async def _count_tool_errors(db: AsyncSession, *, since: datetime) -> int:
    row = (await db.execute(
        select(func.count(ToolCall.id)).where(
            ToolCall.created_at >= since,
            or_(ToolCall.status == "error", ToolCall.error.isnot(None)),
        )
    )).scalar()
    return int(row or 0)


async def _agent_quality_counts(db: AsyncSession, *, since: datetime) -> tuple[int, dict[str, int]]:
    rows = (await db.execute(
        select(TraceEvent.data).where(
            TraceEvent.created_at >= since,
            TraceEvent.event_type == AGENT_QUALITY_AUDIT_EVENT,
        )
    )).scalars().all()
    total = 0
    by_code: dict[str, int] = {}
    for data in rows:
        if not isinstance(data, dict):
            continue
        findings = data.get("findings") or []
        if not isinstance(findings, list):
            continue
        total += len(findings)
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            code = str(finding.get("code") or "unknown")
            by_code[code] = by_code.get(code, 0) + 1
    return total, by_code


def _quality_finding_payload(
    *,
    count: int,
    by_code: dict[str, int],
    period_start: datetime,
    period_end: datetime,
) -> dict:
    sample = ", ".join(f"{code}: {n}" for code, n in sorted(by_code.items())) or "agent quality findings"
    return {
        "service": "agent_quality",
        "severity": "warning",
        "signature": "agent_quality_findings",
        "dedupe_key": f"agent-quality:{period_end.date().isoformat()}",
        "title": f"{count} agent quality finding(s)",
        "sample": sample,
        "first_seen": period_start.isoformat(),
        "last_seen": period_end.isoformat(),
        "count": count,
        "kind": "agent_quality",
    }


async def _matching_attention_item_ids(
    db: AsyncSession,
    *,
    findings: list[LogFinding],
    since: datetime,
) -> list[uuid.UUID]:
    """Find recent attention items whose signature appears in our findings.

    The 60s structured detector keys items off (target, source, signature);
    sharing ``_error_signature`` means a log-derived signature can
    intersect a tool/trace-derived dedupe key by substring. We do a coarse
    LIKE match instead of trying to recompute every shape exactly.
    """
    if not findings:
        return []
    seen_seeds: list[str] = sorted({f.signature for f in findings if f.signature})[:50]
    if not seen_seeds:
        return []
    rows = (await db.execute(
        select(WorkspaceAttentionItem.id, WorkspaceAttentionItem.dedupe_key).where(
            WorkspaceAttentionItem.last_seen_at >= since,
        )
    )).all()
    matches: list[uuid.UUID] = []
    for item_id, key in rows:
        if not key:
            continue
        for seed in seen_seeds:
            if seed and seed in key:
                matches.append(item_id)
                break
    return matches


def _summary_title(error_count: int, critical_count: int, services: int) -> str:
    if error_count == 0 and critical_count == 0:
        return "Daily summary — clean"
    return f"Daily summary — {error_count} errors across {services} services"


async def generate_daily_summary(
    db: AsyncSession | None = None,
    *,
    period_hours: int = 24,
    now: datetime | None = None,
) -> SystemHealthSummary:
    """Generate one ``SystemHealthSummary`` row + rollup attention item.

    ``db`` is optional; when ``None`` we open our own session. The caller
    in ``task_worker`` passes ``None`` so we own the transaction.
    """
    own_session = db is None
    session_cm = async_session() if own_session else _NullCtx(db)
    async with session_cm as session:
        from app.tools.local.get_recent_server_errors import collect_findings

        period_end = now or _now()
        period_start = period_end - timedelta(hours=period_hours)

        findings = await collect_findings(since=f"{period_hours}h")

        error_count = sum(f.count for f in findings)
        critical_count = sum(f.count for f in findings if f.severity == "critical")
        services_set = {f.service for f in findings}
        source_counts: dict[str, int] = {}
        for f in findings:
            source_counts[f.service] = source_counts.get(f.service, 0) + f.count

        trace_event_count = await _count_trace_errors(session, since=period_start)
        tool_error_count = await _count_tool_errors(session, since=period_start)
        quality_count, quality_by_code = await _agent_quality_counts(session, since=period_start)
        if quality_count:
            source_counts["agent_quality"] = quality_count
        attention_refs = await _matching_attention_item_ids(
            session, findings=findings, since=period_start,
        )
        finding_payloads = [_finding_payload(f) for f in findings[:200]]
        if quality_count:
            finding_payloads.append(_quality_finding_payload(
                count=quality_count,
                by_code=quality_by_code,
                period_start=period_start,
                period_end=period_end,
            ))

        summary = SystemHealthSummary(
            period_start=period_start,
            period_end=period_end,
            generated_at=period_end,
            error_count=error_count,
            critical_count=critical_count,
            findings=finding_payloads,
            source_counts=source_counts,
            attention_item_refs=[str(i) for i in attention_refs],
            trace_event_count=trace_event_count,
            tool_error_count=tool_error_count,
        )
        session.add(summary)
        await session.flush()

        attention_severity = "info" if critical_count == 0 and error_count == 0 else (
            "warning" if critical_count == 0 else "error"
        )
        item = await place_attention_item(
            session,
            source_type="system",
            source_id=DAILY_SUMMARY_SOURCE_ID,
            channel_id=None,
            target_kind="system",
            target_id="daily-health-summary",
            title=_summary_title(error_count, critical_count, len(services_set)),
            message=(
                f"Period {period_start.isoformat()} → {period_end.isoformat()}. "
                f"{error_count} errors, {critical_count} critical, "
                f"{trace_event_count} trace_event errors, {tool_error_count} tool errors, "
                f"{quality_count} quality findings."
            )[:1000],
            severity=attention_severity,
            dedupe_key=_date_dedupe_key(period_end),
            evidence={
                "kind": "daily_health_summary",
                "summary_id": str(summary.id),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "error_count": error_count,
                "critical_count": critical_count,
                "services": sorted(services_set),
                "agent_quality_findings": quality_count,
            },
            source_event_key=f"daily-health-summary:{period_end.date().isoformat()}",
        )
        summary.attention_item_id = item.id
        await session.commit()
        await session.refresh(summary)
        logger.info(
            "system_health_summary: generated %s for %s — %d errors (%d critical), %d services",
            summary.id, period_end.date().isoformat(),
            error_count, critical_count, len(services_set),
        )
        return summary


class _NullCtx:
    """Minimal async-context wrapper so ``async with`` works on a passed-in session."""
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


# ---------------------------------------------------------------------------
# Scheduler hook
# ---------------------------------------------------------------------------

async def latest_summary(db: AsyncSession) -> SystemHealthSummary | None:
    return (await db.execute(
        select(SystemHealthSummary).order_by(desc(SystemHealthSummary.generated_at)).limit(1)
    )).scalar_one_or_none()


async def maybe_run_daily_summary(*, run_hour_utc: int = 3, run_minute_utc: int = 15) -> bool:
    """Run a daily summary at most once per UTC date.

    Called from ``task_worker`` every 5s. Returns True if it ran. Cheap when
    the last summary's date matches today's date — one ``SELECT ORDER BY
    DESC LIMIT 1``.
    """
    now = _now()
    if now.hour < run_hour_utc:
        return False
    if now.hour == run_hour_utc and now.minute < run_minute_utc:
        return False
    async with async_session() as db:
        latest = await latest_summary(db)
        if latest is not None and latest.generated_at.date() == now.date():
            return False
    try:
        await generate_daily_summary()
        return True
    except Exception:
        logger.exception("system_health_summary: daily run failed")
        return False
