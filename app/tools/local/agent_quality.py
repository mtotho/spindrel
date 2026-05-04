"""Local diagnostics for deterministic agent quality audits."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Channel, Message, Session, TurnFeedback
from app.services.agent_quality_audit import (
    AGENT_QUALITY_AUDIT_VERSION,
    audit_turn_quality,
)
from app.tools.registry import register


def _serialize_feedback_row(row: TurnFeedback) -> dict:
    """Tool-facing shape for one ``turn_feedback`` row.

    Comments ARE included here — these tools are admin/auditor-scoped
    surfaces, unlike the per-message trace events which intentionally
    omit comment text to keep PII out of the trace store.
    """
    return {
        "vote": row.vote,
        "comment": row.comment,
        "source_integration": row.source_integration,
        "source_user_ref": row.source_user_ref,
        "anonymous": row.user_id is None,
        "user_id": str(row.user_id) if row.user_id else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _fetch_feedback_by_correlation(
    db: AsyncSession, correlation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict]]:
    if not correlation_ids:
        return {}
    rows = (await db.execute(
        select(TurnFeedback)
        .where(TurnFeedback.correlation_id.in_(correlation_ids))
        .order_by(TurnFeedback.created_at)
    )).scalars().all()
    out: dict[uuid.UUID, list[dict]] = {}
    for row in rows:
        out.setdefault(row.correlation_id, []).append(_serialize_feedback_row(row))
    return out


@register({
    "type": "function",
    "function": {
        "name": "audit_trace_quality",
        "description": (
            "Run the deterministic post-turn quality auditor for one trace or a recent batch. "
            "Writes idempotent agent_quality_audit TraceEvent rows and returns findings, plus "
            "any user_feedback rows (thumbs-up/down votes with comment text) keyed to the same "
            "correlation_id. Use for admin diagnostics, scheduled quality review, and "
            "re-auditing old traces — user_feedback should outweigh deterministic findings when both fire."
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
        "user_feedback_count": {"type": "integer"},
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

        feedback_by_cid = await _fetch_feedback_by_correlation(db, ids)
        results = []
        finding_count = 0
        feedback_total = 0
        for cid in ids:
            payload = await audit_turn_quality(db, cid, persist=persist)
            findings = payload.get("findings") or []
            finding_count += len(findings)
            user_feedback = feedback_by_cid.get(cid, [])
            feedback_total += len(user_feedback)
            results.append({
                "correlation_id": str(cid),
                "finding_count": len(findings),
                "findings": findings,
                "features": payload.get("features") or {},
                "user_feedback": user_feedback,
            })

        return json.dumps({
            "audit_version": AGENT_QUALITY_AUDIT_VERSION,
            "audited_count": len(results),
            "finding_count": finding_count,
            "user_feedback_count": feedback_total,
            "results": results,
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# list_user_feedback — discovery entry point for the audit agent
# ---------------------------------------------------------------------------


_EXCERPT_LEN = 240


@register({
    "type": "function",
    "function": {
        "name": "list_user_feedback",
        "description": (
            "List recent user-explicit thumbs-up/down votes on assistant turns, "
            "newest first. Each row carries the vote, the user's comment (if any), "
            "and a short anchor-message excerpt + bot/channel context so the auditor "
            "can decide which correlation_ids to drill into via audit_trace_quality. "
            "Use this as the entry point when triaging quality issues — "
            "vote=down with a comment is the highest-signal starting place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vote": {
                    "type": ["string", "null"],
                    "enum": ["up", "down", None],
                    "description": "Filter to one direction. Default: both.",
                },
                "since_hours": {
                    "type": "integer",
                    "description": "Look-back window in hours. Default 24, max 720 (~30d).",
                },
                "bot_id": {
                    "type": ["string", "null"],
                    "description": "Restrict to feedback on turns served by one bot.",
                },
                "channel_id": {
                    "type": ["string", "null"],
                    "description": "Restrict to one channel UUID.",
                },
                "correlation_id": {
                    "type": ["string", "null"],
                    "description": (
                        "Return all votes for one specific turn — bypasses the "
                        "since_hours window."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return. Default 50, max 500.",
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "row_count": {"type": "integer"},
        "rows": {"type": "array"},
    },
})
async def list_user_feedback(
    vote: str | None = None,
    since_hours: int = 24,
    bot_id: str | None = None,
    channel_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 50,
    **_: object,
) -> str:
    if vote is not None and vote not in ("up", "down"):
        return json.dumps({"error": "vote must be 'up' or 'down' or null"})
    limit = max(1, min(int(limit or 50), 500))
    since_hours = max(1, min(int(since_hours or 24), 720))

    ch_uuid: uuid.UUID | None = None
    if channel_id:
        try:
            ch_uuid = uuid.UUID(str(channel_id))
        except ValueError:
            return json.dumps({"error": f"invalid channel_id: {channel_id}"})
    cid_uuid: uuid.UUID | None = None
    if correlation_id:
        try:
            cid_uuid = uuid.UUID(str(correlation_id))
        except ValueError:
            return json.dumps({"error": f"invalid correlation_id: {correlation_id}"})

    async with async_session() as db:
        stmt = select(TurnFeedback).order_by(desc(TurnFeedback.created_at)).limit(limit)
        if cid_uuid is not None:
            stmt = stmt.where(TurnFeedback.correlation_id == cid_uuid)
        else:
            since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            stmt = stmt.where(TurnFeedback.created_at >= since)
        if vote is not None:
            stmt = stmt.where(TurnFeedback.vote == vote)
        if ch_uuid is not None:
            stmt = stmt.where(TurnFeedback.channel_id == ch_uuid)

        rows = (await db.execute(stmt)).scalars().all()

        # Bot filter requires the session join — apply post-query if requested.
        # Cheaper than a SQL join here because the result set is already capped.
        session_ids = {r.session_id for r in rows}
        sessions: dict[uuid.UUID, Session] = {}
        if session_ids:
            session_rows = (await db.execute(
                select(Session).where(Session.id.in_(session_ids))
            )).scalars().all()
            sessions = {s.id: s for s in session_rows}

        if bot_id:
            rows = [r for r in rows if (sessions.get(r.session_id) and sessions[r.session_id].bot_id == bot_id)]

        # Channel name lookup for context.
        channel_ids = {r.channel_id for r in rows}
        channels: dict[uuid.UUID, Channel] = {}
        if channel_ids:
            ch_rows = (await db.execute(
                select(Channel).where(Channel.id.in_(channel_ids))
            )).scalars().all()
            channels = {c.id: c for c in ch_rows}

        # Anchor excerpt per correlation_id (last user-visible assistant text).
        cids = list({r.correlation_id for r in rows})
        excerpts: dict[uuid.UUID, str] = {}
        if cids:
            anchor_rows = (await db.execute(
                select(Message)
                .where(
                    Message.correlation_id.in_(cids),
                    Message.role == "assistant",
                    Message.content.isnot(None),
                    Message.tool_call_id.is_(None),
                )
                .order_by(desc(Message.created_at))
            )).scalars().all()
            for m in anchor_rows:
                if m.correlation_id in excerpts:
                    continue
                if isinstance(m.tool_calls, list) and len(m.tool_calls) > 0:
                    continue
                content = (m.content or "").strip().replace("\n", " ")
                excerpts[m.correlation_id] = content[:_EXCERPT_LEN]

        out_rows = []
        for r in rows:
            session = sessions.get(r.session_id)
            channel = channels.get(r.channel_id)
            out_rows.append({
                "correlation_id": str(r.correlation_id),
                "channel_id": str(r.channel_id),
                "channel_name": channel.name if channel else None,
                "session_id": str(r.session_id),
                "bot_id": session.bot_id if session else None,
                "vote": r.vote,
                "comment": r.comment,
                "source_integration": r.source_integration,
                "source_user_ref": r.source_user_ref,
                "anonymous": r.user_id is None,
                "user_id": str(r.user_id) if r.user_id else None,
                "anchor_excerpt": excerpts.get(r.correlation_id),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })

        return json.dumps({
            "row_count": len(out_rows),
            "rows": out_rows,
        }, ensure_ascii=False)
