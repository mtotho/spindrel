"""Local tool: get_latest_health_summary — read the most recent daily summary.

Companion to ``read_container_logs`` and ``get_recent_server_errors``.
The daily summary is generated deterministically by
``app/services/system_health_summary.py`` — this tool exposes the
persisted row to bots so an opt-in task pipeline can act on it
(file an issue, ping an operator, run remediation) without re-doing
the parsing work itself.
"""
from __future__ import annotations

import json

from sqlalchemy import desc, select

from app.db.engine import async_session
from app.db.models import SystemHealthSummary
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "get_latest_health_summary",
        "description": (
            "Return the most recent daily system-health summary as JSON. "
            "The summary is generated server-side once per day and contains "
            "deduped error findings across all server log sources plus counts "
            "of structured trace_event and tool errors over the same window. "
            "Use this for pipelines/automations that need to act on yesterday's "
            "errors. Returns null fields if no summary has run yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_findings": {
                    "type": "boolean",
                    "description": "If false, omit the findings array (return counts only). Default true.",
                },
                "max_findings": {
                    "type": "integer",
                    "description": "Cap on findings returned (default 50, max 200).",
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "id": {"type": ["string", "null"]},
        "generated_at": {"type": ["string", "null"]},
        "period_start": {"type": ["string", "null"]},
        "period_end": {"type": ["string", "null"]},
        "error_count": {"type": "integer"},
        "critical_count": {"type": "integer"},
        "trace_event_count": {"type": "integer"},
        "tool_error_count": {"type": "integer"},
        "source_counts": {"type": "object"},
        "findings": {"type": "array"},
        "attention_item_id": {"type": ["string", "null"]},
        "message": {"type": "string"},
    },
})
async def get_latest_health_summary(
    include_findings: bool = True,
    max_findings: int = 50,
    **_: object,
) -> str:
    cap = max(1, min(int(max_findings or 50), 200))
    async with async_session() as db:
        row = (await db.execute(
            select(SystemHealthSummary).order_by(desc(SystemHealthSummary.generated_at)).limit(1)
        )).scalar_one_or_none()
        if row is None:
            return json.dumps({
                "id": None,
                "generated_at": None,
                "period_start": None,
                "period_end": None,
                "error_count": 0,
                "critical_count": 0,
                "trace_event_count": 0,
                "tool_error_count": 0,
                "source_counts": {},
                "findings": [],
                "attention_item_id": None,
                "message": "No daily summary has been generated yet.",
            }, ensure_ascii=False)

        findings = list(row.findings or [])[:cap] if include_findings else []
        return json.dumps({
            "id": str(row.id),
            "generated_at": row.generated_at.isoformat(),
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "error_count": int(row.error_count or 0),
            "critical_count": int(row.critical_count or 0),
            "trace_event_count": int(row.trace_event_count or 0),
            "tool_error_count": int(row.tool_error_count or 0),
            "source_counts": row.source_counts or {},
            "findings": findings,
            "attention_item_id": str(row.attention_item_id) if row.attention_item_id else None,
            "message": "ok",
        }, ensure_ascii=False)
