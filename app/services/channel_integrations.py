"""Channel integration binding and activation policy.

This module owns the host-side lifecycle for ``ChannelIntegration`` rows.
Routers should only handle auth and wire mapping; callers that need binding or
activation behavior should come through this service.
"""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Channel, ChannelIntegration
from app.domain.errors import ConflictError, NotFoundError, ValidationError


@dataclass
class ActivationResult:
    integration_type: str
    activated: bool
    manifest: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


async def _require_channel(db: AsyncSession, channel_id: uuid.UUID) -> Channel:
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise NotFoundError("Channel not found")
    return channel


def _activation_stub_client_id(integration_type: str, channel_id: uuid.UUID) -> str:
    return f"mc-activated:{integration_type}:{channel_id}"


def resolve_activation_client_id(integration_type: str, channel_id: uuid.UUID) -> str:
    """Resolve an activation client_id from binding metadata, with stub fallback."""
    from integrations import discover_binding_metadata
    from app.services.integration_settings import get_value

    binding = discover_binding_metadata().get(integration_type)
    if not binding:
        return _activation_stub_client_id(integration_type, channel_id)

    template = binding.get("auto_client_id")
    if not template:
        return _activation_stub_client_id(integration_type, channel_id)

    def _sub(match: re.Match) -> str:
        return get_value(integration_type, match.group(1))

    resolved = re.sub(r"\{(\w+)\}", _sub, template)

    prefix = binding.get("client_id_prefix", "")
    if resolved == prefix or not resolved or resolved == template:
        return _activation_stub_client_id(integration_type, channel_id)
    return resolved


def _safe_activation_client_id(integration_type: str, channel_id: uuid.UUID) -> str:
    try:
        return resolve_activation_client_id(integration_type, channel_id)
    except Exception:
        return _activation_stub_client_id(integration_type, channel_id)


async def list_channel_bindings(
    db: AsyncSession,
    channel_id: uuid.UUID,
) -> list[ChannelIntegration]:
    """Return integration bindings for a channel, ordered by creation time."""
    await _require_channel(db, channel_id)
    bindings = (await db.execute(
        select(ChannelIntegration)
        .where(ChannelIntegration.channel_id == channel_id)
        .order_by(ChannelIntegration.created_at)
    )).scalars().all()
    return list(bindings)


async def bind_channel_integration(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
    client_id: str,
    dispatch_config: dict | None = None,
    display_name: str | None = None,
) -> ChannelIntegration:
    """Bind an integration to a channel. Raises on duplicate channel client_id."""
    await _require_channel(db, channel_id)

    existing = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.client_id == client_id,
            ChannelIntegration.channel_id == channel_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise ConflictError(f"client_id '{client_id}' is already bound to this channel")

    binding = ChannelIntegration(
        channel_id=channel_id,
        integration_type=integration_type,
        client_id=client_id,
        dispatch_config=dispatch_config,
        display_name=display_name,
    )
    db.add(binding)
    await db.flush()
    return binding


async def unbind_channel_integration(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    binding_id: uuid.UUID,
) -> None:
    """Remove an integration binding from a channel."""
    binding = await db.get(ChannelIntegration, binding_id)
    if not binding or binding.channel_id != channel_id:
        raise NotFoundError("Binding not found")
    await db.delete(binding)
    await db.flush()


async def adopt_channel_integration(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    binding_id: uuid.UUID,
    target_channel_id: uuid.UUID,
) -> ChannelIntegration:
    """Move an existing binding from one channel to another."""
    binding = await db.get(ChannelIntegration, binding_id)
    if not binding or binding.channel_id != channel_id:
        raise NotFoundError("Binding not found")
    target = await db.get(Channel, target_channel_id)
    if target is None:
        raise ValidationError(f"Target channel {target_channel_id} not found")

    binding.channel_id = target_channel_id
    db.add(binding)
    await db.flush()
    return binding


