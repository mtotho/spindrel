"""Security self-assessment: 18 checks across config, tool registry, and DB state.

Read-only diagnostic — no mutations, no new tables.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

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

    # Tool registry checks
    checks.append(_check_tools_missing_tier())
    checks.append(_check_tool_tier_distribution())
    checks.append(_check_bots_with_exec_tools())

    # DB-dependent checks
    checks.append(await _check_exec_tools_without_rules(db))
    checks.append(await _check_approval_timeout(db))
    checks.append(await _check_stale_approvals(db))
    checks.append(await _check_policy_rule_count(db))
    checks.append(await _check_mcp_servers_count(db))

    summary = _compute_summary(checks)
    score = _compute_score(checks)
    return SecurityAuditResponse(checks=checks, summary=summary, score=score)
