"""Integration manifest service: YAML-first, DB-backed, UI-editable.

Integrations are defined via integration.yaml (declarative).  DB is the source
of truth after first seed — the YAML file on disk is never overwritten and
changes to it are detected via content_hash and auto-applied.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import yaml
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

# In-memory cache: integration_id → manifest dict
_manifests: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

# Top-level keys we expect in integration.yaml
_KNOWN_KEYS = {
    "id", "name", "icon", "description", "version", "enabled", "includes",
    "mcp_servers", "settings", "activation", "oauth", "webhook",
    "binding", "dependencies", "docker_compose", "web_ui",
    "chat_hud", "chat_hud_presets", "sidebar_section",
    "debug_actions", "api_permissions", "dashboard_modules",
    "target", "process", "capabilities", "provides", "events",
    "tool_widgets", "widget_presets", "tool_families",
}

# Keys passed through as-is when converting manifest dicts to SETUP-compatible format.
# Used by _manifest_to_setup() in integrations/__init__.py.
PASSTHROUGH_KEYS = (
    "activation", "oauth", "webhook", "binding", "includes",
    "mcp_servers", "docker_compose", "web_ui", "chat_hud",
    "chat_hud_presets", "sidebar_section", "debug_actions",
    "api_permissions", "dashboard_modules",
    "target", "process", "capabilities", "provides", "events",
)


def parse_integration_yaml(path: Path) -> dict:
    """Read and validate an integration.yaml file.

    Returns a dict with at minimum 'id' and 'name'.
    Raises ValueError for invalid files.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        raise ValueError(f"integration.yaml at {path} is empty or not a mapping")

    if "id" not in data:
        raise ValueError(f"integration.yaml at {path} missing required 'id' field")

    if "name" not in data:
        data["name"] = data["id"].replace("_", " ").replace("-", " ").title()

    # Keys starting with `_` are YAML anchors by convention (e.g. `_ha_state_poll: &ha_state_poll`)
    # — the anchor target is inlined elsewhere via `*ha_state_poll`, so the top-level
    # key is load-bearing for YAML but not a manifest directive. Skip them.
    unknown = {k for k in data.keys() if k not in _KNOWN_KEYS and not k.startswith("_")}
    if unknown:
        logger.warning(
            "integration.yaml for '%s' has unknown keys: %s (preserved but not acted on)",
            data["id"], ", ".join(sorted(unknown)),
        )

    return data


