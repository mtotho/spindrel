"""Read-only system-health preflight for agents and operators."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceAttentionItem
from app.services.error_log_parser import LogFinding
from app.services.runtime_identity import runtime_identity
from app.tools.local.get_recent_server_errors import collect_findings

RECENT_ERRORS_SOURCE_ID = "system:recent-server-errors"
RECENT_ERRORS_TARGET_ID = "server-health"


def _finding_to_dict(finding: LogFinding) -> dict[str, Any]:
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


def _resolution_from_item(item: WorkspaceAttentionItem | None) -> dict[str, Any] | None:
    evidence = item.evidence if item else None
    if not isinstance(evidence, dict):
        return None
    resolution = evidence.get("resolution")
    return resolution if isinstance(resolution, dict) else None


def _review_state(finding: LogFinding, attention: WorkspaceAttentionItem | None) -> str:
    if attention is None:
        return "new"
    if attention.status != "resolved":
        return "open"
    resolution = _resolution_from_item(attention) or {}
    kind = str(resolution.get("resolution") or "other")
    if kind == "already_recovered":
        kind = "recovered"
    if attention.resolved_at and finding.last_seen > attention.resolved_at:
        return "stale_resolved_reappeared"
    return f"resolved_{kind}"


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
        .order_by(WorkspaceAttentionItem.last_seen_at.desc())
    )).scalars().all()
    by_key: dict[str, WorkspaceAttentionItem] = {}
    for row in rows:
        if row.dedupe_key and row.dedupe_key not in by_key:
            by_key[row.dedupe_key] = row
    return by_key


def _actionable_review_state(state: str) -> bool:
    return state in {"new", "open", "stale_resolved_reappeared"}


def _recommended_next_action(findings: list[dict[str, Any]], warnings: list[dict[str, str]]) -> str:
    for finding in findings:
        if (
            finding.get("severity") in {"error", "critical"}
            and _actionable_review_state(str(finding.get("review_state") or ""))
        ):
            return "triage_recent_errors"
    if warnings and any(warning.get("code") == "missing_build_sha" for warning in warnings):
        return "no_current_errors"
    return "no_current_errors"


async def build_system_health_preflight(
    db: AsyncSession,
    *,
    since: str = "24h",
    services: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a compact, read-only readiness view for live health triage."""
    capped = max(1, min(int(limit or 50), 500))
    runtime = runtime_identity()
    findings = (await collect_findings(since=since, services=services))[:capped]
    attention = await _attention_by_dedupe_key(db, [f.dedupe_key for f in findings])

    enriched: list[dict[str, Any]] = []
    review_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    for finding in findings:
        row = attention.get(finding.dedupe_key)
        review_state = _review_state(finding, row)
        review_counts[review_state] += 1
        severity_counts[finding.severity] += int(finding.count or 0)
        payload = _finding_to_dict(finding)
        payload["review_state"] = review_state
        payload["attention"] = {
            "id": str(row.id),
            "status": row.status,
            "resolution": _resolution_from_item(row),
        } if row else None
        enriched.append(payload)

    warnings: list[dict[str, str]] = []
    build = runtime.get("build") or {}
    if not build.get("commit_sha"):
        warnings.append({
            "code": "missing_build_sha",
            "message": "Runtime build metadata does not include SPINDREL_BUILD_SHA.",
            "fallback": "Compare behavior through OpenAPI/features and configure deploy stamping when possible.",
        })
    features = runtime.get("features") or {}
    if features.get("recent_errors_review_state") is not True:
        warnings.append({
            "code": "recent_errors_review_state_unavailable",
            "message": "Recent-error review-state overlay is not advertised by this runtime.",
            "fallback": "Do not promote or resolve health findings until the runtime is updated.",
        })

    return {
        "schema_version": "system-health-preflight.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime,
        "window": {
            "since": since,
            "services": list(services or []),
            "limit": capped,
        },
        "recent_errors": {
            "total": len(findings),
            "findings": enriched,
        },
        "review_counts": dict(review_counts),
        "severity_counts": dict(severity_counts),
        "warnings": warnings,
        "recommended_next_action": _recommended_next_action(enriched, warnings),
    }
