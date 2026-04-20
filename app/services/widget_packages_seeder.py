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

    Matches the two sources the template loader walks:
      1. Integration manifests (``tool_widgets`` key)
      2. Core ``app/tools/local/widgets/<tool_name>/template.yaml`` files

    ``widget_def`` may carry a top-level ``sample_payload`` key. It is not
    part of the template body — the caller pops it before the YAML is dumped
    into ``yaml_template`` so it lands on the ``sample_payload`` DB column
    instead.
    """
    from app.services.integration_manifests import get_all_manifests

    out: list[tuple[str, dict, str | None, str | None]] = []

    from app.services.widget_templates import _resolve_html_template_paths

    def _is_widget(widget_def: Any) -> bool:
        return isinstance(widget_def, dict) and (
            "template" in widget_def or "html_template" in widget_def
        )

    # 1. Integration manifests
    for integration_id, manifest in get_all_manifests().items():
        tool_widgets = manifest.get("tool_widgets")
        if not isinstance(tool_widgets, dict):
            continue
        src_path = manifest.get("source_path")
        base_dir = Path(src_path).parent if src_path else None
        for tool_name, widget_def in tool_widgets.items():
            if tool_name.startswith("_"):
                continue
            if not _is_widget(widget_def):
                continue
            resolved, err = _resolve_html_template_paths(widget_def, base_dir)
            if err:
                logger.warning(
                    "integration:%s tool_widgets[%s]: %s",
                    integration_id, tool_name, err,
                )
                continue
            out.append((tool_name, resolved, None, integration_id))

    # 2. Core widget templates: widgets/<tool_name>/template.yaml
    widgets_root = (
        Path(__file__).resolve().parent.parent / "tools" / "local" / "widgets"
    )
    if widgets_root.is_dir():
        for entry in sorted(widgets_root.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / "template.yaml"
            if not yaml_path.is_file():
                continue
            try:
                widget_def = yaml.safe_load(yaml_path.read_text())
            except Exception:
                logger.warning(
                    "Failed to parse core widget file %s", yaml_path, exc_info=True,
                )
                continue
            if not _is_widget(widget_def):
                continue
            tool_name = entry.name
            resolved, err = _resolve_html_template_paths(widget_def, entry)
            if err:
                logger.warning(
                    "core:%s tool_widgets[%s]: %s", tool_name, tool_name, err,
                )
                continue
            out.append((tool_name, resolved, str(yaml_path), None))

    return out


def _extract_sample_payload(widget_def: dict) -> tuple[dict, dict | None]:
    """Split ``sample_payload`` off a widget_def. Returns (stripped_def, sample).

    The sample lives beside the template in YAML for authoring convenience
    but is persisted to its own column so the Library editor preview can
    load it without re-parsing the template body.
    """
    if "sample_payload" not in widget_def:
        return widget_def, None
    stripped = {k: v for k, v in widget_def.items() if k != "sample_payload"}
    sample = widget_def.get("sample_payload")
    if not isinstance(sample, dict):
        return stripped, None
    return stripped, sample


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
            stripped_def, sample_payload = _extract_sample_payload(widget_def)
            yaml_body = _dump_yaml(stripped_def)
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
                    sample_payload=sample_payload,
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
                # Keep the sample_payload in sync with the YAML source when the
                # author hasn't edited it out from under us.
                if existing.sample_payload != sample_payload and sample_payload is not None:
                    existing.sample_payload = sample_payload
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
                    # Force the orphan's deactivation to land in the DB BEFORE
                    # promoting the replacement — the partial unique index
                    # `UNIQUE (tool_name) WHERE is_active` cannot tolerate two
                    # active rows with the same tool_name even transiently. SA's
                    # unit-of-work does not guarantee flush order between
                    # attribute writes on different objects, so we pin the
                    # order explicitly. (When replacement is already active,
                    # SA emits no UPDATE for it — attribute dirty-check sees
                    # no change — so the second flush is a no-op but cheap.)
                    row.is_active = False
                    await db.flush()
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