async def _find_active_row(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
) -> ChannelIntegration | None:
    return (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalar_one_or_none()


async def _inactive_rows(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
) -> list[ChannelIntegration]:
    rows = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == False,  # noqa: E712
        )
    )).scalars().all()
    return list(rows)


def _best_inactive_row(rows: list[ChannelIntegration]) -> ChannelIntegration | None:
    return next(
        (row for row in rows if not row.client_id.startswith("mc-activated:")),
        None,
    ) or (rows[0] if rows else None)


async def _activate_row(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
    preserve_real_client_id: bool,
) -> ChannelIntegration | None:
    existing = await _find_active_row(
        db,
        channel_id=channel_id,
        integration_type=integration_type,
    )
    if existing:
        return None

    client_id = _safe_activation_client_id(integration_type, channel_id)
    inactive = _best_inactive_row(await _inactive_rows(
        db,
        channel_id=channel_id,
        integration_type=integration_type,
    ))
    if inactive:
        inactive.activated = True
        if not preserve_real_client_id or inactive.client_id.startswith("mc-activated:"):
            inactive.client_id = client_id
        db.add(inactive)
        return inactive

    row = ChannelIntegration(
        channel_id=channel_id,
        integration_type=integration_type,
        client_id=client_id,
        activated=True,
    )
    db.add(row)
    return row


async def _activate_includes(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    manifest: dict[str, Any],
    manifests: dict[str, dict],
) -> None:
    for included_id in manifest.get("includes", []):
        if included_id not in manifests:
            continue
        await _activate_row(
            db,
            channel_id=channel_id,
            integration_type=included_id,
            preserve_real_client_id=False,
        )


async def activate_channel_integration(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
    validate_features: bool = True,
) -> ActivationResult:
    """Activate an integration on a channel and activate declared includes."""
    from integrations import get_activation_manifests

    channel = await _require_channel(db, channel_id)
    manifests = get_activation_manifests()
    manifest = manifests.get(integration_type)
    if not manifest:
        raise NotFoundError(f"No activation manifest for '{integration_type}'")

    existing = await _find_active_row(
        db,
        channel_id=channel_id,
        integration_type=integration_type,
    )
    if existing:
        return ActivationResult(
            integration_type=integration_type,
            activated=True,
            manifest=manifest,
            warnings=[],
        )

    await _activate_row(
        db,
        channel_id=channel_id,
        integration_type=integration_type,
        preserve_real_client_id=True,
    )
    await _activate_includes(
        db,
        channel_id=channel_id,
        manifest=manifest,
        manifests=manifests,
    )
    await db.commit()

    warnings: list[dict[str, Any]] = []
    if validate_features:
        try:
            from app.services.feature_validation import validate_activation

            feature_warnings = await validate_activation(channel.bot_id, integration_type)
            warnings = [warning.to_dict() for warning in feature_warnings]
        except Exception:
            warnings = []

    return ActivationResult(
        integration_type=integration_type,
        activated=True,
        manifest=manifest,
        warnings=warnings,
    )


async def activate_channel_integrations_for_create(
    db: AsyncSession,
    *,
    channel: Channel,
    integration_types: list[str] | None,
) -> list[dict[str, str]]:
    """Apply create-wizard activation requests before the channel transaction commits."""
    from integrations import get_activation_manifests

    if not integration_types:
        return []

    manifests = get_activation_manifests()
    warnings: list[dict[str, str]] = []
    for integration_type in integration_types:
        manifest = manifests.get(integration_type)
        if not manifest:
            warnings.append({
                "code": "unknown_integration",
                "message": f"No activation manifest for '{integration_type}'",
            })
            continue
        await _activate_row(
            db,
            channel_id=channel.id,
            integration_type=integration_type,
            preserve_real_client_id=True,
        )
        await _activate_includes(
            db,
            channel_id=channel.id,
            manifest=manifest,
            manifests=manifests,
        )
    return warnings


