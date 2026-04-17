"""Seed widget_template_packages from integration manifests and core YAML files.

Runs at startup before the DB-backed resolver loads the in-memory registry.
YAML on disk is source of truth for shipped templates; the DB stores an
editable shadow (``source='seed'``) plus any user creations (``source='user'``).

User-active selections survive seed refreshes — the seeder only touches
seed rows.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _hash_yaml(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _dump_yaml(widget_def: dict) -> str:
    """Serialize a single widget definition to a stable YAML body.

    Anchors declared in the parent manifest are already resolved by PyYAML
    when we read it, so the output is self-contained.
    """
    return yaml.safe_dump(widget_def, sort_keys=False)


def _collect_sources() -> list[tuple[str, dict, str | None, str | None]]:
    """Yield all (tool_name, widget_def, source_file, source_integration) tuples.

    Matches the two sources the legacy loader walked:
      1. Integration manifests (``tool_widgets`` key)
      2. Core ``app/tools/local/*.widgets.yaml`` files
    """
    from app.services.integration_manifests import get_all_manifests

    out: list[tuple[str, dict, str | None, str | None]] = []

    # 1. Integration manifests
    for integration_id, manifest in get_all_manifests().items():
        tool_widgets = manifest.get("tool_widgets")
        if not isinstance(tool_widgets, dict):
            continue
        for tool_name, widget_def in tool_widgets.items():
            if tool_name.startswith("_"):
                continue
            if not isinstance(widget_def, dict) or "template" not in widget_def:
                continue
            out.append((tool_name, widget_def, None, integration_id))

    # 2. Core *.widgets.yaml files
    core_dir = Path(__file__).resolve().parent.parent / "tools" / "local"
    if core_dir.is_dir():
        for yaml_path in sorted(core_dir.glob("*.widgets.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
            except Exception:
                logger.warning(
                    "Failed to parse core widget file %s", yaml_path, exc_info=True,
                )
                continue
            if not isinstance(raw, dict):
                continue
            for tool_name, widget_def in raw.items():
                if tool_name.startswith("_"):
                    continue
                if not isinstance(widget_def, dict) or "template" not in widget_def:
                    continue
                out.append((tool_name, widget_def, str(yaml_path), None))

    return out


async def seed_widget_packages() -> None:
    """Upsert seed packages + handle orphans. Idempotent."""
    from app.db.engine import async_session
    from app.db.models import WidgetTemplatePackage

    sources = _collect_sources()
    seen_keys: set[tuple[str, str | None, str | None]] = set()
    inserted = 0
    updated = 0

    async with async_session() as db:
        for tool_name, widget_def, source_file, source_integration in sources:
            yaml_body = _dump_yaml(widget_def)
            content_hash = _hash_yaml(yaml_body)
            key = (tool_name, source_file, source_integration)
            seen_keys.add(key)

            stmt = select(WidgetTemplatePackage).where(
                WidgetTemplatePackage.tool_name == tool_name,
                WidgetTemplatePackage.source == "seed",
                WidgetTemplatePackage.source_file.is_(source_file)
                if source_file is None else WidgetTemplatePackage.source_file == source_file,
                WidgetTemplatePackage.source_integration.is_(source_integration)
                if source_integration is None
                else WidgetTemplatePackage.source_integration == source_integration,
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()

            if existing is None:
                any_active_stmt = select(WidgetTemplatePackage.id).where(
                    WidgetTemplatePackage.tool_name == tool_name,
                    WidgetTemplatePackage.is_active.is_(True),
                )
                any_active = (await db.execute(any_active_stmt)).first()

                row = WidgetTemplatePackage(
                    tool_name=tool_name,
                    name=_default_name(widget_def, source_integration, source_file),
                    description=_default_description(source_integration, source_file),
                    yaml_template=yaml_body,
                    python_code=None,
                    source="seed",
                    is_readonly=True,
                    is_active=any_active is None,
                    is_orphaned=False,
                    source_file=source_file,
                    source_integration=source_integration,
                    content_hash=content_hash,
                    version=1,
                )
                db.add(row)
                inserted += 1
            else:
                if existing.is_orphaned:
                    existing.is_orphaned = False
                if existing.content_hash != content_hash:
                    existing.yaml_template = yaml_body
                    existing.content_hash = content_hash
                    existing.version = (existing.version or 1) + 1
                    existing.is_invalid = False
                    existing.invalid_reason = None
                    updated += 1

        # Orphan sweep: seeds not in seen_keys get flagged.
        all_seeds = (
            await db.execute(
                select(WidgetTemplatePackage).where(
                    WidgetTemplatePackage.source == "seed",
                )
            )
        ).scalars().all()
        for row in all_seeds:
            key = (row.tool_name, row.source_file, row.source_integration)
            if key in seen_keys:
                continue
            if not row.is_orphaned:
                row.is_orphaned = True
                logger.info(
                    "Widget seed %s (tool=%s) orphaned — source removed",
                    row.id, row.tool_name,
                )
            if row.is_active:
                replacement = next(
                    (
                        s for s in all_seeds
                        if s.tool_name == row.tool_name
                        and not s.is_orphaned
                        and (s.tool_name, s.source_file, s.source_integration) in seen_keys
                    ),
                    None,
                )
                if replacement is not None and replacement.id != row.id:
                    row.is_active = False
                    replacement.is_active = True

        await db.commit()

    logger.info(
        "Widget package seed complete: %d inserted, %d refreshed", inserted, updated,
    )


def _default_name(widget_def: dict, source_integration: str | None, source_file: str | None) -> str:
    if source_integration:
        return f"{source_integration} default"
    if source_file:
        return f"{Path(source_file).stem} default"
    return "Default"


def _default_description(source_integration: str | None, source_file: str | None) -> str | None:
    if source_integration:
        return f"Shipped with the {source_integration} integration."
    if source_file:
        return f"Core widget template from {Path(source_file).name}."
    return None


def _widget_def_from_yaml(yaml_body: str) -> dict[str, Any]:
    """Parse a stored yaml_template back into a widget_def dict."""
    parsed = yaml.safe_load(yaml_body)
    if not isinstance(parsed, dict):
        raise ValueError("widget_template YAML did not parse to a mapping")
    return parsed