def _file_hash(path: Path) -> str:
    """SHA256 of file contents for change detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# DB seeding and loading
# ---------------------------------------------------------------------------

async def seed_manifests() -> None:
    """Scan all integration dirs and synchronize YAML manifests to DB.

    New manifests are inserted; existing manifests are updated when the
    content_hash changes on disk.  Legacy setup.py rows are upgraded to
    YAML when an integration.yaml appears alongside them.
    """
    from integrations import _iter_integration_candidates
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    candidates = _iter_integration_candidates()
    if not candidates:
        return

    seeded = 0
    async with async_session() as db:
        for candidate_dir, integration_id, _is_external, source in candidates:
            yaml_path = candidate_dir / "integration.yaml"

            if not yaml_path.exists():
                continue

            try:
                data = parse_integration_yaml(yaml_path)
                raw_content = yaml_path.read_text()
                content_hash = _file_hash(yaml_path)
            except Exception:
                logger.error("Failed to parse %s", yaml_path, exc_info=True)
                continue

            existing = await db.get(IntegrationManifest, data["id"])
            if existing and existing.content_hash != content_hash:
                # YAML changed on disk (or legacy setup_py row being upgraded)
                existing.name = data.get("name", integration_id)
                existing.description = data.get("description")
                existing.version = data.get("version")
                existing.icon = data.get("icon", "Plug")
                existing.manifest = data
                existing.yaml_content = raw_content
                existing.source = "yaml"
                existing.source_path = str(yaml_path)
                existing.content_hash = content_hash
                seeded += 1
                logger.info("Updated manifest '%s' from YAML", data["id"])
            elif not existing:
                stmt = pg_insert(IntegrationManifest).values(
                    id=data["id"],
                    name=data.get("name", integration_id),
                    description=data.get("description"),
                    version=data.get("version"),
                    icon=data.get("icon", "Plug"),
                    manifest=data,
                    yaml_content=raw_content,
                    is_enabled=data.get("enabled", False),
                    source="yaml",
                    source_path=str(yaml_path),
                    content_hash=content_hash,
                ).on_conflict_do_nothing(index_elements=["id"])
                await db.execute(stmt)
                seeded += 1
                logger.debug("Seeded YAML manifest '%s' from %s", data["id"], yaml_path)

        await db.commit()

    logger.info("Manifest seed complete: %d manifests seeded/updated", seeded)


async def load_manifests() -> None:
    """Load all manifests from DB into in-memory cache."""
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    _manifests.clear()

    async with async_session() as db:
        rows = (await db.execute(select(IntegrationManifest))).scalars().all()

    for row in rows:
        # Manifest blob (user-authored YAML) spreads first so trusted DB columns
        # below override any colliding keys. Without this ordering, a YAML file
        # containing `content_hash:` / `source:` / `is_enabled:` would corrupt
        # drift detection and enablement state in the cache.
        _manifests[row.id] = {
            **(row.manifest or {}),
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "version": row.version,
            "icon": row.icon,
            "is_enabled": row.is_enabled,
            "source": row.source,
            "source_path": row.source_path,
            "content_hash": row.content_hash,
        }

    logger.info("Loaded %d integration manifest(s) from DB", len(_manifests))


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_manifest(integration_id: str) -> dict | None:
    """Return cached manifest for an integration, or None."""
    return _manifests.get(integration_id)


def get_all_manifests() -> dict[str, dict]:
    """Return all cached manifests."""
    return dict(_manifests)


async def get_yaml_content(integration_id: str) -> str | None:
    """Return raw YAML content from DB for the editor."""
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    async with async_session() as db:
        row = await db.get(IntegrationManifest, integration_id)
        if row is None:
            return None
        return row.yaml_content


async def update_manifest(integration_id: str, new_yaml: str) -> dict:
    """Parse YAML string, update DB manifest and yaml_content.

    Returns the updated manifest dict.
    Raises ValueError if YAML is invalid.
    """
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    data = yaml.safe_load(new_yaml)
    if not data or not isinstance(data, dict):
        raise ValueError("YAML content is empty or not a mapping")

    # Ensure id is consistent
    data["id"] = integration_id

    async with async_session() as db:
        row = await db.get(IntegrationManifest, integration_id)
        if row is None:
            raise ValueError(f"Integration '{integration_id}' not found")

        # Capture values before commit (expire_on_commit would invalidate row)
        row_source = row.source
        row_source_path = row.source_path
        row_content_hash = row.content_hash
        row_is_enabled = row.is_enabled

        row.name = data.get("name", row.name)
        row.description = data.get("description")
        row.version = data.get("version")
        row.icon = data.get("icon", "Plug")
        row.manifest = data
        row.yaml_content = new_yaml
        await db.commit()

    # Update cache. YAML blob spreads first so trusted DB-captured fields below
    # override user-pasted values for internal metadata.
    _manifests[integration_id] = {
        **data,
        "id": integration_id,
        "name": data.get("name", integration_id),
        "description": data.get("description"),
        "version": data.get("version"),
        "icon": data.get("icon", "Plug"),
        "is_enabled": row_is_enabled,
        "source": row_source,
        "source_path": row_source_path,
        "content_hash": row_content_hash,
    }

    return _manifests[integration_id]


def collect_integration_mcp_servers(channel_integrations, exclude: set[str] | None = None) -> list[str]:
    """Return MCP server IDs from activated channel integrations.

    Used by both channel_overrides and context_assembly to inject
    integration-declared MCP servers into a bot's tool set.
    """
    result: list[str] = []
    _exclude = exclude or set()
    for ci in (channel_integrations or []):
        if not getattr(ci, "activated", False):
            continue
        manifest = get_manifest(getattr(ci, "integration_type", ""))
        if not manifest:
            continue
        for srv in manifest.get("mcp_servers", []):
            srv_id = srv.get("id") if isinstance(srv, dict) else None
            if srv_id and srv_id not in _exclude and srv_id not in result:
                result.append(srv_id)
    return result


# ---------------------------------------------------------------------------
# Capabilities & provides
# ---------------------------------------------------------------------------

def get_capabilities(integration_id: str) -> frozenset[str] | None:
    """Return capabilities from the manifest cache, or None if not declared.

    Returns string values matching ``Capability`` StrEnum members so this
    module doesn't need to import ``Capability``.
    """
    manifest = _manifests.get(integration_id)
    if not manifest:
        return None
    caps = manifest.get("capabilities")
    if caps is None:
        return None
    return frozenset(caps)


def set_detected_provides(integration_id: str, detected: set[str]) -> None:
    """Store auto-detected module list on the in-memory manifest."""
    if integration_id in _manifests:
        _manifests[integration_id]["_detected_provides"] = sorted(detected)


def validate_capabilities() -> None:
    """Check that YAML-declared capabilities use valid Capability enum values."""
    from app.domain.capability import Capability
    valid = {c.value for c in Capability}
    for iid, manifest in _manifests.items():
        caps = manifest.get("capabilities")
        if not caps:
            continue
        unknown = set(caps) - valid
        if unknown:
            logger.warning(
                "Integration '%s' declares unknown capabilities: %s (valid: %s)",
                iid, sorted(unknown), sorted(valid),
            )


def validate_provides() -> None:
    """Warn if declared ``provides`` modules don't match detected modules."""
    for iid, manifest in _manifests.items():
        declared = set(manifest.get("provides", []))
        detected = set(manifest.get("_detected_provides", []))
        if not declared:
            continue
        missing = declared - detected
        extra = detected - declared
        if missing:
            logger.warning(
                "Integration '%s' declares provides=%s but modules not found: %s",
                iid, sorted(declared), sorted(missing),
            )
        if extra:
            logger.info(
                "Integration '%s' has undeclared modules: %s (consider adding to provides)",
                iid, sorted(extra),
            )


