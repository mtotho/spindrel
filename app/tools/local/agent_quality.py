"""Local diagnostics for deterministic agent quality audits."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from app.db.engine import async_session
from app.db.models import Message, Session
from app.services.agent_quality_audit import (
    AGENT_QUALITY_AUDIT_VERSION,
    audit_turn_quality,
)
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "audit_trace_quality",
        "description": (
            "Run the deterministic post-turn quality auditor for one trace or a recent batch. "
            "Writes idempotent agent_quality_audit TraceEvent rows and returns findings. "
            "Use for admin diagnostics, scheduled quality review, and re-auditing old traces."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "correlation_id": {
                    "type": ["string", "null"],
                    "description": "Specific trace correlation_id to audit. If omitted, audits recent assistant turns.",
                },
                "bot_id": {
                    "type": ["string", "null"],
                    "description": "Optional bot filter for batch mode.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Batch size when correlation_id is omitted. Default 25, max 200.",
                },
                "since_hours": {
                    "type": "integer",
                    "description": "Batch window in hours. Default 24, max 168.",
                },
                "persist": {
                    "type": "boolean",
                    "description": "If false, compute findings without writing TraceEvent rows. Default true.",
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "audit_version": {"type": "integer"},
        "audited_count": {"type": "integer"},
        "finding_count": {"type": "integer"},
        "results": {"type": "array"},
    },
})
async def audit_trace_quality(
    correlation_id: str | None = None,
    bot_id: str | None = None,
    limit: int = 25,
    since_hours: int = 24,
    persist: bool = True,
    **_: object,
) -> str:
    limit = max(1, min(int(limit or 25), 200))
    since_hours = max(1, min(int(since_hours or 24), 168))

    async with async_session() as db:
        ids: list[uuid.UUID]
        if correlation_id:
            ids = [uuid.UUID(str(correlation_id))]
        else:
            since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            stmt = (
                select(Message.correlation_id)
                .join(Session, Session.id == Message.session_id)
                .where(Message.role == "assistant")
                .where(Message.correlation_id.is_not(None))
                .where(Message.created_at >= since)
            )
            if bot_id:
                stmt = stmt.where(Session.bot_id == bot_id)
            rows = (await db.execute(
                stmt.order_by(desc(Message.created_at)).limit(limit * 3)
            )).scalars().all()
            seen: set[uuid.UUID] = set()
            ids = []
            for row in rows:
                if row and row not in seen:
                    ids.append(row)
                    seen.add(row)
                if len(ids) >= limit:
                    break

        results = []
        finding_count = 0
        for cid in ids:
            payload = await audit_turn_quality(db, cid, persist=persist)
            findings = payload.get("findings") or []
            finding_count += len(findings)
            results.append({
                "correlation_id": str(cid),
                "finding_count": len(findings),
                "findings": findings,
                "features": payload.get("features") or {},
            })

        return json.dumps({
            "audit_version": AGENT_QUALITY_AUDIT_VERSION,
            "audited_count": len(results),
            "finding_count": finding_count,
            "results": results,
        }, ensure_ascii=False)
