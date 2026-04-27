"""Local tool: get_recent_server_errors — pre-parsed error rollup across sources.

Higher-level companion to ``read_container_logs``. Iterates the allowlist,
runs the shared traceback parser, returns deduped findings keyed by the
same signature the 60s structured-attention detector uses.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.services.error_log_parser import (
    LogFinding,
    merge_findings,
    parse_jsonl_entries,
    parse_text_lines,
)
from app.services.server_log_sources import (
    docker_logs,
    list_allowed_sources,
    read_app_jsonl_lines,
    resolve_source,
)
from app.tools.local.read_container_logs import _parse_since_seconds
from app.tools.registry import register

logger = logging.getLogger(__name__)


async def collect_findings(
    *,
    since: str = "24h",
    services: list[str] | None = None,
) -> list[LogFinding]:
    """Run the parser across the allowlist (or a caller-supplied subset)."""
    seconds = _parse_since_seconds(since)
    sources = await list_allowed_sources()
    if services:
        wanted = {s.strip() for s in services if s and s.strip()}
        sources = [s for s in sources if s.name in wanted or (s.container_name and s.container_name in wanted)]

    now = datetime.now(timezone.utc)
    per_source: list[dict] = []

    for source in sources:
        if source.is_app:
            entries = await read_app_jsonl_lines(since_seconds=seconds)
            per_source.append(parse_jsonl_entries(source.name, entries))
            continue
        rc, out, err = await docker_logs(
            source.container_name or source.name,
            since=since,
            tail=5000,
        )
        if rc != 0:
            logger.debug(
                "get_recent_server_errors: docker logs %s failed (%s): %s",
                source.name, rc, (err or "").strip()[:200],
            )
            continue
        per_source.append(parse_text_lines(source.name, (out or "").splitlines(), now=now))

    return merge_findings(*per_source)


def _finding_to_dict(f: LogFinding) -> dict:
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


@register({
    "type": "function",
    "function": {
        "name": "get_recent_server_errors",
        "description": (
            "Return deduplicated error findings across all Spindrel-server log "
            "sources (FastAPI app durable log + sibling containers). Use this "
            "for a fast operational summary without paging raw lines. The "
            "default 24h window matches the daily health summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "Time window e.g. '1h', '24h', '7d'. Default '24h'.",
                },
                "services": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of allowed source names. Default = all.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max findings to return (default 50).",
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "since": {"type": "string"},
        "total": {"type": "integer"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "severity": {"type": "string"},
                    "signature": {"type": "string"},
                    "dedupe_key": {"type": "string"},
                    "title": {"type": "string"},
                    "sample": {"type": "string"},
                    "first_seen": {"type": "string"},
                    "last_seen": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
        },
    },
})
async def get_recent_server_errors(
    since: str = "24h",
    services: list[str] | None = None,
    limit: int = 50,
    **_: object,
) -> str:
    findings = await collect_findings(since=since, services=services)
    cap = max(1, min(int(limit or 50), 500))
    out = [_finding_to_dict(f) for f in findings[:cap]]
    return json.dumps({
        "since": since,
        "total": len(findings),
        "findings": out,
    }, ensure_ascii=False)
