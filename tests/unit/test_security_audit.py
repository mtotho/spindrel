"""Unit tests for the security self-assessment service."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, ToolPolicyRule, ToolApproval
from app.services.security_audit import (
    SecurityCheck,
    Severity,
    Status,
    _check_admin_key_separation,
    _check_approval_timeout,
    _check_audit_logging,
    _check_bots_with_exec_tools,
    _check_bots_with_cross_workspace_access,
    _check_bots_with_high_risk_api_scopes,
    _check_default_policy_action,
    _check_docker_sandbox,
    _check_encryption_key,
    _check_tool_policy_enabled,
    _check_exec_tools_without_rules,
    _check_host_exec,
    _check_inbound_callback_security,
    _check_mcp_servers_count,
    _check_policy_rule_count,
    _check_rate_limiting,
    _check_secret_redaction,
    _check_stale_approvals,
    _check_tier_gating,
    _check_tool_tier_distribution,
    _check_tools_missing_tier,
    _check_widget_action_api_allowlist,
    _check_worksurface_isolation_static,
    _compute_score,
    _compute_summary,
    run_security_audit,
)


# ---------------------------------------------------------------------------
# DB fixture (SQLite in-memory, same pattern as integration conftest)
# ---------------------------------------------------------------------------

from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import (
    JSONB,
    UUID as PG_UUID,
    TIMESTAMP as PG_TIMESTAMP,
    TSVECTOR as PG_TSVECTOR,
)


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


@compiles(PG_TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_TIMESTAMP, "sqlite")
def _compile_timestamp_sqlite(type_, compiler, **kw):
    return "TIMESTAMP"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    from sqlalchemy import text as sa_text
    _REPLACEMENTS = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
    originals = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                if new_default:
                    from sqlalchemy.schema import DefaultClause
                    col.server_default = DefaultClause(sa_text(new_default))
                else:
                    col.server_default = None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        table = Base.metadata.tables[tname]
        table.c[cname].server_default = default

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(
    bot_id="test-bot",
    local_tools=None,
    host_exec_enabled=False,
    cross_workspace_access=False,
    api_permissions=None,
):
    """Create a minimal mock BotConfig."""
    mock = MagicMock()
    mock.id = bot_id
    mock.name = bot_id
    mock.local_tools = local_tools or []
    mock.host_exec.enabled = host_exec_enabled
    mock.cross_workspace_access = cross_workspace_access
    mock.api_permissions = api_permissions or []
    return mock


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------

class TestEncryptionKey:
    def test_pass(self):
        with patch("app.services.security_audit.is_encryption_enabled", return_value=True):
            c = _check_encryption_key()
        assert c.status == Status.passed
        assert c.recommendation is None

    def test_fail(self):
        with patch("app.services.security_audit.is_encryption_enabled", return_value=False):
            c = _check_encryption_key()
        assert c.status == Status.fail
        assert c.severity == Severity.critical
        assert c.recommendation is not None


class TestAdminKeySeparation:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "admin-secret")
        monkeypatch.setattr("app.services.security_audit.settings.API_KEY", "bot-key")
        c = _check_admin_key_separation()
        assert c.status == Status.passed

    def test_fail_same(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "same-key")
        monkeypatch.setattr("app.services.security_audit.settings.API_KEY", "same-key")
        c = _check_admin_key_separation()
        assert c.status == Status.fail

    def test_fail_empty(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "")
        monkeypatch.setattr("app.services.security_audit.settings.API_KEY", "bot-key")
        c = _check_admin_key_separation()
        assert c.status == Status.fail


class TestToolPolicyEnabled:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_ENABLED", True)
        assert _check_tool_policy_enabled().status == Status.passed

    def test_fail(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_ENABLED", False)
        c = _check_tool_policy_enabled()
        assert c.status == Status.fail
        assert c.severity == Severity.critical


class TestDefaultPolicyAction:
    def test_pass_deny(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_DEFAULT_ACTION", "deny")
        assert _check_default_policy_action().status == Status.passed

    def test_pass_require_approval(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_DEFAULT_ACTION", "require_approval")
        assert _check_default_policy_action().status == Status.passed

    def test_fail_allow(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_DEFAULT_ACTION", "allow")
        c = _check_default_policy_action()
        assert c.status == Status.fail
        assert "deny" in c.recommendation


class TestTierGating:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_TIER_GATING", True)
        assert _check_tier_gating().status == Status.passed

    def test_fail(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_TIER_GATING", False)
        assert _check_tier_gating().status == Status.fail


class TestRateLimiting:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.RATE_LIMIT_ENABLED", True)
        assert _check_rate_limiting().status == Status.passed

    def test_fail(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.RATE_LIMIT_ENABLED", False)
        assert _check_rate_limiting().status == Status.fail


class TestSecretRedaction:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.SECRET_REDACTION_ENABLED", True)
        assert _check_secret_redaction().status == Status.passed

    def test_fail(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.SECRET_REDACTION_ENABLED", False)
        assert _check_secret_redaction().status == Status.fail


class TestDockerSandbox:
    def test_enabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DOCKER_SANDBOX_ENABLED", True)
        c = _check_docker_sandbox()
        assert c.status == Status.passed
        assert c.severity == Severity.info

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DOCKER_SANDBOX_ENABLED", False)
        c = _check_docker_sandbox()
        assert c.status == Status.warning


class TestHostExec:
    def test_all_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.HOST_EXEC_ENABLED", False)
        with patch("app.services.security_audit.list_bots", return_value=[_make_bot()]):
            c = _check_host_exec()
        assert c.status == Status.passed

    def test_global_enabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.HOST_EXEC_ENABLED", True)
        with patch("app.services.security_audit.list_bots", return_value=[]):
            c = _check_host_exec()
        assert c.status == Status.warning
        assert c.details["global_enabled"] is True

    def test_bot_enabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.HOST_EXEC_ENABLED", False)
        bot = _make_bot(host_exec_enabled=True)
        with patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_host_exec()
        assert c.status == Status.warning
        assert "test-bot" in c.details["bots_with_exec"]


class TestAuditLogging:
    def test_enabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.SECURITY_AUDIT_ENABLED", True)
        assert _check_audit_logging().status == Status.passed

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.SECURITY_AUDIT_ENABLED", False)
        assert _check_audit_logging().status == Status.warning


# ---------------------------------------------------------------------------
# Tool registry checks
# ---------------------------------------------------------------------------

class TestToolsMissingTier:
    def test_all_assigned(self):
        tiers = {"tool_a": "readonly", "tool_b": "exec_capable"}
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers):
            c = _check_tools_missing_tier()
        assert c.status == Status.passed

    def test_some_unknown(self):
        tiers = {"tool_a": "readonly", "tool_b": "unknown", "tool_c": "unknown"}
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers):
            c = _check_tools_missing_tier()
        assert c.status == Status.fail
        assert c.details["count"] == 2


class TestToolTierDistribution:
    def test_distribution(self):
        tiers = {"a": "readonly", "b": "readonly", "c": "exec_capable", "d": "mutating"}
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers):
            c = _check_tool_tier_distribution()
        assert c.status == Status.passed
        assert c.details["total"] == 4
        assert c.details["by_tier"]["readonly"] == 2


class TestBotsWithExecTools:
    def test_no_dangerous(self):
        tiers = {"search": "readonly", "write_file": "mutating"}
        bot = _make_bot(local_tools=["search"])
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers), \
             patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_exec_tools()
        assert c.status == Status.passed

    def test_has_dangerous(self):
        tiers = {"exec_cmd": "exec_capable", "deploy": "control_plane", "search": "readonly"}
        bot = _make_bot(local_tools=["exec_cmd", "deploy", "search"])
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers), \
             patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_exec_tools()
        assert c.status == Status.warning
        assert len(c.details["bots"]) == 1
        assert set(c.details["bots"][0]["tools"]) == {"exec_cmd", "deploy"}


class TestBotsWithCrossWorkspaceAccess:
    def test_none_enabled(self):
        with patch("app.services.security_audit.list_bots", return_value=[_make_bot()]):
            c = _check_bots_with_cross_workspace_access()
        assert c.status == Status.passed

    def test_enabled_bot_is_reported(self):
        bot = _make_bot("orchestrator", cross_workspace_access=True)
        with patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_cross_workspace_access()
        assert c.status == Status.warning
        assert c.severity == Severity.warning
        assert c.details["bots"][0]["bot_id"] == "orchestrator"


class TestBotsWithHighRiskApiScopes:
    def test_no_high_risk_scopes(self):
        bot = _make_bot(api_permissions=["chat", "channels:read"])
        with patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_high_risk_api_scopes()
        assert c.status == Status.passed

    def test_write_scopes_are_warning(self):
        bot = _make_bot("worker", api_permissions=["chat", "tools:execute", "workspaces.files:write"])
        with patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_high_risk_api_scopes()
        assert c.status == Status.fail
        assert c.severity == Severity.warning
        assert c.details["bots"][0]["scopes"] == ["tools:execute", "workspaces.files:write"]

    def test_admin_scope_is_critical(self):
        bot = _make_bot("operator", api_permissions=["admin"])
        with patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = _check_bots_with_high_risk_api_scopes()
        assert c.status == Status.fail
        assert c.severity == Severity.critical


class TestWidgetActionApiAllowlist:
    def test_current_allowlist_is_narrow(self):
        c = _check_widget_action_api_allowlist()
        assert c.status == Status.passed
        assert c.details["prefixes"]

    def test_broad_prefix_fails(self, monkeypatch):
        monkeypatch.setattr("app.services.widget_action_dispatch._API_ALLOWLIST", ["/api/v1/admin"])
        c = _check_widget_action_api_allowlist()
        assert c.status == Status.fail
        assert c.severity == Severity.critical


class TestWorkSurfaceIsolationStatic:
    def test_static_findings_surface_in_security_audit(self):
        c = _check_worksurface_isolation_static()

        assert c.id == "worksurface_isolation_static"
        assert c.category == "agentic_boundaries"
        assert c.status == Status.warning
        assert c.severity == Severity.warning
        assert c.details is not None
        findings = {f["id"]: f for f in c.details["findings"]}
        assert findings["shared_workspace_unscoped_secret_injection"]["status"] == "pass"
        assert findings["legacy_cross_workspace_access_flag"]["status"] == "pass"


class TestInboundCallbackSecurity:
    def test_current_webhook_contracts_have_only_local_auth_warnings(self):
        with patch("app.services.integration_settings.get_value", return_value=""):
            c = _check_inbound_callback_security()

        assert c.id == "inbound_callback_security"
        assert c.category == "integration_callbacks"
        assert c.status == Status.warning
        assert c.severity == Severity.warning
        callbacks = {item["integration_id"]: item for item in c.details["callbacks"]}
        assert callbacks["github"]["replay_strategy"] == "durable_dedupe"
        assert callbacks["github"]["findings"] == []
        assert "optional_auth_setting_missing" in callbacks["bluebubbles"]["findings"]
        assert "deprecated_auth_transport" in callbacks["bluebubbles"]["findings"]
        assert "optional_auth_setting_missing" in callbacks["frigate"]["findings"]

    def test_missing_replay_contract_fails(self, monkeypatch, tmp_path):
        root = tmp_path / "weak"
        root.mkdir()
        (root / "integration.yaml").write_text(
            "id: weak\n"
            "name: Weak\n"
            "version: '1.0'\n"
            "webhook:\n"
            "  path: /integrations/weak/webhook\n"
            "  description: Weak callback\n"
        )

        monkeypatch.setattr(
            "integrations.discovery.iter_integration_candidates",
            lambda: [(root, "weak", False, "test")],
        )

        c = _check_inbound_callback_security()

        assert c.status == Status.fail
        assert c.severity == Severity.critical
        assert c.details["failed"] == ["weak"]


# ---------------------------------------------------------------------------
# DB checks
# ---------------------------------------------------------------------------

class TestExecToolsWithoutRules:
    @pytest.mark.asyncio
    async def test_no_dangerous_tools(self, db):
        tiers = {"search": "readonly"}
        bot = _make_bot(local_tools=["search"])
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers), \
             patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = await _check_exec_tools_without_rules(db)
        assert c.status == Status.passed

    @pytest.mark.asyncio
    async def test_uncovered_tools(self, db, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_ENABLED", True)
        tiers = {"exec_cmd": "exec_capable", "deploy": "control_plane"}
        bot = _make_bot(local_tools=["exec_cmd", "deploy"])
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers), \
             patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = await _check_exec_tools_without_rules(db)
        assert c.status == Status.fail
        assert c.details["count"] == 2

    @pytest.mark.asyncio
    async def test_covered_tools(self, db, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_ENABLED", True)
        tiers = {"exec_cmd": "exec_capable"}
        bot = _make_bot(local_tools=["exec_cmd"])
        rule = ToolPolicyRule(
            id=uuid.uuid4(), tool_name="exec_cmd", action="require_approval",
            enabled=True, conditions={}, priority=100, approval_timeout=300,
        )
        db.add(rule)
        await db.commit()
        with patch("app.services.security_audit.get_all_tool_tiers", return_value=tiers), \
             patch("app.services.security_audit.list_bots", return_value=[bot]):
            c = await _check_exec_tools_without_rules(db)
        assert c.status == Status.passed


class TestApprovalTimeout:
    @pytest.mark.asyncio
    async def test_all_reasonable(self, db):
        rule = ToolPolicyRule(
            id=uuid.uuid4(), tool_name="test_tool", action="require_approval",
            enabled=True, conditions={}, priority=100, approval_timeout=300,
        )
        db.add(rule)
        await db.commit()
        c = await _check_approval_timeout(db)
        assert c.status == Status.passed

    @pytest.mark.asyncio
    async def test_long_timeout(self, db):
        rule = ToolPolicyRule(
            id=uuid.uuid4(), tool_name="slow_tool", action="require_approval",
            enabled=True, conditions={}, priority=100, approval_timeout=7200,
        )
        db.add(rule)
        await db.commit()
        c = await _check_approval_timeout(db)
        assert c.status == Status.fail
        assert c.details["count"] == 1


class TestStaleApprovals:
    @pytest.mark.asyncio
    async def test_no_stale(self, db):
        approval = ToolApproval(
            id=uuid.uuid4(), bot_id="test-bot", tool_name="test",
            tool_type="local", status="pending", timeout_seconds=300,
            created_at=datetime.now(timezone.utc),
        )
        db.add(approval)
        await db.commit()
        c = await _check_stale_approvals(db)
        assert c.status == Status.passed

    @pytest.mark.asyncio
    async def test_has_stale(self, db):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        approval = ToolApproval(
            id=uuid.uuid4(), bot_id="test-bot", tool_name="exec_cmd",
            tool_type="local", status="pending", timeout_seconds=300,
            created_at=old_time,
        )
        db.add(approval)
        await db.commit()
        c = await _check_stale_approvals(db)
        assert c.status == Status.fail
        assert c.details["count"] == 1


class TestPolicyRuleCount:
    @pytest.mark.asyncio
    async def test_count(self, db):
        for i in range(3):
            db.add(ToolPolicyRule(
                id=uuid.uuid4(), tool_name=f"tool_{i}", action="deny",
                enabled=True, conditions={}, priority=100, approval_timeout=300,
            ))
        db.add(ToolPolicyRule(
            id=uuid.uuid4(), tool_name="disabled_tool", action="deny",
            enabled=False, conditions={}, priority=100, approval_timeout=300,
        ))
        await db.commit()
        c = await _check_policy_rule_count(db)
        assert c.details["count"] == 3


class TestMCPServersCount:
    @pytest.mark.asyncio
    async def test_combined_count(self, db):
        with patch("app.services.security_audit.get_configured_server_count", return_value=2):
            c = await _check_mcp_servers_count(db)
        assert c.details["yaml"] == 2
        assert c.details["db"] == 0
        assert c.details["total"] == 2


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

class TestScore:
    def test_all_pass(self):
        checks = [
            SecurityCheck(id="a", category="x", severity=Severity.critical, status=Status.passed, message="ok"),
            SecurityCheck(id="b", category="x", severity=Severity.warning, status=Status.passed, message="ok"),
            SecurityCheck(id="c", category="x", severity=Severity.info, status=Status.passed, message="ok"),
        ]
        assert _compute_score(checks) == 100

    def test_one_critical_fail(self):
        checks = [
            SecurityCheck(id="a", category="x", severity=Severity.critical, status=Status.fail, message="bad"),
            SecurityCheck(id="b", category="x", severity=Severity.warning, status=Status.passed, message="ok"),
        ]
        assert _compute_score(checks) == 75

    def test_one_warning_fail(self):
        checks = [
            SecurityCheck(id="a", category="x", severity=Severity.warning, status=Status.fail, message="bad"),
        ]
        assert _compute_score(checks) == 90

    def test_cumulative(self):
        checks = [
            SecurityCheck(id="a", category="x", severity=Severity.critical, status=Status.fail, message="bad"),
            SecurityCheck(id="b", category="x", severity=Severity.critical, status=Status.fail, message="bad"),
            SecurityCheck(id="c", category="x", severity=Severity.warning, status=Status.fail, message="bad"),
            SecurityCheck(id="d", category="x", severity=Severity.warning, status=Status.fail, message="bad"),
        ]
        # 100 - 25 - 25 - 10 - 10 = 30
        assert _compute_score(checks) == 30

    def test_floor_at_zero(self):
        checks = [
            SecurityCheck(id=f"c{i}", category="x", severity=Severity.critical, status=Status.fail, message="bad")
            for i in range(5)
        ]
        # 100 - 125 = -25 -> 0
        assert _compute_score(checks) == 0


class TestSummary:
    def test_counts(self):
        checks = [
            SecurityCheck(id="a", category="x", severity=Severity.critical, status=Status.fail, message="bad"),
            SecurityCheck(id="b", category="x", severity=Severity.critical, status=Status.passed, message="ok"),
            SecurityCheck(id="c", category="x", severity=Severity.warning, status=Status.fail, message="bad"),
            SecurityCheck(id="d", category="x", severity=Severity.info, status=Status.passed, message="ok"),
            SecurityCheck(id="e", category="x", severity=Severity.info, status=Status.warning, message="notice"),
        ]
        summary = _compute_summary(checks)
        assert summary["critical"] == 2
        assert summary["warning"] == 1
        assert summary["info"] == 2
        assert summary["pass"] == 2
        assert summary["fail"] == 2
        assert summary["warn"] == 1
        # All checks accounted for
        assert summary["pass"] + summary["fail"] + summary["warn"] == len(checks)


# ---------------------------------------------------------------------------
# Full orchestrator
# ---------------------------------------------------------------------------

class TestRunSecurityAudit:
    @pytest.mark.asyncio
    async def test_returns_23_checks(self, db, monkeypatch):
        # Patch config settings
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_ENABLED", True)
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_DEFAULT_ACTION", "deny")
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_TIER_GATING", True)
        monkeypatch.setattr("app.services.security_audit.settings.RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr("app.services.security_audit.settings.SECRET_REDACTION_ENABLED", True)
        monkeypatch.setattr("app.services.security_audit.settings.DOCKER_SANDBOX_ENABLED", False)
        monkeypatch.setattr("app.services.security_audit.settings.HOST_EXEC_ENABLED", False)
        monkeypatch.setattr("app.services.security_audit.settings.SECURITY_AUDIT_ENABLED", True)
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "admin-key")
        monkeypatch.setattr("app.services.security_audit.settings.API_KEY", "bot-key")

        with patch("app.services.security_audit.is_encryption_enabled", return_value=True), \
             patch("app.services.security_audit.get_all_tool_tiers", return_value={"t1": "readonly"}), \
             patch("app.services.security_audit.list_bots", return_value=[_make_bot()]), \
             patch("app.services.security_audit.get_configured_server_count", return_value=0):
            result = await run_security_audit(db)

        assert len(result.checks) == 23
        assert result.score >= 0
        assert result.score <= 100
        assert "pass" in result.summary
        assert "fail" in result.summary
        # Verify all check IDs are unique
        ids = [c.id for c in result.checks]
        assert len(ids) == len(set(ids))
        assert "worksurface_isolation_static" in ids
        assert "inbound_callback_security" in ids
