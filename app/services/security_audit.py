"""Security self-assessment across config, tool registry, and DB state.

Read-only diagnostic — no mutations, no new tables.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import list_bots
from app.config import settings
from app.db.models import MCPServer, MachineTargetLease, Session, ToolApproval, ToolPolicyRule
from app.services.encryption import is_encryption_enabled
from app.tools.mcp import get_configured_server_count
from app.tools.registry import get_all_tool_tiers, get_tool_execution_policy, get_tool_safety_tier

logger = logging.getLogger(__name__)

HIGH_RISK_BOT_API_SCOPES = {
    "*",
    "admin",
    "api_keys:write",
    "integrations:write",
    "mcp_servers:write",
    "operations:write",
    "providers:write",
    "secrets:write",
    "settings:write",
    "tools:execute",
    "users:write",
    "workspaces.files:write",
}

MACHINE_CONTROL_TOOL_CONTRACTS = {
    "machine_status": {"safety_tier": "readonly", "execution_policy": "interactive_user"},
    "machine_inspect_command": {"safety_tier": "readonly", "execution_policy": "live_target_lease"},
    "machine_exec_command": {"safety_tier": "exec_capable", "execution_policy": "live_target_lease"},
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Status(str, Enum):
    passed = "pass"
    fail = "fail"
    warning = "warning"


class SecurityCheck(BaseModel):
    id: str
    category: str
    severity: Severity
    status: Status
    message: str
    recommendation: str | None = None
    details: dict | None = None


class SecurityAuditResponse(BaseModel):
    checks: list[SecurityCheck]
    summary: dict
    score: int


# ---------------------------------------------------------------------------
# Config-only checks (no DB, no registry)
# ---------------------------------------------------------------------------

def _check_encryption_key() -> SecurityCheck:
    enabled = is_encryption_enabled()
    strict = bool(getattr(settings, "ENCRYPTION_STRICT", True))
    if enabled and strict:
        return SecurityCheck(
            id="encryption_key_configured",
            category="encryption",
            severity=Severity.critical,
            status=Status.passed,
            message="Encryption key is configured (strict mode on)",
            details={"strict": True},
        )
    if enabled and not strict:
        return SecurityCheck(
            id="encryption_key_configured",
            category="encryption",
            severity=Severity.critical,
            status=Status.warning,
            message="Encryption key is configured but strict mode is off",
            recommendation=(
                "Remove ENCRYPTION_STRICT=false (default true) so encrypt() "
                "fails fast if the key is ever lost or misconfigured."
            ),
            details={"strict": False},
        )
    return SecurityCheck(
        id="encryption_key_configured",
        category="encryption",
        severity=Severity.critical,
        status=Status.fail,
        message="No encryption key configured — secrets stored in plaintext",
        recommendation=(
            "Set ENCRYPTION_KEY in .env. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ),
        details={"strict": strict},
    )


def _check_admin_key_separation() -> SecurityCheck:
    admin_key = settings.ADMIN_API_KEY
    api_key = settings.API_KEY
    if admin_key and admin_key != api_key:
        return SecurityCheck(
            id="admin_key_separation",
            category="authentication",
            severity=Severity.critical,
            status=Status.passed,
            message="Admin API key is separate from bot API key",
        )
    return SecurityCheck(
        id="admin_key_separation",
        category="authentication",
        severity=Severity.critical,
        status=Status.fail,
        message="Admin API key is missing or identical to bot API key",
        recommendation="Set ADMIN_API_KEY to a value different from API_KEY",
    )


def _check_tool_policy_enabled() -> SecurityCheck:
    enabled = settings.TOOL_POLICY_ENABLED
    return SecurityCheck(
        id="tool_policy_enabled",
        category="tool_policies",
        severity=Severity.critical,
        status=Status.passed if enabled else Status.fail,
        message="Tool policy engine is enabled" if enabled else "Tool policy engine is disabled — all tool calls are uncontrolled",
        recommendation=None if enabled else "Set TOOL_POLICY_ENABLED=true in .env",
    )


def _check_default_policy_action() -> SecurityCheck:
    action = settings.TOOL_POLICY_DEFAULT_ACTION
    if action != "allow":
        return SecurityCheck(
            id="default_policy_action",
            category="tool_policies",
            severity=Severity.critical,
            status=Status.passed,
            message=f"Default policy action is '{action}'",
        )
    return SecurityCheck(
        id="default_policy_action",
        category="tool_policies",
        severity=Severity.critical,
        status=Status.fail,
        message="Default policy action is 'allow' — unmatched tools are permitted without rules",
        recommendation="Set TOOL_POLICY_DEFAULT_ACTION=deny to block unmatched tools by default",
    )


def _check_tier_gating() -> SecurityCheck:
    enabled = settings.TOOL_POLICY_TIER_GATING
    return SecurityCheck(
        id="tier_gating_enabled",
        category="tool_policies",
        severity=Severity.warning,
        status=Status.passed if enabled else Status.fail,
        message="Tier-based gating is enabled" if enabled else "Tier-based gating is disabled — safety tiers have no enforcement effect",
        recommendation=None if enabled else "Set TOOL_POLICY_TIER_GATING=true to auto-gate dangerous tool tiers",
    )


def _check_rate_limiting() -> SecurityCheck:
    enabled = settings.RATE_LIMIT_ENABLED
    return SecurityCheck(
        id="rate_limiting_enabled",
        category="rate_limiting",
        severity=Severity.warning,
        status=Status.passed if enabled else Status.fail,
        message="Rate limiting is enabled" if enabled else "Rate limiting is disabled",
        recommendation=None if enabled else "Set RATE_LIMIT_ENABLED=true to protect against abuse",
    )


def _check_secret_redaction() -> SecurityCheck:
    enabled = settings.SECRET_REDACTION_ENABLED
    return SecurityCheck(
        id="secret_redaction_enabled",
        category="secrets",
        severity=Severity.warning,
        status=Status.passed if enabled else Status.fail,
        message="Secret redaction is enabled" if enabled else "Secret redaction is disabled — tool outputs may leak secrets",
        recommendation=None if enabled else "Set SECRET_REDACTION_ENABLED=true",
    )


def _check_docker_sandbox() -> SecurityCheck:
    enabled = settings.DOCKER_SANDBOX_ENABLED
    return SecurityCheck(
        id="docker_sandbox_status",
        category="sandboxing",
        severity=Severity.info,
        status=Status.passed if enabled else Status.warning,
        message="Docker sandboxing is enabled" if enabled else "Docker sandboxing is disabled",
        details={"enabled": enabled},
    )


def _check_host_exec() -> SecurityCheck:
    enabled = settings.HOST_EXEC_ENABLED
    bots_with_exec = [b.id for b in list_bots() if b.host_exec.enabled]
    if not enabled and not bots_with_exec:
        return SecurityCheck(
            id="host_exec_status",
            category="execution",
            severity=Severity.info,
            status=Status.passed,
            message="Host execution is disabled globally and per-bot",
            details={"global_enabled": False, "bots_with_exec": []},
        )
    return SecurityCheck(
        id="host_exec_status",
        category="execution",
        severity=Severity.info,
        status=Status.warning,
        message=f"Host execution is {'globally enabled' if enabled else 'enabled for ' + str(len(bots_with_exec)) + ' bot(s)'}",
        details={"global_enabled": enabled, "bots_with_exec": bots_with_exec},
    )


def _check_audit_logging() -> SecurityCheck:
    enabled = settings.SECURITY_AUDIT_ENABLED
    return SecurityCheck(
        id="audit_logging_status",
        category="logging",
        severity=Severity.info,
        status=Status.passed if enabled else Status.warning,
        message="Security audit logging is enabled" if enabled else "Security audit logging is disabled",
        details={"enabled": enabled},
    )


# ---------------------------------------------------------------------------
# Tool registry checks (no DB)
# ---------------------------------------------------------------------------

def _check_tools_missing_tier() -> SecurityCheck:
    tiers = get_all_tool_tiers()
    unknown = [name for name, tier in tiers.items() if tier == "unknown"]
    if not unknown:
        return SecurityCheck(
            id="tools_missing_safety_tier",
            category="tool_policies",
            severity=Severity.warning,
            status=Status.passed,
            message=f"All {len(tiers)} registered tools have safety tiers assigned",
        )
    return SecurityCheck(
        id="tools_missing_safety_tier",
        category="tool_policies",
        severity=Severity.warning,
        status=Status.fail,
        message=f"{len(unknown)} tool(s) have no safety tier assigned",
        recommendation="Add safety_tier to @register() for these tools",
        details={"count": len(unknown), "tools": unknown[:20]},
    )


def _check_tool_tier_distribution() -> SecurityCheck:
    tiers = get_all_tool_tiers()
    distribution: dict[str, int] = {}
    for tier in tiers.values():
        distribution[tier] = distribution.get(tier, 0) + 1
    return SecurityCheck(
        id="tool_tier_distribution",
        category="tool_policies",
        severity=Severity.info,
        status=Status.passed,
        message=f"{len(tiers)} tools registered across {len(distribution)} tier(s)",
        details={"total": len(tiers), "by_tier": distribution},
    )


def _check_machine_control_tool_gates() -> SecurityCheck:
    mismatches = []
    observed = {}
    for tool_name, expected in MACHINE_CONTROL_TOOL_CONTRACTS.items():
        actual = {
            "safety_tier": get_tool_safety_tier(tool_name),
            "execution_policy": get_tool_execution_policy(tool_name),
        }
        observed[tool_name] = actual
        if actual != expected:
            mismatches.append({
                "tool": tool_name,
                "expected": expected,
                "actual": actual,
            })

    if mismatches:
        return SecurityCheck(
            id="machine_control_tool_gates",
            category="machine_control",
            severity=Severity.critical,
            status=Status.fail,
            message=f"{len(mismatches)} machine-control tool gate contract(s) drifted",
            recommendation=(
                "Keep machine_status behind interactive_user and command tools behind live_target_lease; "
                "machine_exec_command must remain exec_capable."
            ),
            details={"mismatches": mismatches, "observed": observed},
        )
    return SecurityCheck(
        id="machine_control_tool_gates",
        category="machine_control",
        severity=Severity.warning,
        status=Status.passed,
        message="Machine-control tools require the expected user/lease execution gates",
        details={"observed": observed},
    )


def _check_browser_live_pairing_surface() -> SecurityCheck:
    try:
        from app.services.integration_settings import get_status, get_value
        from integrations.browser_live.bridge import bridge
    except Exception as exc:
        return SecurityCheck(
            id="browser_live_pairing_surface",
            category="machine_control",
            severity=Severity.warning,
            status=Status.fail,
            message="Could not inspect browser_live pairing surface",
            recommendation="Fix browser_live imports/settings so the pairing boundary is auditable.",
            details={"error": str(exc)},
        )

    token_configured = bool(get_value("browser_live", "BROWSER_LIVE_PAIRING_TOKEN", ""))
    status = get_status("browser_live")
    connections = bridge.list_connections()
    details = {
        "integration_status": status,
        "token_configured": token_configured,
        "connection_count": len(connections),
        "connections": connections[:10],
    }

    if connections:
        return SecurityCheck(
            id="browser_live_pairing_surface",
            category="machine_control",
            severity=Severity.warning,
            status=Status.warning,
            message=f"{len(connections)} browser_live connection(s) are currently paired",
            recommendation="Treat paired browsers as operator-equivalent logged-in sessions; rotate the pairing token when a browser should no longer reconnect.",
            details=details,
        )
    if token_configured:
        return SecurityCheck(
            id="browser_live_pairing_surface",
            category="machine_control",
            severity=Severity.warning,
            status=Status.warning,
            message="browser_live has a reusable pairing token configured",
            recommendation="Rotate the pairing token after setup or before exposing the server beyond a trusted local network.",
            details=details,
        )
    return SecurityCheck(
        id="browser_live_pairing_surface",
        category="machine_control",
        severity=Severity.warning,
        status=Status.passed,
        message="browser_live has no active pairings and no reusable pairing token configured",
        details=details,
    )


def _check_bots_with_exec_tools() -> SecurityCheck:
    tiers = get_all_tool_tiers()
    dangerous_tiers = {"exec_capable", "control_plane"}
    dangerous_tools = {name for name, tier in tiers.items() if tier in dangerous_tiers}

    bots = list_bots()
    result = []
    for bot in bots:
        bot_dangerous = [t for t in bot.local_tools if t in dangerous_tools]
        if bot_dangerous:
            result.append({"bot_id": bot.id, "tools": bot_dangerous})

    return SecurityCheck(
        id="active_bots_with_exec_tools",
        category="tool_policies",
        severity=Severity.info,
        status=Status.passed if not result else Status.warning,
        message=f"{len(result)} bot(s) have exec/control_plane tools" if result else "No bots have exec-tier or control_plane tools",
        details={"bots": result},
    )


def _check_bots_with_cross_workspace_access() -> SecurityCheck:
    # Migration 287_clear_cross_workspace_access pops the deprecated key
    # from every bot row at upgrade time, and admin_bots refuses new
    # writes. This check now serves as a regression guard — if anything
    # ever resets the flag, the audit will catch it.
    bots = [
        {"bot_id": b.id, "name": getattr(b, "name", b.id)}
        for b in list_bots()
        if getattr(b, "cross_workspace_access", False)
    ]
    if not bots:
        return SecurityCheck(
            id="bots_with_cross_workspace_access",
            category="agentic_boundaries",
            severity=Severity.warning,
            status=Status.passed,
            message="No bots carry deprecated cross_workspace_access config",
        )
    return SecurityCheck(
        id="bots_with_cross_workspace_access",
        category="agentic_boundaries",
        severity=Severity.warning,
        status=Status.warning,
        message=f"{len(bots)} bot(s) still carry deprecated cross_workspace_access config",
        recommendation=(
            "Clear this stale config. Channel WorkSurface access is now granted by "
            "channel ownership or ChannelBotMember participation, not this flag."
        ),
        details={"count": len(bots), "bots": bots[:20]},
    )


def _check_bots_with_high_risk_api_scopes() -> SecurityCheck:
    findings = []
    critical = False
    for bot in list_bots():
        scopes = set(getattr(bot, "api_permissions", []) or [])
        risky = sorted(scopes & HIGH_RISK_BOT_API_SCOPES)
        if not risky:
            continue
        if "admin" in risky or "*" in risky:
            critical = True
        findings.append(
            {
                "bot_id": bot.id,
                "name": getattr(bot, "name", bot.id),
                "scopes": risky,
            }
        )

    if not findings:
        return SecurityCheck(
            id="bots_with_high_risk_api_scopes",
            category="agentic_boundaries",
            severity=Severity.warning,
            status=Status.passed,
            message="No bots have high-risk API scopes",
        )
    severity = Severity.critical if critical else Severity.warning
    return SecurityCheck(
        id="bots_with_high_risk_api_scopes",
        category="agentic_boundaries",
        severity=severity,
        status=Status.fail,
        message=f"{len(findings)} bot(s) have high-risk API scopes",
        recommendation=(
            "Use least-privilege bot API keys. Avoid admin, wildcard, direct tool "
            "execution, secret, provider, settings, and broad file-write scopes unless "
            "the bot is intentionally operator-equivalent."
        ),
        details={"count": len(findings), "bots": findings[:20]},
    )


def _check_widget_action_api_allowlist() -> SecurityCheck:
    try:
        from app.services.widget_action_dispatch import _API_ALLOWLIST
    except Exception as exc:
        return SecurityCheck(
            id="widget_action_api_allowlist",
            category="widget_actions",
            severity=Severity.warning,
            status=Status.fail,
            message="Could not inspect widget action API allowlist",
            recommendation="Fix widget action dispatch imports so the API proxy boundary is inspectable.",
            details={"error": str(exc)},
        )

    broad = [
        prefix for prefix in _API_ALLOWLIST
        if prefix in {"/", "/api", "/api/v1", "/api/v1/admin"}
    ]
    non_api = [prefix for prefix in _API_ALLOWLIST if not prefix.startswith("/api/v1/")]
    if broad or non_api:
        return SecurityCheck(
            id="widget_action_api_allowlist",
            category="widget_actions",
            severity=Severity.critical,
            status=Status.fail,
            message="Widget action API allowlist contains broad or non-API prefixes",
            recommendation="Keep widget action API dispatch pinned to narrow endpoint prefixes.",
            details={
                "prefixes": list(_API_ALLOWLIST),
                "broad_prefixes": broad,
                "non_api_prefixes": non_api,
            },
        )
    return SecurityCheck(
        id="widget_action_api_allowlist",
        category="widget_actions",
        severity=Severity.warning,
        status=Status.passed,
        message=f"Widget action API dispatch is limited to {len(_API_ALLOWLIST)} narrow prefix(es)",
        details={"prefixes": list(_API_ALLOWLIST)},
    )


def _check_widget_db_sql_authorizer() -> SecurityCheck:
    expected_denials = {
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
    }
    expected_functions = {"load_extension"}
    try:
        from app.services.widget_db import (
            _DENIED_SQLITE_ACTION_NAMES,
            _DENIED_SQLITE_FUNCTION_NAMES,
            install_widget_sql_authorizer,
        )
    except Exception as exc:
        return SecurityCheck(
            id="widget_db_sql_authorizer",
            category="widget_actions",
            severity=Severity.critical,
            status=Status.fail,
            message="Could not inspect widget DB SQL authorizer",
            recommendation="Fix widget DB imports so SQLite file-boundary protections are auditable.",
            details={"error": str(exc)},
        )

    observed = set(_DENIED_SQLITE_ACTION_NAMES)
    observed_functions = set(_DENIED_SQLITE_FUNCTION_NAMES)
    missing = sorted(expected_denials - observed)
    missing_functions = sorted(expected_functions - observed_functions)
    if missing or missing_functions or not callable(install_widget_sql_authorizer):
        return SecurityCheck(
            id="widget_db_sql_authorizer",
            category="widget_actions",
            severity=Severity.critical,
            status=Status.fail,
            message="Widget DB SQL authorizer is missing required denied operations",
            recommendation=(
                "Widget DB connections must deny SQLite file-boundary operations "
                "such as ATTACH/DETACH and extension loading."
            ),
            details={
                "required_actions": sorted(expected_denials),
                "observed_actions": sorted(observed),
                "missing_actions": missing,
                "required_functions": sorted(expected_functions),
                "observed_functions": sorted(observed_functions),
                "missing_functions": missing_functions,
            },
        )
    return SecurityCheck(
        id="widget_db_sql_authorizer",
        category="widget_actions",
        severity=Severity.warning,
        status=Status.passed,
        message="Widget DB SQL authorizer denies SQLite file-boundary operations",
        details={"denied_actions": sorted(observed), "denied_functions": sorted(observed_functions)},
    )


def _check_worksurface_isolation_static() -> SecurityCheck:
    from app.services.worksurface_isolation_audit import (
        POLICY_TARGET,
        audit_worksurface_isolation,
        summarize_worksurface_isolation,
    )

    findings = audit_worksurface_isolation()
    summary = summarize_worksurface_isolation(findings)
    failing = [finding for finding in findings if finding.status == "fail"]
    warnings = [finding for finding in findings if finding.status == "warning"]
    critical = [finding for finding in findings if finding.severity == "critical" and finding.status != "pass"]

    if not failing and not warnings:
        return SecurityCheck(
            id="worksurface_isolation_static",
            category="agentic_boundaries",
            severity=Severity.info,
            status=Status.passed,
            message="WorkSurface isolation static audit has no active findings",
            details={
                "summary": summary,
                "findings": [finding.payload() for finding in findings],
                "policy": POLICY_TARGET,
            },
        )

    severity = Severity.critical if critical else Severity.warning
    return SecurityCheck(
        id="worksurface_isolation_static",
        category="agentic_boundaries",
        severity=severity,
        status=Status.fail if failing else Status.warning,
        message=(
            f"WorkSurface isolation audit found {len(failing)} failing and "
            f"{len(warnings)} warning finding(s)"
        ),
        recommendation=(
            "Use WorkSurface as the canonical boundary for file/search/context/exec/harness/widget paths; "
            "replace vestigial cross-workspace access with explicit operator grants; make secret injection binding-scoped."
        ),
        details={
            "summary": summary,
            "findings": [finding.payload() for finding in findings],
            "policy": POLICY_TARGET,
        },
    )


def _webhook_auth_recommendation() -> str:
    return (
        "Declare webhook.security auth/replay metadata; require signed or bearer-token auth "
        "for exposed callbacks; use record_inbound_webhook_delivery for durable replay keys."
    )


def _check_inbound_callback_security() -> SecurityCheck:
    try:
        from integrations.discovery import iter_integration_candidates
        from app.services.integration_manifests import parse_integration_yaml
        from app.services.integration_settings import get_value as get_integration_setting
    except Exception as exc:
        return SecurityCheck(
            id="inbound_callback_security",
            category="integration_callbacks",
            severity=Severity.warning,
            status=Status.fail,
            message="Could not inspect integration webhook manifests",
            recommendation=_webhook_auth_recommendation(),
            details={"error": str(exc)},
        )

    callbacks: list[dict[str, Any]] = []
    missing_contracts: list[str] = []
    warnings: list[str] = []

    for candidate_dir, integration_id, _is_external, _source in iter_integration_candidates():
        yaml_path = candidate_dir / "integration.yaml"
        if not yaml_path.exists():
            continue
        try:
            manifest = parse_integration_yaml(yaml_path)
        except Exception as exc:
            missing_contracts.append(integration_id)
            callbacks.append({
                "integration_id": integration_id,
                "status": "fail",
                "reason": f"manifest parse failed: {exc}",
            })
            continue

        webhook = manifest.get("webhook")
        if not isinstance(webhook, dict):
            continue

        security = webhook.get("security") if isinstance(webhook.get("security"), dict) else {}
        auth = security.get("auth") if isinstance(security.get("auth"), dict) else {}
        replay = security.get("replay") if isinstance(security.get("replay"), dict) else {}
        callback: dict[str, Any] = {
            "integration_id": manifest.get("id", integration_id),
            "path": webhook.get("path"),
            "triggers_agent": bool(security.get("triggers_agent")),
            "auth_type": auth.get("type"),
            "auth_required": bool(auth.get("required")),
            "auth_setting": auth.get("setting"),
            "replay_strategy": replay.get("strategy"),
            "replay_key": replay.get("key"),
            "deprecated_transports": auth.get("deprecated_transports") or [],
            "findings": [],
        }

        if not security:
            callback["findings"].append("missing_security_contract")
            missing_contracts.append(callback["integration_id"])
        if not auth.get("type"):
            callback["findings"].append("missing_auth_contract")
            missing_contracts.append(callback["integration_id"])
        if replay.get("strategy") != "durable_dedupe" or not replay.get("key"):
            callback["findings"].append("missing_durable_replay_contract")
            missing_contracts.append(callback["integration_id"])

        setting = auth.get("setting")
        if setting:
            configured = bool(get_integration_setting(callback["integration_id"], setting, ""))
            callback["auth_configured"] = configured
            if not auth.get("required") and not configured:
                callback["findings"].append("optional_auth_setting_missing")
                warnings.append(callback["integration_id"])
        elif auth.get("type") not in (None, "none"):
            callback["findings"].append("auth_setting_missing")
            missing_contracts.append(callback["integration_id"])

        if callback["deprecated_transports"]:
            callback["findings"].append("deprecated_auth_transport")
            warnings.append(callback["integration_id"])

        callbacks.append(callback)

    if not callbacks:
        return SecurityCheck(
            id="inbound_callback_security",
            category="integration_callbacks",
            severity=Severity.info,
            status=Status.passed,
            message="No inbound integration callbacks are declared",
            details={"callbacks": []},
        )

    failed = sorted(set(missing_contracts))
    warned = sorted(set(warnings) - set(failed))
    if failed:
        return SecurityCheck(
            id="inbound_callback_security",
            category="integration_callbacks",
            severity=Severity.critical,
            status=Status.fail,
            message=f"{len(failed)} inbound callback integration(s) have missing auth/replay contracts",
            recommendation=_webhook_auth_recommendation(),
            details={"callbacks": callbacks, "failed": failed, "warnings": warned},
        )
    if warned:
        return SecurityCheck(
            id="inbound_callback_security",
            category="integration_callbacks",
            severity=Severity.warning,
            status=Status.warning,
            message=f"{len(warned)} inbound callback integration(s) have local-network/deprecated auth warnings",
            recommendation=(
                "Configure webhook bearer tokens before exposing callbacks beyond a trusted local network; "
                "prefer Authorization bearer tokens over query-token URLs."
            ),
            details={"callbacks": callbacks, "warnings": warned},
        )
    return SecurityCheck(
        id="inbound_callback_security",
        category="integration_callbacks",
        severity=Severity.warning,
        status=Status.passed,
        message=f"{len(callbacks)} inbound callback integration(s) declare auth and durable replay contracts",
        details={"callbacks": callbacks},
    )


# ---------------------------------------------------------------------------
# DB-dependent checks
# ---------------------------------------------------------------------------

async def _check_exec_tools_without_rules(db: AsyncSession) -> SecurityCheck:
    tiers = get_all_tool_tiers()
    dangerous_tiers = {"exec_capable", "control_plane"}
    dangerous_tools = {name for name, tier in tiers.items() if tier in dangerous_tiers}

    # Collect dangerous tools used by bots
    bots = list_bots()
    used_dangerous: set[str] = set()
    for bot in bots:
        used_dangerous.update(t for t in bot.local_tools if t in dangerous_tools)

    if not used_dangerous:
        return SecurityCheck(
            id="exec_tools_without_rules",
            category="tool_policies",
            severity=Severity.warning,
            status=Status.passed,
            message="No dangerous tools in use by any bot",
        )

    # Find which of these have policy rules
    stmt = select(ToolPolicyRule.tool_name).where(
        ToolPolicyRule.tool_name.in_(list(used_dangerous)),
        ToolPolicyRule.enabled.is_(True),
    )
    result = await db.execute(stmt)
    covered = {row[0] for row in result.all()}
    uncovered = used_dangerous - covered

    if not uncovered:
        return SecurityCheck(
            id="exec_tools_without_rules",
            category="tool_policies",
            severity=Severity.warning,
            status=Status.passed,
            message=f"All {len(used_dangerous)} dangerous tools have policy rules",
        )
    return SecurityCheck(
        id="exec_tools_without_rules",
        category="tool_policies",
        severity=Severity.warning,
        status=Status.fail,
        message=f"{len(uncovered)} dangerous tool(s) have no policy rules",
        recommendation="Create policy rules for these tools to control access",
        details={"count": len(uncovered), "tools": sorted(uncovered)},
    )


async def _check_approval_timeout(db: AsyncSession) -> SecurityCheck:
    stmt = select(ToolPolicyRule).where(
        ToolPolicyRule.enabled.is_(True),
        ToolPolicyRule.approval_timeout > 3600,
    )
    result = await db.execute(stmt)
    long_timeout = result.scalars().all()
    if not long_timeout:
        return SecurityCheck(
            id="approval_timeout_reasonable",
            category="tool_policies",
            severity=Severity.warning,
            status=Status.passed,
            message="All approval timeouts are under 1 hour",
        )
    return SecurityCheck(
        id="approval_timeout_reasonable",
        category="tool_policies",
        severity=Severity.warning,
        status=Status.fail,
        message=f"{len(long_timeout)} rule(s) have approval timeouts exceeding 1 hour",
        recommendation="Reduce approval_timeout to 3600 seconds or less",
        details={
            "count": len(long_timeout),
            "rules": [
                {"id": str(r.id), "tool_name": r.tool_name, "timeout": r.approval_timeout}
                for r in long_timeout[:10]
            ],
        },
    )


async def _check_stale_approvals(db: AsyncSession) -> SecurityCheck:
    stmt = select(ToolApproval).where(ToolApproval.status == "pending")
    result = await db.execute(stmt)
    pending = result.scalars().all()

    now = datetime.now(timezone.utc)
    stale = []
    for approval in pending:
        created = approval.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        deadline = created + timedelta(seconds=approval.timeout_seconds)
        if now > deadline:
            stale.append({
                "id": str(approval.id),
                "tool_name": approval.tool_name,
                "created_at": created.isoformat(),
                "timeout_seconds": approval.timeout_seconds,
            })

    if not stale:
        return SecurityCheck(
            id="stale_pending_approvals",
            category="approvals",
            severity=Severity.warning,
            status=Status.passed,
            message=f"{len(pending)} pending approval(s), none past timeout",
        )
    return SecurityCheck(
        id="stale_pending_approvals",
        category="approvals",
        severity=Severity.warning,
        status=Status.fail,
        message=f"{len(stale)} approval(s) past their timeout still in pending state",
        recommendation="Review and resolve stale pending approvals",
        details={"count": len(stale), "approvals": stale[:10]},
    )


async def _check_policy_rule_count(db: AsyncSession) -> SecurityCheck:
    stmt = select(func.count()).select_from(ToolPolicyRule).where(ToolPolicyRule.enabled.is_(True))
    result = await db.execute(stmt)
    count = result.scalar() or 0
    return SecurityCheck(
        id="policy_rule_count",
        category="tool_policies",
        severity=Severity.info,
        status=Status.passed,
        message=f"{count} active policy rule(s) configured",
        details={"count": count},
    )


async def _check_allow_rules_autonomous_scope(db: AsyncSession) -> SecurityCheck:
    """Surface ``allow`` rules whose scope is interactive-only by default.

    Since 2026-05, a rule with no ``origin_kind`` matcher and no
    ``apply_to_autonomous`` opt-in only matches the interactive ``chat``
    origin. That's a fail-closed default — autonomous heartbeats / tasks /
    sub-agents / hygiene runs will hit the require_approval defaults
    instead of the rule. This check lists the ``allow`` rules whose
    scope is interactive-only so operators can verify the posture (e.g.
    deliberately broaden a rule by setting ``apply_to_autonomous: true``
    in its conditions if they really want it to cover autonomous runs).
    """
    rows = (
        await db.execute(
            select(ToolPolicyRule)
            .where(ToolPolicyRule.enabled.is_(True))
            .where(ToolPolicyRule.action == "allow")
        )
    ).scalars().all()

    interactive_only: list[dict[str, Any]] = []
    autonomous_opt_in: list[dict[str, Any]] = []
    for row in rows:
        cond = row.conditions or {}
        has_origin = bool(cond.get("origin_kind"))
        opt_in = bool(cond.get("apply_to_autonomous"))
        info = {
            "id": str(row.id),
            "tool_name": row.tool_name,
            "bot_id": str(row.bot_id) if row.bot_id else None,
            "origin_kind": cond.get("origin_kind"),
            "apply_to_autonomous": opt_in,
        }
        if has_origin or opt_in:
            autonomous_opt_in.append(info)
        else:
            interactive_only.append(info)

    if not rows:
        return SecurityCheck(
            id="allow_rules_origin_scope",
            category="tool_policies",
            severity=Severity.info,
            status=Status.passed,
            message="No active 'allow' rules — autonomous defaults apply.",
            details={"interactive_only": [], "autonomous_opt_in": []},
        )

    return SecurityCheck(
        id="allow_rules_origin_scope",
        category="tool_policies",
        severity=Severity.info,
        status=Status.passed,
        message=(
            f"{len(interactive_only)} 'allow' rule(s) limited to interactive chat; "
            f"{len(autonomous_opt_in)} also cover autonomous runs"
        ),
        recommendation=(
            "Review the rules under 'autonomous_opt_in' — those grant the same "
            "tool to heartbeats, tasks, sub-agents, and hygiene runs. Tighten "
            "by removing ``apply_to_autonomous`` or constraining ``origin_kind`` "
            "if any were not intended for unattended use."
        ),
        details={
            "interactive_only": interactive_only[:25],
            "autonomous_opt_in": autonomous_opt_in[:25],
        },
    )


def _check_backup_encryption_at_rest() -> SecurityCheck:
    """Surface backup archives in ``backups/`` that are stored as
    plaintext. Encrypted backups (``.tar.gz.enc``) are produced by the
    2026-05 ``backup.sh`` pipeline; plaintext ``.tar.gz`` archives are
    legacy and should be re-encrypted (run a fresh ``backup.sh``) and
    removed once verified.
    """
    from pathlib import Path
    from app.services.backup_encryption import inspect_backup_dir

    # backups/ lives at the repo root regardless of cwd.
    repo_root = Path(__file__).resolve().parents[2]
    backup_dir = repo_root / "backups"
    statuses = inspect_backup_dir(backup_dir)

    if not statuses:
        return SecurityCheck(
            id="backup_encryption_at_rest",
            category="backups",
            severity=Severity.warning,
            status=Status.passed,
            message="No backup archives present in backups/.",
            details={"backup_dir": str(backup_dir), "archive_count": 0},
        )

    plaintext = [s.name for s in statuses if not s.encrypted]
    encrypted = [s.name for s in statuses if s.encrypted]

    if not plaintext:
        return SecurityCheck(
            id="backup_encryption_at_rest",
            category="backups",
            severity=Severity.warning,
            status=Status.passed,
            message=f"All {len(encrypted)} backup archive(s) encrypted at rest.",
            details={
                "backup_dir": str(backup_dir),
                "encrypted_count": len(encrypted),
                "plaintext_count": 0,
            },
        )

    return SecurityCheck(
        id="backup_encryption_at_rest",
        category="backups",
        severity=Severity.warning,
        status=Status.warning,
        message=(
            f"{len(plaintext)} of {len(statuses)} backup archive(s) are plaintext "
            ".tar.gz — they include the .env file (API keys/OAuth tokens) and a "
            "Postgres dump that may contain decrypted secrets."
        ),
        recommendation=(
            "Set BACKUP_ENCRYPTION_KEY (or use ENCRYPTION_KEY) and run "
            "scripts/backup.sh to produce a .tar.gz.enc archive; verify "
            "scripts/restore.sh decrypts it; then delete the plaintext "
            ".tar.gz copies. Future backups encrypt automatically when "
            "ENCRYPTION_STRICT=true (default)."
        ),
        details={
            "backup_dir": str(backup_dir),
            "encrypted_count": len(encrypted),
            "plaintext_count": len(plaintext),
            "plaintext_archives": plaintext[:25],
        },
    )


async def _check_manifest_hash_drift(db: AsyncSession) -> SecurityCheck:
    """Recompute canonical content hashes for Skill + WidgetTemplatePackage
    rows and report any whose stored ``content_hash`` no longer matches.

    Drift means a writer mutated the body without updating the hash, OR
    a non-writer code path (direct DB tampering, an out-of-band import,
    a migration that landed body-only) bypassed the hash bookkeeping.
    Either way, the row's integrity record is unreliable until the hash
    is recomputed and re-signed.

    This is the Phase 1 audit signal for the supply-chain signing track —
    it surfaces existing tamper evidence today without requiring the
    Phase 2 ``signature`` column or verify-on-read enforcement.
    """
    from app.db.models import Skill, WidgetTemplatePackage
    from app.services.manifest_signing import (
        detect_skill_drift,
        detect_widget_drift,
    )

    skill_rows = (await db.execute(select(Skill))).scalars().all()
    widget_rows = (await db.execute(select(WidgetTemplatePackage))).scalars().all()

    skill_findings = detect_skill_drift(list(skill_rows))
    widget_findings = detect_widget_drift(list(widget_rows))

    total_findings = len(skill_findings) + len(widget_findings)
    total_rows = len(skill_rows) + len(widget_rows)

    if total_rows == 0:
        return SecurityCheck(
            id="manifest_hash_drift",
            category="manifest_signing",
            severity=Severity.warning,
            status=Status.passed,
            message="No skills or widget template packages to verify.",
            details={
                "skill_count": 0,
                "widget_template_count": 0,
                "drift_findings": 0,
            },
        )

    if total_findings == 0:
        return SecurityCheck(
            id="manifest_hash_drift",
            category="manifest_signing",
            severity=Severity.warning,
            status=Status.passed,
            message=(
                f"All {total_rows} skill / widget rows have intact "
                "content_hash bookkeeping."
            ),
            details={
                "skill_count": len(skill_rows),
                "widget_template_count": len(widget_rows),
                "drift_findings": 0,
            },
        )

    return SecurityCheck(
        id="manifest_hash_drift",
        category="manifest_signing",
        severity=Severity.warning,
        status=Status.warning,
        message=(
            f"{total_findings} row(s) have content_hash drift "
            f"({len(skill_findings)} skill, {len(widget_findings)} widget). "
            "Stored hash does not match a fresh sha256 of the body — a "
            "writer skipped the hash update or the body was edited "
            "out-of-band."
        ),
        recommendation=(
            "Inspect each drifted row. If the body is the intended state, "
            "rewrite it via the normal writer (e.g. manage_bot_skill, widget "
            "package edit) so the hash is recomputed. If the body is wrong, "
            "restore from a backup. Phase 2 of this track will add a "
            "signature column and verify-on-read so out-of-band edits are "
            "rejected automatically."
        ),
        details={
            "skill_count": len(skill_rows),
            "widget_template_count": len(widget_rows),
            "drift_findings": total_findings,
            "skill_drift": [
                {
                    "id": f.target_id,
                    "name": f.name,
                    "stored": f.stored_hash[:16] + "…",
                    "recomputed": f.recomputed_hash[:16] + "…",
                }
                for f in skill_findings[:25]
            ],
            "widget_drift": [
                {
                    "id": f.target_id,
                    "name": f.name,
                    "stored": f.stored_hash[:16] + "…",
                    "recomputed": f.recomputed_hash[:16] + "…",
                }
                for f in widget_findings[:25]
            ],
        },
    )


async def _check_run_script_allowed_tools_coverage(db: AsyncSession) -> SecurityCheck:
    """Surface stored scripts that lack an explicit ``allowed_tools`` allowlist.

    Since the run_script tightening pass, stored scripts may declare an
    ``allowed_tools`` allowlist that the inner /internal/tools/exec endpoint
    enforces fail-closed. Without one, the script can call any tool the bot
    has policy access to. Scripts that only do read aggregation should
    declare a tight allowlist; scripts that need broad reach can omit it
    deliberately. This check makes the choice visible.
    """
    from app.db.models import Skill

    try:
        rows = (
            await db.execute(select(Skill.id, Skill.scripts))
        ).all()
    except Exception:
        logger.debug("Could not collect Skill rows for run_script audit", exc_info=True)
        rows = []

    total_scripts = 0
    with_allowlist = 0
    without_allowlist: list[dict[str, Any]] = []
    for skill_id, scripts in rows:
        if not isinstance(scripts, list):
            continue
        for script in scripts:
            if not isinstance(script, dict):
                continue
            total_scripts += 1
            if isinstance(script.get("allowed_tools"), list) and script.get("allowed_tools"):
                with_allowlist += 1
            else:
                without_allowlist.append({
                    "skill_id": str(skill_id),
                    "script_name": script.get("name"),
                })

    if total_scripts == 0:
        return SecurityCheck(
            id="run_script_allowed_tools_coverage",
            category="run_script",
            severity=Severity.info,
            status=Status.passed,
            message="No stored scripts configured.",
            details={"total_scripts": 0, "with_allowlist": 0},
        )

    coverage_pct = round((with_allowlist / total_scripts) * 100)
    return SecurityCheck(
        id="run_script_allowed_tools_coverage",
        category="run_script",
        severity=Severity.info,
        status=Status.passed,
        message=(
            f"{with_allowlist}/{total_scripts} stored scripts ({coverage_pct}%) "
            "declare an allowed_tools allowlist."
        ),
        recommendation=(
            "Stored scripts that aggregate or filter known tools should declare "
            "``allowed_tools`` so a prompt-injected edit cannot broaden their "
            "blast radius. Scripts that genuinely need open dispatch can omit it."
        ),
        details={
            "total_scripts": total_scripts,
            "with_allowlist": with_allowlist,
            "without_allowlist": without_allowlist[:25],
        },
    )


async def _check_mcp_outbound_url_guard(db: AsyncSession) -> SecurityCheck:
    """Report whether the MCP outbound URL guard is in default-deny mode.

    The guard ships default-deny for private/loopback ranges so a typo or
    attacker-supplied MCP server URL cannot reach internal admin surfaces or
    cloud metadata. Operators who genuinely run MCP on the LAN can opt in via
    ``MCP_ALLOW_PRIVATE_NETWORKS``. This check makes the chosen posture
    visible — passing when default-deny, warning when opted in, with the list
    of configured server hosts so the operator can see what they accepted.
    """
    from app.tools.mcp import _servers as mcp_yaml_servers
    from urllib.parse import urlparse

    allow_private = bool(settings.MCP_ALLOW_PRIVATE_NETWORKS)
    allow_loopback = bool(settings.MCP_ALLOW_LOOPBACK)
    yaml_hosts = sorted({
        urlparse(srv.url).hostname or srv.url
        for srv in mcp_yaml_servers.values()
    })
    db_hosts: list[str] = []
    try:
        rows = (await db.execute(
            select(MCPServer.url).where(MCPServer.is_enabled.is_(True))
        )).scalars().all()
        db_hosts = sorted({urlparse(u or "").hostname or (u or "") for u in rows if u})
    except Exception:
        logger.debug("Could not collect DB MCP server URLs for audit", exc_info=True)

    details = {
        "allow_private_networks": allow_private,
        "allow_loopback": allow_loopback,
        "yaml_hosts": yaml_hosts,
        "db_hosts": db_hosts,
    }
    if not allow_private and not allow_loopback:
        return SecurityCheck(
            id="mcp_outbound_url_guard",
            category="mcp",
            severity=Severity.warning,
            status=Status.passed,
            message="MCP outbound URL guard in default-deny mode (private/loopback blocked)",
            details=details,
        )
    relaxed = []
    if allow_private:
        relaxed.append("private networks")
    if allow_loopback:
        relaxed.append("loopback")
    return SecurityCheck(
        id="mcp_outbound_url_guard",
        category="mcp",
        severity=Severity.warning,
        status=Status.warning,
        message=(
            "MCP outbound URL guard relaxed for: " + ", ".join(relaxed)
            + ". Verify every configured MCP server is intentional."
        ),
        recommendation=(
            "Unset MCP_ALLOW_PRIVATE_NETWORKS / MCP_ALLOW_LOOPBACK once you've "
            "confirmed every configured server should remain reachable."
        ),
        details=details,
    )


async def _check_mcp_servers_count(db: AsyncSession) -> SecurityCheck:
    yaml_count = get_configured_server_count()
    stmt = select(func.count()).select_from(MCPServer).where(MCPServer.is_enabled.is_(True))
    result = await db.execute(stmt)
    db_count = result.scalar() or 0
    total = yaml_count + db_count
    return SecurityCheck(
        id="mcp_servers_count",
        category="mcp",
        severity=Severity.info,
        status=Status.passed,
        message=f"{total} MCP server(s) configured ({yaml_count} from YAML, {db_count} from DB)",
        details={"yaml": yaml_count, "db": db_count, "total": total},
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _legacy_machine_lease(session: Session) -> dict[str, Any] | None:
    raw = (session.metadata_ or {}).get("machine_target_lease")
    return raw if isinstance(raw, dict) else None


async def _check_machine_control_lease_state(db: AsyncSession) -> SecurityCheck:
    now = datetime.now(timezone.utc)
    rows = (await db.execute(select(MachineTargetLease))).scalars().all()

    active = []
    expired = []
    overlong = []
    for row in rows:
        granted_at = _aware(row.granted_at)
        expires_at = _aware(row.expires_at)
        ttl_seconds = int((expires_at - granted_at).total_seconds())
        payload = {
            "lease_id": row.lease_id,
            "session_id": str(row.session_id),
            "user_id": str(row.user_id),
            "provider_id": row.provider_id,
            "target_id": row.target_id,
            "granted_at": granted_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": ttl_seconds,
        }
        if expires_at <= now:
            expired.append(payload)
        else:
            active.append(payload)
        if ttl_seconds > 3600:
            overlong.append(payload)

    sessions = (await db.execute(select(Session))).scalars().all()
    legacy = []
    for session in sessions:
        lease = _legacy_machine_lease(session)
        if lease is not None:
            legacy.append({
                "session_id": str(session.id),
                "provider_id": lease.get("provider_id"),
                "target_id": lease.get("target_id"),
                "expires_at": lease.get("expires_at"),
            })

    details = {
        "active_count": len(active),
        "expired_count": len(expired),
        "overlong_count": len(overlong),
        "legacy_metadata_count": len(legacy),
        "active": active[:20],
        "expired": expired[:20],
        "overlong": overlong[:20],
        "legacy_metadata": legacy[:20],
        "max_ttl_seconds": 3600,
    }

    if overlong:
        return SecurityCheck(
            id="machine_control_lease_state",
            category="machine_control",
            severity=Severity.critical,
            status=Status.fail,
            message=f"{len(overlong)} machine-control lease(s) exceed the max TTL",
            recommendation="Revoke overlong leases and keep session leases capped to MAX_LEASE_TTL_SECONDS.",
            details=details,
        )
    if active or expired or legacy:
        parts = []
        if active:
            parts.append(f"{len(active)} active")
        if expired:
            parts.append(f"{len(expired)} expired")
        if legacy:
            parts.append(f"{len(legacy)} legacy metadata")
        return SecurityCheck(
            id="machine_control_lease_state",
            category="machine_control",
            severity=Severity.warning,
            status=Status.warning,
            message="Machine-control leases present: " + ", ".join(parts),
            recommendation="Review active leases before handing a session to another operator; expired or legacy metadata leases should be cleared.",
            details=details,
        )
    return SecurityCheck(
        id="machine_control_lease_state",
        category="machine_control",
        severity=Severity.warning,
        status=Status.passed,
        message="No active, expired, overlong, or legacy machine-control leases found",
        details=details,
    )


async def _check_widget_token_revocations(db: AsyncSession) -> SecurityCheck:
    """Surface revocation-list state. Operators see how many active
    revocations exist plus the oldest one — a proxy for whether the
    purge sweep is running."""
    from sqlalchemy import func

    from app.db.models import WidgetTokenRevocation

    now = datetime.now(timezone.utc)
    total = (
        await db.execute(select(func.count(WidgetTokenRevocation.jti)))
    ).scalar() or 0
    active = (
        await db.execute(
            select(func.count(WidgetTokenRevocation.jti)).where(
                WidgetTokenRevocation.expires_at >= now
            )
        )
    ).scalar() or 0
    oldest_active = (
        await db.execute(
            select(func.min(WidgetTokenRevocation.revoked_at)).where(
                WidgetTokenRevocation.expires_at >= now
            )
        )
    ).scalar()

    return SecurityCheck(
        id="widget_token_revocations",
        category="auth",
        severity=Severity.info,
        status=Status.passed,
        message=(
            f"{active} active widget token revocation(s); "
            f"{total - active} stale row(s) pending purge."
        ),
        details={
            "total": total,
            "active": active,
            "oldest_active_revoked_at": (
                oldest_active.isoformat() if oldest_active else None
            ),
        },
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _compute_summary(checks: list[SecurityCheck]) -> dict:
    summary: dict[str, int] = {
        "critical": 0, "warning": 0, "info": 0,
        "pass": 0, "fail": 0, "warn": 0,
    }
    for c in checks:
        summary[c.severity.value] = summary.get(c.severity.value, 0) + 1
        if c.status == Status.passed:
            summary["pass"] += 1
        elif c.status == Status.fail:
            summary["fail"] += 1
        elif c.status == Status.warning:
            summary["warn"] += 1
    return summary


def _compute_score(checks: list[SecurityCheck]) -> int:
    score = 100
    for c in checks:
        if c.status != Status.fail:
            continue
        if c.severity == Severity.critical:
            score -= 25
        elif c.severity == Severity.warning:
            score -= 10
    return max(0, score)


async def run_security_audit(db: AsyncSession) -> SecurityAuditResponse:
    checks: list[SecurityCheck] = []

    # Config-only checks
    checks.append(_check_encryption_key())
    checks.append(_check_admin_key_separation())
    checks.append(_check_tool_policy_enabled())
    checks.append(_check_default_policy_action())
    checks.append(_check_tier_gating())
    checks.append(_check_rate_limiting())
    checks.append(_check_secret_redaction())
    checks.append(_check_docker_sandbox())
    checks.append(_check_host_exec())
    checks.append(_check_audit_logging())

    # Tool registry and agentic boundary checks
    checks.append(_check_tools_missing_tier())
    checks.append(_check_tool_tier_distribution())
    checks.append(_check_bots_with_exec_tools())
    checks.append(_check_bots_with_cross_workspace_access())
    checks.append(_check_bots_with_high_risk_api_scopes())
    checks.append(_check_widget_action_api_allowlist())
    checks.append(_check_widget_db_sql_authorizer())
    checks.append(_check_worksurface_isolation_static())
    checks.append(_check_inbound_callback_security())
    checks.append(_check_machine_control_tool_gates())
    checks.append(_check_browser_live_pairing_surface())
    checks.append(_check_backup_encryption_at_rest())

    # DB-dependent checks
    checks.append(await _check_exec_tools_without_rules(db))
    checks.append(await _check_approval_timeout(db))
    checks.append(await _check_stale_approvals(db))
    checks.append(await _check_policy_rule_count(db))
    checks.append(await _check_allow_rules_autonomous_scope(db))
    checks.append(await _check_run_script_allowed_tools_coverage(db))
    checks.append(await _check_manifest_hash_drift(db))
    checks.append(await _check_mcp_servers_count(db))
    checks.append(await _check_mcp_outbound_url_guard(db))
    checks.append(await _check_machine_control_lease_state(db))
    checks.append(await _check_widget_token_revocations(db))

    summary = _compute_summary(checks)
    score = _compute_score(checks)
    return SecurityAuditResponse(checks=checks, summary=summary, score=score)
