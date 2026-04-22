"""Workflow registry — in-memory cache of workflow definitions.

Follows the in-memory registry pattern: loaded from DB at startup,
refreshed after edits. YAML files from ``workflows/`` and
``integrations/*/workflows/`` are synced via ``file_sync.py``.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Workflow

logger = logging.getLogger(__name__)

_registry: dict[str, Workflow] = {}

WORKFLOWS_DIR = Path("workflows")


# ---------------------------------------------------------------------------
# Registry accessors
# ---------------------------------------------------------------------------

def get_workflow(workflow_id: str) -> Workflow | None:
    return _registry.get(workflow_id)


def list_workflows() -> list[Workflow]:
    return list(_registry.values())


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

async def load_workflows() -> None:
    """Load all workflows from DB into the in-memory registry."""
    _registry.clear()
    async with async_session() as db:
        rows = (await db.execute(select(Workflow))).scalars().all()
    for row in rows:
        _registry[row.id] = row
    logger.info("Loaded %d workflow(s) from DB", len(_registry))


async def reload_workflows() -> None:
    """Re-populate registry from DB — called after admin edits."""
    await load_workflows()


# ---------------------------------------------------------------------------
# File collection (for file_sync)
# ---------------------------------------------------------------------------

def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _integration_dirs() -> list[Path]:
    """Return all integration/package directories.

    Includes in-repo ``integrations/`` + ``packages/`` plus every directory
    returned by ``effective_integration_dirs()`` (SPINDREL_HOME, legacy
    INTEGRATION_DIRS, runtime-added dirs).
    """
    dirs = [Path("integrations"), Path("packages")]
    try:
        from app.services.paths import effective_integration_dirs
        for p in effective_integration_dirs():
            path = Path(p)
            if path.is_dir() and path not in dirs:
                dirs.append(path)
    except Exception:
        logger.warning("Could not resolve effective_integration_dirs", exc_info=True)
    return dirs


def collect_workflow_files() -> list[tuple[Path, str, str]]:
    """Return (path, workflow_id, source_type) for all discoverable workflow YAML files."""
    items: list[tuple[Path, str, str]] = []

    # workflows/*.yaml
    if WORKFLOWS_DIR.is_dir():
        for p in sorted(WORKFLOWS_DIR.glob("*.yaml")):
            items.append((p, p.stem, "file"))

    # integrations/*/workflows/*.yaml
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_workflows = intg_dir / "workflows"
            if intg_workflows.is_dir():
                for p in sorted(intg_workflows.glob("*.yaml")):
                    items.append((p, p.stem, "integration"))

    return items


# ---------------------------------------------------------------------------
# CRUD helpers (for API + tool)
# ---------------------------------------------------------------------------

async def create_workflow(data: dict) -> Workflow:
    """Create a workflow from a dict and add to registry."""
    row = Workflow(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description"),
        params=data.get("params", {}),
        secrets=data.get("secrets", []),
        defaults=data.get("defaults", {}),
        steps=data.get("steps", []),
        triggers=data.get("triggers", {}),
        tags=data.get("tags", []),
        session_mode=data.get("session_mode", "isolated"),
        source_type=data.get("source_type", "manual"),
        source_path=data.get("source_path"),
        content_hash=data.get("content_hash"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    async with async_session() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    _registry[row.id] = row
    return row


async def update_workflow(workflow_id: str, data: dict) -> Workflow | None:
    """Update a workflow. Auto-detaches file/integration sources to manual."""
    async with async_session() as db:
        row = await db.get(Workflow, workflow_id)
        if not row:
            return None

        # Auto-detach file-sourced workflows when edited — makes them user-managed
        if row.source_type in ("file", "integration"):
            row.source_type = "manual"
            row.content_hash = None

        for field in ("name", "description", "params", "secrets", "defaults",
                       "steps", "triggers", "tags", "session_mode"):
            if field in data:
                setattr(row, field, data[field])
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
    _registry[workflow_id] = row
    return row


async def delete_workflow(workflow_id: str) -> bool:
    """Delete a workflow. Raises ValueError if active runs exist."""
    from sqlalchemy import select as sa_select, func
    from app.db.models import WorkflowRun

    async with async_session() as db:
        row = await db.get(Workflow, workflow_id)
        if not row:
            return False

        # Guard: prevent deletion if active runs exist
        active_count = (await db.execute(
            sa_select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status.in_(("running", "awaiting_approval")),
            )
        )).scalar() or 0
        if active_count > 0:
            raise ValueError(
                f"Cannot delete workflow '{workflow_id}': "
                f"{active_count} active run(s) still in progress. "
                f"Cancel them first."
            )

        await db.delete(row)
        await db.commit()
    _registry.pop(workflow_id, None)
    return True
