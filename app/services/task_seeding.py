"""Seed Task rows from system pipeline YAML files on boot.

Mirrors the bot-seeding pattern (``app/agent/bots.py:seed_bots_from_yaml``)
but for task pipelines. System pipelines are the source of truth for the
row with ``source='system'`` — they are refreshed on every boot.

If a row with the same id already exists as ``source='user'``, the
system seed is refused and a warning is logged so local edits are never
clobbered by the package.

Each YAML maps to one Task row via a deterministic UUID derived from a
stable string id (``uuid5`` under a fixed namespace).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Task

logger = logging.getLogger(__name__)

SYSTEM_PIPELINES_DIR = Path(__file__).parent.parent / "data" / "system_pipelines"

# Fixed namespace for deterministic uuid5 from YAML string ids.
# Do not change — changing this re-keys every system pipeline row.
_PIPELINE_NAMESPACE = uuid.UUID("6f9e2a4c-7e2f-5b9a-b2e1-1a3c7d9b0e42")


def pipeline_uuid(slug: str) -> uuid.UUID:
    """Deterministic UUID for a system pipeline slug."""
    return uuid.uuid5(_PIPELINE_NAMESPACE, slug)


_SYSTEM_PIPELINE_FIELDS = {
    "bot_id",
    "title",
    "prompt",
    "steps",
    "task_type",
    "trigger_config",
    "recurrence",
    "dispatch_type",
    "dispatch_config",
    "callback_config",
    "execution_config",
    "max_run_seconds",
    "workflow_id",
    "workflow_session_mode",
    "client_id",
    "channel_id",
}


def _yaml_to_row_fields(data: dict) -> dict:
    """Pick only supported Task fields out of the YAML dict.

    Defaults ``task_type`` to ``'pipeline'`` when ``steps`` is present.
    """
    fields = {k: v for k, v in data.items() if k in _SYSTEM_PIPELINE_FIELDS}
    if "task_type" not in fields:
        fields["task_type"] = "pipeline" if fields.get("steps") else "agent"
    return fields


async def seed_pipelines_from_yaml(directory: Path = SYSTEM_PIPELINES_DIR) -> None:
    """Seed/refresh system pipeline rows from YAML files in ``directory``.

    Semantics per YAML file:
      * Deterministic row id via :func:`pipeline_uuid` on the YAML ``id``.
      * Row missing         → insert with ``source='system'``.
      * Row exists, system  → overwrite from YAML.
      * Row exists, user    → refuse, log warning, leave user row intact.
    """
    if not directory.exists():
        logger.info("System pipeline dir not present: %s", directory)
        return

    yaml_files = sorted(directory.glob("*.yaml"))
    if not yaml_files:
        logger.info("No system pipeline YAMLs found in %s", directory)
        return

    async with async_session() as db:
        for path in yaml_files:
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
            except Exception:
                logger.error("Failed to parse pipeline YAML %s", path, exc_info=True)
                continue

            if not data or "id" not in data:
                logger.warning("Pipeline YAML %s missing top-level 'id'; skipping", path)
                continue

            slug = str(data["id"])
            row_id = pipeline_uuid(slug)
            fields = _yaml_to_row_fields(data)

            # Steps / prompt fallbacks — a pipeline row must have a prompt per
            # the NOT NULL constraint on Task.prompt. Use the title or a
            # synthetic label if none provided.
            if "prompt" not in fields or fields["prompt"] is None:
                fields["prompt"] = fields.get("title") or f"[System pipeline: {slug}]"

            # Pipelines stay channel-unbound at the definition level; the
            # launcher (chat channel UI / admin /run endpoint) supplies the
            # channel_id at launch time. This keeps system pipelines
            # reusable across channels without a channel-per-pipeline
            # multiplication problem.

            existing = await db.get(Task, row_id)
            now = datetime.now(timezone.utc)
            if existing is None:
                # status="active" is load-bearing: system pipelines are definitions,
                # not pending executions. The default Task.status is "pending", which
                # fetch_due_tasks (app/agent/tasks.py) polls and auto-runs in-place.
                # System pipelines must only run via POST /tasks/{id}/run or an event
                # trigger, never at boot.
                row = Task(
                    id=row_id,
                    source="system",
                    status="active",
                    created_at=now,
                    **fields,
                )
                db.add(row)
                logger.info("Seeded system pipeline '%s' (%s)", slug, path.name)
            elif existing.source == "user":
                logger.warning(
                    "System pipeline id collision with user-owned row '%s' (%s) — "
                    "leaving user row intact",
                    slug,
                    row_id,
                )
                continue
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
                # Force definition status on every refresh so a prior boot that
                # auto-ran the pipeline in-place (leaving status=failed/done on
                # the parent) gets reset back to "active". Child runs created
                # via spawn_child_run carry their own status rows — parent
                # status has no meaning beyond "definition is active".
                if existing.status != "active":
                    logger.info(
                        "Resetting system pipeline '%s' status %s → active",
                        slug, existing.status,
                    )
                    existing.status = "active"
                logger.info("Refreshed system pipeline '%s' (%s)", slug, path.name)

        await db.commit()


async def ensure_system_pipelines() -> None:
    """Lifespan entry point — seed/refresh all system pipelines on boot."""
    await seed_pipelines_from_yaml()
