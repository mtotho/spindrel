"""Container allowlist + log-source resolution for the server-side log tools.

The `read_container_logs` and `get_recent_server_errors` tools need a
curated set of containers to scan. Returning a free-form name to `docker logs`
would let any caller probe arbitrary containers on the host. Instead we
resolve the allowlist at call time from:

1. The known core service names from this repo's ``docker-compose.yml``.
2. Active integration sidecar/stack containers tracked in our own DB tables.

A caller may pass an allowed name; we reject anything else with a clear
error envelope so the model can fall back to a tighter scope.

The app container is special: prefer reading the durable JSONL log file
rather than `docker logs` against ourselves (faster, structured, survives
container restart).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Compose-level service names from the project's docker-compose.yml.
# Keeping this hard-coded matches the spirit of the existing
# `_LEGACY_INTEGRATION_CONTAINER_NAMES` list in app/main.py — the names
# don't drift often, and a stale entry just produces an empty result.
_CORE_SERVICE_NAMES: tuple[str, ...] = (
    "agent-server",
    "postgres",
)


@dataclass(frozen=True, slots=True)
class LogSource:
    """One readable log source.

    For the app itself we use the durable JSONL file; for everything else
    we shell out to ``docker logs <container>``.
    """

    name: str
    container_name: str | None  # None => internal file source (the app)
    file_path: Path | None = None  # set when reading from disk
    is_app: bool = False


def app_log_source() -> LogSource:
    from app.services.log_file import get_log_path
    return LogSource(
        name="agent-server",
        container_name=None,
        file_path=get_log_path(),
        is_app=True,
    )


async def _docker_running_names() -> list[str]:
    """Best-effort list of currently running container names from the host
    Docker daemon. Empty list on any failure (e.g. socket not mounted)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "--format", "{{.Names}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            return []
        return [line.strip() for line in out.decode().splitlines() if line.strip()]
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return []


def _core_compose_names(running: Iterable[str]) -> list[str]:
    """Map the core compose service names (`agent-server`, `postgres`) to the
    actual container names docker chose (`agent-server-postgres-1`, etc.).

    Compose containers are typically named ``<project>-<service>-<n>``. We
    accept any running name whose service component matches a core name.
    """
    matches: list[str] = []
    running_set = list(running)
    for service in _CORE_SERVICE_NAMES:
        # Exact match first
        if service in running_set:
            matches.append(service)
            continue
        # Then compose-style suffix match: ends with ``-<service>-<n>``
        for name in running_set:
            parts = name.split("-")
            if len(parts) >= 2 and parts[-2] == service:
                matches.append(name)
                break
    return matches


async def _integration_container_names() -> list[str]:
    """Container IDs/names from Spindrel-managed Docker Compose stacks.

    ``DockerStack.container_ids`` is ``{service_name: short_container_id}``
    written by ``_inspect_stack``; ``docker logs`` accepts either a name or
    an id, so we feed those ids straight through.
    """
    names: list[str] = []
    try:
        from app.db.engine import async_session
        from app.db.models import DockerStack
        from sqlalchemy import select
        async with async_session() as db:
            stacks = (await db.execute(
                select(DockerStack).where(DockerStack.status == "running")
            )).scalars().all()
            for stack in stacks:
                ids = stack.container_ids or {}
                if isinstance(ids, dict):
                    for cid in ids.values():
                        if isinstance(cid, str) and cid:
                            names.append(cid)
    except Exception:
        # DockerStack model or column may be absent in tests — fail soft.
        pass
    return names


async def list_allowed_sources() -> list[LogSource]:
    """Resolve the allowlist of log sources the tools may read."""
    sources: list[LogSource] = [app_log_source()]
    running = await _docker_running_names()
    seen = {sources[0].name}

    for name in _core_compose_names(running):
        if name == "agent-server" or name in seen:
            continue
        sources.append(LogSource(name=name, container_name=name))
        seen.add(name)

    for name in await _integration_container_names():
        if name in seen or name not in running:
            continue
        sources.append(LogSource(name=name, container_name=name))
        seen.add(name)

    return sources


async def resolve_source(name: str) -> LogSource | None:
    """Resolve a single named source. Returns None if not allowlisted."""
    target = (name or "").strip()
    if not target:
        return None
    sources = await list_allowed_sources()
    for s in sources:
        if s.name == target or s.container_name == target:
            return s
    return None


async def read_app_jsonl_lines(*, since_seconds: int | None, max_bytes: int = 5 * 1024 * 1024) -> list[dict]:
    """Read the durable JSONL log tail and return parsed entries.

    Cheap: caps at ``max_bytes`` from the end of the current log file (does
    not walk rotated backups).
    """
    path = app_log_source().file_path
    if not path or not path.exists():
        return []
    entries: list[dict] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # discard the partial leading line
            for raw in fh:
                try:
                    obj = json.loads(raw.decode("utf-8", errors="replace"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                entries.append(obj)
    except OSError:
        return []
    if since_seconds is not None and since_seconds > 0:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        kept: list[dict] = []
        for entry in entries:
            ts_raw = entry.get("ts")
            try:
                ts = datetime.fromisoformat(ts_raw) if ts_raw else None
            except (TypeError, ValueError):
                ts = None
            if ts is None or ts >= cutoff:
                kept.append(entry)
        entries = kept
    return entries


async def docker_logs(
    container: str,
    *,
    since: str = "1h",
    tail: int = 500,
    timeout: float = 15.0,
) -> tuple[int, str, str]:
    """Run `docker logs --since <since> --tail <tail> <container>`.

    Returns (returncode, stdout, stderr). Caller is responsible for having
    resolved ``container`` against the allowlist first.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "logs",
        "--since", since,
        "--tail", str(int(tail)),
        container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "", "docker logs timed out"
    return proc.returncode or 0, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
