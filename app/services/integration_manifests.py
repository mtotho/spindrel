"""Integration manifest service: YAML-first, DB-backed, UI-editable.

Integrations can be defined via integration.yaml (declarative) or setup.py (legacy).

YAML manifests:
  - Seeded on first startup. DB is source of truth after that — the YAML file on
    disk is never overwritten and changes to it are *reported* via
    ``check_file_drift`` but not auto-applied. The user reconciles via the UI editor.

setup.py manifests:
  - Re-synced on every startup. setup.py is the only source — there is no UI
    editor for these rows (``yaml_content`` is NULL). When the file's content
    hash changes, the DB row is updated in place via ``ON CONFLICT DO UPDATE``.
    No drift reporting is needed because drift can never exist between
    consecutive startups.
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
    "id", "name", "icon", "description", "version", "includes",
    "mcp_servers", "settings", "activation", "oauth", "webhook",
    "binding", "dependencies", "docker_compose", "web_ui",
    "chat_hud", "chat_hud_presets", "sidebar_section",
    "debug_actions", "api_permissions", "dashboard_modules",
    "target", "process", "capabilities", "provides",
}

# Keys passed through as-is between manifest and SETUP dict formats.
# Shared between setup_dict_to_manifest() and _manifest_to_setup() in integrations/__init__.py.
PASSTHROUGH_KEYS = (
    "activation", "oauth", "webhook", "binding", "includes",
    "mcp_servers", "docker_compose", "web_ui", "chat_hud",
    "chat_hud_presets", "sidebar_section", "debug_actions",
    "api_permissions", "dashboard_modules",
    "target", "process", "capabilities", "provides",
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

    unknown = set(data.keys()) - _KNOWN_KEYS
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
# Setup.py → manifest conversion
# ---------------------------------------------------------------------------

def setup_dict_to_manifest(integration_id: str, setup: dict) -> dict:
    """Convert a legacy SETUP dict from setup.py into a manifest-shaped dict."""
    manifest: dict = {"id": integration_id}

    manifest["name"] = setup.get("name", integration_id.replace("_", " ").replace("-", " ").title())
    manifest["icon"] = setup.get("icon", "Plug")
    manifest["description"] = setup.get("description")
    manifest["version"] = setup.get("version")

    # Map env_vars → settings
    if "env_vars" in setup:
        manifest["settings"] = [
            {
                "key": ev["key"],
                "type": ev.get("type", "string"),
                "label": ev.get("description", ev["key"]),
                "required": ev.get("required", False),
                "secret": ev.get("secret", False),
                "default": ev.get("default"),
            }
            for ev in setup["env_vars"]
        ]

    # Copy through all other known fields
    for key in PASSTHROUGH_KEYS:
        if key in setup:
            manifest[key] = setup[key]

    # Dependencies
    deps = {}
    if "python_dependencies" in setup:
        deps["python"] = setup["python_dependencies"]
    if "npm_dependencies" in setup:
        deps["npm"] = setup["npm_dependencies"]
    if deps:
        manifest["dependencies"] = deps

    return manifest


# ---------------------------------------------------------------------------
# DB seeding and loading
# ---------------------------------------------------------------------------

async def seed_manifests() -> None:
    """Scan all integration dirs and synchronize manifests to DB.

    YAML manifests use INSERT ON CONFLICT DO NOTHING — seeded once, then
    edited via the UI. File-on-disk drift is *reported* via check_file_drift,
    not auto-applied (the UI editor is the canonical edit surface).

    setup.py manifests use INSERT ON CONFLICT DO UPDATE keyed on content_hash —
    the file on disk is the only source (yaml_content is NULL, no UI editor),
    so any change to setup.py must propagate on the next startup. Without
    this, env_vars added to setup.py would never appear in the admin UI.
    """
    from integrations import _iter_integration_candidates
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    candidates = _iter_integration_candidates()
    if not candidates:
        return

    yaml_seeded = 0
    setup_seeded = 0
    setup_refreshed = 0
    async with async_session() as db:
        for candidate_dir, integration_id, _is_external, source in candidates:
            yaml_path = candidate_dir / "integration.yaml"

            if yaml_path.exists():
                try:
                    data = parse_integration_yaml(yaml_path)
                    raw_content = yaml_path.read_text()
                    content_hash = _file_hash(yaml_path)
                except Exception:
                    logger.error("Failed to parse %s", yaml_path, exc_info=True)
                    continue

                # Check if an existing row was seeded from setup.py — if so,
                # the integration has migrated from setup.py to YAML and the
                # row needs to be upgraded (otherwise ON CONFLICT DO NOTHING
                # would keep the stale setup.py data forever).
                existing = await db.get(IntegrationManifest, data["id"])
                if existing and existing.source == "setup_py":
                    existing.name = data.get("name", integration_id)
                    existing.description = data.get("description")
                    existing.version = data.get("version")
                    existing.icon = data.get("icon", "Plug")
                    existing.manifest = data
                    existing.yaml_content = raw_content
                    existing.source = "yaml"
                    existing.source_path = str(yaml_path)
                    existing.content_hash = content_hash
                    yaml_seeded += 1
                    logger.info(
                        "Upgraded manifest '%s' from setup.py → YAML",
                        data["id"],
                    )
                else:
                    stmt = pg_insert(IntegrationManifest).values(
                        id=data["id"],
                        name=data.get("name", integration_id),
                        description=data.get("description"),
                        version=data.get("version"),
                        icon=data.get("icon", "Plug"),
                        manifest=data,
                        yaml_content=raw_content,
                        is_enabled=True,
                        source="yaml",
                        source_path=str(yaml_path),
                        content_hash=content_hash,
                    ).on_conflict_do_nothing(index_elements=["id"])
                    await db.execute(stmt)
                    yaml_seeded += 1
                    logger.debug("Seeded YAML manifest '%s' from %s", data["id"], yaml_path)

            else:
                # Try setup.py for legacy integrations
                setup_file = candidate_dir / "setup.py"
                if not setup_file.exists():
                    continue
                try:
                    import importlib.util
                    mod_name = f"_seed_setup_{integration_id}"
                    spec = importlib.util.spec_from_file_location(mod_name, setup_file)
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    setup_dict = getattr(mod, "SETUP", None)
                    if not setup_dict or not isinstance(setup_dict, dict):
                        continue
                    data = setup_dict_to_manifest(integration_id, setup_dict)
                    content_hash = _file_hash(setup_file)
                except Exception:
                    logger.debug("Could not read setup.py for '%s'", integration_id, exc_info=True)
                    continue

                # Look up the existing row's hash so we can log seed-vs-refresh
                # accurately. (The UPSERT below is idempotent regardless.)
                existing = await db.get(IntegrationManifest, integration_id)
                existing_hash = existing.content_hash if existing else None

                base_stmt = pg_insert(IntegrationManifest).values(
                    id=integration_id,
                    name=data.get("name", integration_id),
                    description=data.get("description"),
                    version=data.get("version"),
                    icon=data.get("icon", "Plug"),
                    manifest=data,
                    yaml_content=None,
                    is_enabled=True,
                    source="setup_py",
                    source_path=str(setup_file),
                    content_hash=content_hash,
                )
                # ON CONFLICT DO UPDATE — but only when the file content has
                # actually changed. The IS DISTINCT FROM filter keeps updated_at
                # stable across no-op startups so the row's mtime is meaningful.
                stmt = base_stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": base_stmt.excluded.name,
                        "description": base_stmt.excluded.description,
                        "version": base_stmt.excluded.version,
                        "icon": base_stmt.excluded.icon,
                        "manifest": base_stmt.excluded.manifest,
                        "source": base_stmt.excluded.source,
                        "source_path": base_stmt.excluded.source_path,
                        "content_hash": base_stmt.excluded.content_hash,
                        "updated_at": text("now()"),
                    },
                    where=IntegrationManifest.content_hash.is_distinct_from(
                        base_stmt.excluded.content_hash
                    ),
                )
                await db.execute(stmt)

                if existing is None:
                    setup_seeded += 1
                    logger.info(
                        "Seeded new setup.py manifest '%s' (hash=%s)",
                        integration_id, content_hash[:8],
                    )
                elif existing_hash != content_hash:
                    setup_refreshed += 1
                    logger.info(
                        "Refreshed setup.py manifest '%s' (hash %s → %s) — "
                        "setup.py changed since last startup",
                        integration_id,
                        (existing_hash or "none")[:8],
                        content_hash[:8],
                    )
                else:
                    logger.debug(
                        "setup.py manifest '%s' unchanged (hash=%s)",
                        integration_id, content_hash[:8],
                    )

        await db.commit()

    logger.info(
        "Manifest seed complete: %d YAML seeded, %d setup.py seeded, %d setup.py refreshed",
        yaml_seeded, setup_seeded, setup_refreshed,
    )


async def load_manifests() -> None:
    """Load all manifests from DB into in-memory cache."""
    from app.db.engine import async_session
    from app.db.models import IntegrationManifest

    _manifests.clear()

    async with async_session() as db:
        rows = (await db.execute(select(IntegrationManifest))).scalars().all()

    for row in rows:
        _manifests[row.id] = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "version": row.version,
            "icon": row.icon,
            "is_enabled": row.is_enabled,
            "source": row.source,
            "source_path": row.source_path,
            "content_hash": row.content_hash,
            **(row.manifest or {}),
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

        row.name = data.get("name", row.name)
        row.description = data.get("description")
        row.version = data.get("version")
        row.icon = data.get("icon", "Plug")
        row.manifest = data
        row.yaml_content = new_yaml
        await db.commit()

    # Update cache
    _manifests[integration_id] = {
        "id": integration_id,
        "name": data.get("name", integration_id),
        "description": data.get("description"),
        "version": data.get("version"),
        "icon": data.get("icon", "Plug"),
        "is_enabled": True,
        "source": row_source,
        "source_path": row_source_path,
        "content_hash": row_content_hash,
        **data,
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
