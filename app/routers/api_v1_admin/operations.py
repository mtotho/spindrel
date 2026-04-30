"""System operations: backup, pull, restart.

POST /operations/backup       — trigger backup.sh as background task
POST /operations/pull         — update to stable release tag, or development channel
POST /operations/restart      — pull + systemd restart (requires confirm)
GET  /operations              — list active background operations
GET  /operations/backup/config   — get backup settings
PUT  /operations/backup/config   — update backup settings
GET  /operations/backup/history  — list local backup archives
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ServerSetting
from app.dependencies import get_db, require_scopes
from app.services import progress

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operations", tags=["Operations"])

# Repo root (backup.sh lives in scripts/)
_REPO_DIR = Path(__file__).resolve().parents[3]
_BACKUP_SCRIPT = _REPO_DIR / "scripts" / "backup.sh"
DEVELOPMENT_BRANCH = "development"
STABLE_CHANNEL = "stable"
DEVELOPMENT_CHANNEL = "development"

# backup.* keys stored in server_settings
_BACKUP_SETTING_KEYS = {
    "backup.rclone_remote": "RCLONE_REMOTE",
    "backup.local_keep": "LOCAL_KEEP",
    "backup.aws_region": "AWS_REGION",
    "backup.backup_dir": "BACKUP_DIR",
}

_BACKUP_DEFAULTS = {
    "backup.rclone_remote": "",
    "backup.local_keep": "7",
    "backup.aws_region": "us-east-1",
    "backup.backup_dir": "./backups",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_backup_settings(db: AsyncSession) -> dict[str, str]:
    """Read backup.* keys from server_settings, fall back to .env, then defaults."""
    rows = (
        await db.execute(
            select(ServerSetting).where(
                ServerSetting.key.in_(_BACKUP_SETTING_KEYS.keys())
            )
        )
    ).scalars().all()
    db_map = {r.key: r.value for r in rows}

    result = {}
    for key, env_var in _BACKUP_SETTING_KEYS.items():
        if key in db_map and db_map[key]:
            result[key] = db_map[key]
        elif os.environ.get(env_var):
            result[key] = os.environ[env_var]
        else:
            result[key] = _BACKUP_DEFAULTS[key]
    return result


def _build_backup_env(cfg: dict[str, str]) -> dict[str, str]:
    """Build env dict for subprocess from backup config — merges into current env."""
    env = os.environ.copy()
    for key, env_var in _BACKUP_SETTING_KEYS.items():
        if cfg.get(key):
            env[env_var] = cfg[key]
    return env


# ---------------------------------------------------------------------------
# GET /operations — list active background operations
# ---------------------------------------------------------------------------

@router.get("")
async def list_operations(
    _auth=Depends(require_scopes("operations:read")),
):
    """List active background operations."""
    return {"operations": progress.list_operations()}


# ---------------------------------------------------------------------------
# POST /operations/backup — trigger backup
# ---------------------------------------------------------------------------

@router.post("/backup")
async def trigger_backup(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("operations:write")),
):
    """Run scripts/backup.sh as a background subprocess, tracked via progress."""
    if not _BACKUP_SCRIPT.exists():
        raise HTTPException(404, f"Backup script not found: {_BACKUP_SCRIPT}")

    cfg = await _get_backup_settings(db)
    env = _build_backup_env(cfg)
    op_id = progress.start("backup", "Running backup")

    async def _run():
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", str(_BACKUP_SCRIPT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                progress.complete(op_id, message=stdout.decode(errors="replace").strip()[-500:])
                logger.info("Backup completed successfully (op=%s)", op_id)
            else:
                msg = stderr.decode(errors="replace").strip()[-500:]
                progress.fail(op_id, message=f"exit {proc.returncode}: {msg}")
                logger.error("Backup failed (op=%s): exit %d — %s", op_id, proc.returncode, msg)
        except Exception as exc:
            progress.fail(op_id, message=str(exc))
            logger.exception("Backup exception (op=%s)", op_id)

    asyncio.create_task(_run())
    return {"operation_id": op_id, "status": "started"}


# ---------------------------------------------------------------------------
# POST /operations/pull — update repo
# ---------------------------------------------------------------------------

@router.post("/pull")
async def git_pull(
    channel: str = Query(STABLE_CHANNEL, pattern="^(stable|development)$"),
    _auth=Depends(require_scopes("operations:write")),
):
    """Update the repo synchronously, return stdout/stderr/exit_code."""
    return await _update_repo(channel)


# ---------------------------------------------------------------------------
# POST /operations/restart — pull + restart
# ---------------------------------------------------------------------------

class RestartBody(BaseModel):
    confirm: bool = False
    channel: str = STABLE_CHANNEL


@router.post("/restart")
async def restart_server(
    body: RestartBody,
    _auth=Depends(require_scopes("operations:write")),
):
    """Pull latest code and restart the server via systemd.

    Requires {"confirm": true}. Uses systemd-run to survive server death.
    """
    if not body.confirm:
        raise HTTPException(400, "Pass {\"confirm\": true} to confirm restart")

    pull_result = await _update_repo(body.channel)

    # Restart via transient systemd unit (survives our process dying)
    restart_proc = await asyncio.create_subprocess_exec(
        "systemd-run", "--no-block",
        "systemctl", "restart", "spindrel.service",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    r_stdout, r_stderr = await restart_proc.communicate()

    return {
        "pull": pull_result,
        "restart": {
            "exit_code": restart_proc.returncode,
            "stdout": r_stdout.decode(errors="replace"),
            "stderr": r_stderr.decode(errors="replace"),
        },
    }


async def _run_git(*args: str) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(_REPO_DIR), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_DIR),
    )
    stdout, stderr = await proc.communicate()
    return {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


async def _update_repo(channel: str) -> dict[str, object]:
    if channel == DEVELOPMENT_CHANNEL:
        return await _update_development()
    if channel != STABLE_CHANNEL:
        return {"exit_code": 2, "stdout": "", "stderr": f"unsupported channel: {channel}"}
    return await _update_stable()


async def _update_stable() -> dict[str, object]:
    fetch = await _run_git("fetch", "origin", "--tags", "--prune")
    if fetch["exit_code"] != 0:
        return fetch

    tags = await _run_git("tag", "--sort=-v:refname")
    if tags["exit_code"] != 0:
        return tags
    tag = next((line.strip() for line in str(tags["stdout"]).splitlines() if line.strip()), "")
    if not tag:
        return {
            "exit_code": 1,
            "stdout": fetch["stdout"],
            "stderr": "No release tags found after fetching origin.",
        }

    checkout = await _run_git("checkout", "--detach", f"refs/tags/{tag}")
    checkout["stdout"] = f"{fetch['stdout']}{checkout['stdout']}"
    checkout["stderr"] = f"{fetch['stderr']}{checkout['stderr']}"
    return checkout


async def _update_development() -> dict[str, object]:
    fetch = await _run_git("fetch", "origin", DEVELOPMENT_BRANCH)
    if fetch["exit_code"] != 0:
        return fetch

    switch = await _run_git("switch", DEVELOPMENT_BRANCH)
    if switch["exit_code"] != 0:
        switch = await _run_git("switch", "-c", DEVELOPMENT_BRANCH, "--track", f"origin/{DEVELOPMENT_BRANCH}")
    if switch["exit_code"] != 0:
        switch["stdout"] = f"{fetch['stdout']}{switch['stdout']}"
        switch["stderr"] = f"{fetch['stderr']}{switch['stderr']}"
        return switch

    pull = await _run_git("pull", "--rebase", "origin", DEVELOPMENT_BRANCH)
    pull["stdout"] = f"{fetch['stdout']}{switch['stdout']}{pull['stdout']}"
    pull["stderr"] = f"{fetch['stderr']}{switch['stderr']}{pull['stderr']}"
    return pull


# ---------------------------------------------------------------------------
# GET /operations/backup/config — read backup settings
# ---------------------------------------------------------------------------

@router.get("/backup/config")
async def get_backup_config(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("operations:read")),
):
    """Get backup configuration (DB overrides > .env > defaults)."""
    cfg = await _get_backup_settings(db)
    return {
        "rclone_remote": cfg["backup.rclone_remote"],
        "local_keep": int(cfg["backup.local_keep"]),
        "aws_region": cfg["backup.aws_region"],
        "backup_dir": cfg["backup.backup_dir"],
    }


# ---------------------------------------------------------------------------
# PUT /operations/backup/config — update backup settings
# ---------------------------------------------------------------------------

class BackupConfigBody(BaseModel):
    rclone_remote: str | None = None
    local_keep: int | None = None
    aws_region: str | None = None
    backup_dir: str | None = None


@router.put("/backup/config")
async def update_backup_config(
    body: BackupConfigBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("operations:write")),
):
    """Update backup settings in server_settings table."""
    updates = {}
    if body.rclone_remote is not None:
        updates["backup.rclone_remote"] = body.rclone_remote
    if body.local_keep is not None:
        updates["backup.local_keep"] = str(body.local_keep)
    if body.aws_region is not None:
        updates["backup.aws_region"] = body.aws_region
    if body.backup_dir is not None:
        updates["backup.backup_dir"] = body.backup_dir

    if not updates:
        raise HTTPException(400, "No fields to update")

    now = datetime.now(timezone.utc)
    for key, value in updates.items():
        stmt = pg_insert(ServerSetting).values(
            key=key, value=value, updated_at=now,
        ).on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value, "updated_at": now},
        )
        await db.execute(stmt)
    await db.commit()

    # Return updated config
    cfg = await _get_backup_settings(db)
    return {
        "rclone_remote": cfg["backup.rclone_remote"],
        "local_keep": int(cfg["backup.local_keep"]),
        "aws_region": cfg["backup.aws_region"],
        "backup_dir": cfg["backup.backup_dir"],
    }


# ---------------------------------------------------------------------------
# GET /operations/backup/history — list local backup archives
# ---------------------------------------------------------------------------

@router.get("/backup/history")
async def backup_history(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("operations:read")),
):
    """List local agent-backup-*.tar.gz files with sizes and dates."""
    cfg = await _get_backup_settings(db)
    backup_dir = Path(cfg["backup.backup_dir"])
    if not backup_dir.is_absolute():
        backup_dir = _REPO_DIR / backup_dir

    if not backup_dir.is_dir():
        return {"backup_dir": str(backup_dir), "files": []}

    files = []
    for f in sorted(backup_dir.glob("agent-backup-*.tar.gz"), reverse=True):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })

    return {"backup_dir": str(backup_dir), "files": files}
