"""Local tool: read_container_logs — raw `docker logs` wrapper, allowlisted."""
from __future__ import annotations

import json
import logging

from app.services.server_log_sources import (
    docker_logs,
    list_allowed_sources,
    read_app_jsonl_lines,
    resolve_source,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)


def _parse_since_seconds(since: str) -> int:
    """Best-effort `1h` / `30m` / `45s` / `2d` → seconds. Defaults to 1h."""
    if not since:
        return 3600
    s = since.strip().lower()
    try:
        if s.endswith("ms"):
            return max(0, int(float(s[:-2]) / 1000))
        unit = s[-1]
        value = float(s[:-1])
        if unit == "s":
            return int(value)
        if unit == "m":
            return int(value * 60)
        if unit == "h":
            return int(value * 3600)
        if unit == "d":
            return int(value * 86400)
        return int(float(s))  # bare number = seconds
    except (ValueError, IndexError):
        return 3600


@register({
    "type": "function",
    "function": {
        "name": "read_container_logs",
        "description": (
            "Read recent log lines from a Spindrel-server container (allowlisted). "
            "Use this for debugging or inspecting raw stderr/stdout that does not "
            "appear in trace_events. The 'agent-server' source reads from the "
            "durable JSONL log file rather than `docker logs`. Pass `container=\"\"` "
            "with no other args to discover allowed names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": (
                        "Allowlisted container name. Empty string lists allowed names. "
                        "Use 'agent-server' for the FastAPI app's own logs."
                    ),
                },
                "since": {
                    "type": "string",
                    "description": "Time window e.g. '15m', '1h', '24h'. Default '1h'.",
                },
                "tail": {
                    "type": "integer",
                    "description": "Max lines to return (capped at 5000). Default 500.",
                },
                "grep": {
                    "type": "string",
                    "description": "Optional case-insensitive substring filter applied to each line.",
                },
            },
            "required": ["container"],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "container": {"type": "string"},
        "allowed": {"type": "array", "items": {"type": "string"}},
        "lines": {"type": "array", "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
        "error": {"type": "string"},
    },
})
async def read_container_logs(
    container: str,
    since: str = "1h",
    tail: int = 500,
    grep: str | None = None,
    **_: object,
) -> str:
    target = (container or "").strip()
    sources = await list_allowed_sources()
    allowed_names = [s.name for s in sources]

    if not target:
        return json.dumps({
            "container": "",
            "allowed": allowed_names,
            "lines": [],
            "truncated": False,
        }, ensure_ascii=False)

    source = await resolve_source(target)
    if source is None:
        return json.dumps({
            "container": target,
            "allowed": allowed_names,
            "lines": [],
            "truncated": False,
            "error": f"Container '{target}' is not in the allowlist.",
        }, ensure_ascii=False)

    tail = max(1, min(int(tail or 500), 5000))
    grep_lower = grep.lower() if grep else None

    if source.is_app:
        seconds = _parse_since_seconds(since)
        entries = await read_app_jsonl_lines(since_seconds=seconds)
        lines: list[str] = []
        for entry in entries[-tail:]:
            ts = entry.get("ts", "")
            level = entry.get("level", "")
            logger_name = entry.get("logger", "")
            message = entry.get("message", "")
            line = f"{ts} {level:<5} [{logger_name}] {message}"
            if entry.get("exc_info"):
                line = f"{line}\n{entry['exc_info']}"
            if grep_lower and grep_lower not in line.lower():
                continue
            lines.append(line)
        truncated = len(entries) > tail
        return json.dumps({
            "container": source.name,
            "allowed": allowed_names,
            "lines": lines,
            "truncated": truncated,
        }, ensure_ascii=False)

    rc, out, err = await docker_logs(
        source.container_name or source.name,
        since=since,
        tail=tail,
    )
    if rc != 0:
        return json.dumps({
            "container": source.name,
            "allowed": allowed_names,
            "lines": [],
            "truncated": False,
            "error": (err or "docker logs failed").strip()[:500],
        }, ensure_ascii=False)

    raw_lines = (out or "").splitlines()
    if grep_lower:
        raw_lines = [ln for ln in raw_lines if grep_lower in ln.lower()]
    truncated = len(raw_lines) > tail
    if truncated:
        raw_lines = raw_lines[-tail:]
    return json.dumps({
        "container": source.name,
        "allowed": allowed_names,
        "lines": raw_lines,
        "truncated": truncated,
    }, ensure_ascii=False)
