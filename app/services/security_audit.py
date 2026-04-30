"""Security self-assessment: 18 checks across config, tool registry, and DB state.

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
from app.db.models import MCPServer, ToolApproval, ToolPolicyRule
from app.services.encryption import is_encryption_enabled
from app.tools.mcp import get_configured_server_count
from app.tools.registry import get_all_tool_tiers

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
    return SecurityCheck(
        id="encryption_key_configured",
        category="encryption",
        severity=Severity.critical,
        status=Status.passed if enabled else Status.fail,
        message="Encryption key is configured" if enabled else "No encryption key configured — secrets stored in plaintext",
        recommendation=None if enabled else (
            "Set ENCRYPTION_KEY in .env. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ),
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


def _check_worksurface_isolation_static() -> SecurityCheck:
    from app.services.worksurface_isolation_audit import (
        POLICY_TARGET,
        audit_worksurface_isolation,
        summarize_worksurface_isolation,
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
    checks.append(_check_worksurface_isolation_static())
    checks.append(_check_inbound_callback_security())

    # DB-dependent checks
    checks.append(await _check_exec_tools_without_rules(db))
    checks.append(await _check_approval_timeout(db))
    checks.append(await _check_stale_approvals(db))
    checks.append(await _check_policy_rule_count(db))
    checks.append(await _check_mcp_servers_count(db))

    summary = _compute_summary(checks)
    score = _compute_score(checks)
    return SecurityAuditResponse(checks=checks, summary=summary, score=score)