def validate_manifest_consistency() -> None:
    """Cross-check manifests against runtime registries after discovery."""
    from app.integrations import renderer_registry
    from app.agent.hooks import get_integration_meta

    for iid, manifest in _manifests.items():
        caps = manifest.get("capabilities")
        if caps and not renderer_registry.get(iid):
            logger.warning(
                "Integration '%s' declares capabilities but has no registered renderer",
                iid,
            )

        binding = manifest.get("binding", {})
        if binding.get("client_id_prefix") and not get_integration_meta(iid):
            logger.warning(
                "Integration '%s' has binding.client_id_prefix but no IntegrationMeta registered",
                iid,
            )


async def check_file_drift(integration_id: str) -> dict | None:
    """Check if the on-disk YAML has changed since seeding.

    Returns {'drifted': True, 'disk_hash': '...'} if changed, None if not.
    """
    manifest = _manifests.get(integration_id)
    if not manifest or manifest.get("source") != "yaml":
        return None

    source_path = manifest.get("source_path")
    if not source_path:
        return None

    path = Path(source_path)
    if not path.exists():
        return {"drifted": True, "disk_hash": None, "reason": "file_missing"}

    disk_hash = _file_hash(path)
    stored_hash = manifest.get("content_hash")
    if disk_hash != stored_hash:
        return {"drifted": True, "disk_hash": disk_hash, "reason": "content_changed"}

    return None