async def deactivate_channel_integration(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
) -> dict[str, Any]:
    """Deactivate an integration and unneeded included integrations on a channel."""
    from integrations import get_activation_manifests

    await _require_channel(db, channel_id)
    manifests = get_activation_manifests()

    rows = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.integration_type == integration_type,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalars().all()
    for row in rows:
        row.activated = False
        db.add(row)

    await db.flush()

    manifest = manifests.get(integration_type, {})
    for included_id in manifest.get("includes", []):
        still_needed = False
        for other_type, other_manifest in manifests.items():
            if other_type == integration_type:
                continue
            if included_id not in other_manifest.get("includes", []):
                continue
            if await _find_active_row(
                db,
                channel_id=channel_id,
                integration_type=other_type,
            ):
                still_needed = True
                break
        if still_needed:
            continue

        included_rows = (await db.execute(
            select(ChannelIntegration).where(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.integration_type == included_id,
                ChannelIntegration.activated == True,  # noqa: E712
            )
        )).scalars().all()
        for row in included_rows:
            row.activated = False
            db.add(row)

    await db.commit()
    return {"ok": True, "integration_type": integration_type, "activated": False}


async def list_activation_options(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """List activation manifests with channel-specific activation state."""
    from integrations import get_activation_manifests

    await _require_channel(db, channel_id)
    manifests = get_activation_manifests()

    ci_rows = (await db.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalars().all()
    active_by_type = {row.integration_type: row for row in ci_rows}

    result: list[dict[str, Any]] = []
    for integration_type, manifest in manifests.items():
        row = active_by_type.get(integration_type)
        result.append({
            "integration_type": integration_type,
            "description": manifest.get("description", ""),
            "requires_workspace": manifest.get("requires_workspace", False),
            "activated": integration_type in active_by_type,
            "tools": list(manifest.get("tools", []) or []),
            "has_system_prompt": bool(manifest.get("system_prompt")),
            "version": manifest.get("version"),
            "includes": manifest.get("includes", []),
            "activation_config": (row.activation_config or {}) if row else {},
            "config_fields": manifest.get("config_fields", []),
            "included_by": [],
        })

    by_type = {item["integration_type"]: item for item in result}
    for item in result:
        for included_id in item["includes"]:
            included = by_type.get(included_id)
            if included:
                included["included_by"].append(item["integration_type"])
    return result


async def update_activation_config(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID,
    integration_type: str,
    config: dict,
) -> dict[str, Any]:
    """Merge config values into an active integration row."""
    row = await _find_active_row(
        db,
        channel_id=channel_id,
        integration_type=integration_type,
    )
    if not row:
        raise NotFoundError("Activated integration not found on this channel")

    merged = copy.deepcopy(row.activation_config or {})
    merged.update(config)
    row.activation_config = merged
    flag_modified(row, "activation_config")
    await db.commit()
    return {"ok": True, "activation_config": merged}


def list_global_activation_options() -> list[dict[str, Any]]:
    """List activatable integrations without channel state."""
    from integrations import get_activation_manifests

    return [
        {
            "integration_type": integration_type,
            "description": manifest.get("description", ""),
            "requires_workspace": manifest.get("requires_workspace", False),
            "activated": False,
            "tools": list(manifest.get("tools", []) or []),
            "has_system_prompt": bool(manifest.get("system_prompt")),
            "version": manifest.get("version"),
            "includes": manifest.get("includes", []),
        }
        for integration_type, manifest in get_activation_manifests().items()
    ]


def list_bindable_integrations() -> list[dict[str, Any]]:
    """List registered user-facing integration types with binding metadata."""
    from app.integrations import renderer_registry
    from integrations import discover_binding_metadata, discover_integrations

    types = set(renderer_registry.all_renderers().keys()) - {
        "none", "web", "webhook", "internal",
    }
    for integration_id, _router in discover_integrations():
        types.add(integration_id)

    binding_meta = discover_binding_metadata()
    return [
        {
            "type": integration_type,
            "binding": binding_meta.get(integration_type),
        }
        for integration_type in sorted(types)
    ]
