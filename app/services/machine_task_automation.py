from __future__ import annotations

import logging
from typing import Any

from app.db.models import TaskMachineGrant
from app.services.integration_manifests import get_manifest, parse_integration_yaml
from app.services.integration_settings import get_status, is_configured
from integrations.discovery import iter_integration_candidates

logger = logging.getLogger(__name__)

TASK_MACHINE_AUTOMATION_CAPABILITIES = ("inspect", "exec")
TASK_MACHINE_STEP_TYPES = {
    "inspect": {"type": "machine_inspect", "label": "Machine inspect", "capability": "inspect"},
    "exec": {"type": "machine_exec", "label": "Machine exec", "capability": "exec"},
}


def _provider_manifest(provider_id: str) -> dict[str, Any]:
    manifest = get_manifest(provider_id)
    if manifest:
        return manifest
    for candidate, integration_id, _is_external, _source in iter_integration_candidates():
        if integration_id != provider_id:
            continue
        yaml_path = candidate / "integration.yaml"
        if not yaml_path.exists():
            return {}
        try:
            return parse_integration_yaml(yaml_path)
        except Exception:
            logger.debug("Failed to parse integration manifest for %s", provider_id, exc_info=True)
            return {}
    return {}


def provider_task_automation_block(provider_id: str) -> dict[str, Any]:
    manifest = _provider_manifest(provider_id)
    block = manifest.get("machine_control")
    if not isinstance(block, dict):
        return {}
    task_automation = block.get("task_automation")
    return task_automation if isinstance(task_automation, dict) else {}


def normalize_task_automation_capabilities(raw: Any = None) -> list[str]:
    values = raw if isinstance(raw, list) else TASK_MACHINE_AUTOMATION_CAPABILITIES
    requested = {str(value).strip() for value in values}
    return [capability for capability in TASK_MACHINE_AUTOMATION_CAPABILITIES if capability in requested]


def get_provider_task_automation_capabilities(provider_id: str) -> list[str]:
    task_automation = provider_task_automation_block(provider_id)
    if not task_automation.get("enabled"):
        return []
    return normalize_task_automation_capabilities(task_automation.get("capabilities"))


def provider_supports_task_machine_automation(
    provider_id: str,
    *,
    capability: str | None = None,
) -> bool:
    if get_status(provider_id) != "enabled" or not is_configured(provider_id):
        return False
    capabilities = get_provider_task_automation_capabilities(provider_id)
    if capability is not None:
        return capability in capabilities
    return bool(capabilities)


def machine_step_required_capabilities(steps: list[dict] | None) -> list[str]:
    required: set[str] = set()

    def visit(items: list[dict] | None) -> None:
        for step in items or []:
            if not isinstance(step, dict):
                continue
            step_type = step.get("type")
            if step_type == "machine_inspect":
                required.add("inspect")
            elif step_type == "machine_exec":
                required.add("exec")
            nested = step.get("do")
            if isinstance(nested, list):
                visit(nested)

    visit(steps)
    return [capability for capability in TASK_MACHINE_AUTOMATION_CAPABILITIES if capability in required]


def _diagnostic(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def provider_display_label(provider_id: str) -> str:
    manifest = _provider_manifest(provider_id)
    block = manifest.get("machine_control")
    if isinstance(block, dict) and block.get("label"):
        return str(block["label"])
    if manifest.get("name"):
        return str(manifest["name"])
    return provider_id.replace("_", " ").replace("-", " ").title()


def task_machine_automation_diagnostics(
    grant: TaskMachineGrant | None,
    *,
    steps: list[dict] | None = None,
) -> list[dict[str, str]]:
    required_capabilities = machine_step_required_capabilities(steps)
    if grant is None:
        if required_capabilities:
            return [
                _diagnostic(
                    "warning",
                    "machine_grant_missing",
                    "This pipeline has machine steps but no machine target grant.",
                ),
            ]
        return []

    diagnostics: list[dict[str, str]] = []
    advertised_capabilities = get_provider_task_automation_capabilities(grant.provider_id)
    if get_status(grant.provider_id) != "enabled" or not is_configured(grant.provider_id) or not advertised_capabilities:
        diagnostics.append(
            _diagnostic(
                "warning",
                "provider_not_available",
                "The granted machine provider is no longer available for scheduled task automation.",
            ),
        )
    for capability in required_capabilities:
        if capability not in advertised_capabilities:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "provider_capability_missing",
                    f"The granted machine provider no longer advertises scheduled '{capability}' automation.",
                ),
            )
        if capability not in set(grant.capabilities or []):
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "grant_capability_missing",
                    f"The task grant does not include the '{capability}' capability required by this pipeline.",
                ),
            )

    try:
        from app.services.machine_control import get_provider

        provider = get_provider(grant.provider_id)
        target = provider.get_target(grant.target_id)
        if target is None:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "target_missing",
                    "The granted machine target no longer exists.",
                ),
            )
        else:
            status = provider.get_target_status(grant.target_id) or {}
            if status and not bool(status.get("ready")):
                diagnostics.append(
                    _diagnostic(
                        "info",
                        "target_not_ready",
                        str(status.get("reason") or "The granted machine target is not currently ready."),
                    ),
                )
    except Exception:
        logger.exception("Failed to inspect task machine automation grant provider %s", grant.provider_id)
        diagnostics.append(
            _diagnostic(
                "warning",
                "provider_load_failed",
                "The granted machine provider could not be loaded.",
            ),
        )
    return diagnostics


def build_machine_task_automation_options() -> dict[str, Any]:
    from app.services.machine_control import build_targets_status, get_provider, list_provider_ids

    providers: list[dict[str, Any]] = []
    available_capabilities: set[str] = set()
    for provider_id in list_provider_ids():
        capabilities = get_provider_task_automation_capabilities(provider_id)
        if not capabilities:
            continue
        if get_status(provider_id) != "enabled" or not is_configured(provider_id):
            continue
        try:
            provider = get_provider(provider_id)
        except Exception:
            logger.exception("Failed to load machine-control provider %s", provider_id)
            continue
        targets = build_targets_status(provider_id=provider_id)
        if not targets:
            continue
        task_automation = provider_task_automation_block(provider_id)
        available_capabilities.update(capabilities)
        providers.append({
            "provider_id": provider_id,
            "provider_label": getattr(provider, "label", None) or provider_display_label(provider_id),
            "driver": getattr(provider, "driver", None) or "unknown",
            "label": str(task_automation.get("label") or getattr(provider, "label", None) or provider_display_label(provider_id)),
            "target_label": str(task_automation.get("target_label") or "Machine target"),
            "description": str(task_automation.get("description") or "") or None,
            "capabilities": capabilities,
            "targets": targets,
            "target_count": len(targets),
            "ready_target_count": sum(1 for target in targets if target.get("ready")),
        })
    return {
        "providers": providers,
        "step_types": [
            TASK_MACHINE_STEP_TYPES[capability]
            for capability in TASK_MACHINE_AUTOMATION_CAPABILITIES
            if capability in available_capabilities
        ],
    }
