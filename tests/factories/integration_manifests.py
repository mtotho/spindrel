"""Factory for app.db.models.IntegrationManifest."""
from __future__ import annotations

from app.db.models import IntegrationManifest


def build_integration_manifest(
    integration_id: str,
    **overrides,
) -> IntegrationManifest:
    """Return a minimal IntegrationManifest row with sensible defaults.

    ``manifest`` defaults to ``{"id": integration_id, "name": ...}`` so
    accessor tests that read ``row.manifest`` see a self-consistent payload.
    """
    name = overrides.pop("name", integration_id.replace("_", " ").title())
    default_manifest = {
        "id": integration_id,
        "name": name,
    }
    defaults = dict(
        id=integration_id,
        name=name,
        description=None,
        version=None,
        icon="Plug",
        manifest=default_manifest,
        yaml_content=f"id: {integration_id}\nname: {name}\n",
        is_enabled=False,
        source="yaml",
        source_path=f"/integrations/{integration_id}/integration.yaml",
        content_hash="seed-hash",
    )
    return IntegrationManifest(**{**defaults, **overrides})
