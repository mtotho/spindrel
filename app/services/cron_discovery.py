"""Discover cron jobs from workspace containers and the host OS."""
from __future__ import annotations

import asyncio
import logging
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.db.engine import async_session

logger = logging.getLogger(__name__)

# Matches a standard 5-field cron line: min hour dom month dow command
_CRON_LINE_RE = re.compile(
    r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(.+)$"
)
# Lines to skip: comments, blanks, env vars (VAR=val with no cron fields)
_SKIP_RE = re.compile(r"^\s*$|^\s*#|^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass
class CronEntry:
    expression: str
    command: str
    source_type: str  # "container" or "host"
    source_name: str  # container name or hostname
    workspace_id: str | None = None
    workspace_name: str | None = None
    user: str = "root"


@dataclass
class DiscoveryResult:
    cron_jobs: list[CronEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_crontab_lines(
    text: str,
    *,
    source_type: str,
    source_name: str,
    workspace_id: str | None = None,
    workspace_name: str | None = None,
    user: str = "root",
) -> list[CronEntry]:
    """Parse crontab output into CronEntry objects."""
    entries: list[CronEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if _SKIP_RE.match(line):
            continue
        m = _CRON_LINE_RE.match(line)
        if m:
            entries.append(CronEntry(
                expression=m.group(1),
                command=m.group(2),
                source_type=source_type,
                source_name=source_name,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                user=user,
            ))
    return entries


async def _discover_container_crons(
    workspace_id: str | None = None,
) -> DiscoveryResult:
    """Discover cron jobs from running workspace containers."""
    from sqlalchemy import select
    from app.db.models import SharedWorkspace

    result = DiscoveryResult()

    async with async_session() as db:
        stmt = select(SharedWorkspace)
        if workspace_id:
            stmt = stmt.where(SharedWorkspace.id == workspace_id)
        workspaces = (await db.execute(stmt)).scalars().all()

    cmd = (
        "crontab -l 2>/dev/null; "
        "cat /etc/cron.d/* 2>/dev/null; "
        "cat /etc/crontab 2>/dev/null"
    )

    for ws in workspaces:
        try:
            proc = await asyncio.create_subprocess_exec(
                "sh", "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=10,
            )
            output = stdout_bytes.decode(errors="replace")
            entries = parse_crontab_lines(
                output,
                source_type="workspace",
                source_name=ws.name,
                workspace_id=str(ws.id),
                workspace_name=ws.name,
            )
            result.cron_jobs.extend(entries)
        except asyncio.TimeoutError:
            result.errors.append(f"Timeout querying crons for workspace {ws.name}")
        except Exception as e:
            result.errors.append(f"Error querying crons for workspace {ws.name}: {e}")

    return result


async def _discover_host_crons() -> DiscoveryResult:
    """Discover cron jobs from the host OS."""
    result = DiscoveryResult()
    hostname = platform.node()

    # User crontab
    try:
        proc = await asyncio.create_subprocess_exec(
            "crontab", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        output = stdout_bytes.decode(errors="replace")
        entries = parse_crontab_lines(
            output,
            source_type="host",
            source_name=hostname,
        )
        result.cron_jobs.extend(entries)
    except FileNotFoundError:
        pass  # crontab binary not available
    except asyncio.TimeoutError:
        result.errors.append("Timeout reading host crontab")
    except Exception as e:
        result.errors.append(f"Error reading host crontab: {e}")

    # System cron.d
    cron_d = Path("/etc/cron.d")
    if cron_d.is_dir():
        try:
            for f in sorted(cron_d.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    text = f.read_text(errors="replace")
                    entries = parse_crontab_lines(
                        text,
                        source_type="host",
                        source_name=hostname,
                    )
                    result.cron_jobs.extend(entries)
        except Exception as e:
            result.errors.append(f"Error reading /etc/cron.d: {e}")

    return result


async def discover_crons(workspace_id: str | None = None) -> DiscoveryResult:
    """Discover cron jobs from containers and optionally the host OS.

    If workspace_id is given, only that container is queried (no host).
    """
    if workspace_id:
        return await _discover_container_crons(workspace_id=workspace_id)

    container_result, host_result = await asyncio.gather(
        _discover_container_crons(),
        _discover_host_crons(),
    )

    return DiscoveryResult(
        cron_jobs=container_result.cron_jobs + host_result.cron_jobs,
        errors=container_result.errors + host_result.errors,
    )
