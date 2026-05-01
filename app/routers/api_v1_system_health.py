"""System Health API.

Daily-summary and on-demand live-health surfaces for agents and operators.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SystemHealthSummary, WorkspaceAttentionItem
from app.dependencies import get_db, require_scopes
from app.domain.errors import ValidationError
from app.services.error_log_parser import LogFinding
from app.services.runtime_identity import runtime_identity
from app.services.system_health_preflight import build_system_health_preflight
from app.services.workspace_attention import place_attention_item, serialize_attention_item
from app.tools.local.get_recent_server_errors import collect_findings


router = APIRouter(prefix="/system-health", tags=["system-health"])

RECENT_ERRORS_SOURCE_ID = "system:recent-server-errors"
RECENT_ERRORS_TARGET_ID = "server-health"
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}
VALID_PROMOTE_SEVERITIES = set(SEVERITY_RANK)
KNOWN_REVIEW_STATES = {
    "new",
    "open",
    "resolved_benign",
    "resolved_duplicate",
    "resolved_external",
    "resolved_fixed",
    "resolved_not_reproducible",
    "resolved_other",
    "resolved_recovered",
    "resolved_stale",
    "stale_resolved_reappeared",
}


class PromoteRecentErrorsRequest(BaseModel):
    since: str = "24h"
    services: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=500)
    min_severity: str = "error"
    dedupe_keys: list[str] | None = None
    include_resolved: bool = False


@router.get("/runtime")
async def get_runtime_identity(
    auth=Depends(require_scopes("channels:read")),
):
    return runtime_identity()


@router.get("/preflight")
async def get_system_health_preflight(
    since: str = "24h",
    services: list[str] | None = Query(default=None),
    limit: int = 50,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await build_system_health_preflight(
        db,
        since=since,
        services=_normalize_services(services),
        limit=limit,
    )


def _serialize(row: SystemHealthSummary, *, include_findings: bool = True) -> dict:
    return {
        "id": str(row.id),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "error_count": int(row.error_count or 0),
        "critical_count": int(row.critical_count or 0),
        "trace_event_count": int(row.trace_event_count or 0),
        "tool_error_count": int(row.tool_error_count or 0),
        "source_counts": row.source_counts or {},
        "findings": list(row.findings or []) if include_findings else [],
        "attention_item_id": str(row.attention_item_id) if row.attention_item_id else None,
        "attention_item_refs": list(row.attention_item_refs or []),
    }


def _finding_to_dict(finding: LogFinding) -> dict:
    return {
        "service": finding.service,
        "severity": finding.severity,
        "signature": finding.signature,
        "dedupe_key": finding.dedupe_key,
        "title": finding.title,
        "sample": finding.sample,
        "first_seen": finding.first_seen.isoformat(),
        "last_seen": finding.last_seen.isoformat(),
        "count": finding.count,
        "kind": finding.extra.get("kind"),
    }


def _normalize_csv_values(values, *, lower: bool = False) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, (list, tuple, set)):
        raw_values = values
    else:
        return None
    services: list[str] = []
    for value in raw_values:
        parts = [part.strip() for part in str(value).split(",") if part.strip()]
        services.extend(part.lower() if lower else part for part in parts)
    return services or None


def _normalize_services(values: list[str] | None) -> list[str] | None:
    return _normalize_csv_values(values)


def _normalize_review_states(values) -> set[str]:
    states = set(_normalize_csv_values(values, lower=True) or [])
    unknown = states - KNOWN_REVIEW_STATES
    if unknown:
        raise HTTPException(
            400,
            f"unknown review_state value(s): {sorted(unknown)}; "
            f"expected one of {sorted(KNOWN_REVIEW_STATES)}",
        )
    return states


def _severity_at_least(severity: str | None, minimum: str) -> bool:
    return SEVERITY_RANK.get(severity or "warning", 1) >= SEVERITY_RANK[minimum]


def _resolution_from_item(item: WorkspaceAttentionItem | None) -> dict | None:
    evidence = item.evidence if item else None
    resolution = evidence.get("resolution") if isinstance(evidence, dict) else None
    return resolution if isinstance(resolution, dict) else None


def _review_state(finding: LogFinding, attention: WorkspaceAttentionItem | None) -> str:
    if attention is None:
        return "new"
    if attention.status != "resolved":
        return "open"
    resolution = _resolution_from_item(attention) or {}
    resolution_value = str(resolution.get("resolution") or "other")
    if resolution_value == "duplicate":
        return "resolved_duplicate"
    if attention.resolved_at and finding.last_seen > attention.resolved_at:
        return "stale_resolved_reappeared"
    if resolution_value == "already_recovered":
        return "resolved_recovered"
    return f"resolved_{resolution_value}"


async def _attention_by_dedupe_key(
    db: AsyncSession,
    dedupe_keys: list[str],
) -> dict[str, WorkspaceAttentionItem]:
    if not dedupe_keys:
        return {}
    rows = (await db.execute(
        select(WorkspaceAttentionItem)
        .where(
            WorkspaceAttentionItem.source_type == "system",
            WorkspaceAttentionItem.source_id == RECENT_ERRORS_SOURCE_ID,
            WorkspaceAttentionItem.target_kind == "system",
            WorkspaceAttentionItem.target_id == RECENT_ERRORS_TARGET_ID,
            WorkspaceAttentionItem.dedupe_key.in_(dedupe_keys),
        )
        .order_by(desc(WorkspaceAttentionItem.last_seen_at))
    )).scalars().all()
    out: dict[str, WorkspaceAttentionItem] = {}
    for row in rows:
        out.setdefault(row.dedupe_key, row)
    return out


async def _serialize_finding_with_attention(
    db: AsyncSession,
    finding: LogFinding,
    attention: WorkspaceAttentionItem | None,
    *,
    include_attention_details: bool = True,
) -> dict:
    data = _finding_to_dict(finding)
    if not include_attention_details or attention is None:
        data["attention"] = None
    else:
        serialized = await serialize_attention_item(db, attention)
        resolution = _resolution_from_item(attention)
        data["attention"] = {
            "id": serialized["id"],
            "status": serialized["status"],
            "severity": serialized["severity"],
            "title": serialized["title"],
            "resolved_at": serialized["resolved_at"],
            "resolution": resolution.get("resolution") if resolution else None,
            "note": resolution.get("note") if resolution else None,
            "duplicate_of": resolution.get("duplicate_of") if resolution else None,
        }
    data["review_state"] = _review_state(finding, attention)
    return data


def _recent_error_message(finding: LogFinding) -> str:
    sample = (finding.sample or "").strip()
    count = int(finding.count or 0)
    return (
        f"{finding.service} reported {finding.severity} {count} time(s) "
        f"for signature {finding.signature}.\n\nSample: {sample}"
    )[:1200]


async def _promote_finding(
    db: AsyncSession,
    *,
    finding: LogFinding,
    since: str,
) -> WorkspaceAttentionItem:
    data = _finding_to_dict(finding)
    return await place_attention_item(
        db,
        source_type="system",
        source_id=RECENT_ERRORS_SOURCE_ID,
        channel_id=None,
        target_kind="system",
        target_id=RECENT_ERRORS_TARGET_ID,
        title=finding.title or f"{finding.service}: {finding.signature}",
        message=_recent_error_message(finding),
        severity=finding.severity if finding.severity in VALID_PROMOTE_SEVERITIES else "warning",
        requires_response=finding.severity in {"error", "critical"},
        next_steps=[
            "Classify the finding as benign, duplicate, recovered, external, likely code bug, or unknown.",
            "Resolve only when evidence is clear; keep likely code bugs open with a code/test recommendation.",
        ],
        dedupe_key=finding.dedupe_key,
        evidence={
            "kind": "recent_server_error",
            "source": "system-health/recent-errors",
            "since": since,
            "finding": data,
        },
        source_event_key=f"{finding.service}:{finding.dedupe_key}:{finding.last_seen.isoformat()}",
    )


@router.get("/summaries/latest")
async def get_latest_summary(
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(SystemHealthSummary).order_by(desc(SystemHealthSummary.generated_at)).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"summary": None, "message": "No daily summary has been generated yet."}
    return {"summary": _serialize(row)}


@router.get("/summaries")
async def list_summaries(
    limit: int = 14,
    include_findings: bool = False,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    capped = max(1, min(int(limit or 14), 60))
    rows = (await db.execute(
        select(SystemHealthSummary)
        .order_by(desc(SystemHealthSummary.generated_at))
        .limit(capped)
    )).scalars().all()
    return {"summaries": [_serialize(r, include_findings=include_findings) for r in rows]}


@router.get("/summaries/{summary_id}")
async def get_summary(
    summary_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SystemHealthSummary, summary_id)
    if row is None:
        raise HTTPException(404, "summary not found")
    return {"summary": _serialize(row)}


@router.get("/recent-errors")
async def get_recent_errors(
    since: str = "24h",
    services: list[str] | None = Query(default=None),
    limit: int = 50,
    include_attention: bool = True,
    include_resolved: bool = True,
    hide_resolved_duplicates: bool = False,
    review_state: list[str] | None = Query(default=None),
    exclude_review_state: list[str] | None = Query(default=None),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    capped = max(1, min(int(limit or 50), 500))
    findings = await collect_findings(
        since=since,
        services=_normalize_services(services),
    )
    total = len(findings)
    findings = findings[:capped]
    attention = await _attention_by_dedupe_key(db, [f.dedupe_key for f in findings])
    if not include_resolved:
        findings = [
            f
            for f in findings
            if attention.get(f.dedupe_key) is None
            or attention[f.dedupe_key].status != "resolved"
        ]
    if hide_resolved_duplicates:
        findings = [
            f
            for f in findings
            if _review_state(f, attention.get(f.dedupe_key)) != "resolved_duplicate"
        ]
    wanted_review_states = _normalize_review_states(review_state)
    excluded_review_states = _normalize_review_states(exclude_review_state)
    if wanted_review_states or excluded_review_states:
        findings = [
            f
            for f in findings
            if (
                not wanted_review_states
                or _review_state(f, attention.get(f.dedupe_key)) in wanted_review_states
            )
            and _review_state(f, attention.get(f.dedupe_key)) not in excluded_review_states
        ]
    return {
        "since": since,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "findings": [
            await _serialize_finding_with_attention(
                db,
                f,
                attention.get(f.dedupe_key),
                include_attention_details=include_attention,
            )
            for f in findings
        ],
    }


@router.post("/recent-errors/promote")
async def promote_recent_errors(
    body: PromoteRecentErrorsRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    min_severity = (body.min_severity or "error").strip().lower()
    if min_severity not in SEVERITY_RANK:
        raise HTTPException(400, f"min_severity must be one of {sorted(SEVERITY_RANK)}")
    wanted_keys = set(body.dedupe_keys or [])
    findings = await collect_findings(
        since=body.since,
        services=_normalize_services(body.services),
    )
    attention = await _attention_by_dedupe_key(db, [f.dedupe_key for f in findings])
    selected: list[LogFinding] = []
    skipped: list[dict] = []
    for finding in findings:
        if not _severity_at_least(finding.severity, min_severity):
            continue
        if wanted_keys and finding.dedupe_key not in wanted_keys:
            continue
        review_state = _review_state(finding, attention.get(finding.dedupe_key))
        if (
            not body.include_resolved
            and finding.dedupe_key not in wanted_keys
            and review_state == "resolved_duplicate"
        ):
            skipped.append({
                "dedupe_key": finding.dedupe_key,
                "reason": review_state,
                "title": finding.title,
            })
            continue
        selected.append(finding)
        if len(selected) >= body.limit:
            break
    promoted: list[dict] = []
    for finding in selected:
        try:
            item = await _promote_finding(db, finding=finding, since=body.since)
        except ValidationError as e:
            raise HTTPException(400, str(e)) from e
        promoted.append({
            "finding": _finding_to_dict(finding),
            "attention": await serialize_attention_item(db, item),
        })
    return {
        "since": body.since,
        "min_severity": min_severity,
        "selected": len(selected),
        "skipped": skipped,
        "promoted": promoted,
    }
