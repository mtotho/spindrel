"""Manifest-declared shared runtime service resolution.

Runtime services are sidecar capabilities one integration can provide for
another without duplicating containers.  They intentionally model only the
runtime endpoint and owner; the consumer still decides which tools to expose.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.services.integration_manifests import get_all_manifests, get_manifest
from app.services.integration_settings import get_value


@dataclass(frozen=True)
class RuntimeServiceResolution:
    capability: str
    endpoint: str | None
    provider_integration_id: str | None
    source: str
    protocol: str | None = None
    browser: str | None = None
    service: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.endpoint)


def _runtime_section(manifest: dict[str, Any] | None) -> dict[str, Any]:
    section = (manifest or {}).get("runtime_services")
    return section if isinstance(section, dict) else {}


def _iter_list(section: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = section.get(key)
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, dict)]


def _instance_id() -> str:
    return settings.SPINDREL_INSTANCE_ID or os.environ.get("SPINDREL_INSTANCE_ID", "").strip() or "default"


def interpolate_endpoint(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("${SPINDREL_INSTANCE_ID}", _instance_id()).replace(
        "${SPINDREL_INSTANCE_ID:-default}",
        _instance_id(),
    )


def provides_for(integration_id: str) -> list[dict[str, Any]]:
    return _iter_list(_runtime_section(get_manifest(integration_id)), "provides")


def requirements_for(integration_id: str) -> list[dict[str, Any]]:
    return [
        req
        for req in _iter_list(_runtime_section(get_manifest(integration_id)), "requires")
        if requirement_applies(integration_id, req)
    ]


def requirement_applies(integration_id: str, requirement: dict[str, Any]) -> bool:
    when = requirement.get("when")
    if not isinstance(when, dict):
        return True
    setting = when.get("setting")
    if not setting:
        return True
    values = when.get("values")
    value = get_value(integration_id, str(setting), "")
    if isinstance(values, list):
        return value in {str(v) for v in values}
    equals = when.get("equals")
    if equals is not None:
        return value == str(equals)
    return bool(value)


def external_override(integration_id: str, requirement: dict[str, Any]) -> str | None:
    setting = requirement.get("override_setting")
    if not setting:
        return None
    value = get_value(integration_id, str(setting), "").strip()
    return value or None


def _provider_matches(provider: dict[str, Any], capability: str) -> bool:
    return str(provider.get("capability") or "").strip() == capability


def resolve_runtime_requirement(
    integration_id: str,
    capability: str,
) -> RuntimeServiceResolution:
    raw_requirements = _iter_list(_runtime_section(get_manifest(integration_id)), "requires")
    has_matching_requirement = any(
        str(req.get("capability") or "").strip() == capability
        for req in raw_requirements
    )
    for requirement in requirements_for(integration_id):
        if str(requirement.get("capability") or "").strip() != capability:
            continue
        override = external_override(integration_id, requirement)
        if override:
            return RuntimeServiceResolution(
                capability=capability,
                endpoint=interpolate_endpoint(override),
                provider_integration_id=None,
                source="external",
                protocol=requirement.get("protocol"),
                browser=requirement.get("browser"),
            )
        break

    if has_matching_requirement:
        active_match = any(
            str(req.get("capability") or "").strip() == capability
            for req in requirements_for(integration_id)
        )
        if not active_match:
            return RuntimeServiceResolution(
                capability=capability,
                endpoint=None,
                provider_integration_id=None,
                source="missing",
            )

    for provider_id, manifest in get_all_manifests().items():
        for provider in _iter_list(_runtime_section(manifest), "provides"):
            if not _provider_matches(provider, capability):
                continue
            return RuntimeServiceResolution(
                capability=capability,
                endpoint=interpolate_endpoint(provider.get("endpoint")),
                provider_integration_id=provider_id,
                source="integration",
                protocol=provider.get("protocol"),
                browser=provider.get("browser"),
                service=provider.get("service"),
            )

    return RuntimeServiceResolution(
        capability=capability,
        endpoint=None,
        provider_integration_id=None,
        source="missing",
    )


def required_provider_ids(integration_id: str) -> list[str]:
    providers: list[str] = []
    for requirement in requirements_for(integration_id):
        if external_override(integration_id, requirement):
            continue
        capability = str(requirement.get("capability") or "").strip()
        if not capability:
            continue
        resolved = resolve_runtime_requirement(integration_id, capability)
        if resolved.provider_integration_id and resolved.provider_integration_id not in providers:
            providers.append(resolved.provider_integration_id)
    return providers


async def ensure_required_providers_enabled(integration_id: str) -> list[str]:
    """Enable missing provider integrations for active runtime requirements.

    Side effects such as tool loading and Docker sync stay with callers that
    already own those lifecycle transitions.
    """
    from app.services.integration_settings import get_status, set_status

    enabled: list[str] = []
    for provider_id in required_provider_ids(integration_id):
        if get_status(provider_id) == "enabled":
            continue
        await set_status(provider_id, "enabled")
        enabled.append(provider_id)
    return enabled


async def ensure_required_providers_for_active_integrations() -> dict[str, list[str]]:
    """Enable runtime providers required by already-active consumers.

    This covers upgrade/startup recovery: an integration such as ``web_search``
    may already be enabled before a shared provider integration exists in the
    manifest set.  Running this before dependency/tool loading makes the new
    provider visible to the normal startup lifecycle.
    """
    from app.services.integration_settings import is_active

    enabled_by_consumer: dict[str, list[str]] = {}
    for integration_id in sorted(get_all_manifests()):
        if not is_active(integration_id):
            continue
        enabled = await ensure_required_providers_enabled(integration_id)
        if enabled:
            enabled_by_consumer[integration_id] = enabled
    return enabled_by_consumer
