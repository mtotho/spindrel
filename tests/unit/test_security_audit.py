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
    _check_deployment_tier_readiness,
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
    _check_browser_live_pairing_surface,
    _check_machine_control_lease_state,
    _check_machine_control_tool_gates,
    _check_mcp_servers_count,
    _check_policy_rule_count,
    _check_rate_limiting,
    _check_secret_redaction,
    _check_stale_approvals,
    _check_tier_gating,
    _check_tool_tier_distribution,
    _check_tools_missing_tier,
    _check_widget_action_api_allowlist,
    _check_widget_db_sql_authorizer,
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


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _fake_machine_db(leases, sessions):
    db = MagicMock()
    results = [_FakeScalarResult(leases), _FakeScalarResult(sessions)]

    async def _execute(_stmt):
        return results.pop(0)

    db.execute.side_effect = _execute
    return db


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------

class TestEncryptionKey:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.ENCRYPTION_STRICT", True)
        with patch("app.services.security_audit.is_encryption_enabled", return_value=True):
            c = _check_encryption_key()
        assert c.status == Status.passed
        assert c.recommendation is None
        assert c.details == {"strict": True}

    def test_warns_when_strict_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.ENCRYPTION_STRICT", False)
        with patch("app.services.security_audit.is_encryption_enabled", return_value=True):
            c = _check_encryption_key()
        assert c.status == Status.warning
        assert c.recommendation is not None
        assert c.details == {"strict": False}

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


class TestDeploymentTierReadiness:
    def _set_baseline(self, monkeypatch, *, encrypted=True, strict=True, tier_gating=True, jwt="persistent"):
        monkeypatch.setattr("app.services.security_audit.settings.ENCRYPTION_STRICT", strict)
        monkeypatch.setattr("app.services.security_audit.settings.TOOL_POLICY_TIER_GATING", tier_gating)
        monkeypatch.setattr("app.services.security_audit.settings.JWT_SECRET", jwt)
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "admin-secret")
        monkeypatch.setattr("app.services.security_audit.settings.RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr("app.services.security_audit.settings.SECRET_REDACTION_ENABLED", True)
        return patch(
            "app.services.security_audit.is_encryption_enabled",
            return_value=encrypted,
        )

    def test_localhost_baseline_passes(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "localhost")
        with self._set_baseline(monkeypatch):
            c = _check_deployment_tier_readiness()
        assert c.status == Status.passed
        assert c.severity == Severity.info
        assert c.details["gaps"] == []

    def test_localhost_flags_missing_encryption(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "localhost")
        with self._set_baseline(monkeypatch, encrypted=False):
            c = _check_deployment_tier_readiness()
        assert c.status == Status.warning
        assert c.severity == Severity.info
        ids = {g["id"] for g in c.details["gaps"]}
        assert "encryption_key" in ids

    def test_lan_requires_admin_key_separation(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "lan")
        monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "")
        with self._set_baseline(monkeypatch):
            monkeypatch.setattr("app.services.security_audit.settings.ADMIN_API_KEY", "")
            c = _check_deployment_tier_readiness()
        assert c.status == Status.warning
        assert c.severity == Severity.warning
        ids = {g["id"] for g in c.details["gaps"]}
        assert "admin_api_key_separation" in ids

    def test_vpn_critical_when_rate_limit_off(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "vpn")
        with self._set_baseline(monkeypatch):
            monkeypatch.setattr("app.services.security_audit.settings.RATE_LIMIT_ENABLED", False)
            c = _check_deployment_tier_readiness()
        assert c.status == Status.fail
        assert c.severity == Severity.critical
        ids = {g["id"] for g in c.details["gaps"]}
        assert "rate_limiting" in ids

    def test_public_tier_unsupported(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "public")
        with self._set_baseline(monkeypatch):
            c = _check_deployment_tier_readiness()
        assert c.status == Status.fail
        assert c.severity == Severity.critical
        ids = {g["id"] for g in c.details["gaps"]}
        assert "tier_unsupported" in ids

    def test_unknown_tier_value_flagged(self, monkeypatch):
        monkeypatch.setattr("app.services.security_audit.settings.DEPLOYMENT_TIER", "datacenter")
        with self._set_baseline(monkeypatch):
            c = _check_deployment_tier_readiness()
        assert c.status == Status.fail
        assert c.details["declared_tier"] == "datacenter"


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


class TestWidgetDbSqlAuthorizer:
    def test_current_authorizer_denies_file_boundary_operations(self):
        c = _check_widget_db_sql_authorizer()
        assert c.status == Status.passed
        assert "SQLITE_ATTACH" in c.details["denied_actions"]
        assert "SQLITE_DETACH" in c.details["denied_actions"]
        assert "load_extension" in c.details["denied_functions"]

    def test_missing_attach_denial_fails_critical(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.widget_db._DENIED_SQLITE_ACTION_NAMES",
            {"SQLITE_DETACH", "SQLITE_LOAD_EXTENSION", "SQLITE_VACUUM"},
        )
        c = _check_widget_db_sql_authorizer()
        assert c.status == Status.fail
        assert c.severity == Severity.critical
        assert "SQLITE_ATTACH" in c.details["missing_actions"]


class TestWorkSurfaceIsolationStatic:
    def test_static_findings_surface_in_security_audit(self):
        c = _check_worksurface_isolation_static()

        assert c.id == "worksurface_isolation_static"
        assert c.category == "agentic_boundaries"
        assert c.status == Status.passed
        assert c.severity == Severity.info
        assert c.details is not None
        findings = {f["id"]: f for f in c.details["findings"]}
        assert findings["shared_workspace_unscoped_secret_injection"]["status"] == "pass"
        assert findings["legacy_cross_workspace_access_flag"]["status"] == "pass"
        assert findings["widget_workspace_scope_needs_worksurface_review"]["status"] == "pass"


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


class TestMachineControlToolGates:
    def test_machine_tools_have_expected_execution_gates(self):
        expected = {
            "machine_status": ("readonly", "interactive_user"),
            "machine_inspect_command": ("readonly", "live_target_lease"),
            "machine_exec_command": ("exec_capable", "live_target_lease"),
        }

        with patch("app.services.security_audit.get_tool_safety_tier", side_effect=lambda name: expected[name][0]), \
             patch("app.services.security_audit.get_tool_execution_policy", side_effect=lambda name: expected[name][1]):
            c = _check_machine_control_tool_gates()

        assert c.status == Status.passed
        assert c.details["observed"]["machine_exec_command"]["execution_policy"] == "live_target_lease"

    def test_machine_exec_without_lease_gate_fails_critical(self):
        with patch("app.services.security_audit.get_tool_safety_tier", return_value="readonly"), \
             patch("app.services.security_audit.get_tool_execution_policy", return_value="normal"):
            c = _check_machine_control_tool_gates()

        assert c.status == Status.fail
        assert c.severity == Severity.critical
        assert c.details["mismatches"]


class TestBrowserLivePairingSurface:
    def test_no_token_no_connections_passes(self):
        bridge = MagicMock()
        bridge.list_connections.return_value = []
        with patch("app.services.integration_settings.get_status", return_value="available"), \
             patch("app.services.integration_settings.get_value", return_value=""), \
             patch("integrations.browser_live.bridge.bridge", bridge):
            c = _check_browser_live_pairing_surface()

        assert c.status == Status.passed

    def test_configured_token_warns(self):
        bridge = MagicMock()
        bridge.list_connections.return_value = []
        with patch("app.services.integration_settings.get_status", return_value="enabled"), \
             patch("app.services.integration_settings.get_value", return_value="secret"), \
             patch("integrations.browser_live.bridge.bridge", bridge):
            c = _check_browser_live_pairing_surface()

        assert c.status == Status.warning
        assert c.details["token_configured"] is True

    def test_active_connection_warns(self):
        bridge = MagicMock()
        bridge.list_connections.return_value = [{"connection_id": "c1", "label": "browser"}]
        with patch("app.services.integration_settings.get_status", return_value="enabled"), \
             patch("app.services.integration_settings.get_value", return_value="secret"), \
             patch("integrations.browser_live.bridge.bridge", bridge):
            c = _check_browser_live_pairing_surface()

        assert c.status == Status.warning
        assert c.details["connection_count"] == 1


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


class TestMCPOutboundUrlGuard:
    @pytest.mark.asyncio
    async def test_default_deny_passes(self, db, monkeypatch):
        from app.services.security_audit import _check_mcp_outbound_url_guard
        monkeypatch.setattr(
            "app.services.security_audit.settings.MCP_ALLOW_PRIVATE_NETWORKS", False,
        )
        monkeypatch.setattr(
            "app.services.security_audit.settings.MCP_ALLOW_LOOPBACK", False,
        )
        c = await _check_mcp_outbound_url_guard(db)
        assert c.status == Status.passed
        assert c.details["allow_private_networks"] is False
        assert c.details["allow_loopback"] is False

    @pytest.mark.asyncio
    async def test_private_opt_in_warns(self, db, monkeypatch):
        from app.services.security_audit import _check_mcp_outbound_url_guard
        monkeypatch.setattr(
            "app.services.security_audit.settings.MCP_ALLOW_PRIVATE_NETWORKS", True,
        )
        monkeypatch.setattr(
            "app.services.security_audit.settings.MCP_ALLOW_LOOPBACK", False,
        )
        c = await _check_mcp_outbound_url_guard(db)
        assert c.status == Status.warning
        assert "private networks" in c.message
        assert c.details["allow_private_networks"] is True


class TestAllowRulesAutonomousScope:
    @pytest.mark.asyncio
    async def test_no_rules_passes(self, db):
        from app.services.security_audit import _check_allow_rules_autonomous_scope
        c = await _check_allow_rules_autonomous_scope(db)
        assert c.status == Status.passed
        assert c.details["interactive_only"] == []
        assert c.details["autonomous_opt_in"] == []

    @pytest.mark.asyncio
    async def test_interactive_only_rule_listed(self, db):
        from app.services.security_audit import _check_allow_rules_autonomous_scope
        rule = ToolPolicyRule(
            id=uuid.uuid4(),
            tool_name="exec_command",
            action="allow",
            enabled=True,
            priority=0,
            conditions=None,
            approval_timeout=300,
        )
        db.add(rule)
        await db.commit()
        c = await _check_allow_rules_autonomous_scope(db)
        assert len(c.details["interactive_only"]) == 1
        assert c.details["interactive_only"][0]["tool_name"] == "exec_command"
        assert c.details["autonomous_opt_in"] == []

    @pytest.mark.asyncio
    async def test_autonomous_opt_in_rule_separated(self, db):
        from app.services.security_audit import _check_allow_rules_autonomous_scope
        rule = ToolPolicyRule(
            id=uuid.uuid4(),
            tool_name="file",
            action="allow",
            enabled=True,
            priority=0,
            conditions={"apply_to_autonomous": True},
            approval_timeout=300,
        )
        db.add(rule)
        await db.commit()
        c = await _check_allow_rules_autonomous_scope(db)
        assert c.details["interactive_only"] == []
        assert len(c.details["autonomous_opt_in"]) == 1
        assert c.details["autonomous_opt_in"][0]["apply_to_autonomous"] is True


class TestMachineControlLeaseState:
    @pytest.mark.asyncio
    async def test_no_leases_passes(self):
        c = await _check_machine_control_lease_state(_fake_machine_db([], []))

        assert c.status == Status.passed
        assert c.details["active_count"] == 0

    @pytest.mark.asyncio
    async def test_active_lease_warns(self):
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        lease = MagicMock(
            session_id=session_id,
            user_id=user_id,
            provider_id="local_companion",
            target_id="laptop",
            lease_id="lease-active",
            granted_at=now,
            expires_at=now + timedelta(minutes=15),
            capabilities=["shell"],
            metadata_={},
        )

        c = await _check_machine_control_lease_state(_fake_machine_db([lease], []))

        assert c.status == Status.warning
        assert c.details["active_count"] == 1
        assert c.details["overlong_count"] == 0

    @pytest.mark.asyncio
    async def test_overlong_lease_fails_critical(self):
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        lease = MagicMock(
            session_id=session_id,
            user_id=user_id,
            provider_id="local_companion",
            target_id="laptop",
            lease_id="lease-overlong",
            granted_at=now,
            expires_at=now + timedelta(hours=2),
            capabilities=["shell"],
            metadata_={},
        )

        c = await _check_machine_control_lease_state(_fake_machine_db([lease], []))

        assert c.status == Status.fail
        assert c.severity == Severity.critical
        assert c.details["overlong_count"] == 1

    @pytest.mark.asyncio
    async def test_legacy_metadata_lease_warns(self):
        session_id = uuid.uuid4()
        session = MagicMock(
            id=session_id,
            client_id="web",
            bot_id="default",
            metadata_={
                "machine_target_lease": {
                    "lease_id": "legacy",
                    "provider_id": "local_companion",
                    "target_id": "old",
                    "expires_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )

        c = await _check_machine_control_lease_state(_fake_machine_db([], [session]))

        assert c.status == Status.warning
        assert c.details["legacy_metadata_count"] == 1


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

class TestManifestHashDriftSeverity:
    """Phase 2 promotes signed-and-tampered to a hard fail; unsigned-and-
    drifted stays a warning. Exercised against the live function so the
    severity branches stay in sync with what the dashboard surfaces."""

    @pytest.mark.asyncio
    async def test_passes_when_no_drift_and_all_signed_clean(self, db, monkeypatch):
        from app.services.security_audit import _check_manifest_hash_drift
        from app.services.manifest_signing import sign_skill_payload
        from app.db.models import Skill
        import hashlib

        monkeypatch.setattr(
            "app.services.manifest_signing.settings.ENCRYPTION_KEY", "k"
        )
        sig = sign_skill_payload("body", [])
        db.add(Skill(
            id="s1", name="s1", content="body",
            content_hash=hashlib.sha256(b"body").hexdigest(),
            signature=sig,
        ))
        await db.commit()

        result = await _check_manifest_hash_drift(db)
        assert result.status == Status.passed
        assert result.severity == Severity.warning  # baseline severity stays warning when passed

    @pytest.mark.asyncio
    async def test_warns_on_unsigned_hash_drift(self, db, monkeypatch):
        from app.services.security_audit import _check_manifest_hash_drift
        from app.db.models import Skill

        monkeypatch.setattr(
            "app.services.manifest_signing.settings.ENCRYPTION_KEY", "k"
        )
        # Unsigned (signature=NULL) row whose content_hash drifted.
        db.add(Skill(
            id="s1", name="s1", content="real body",
            content_hash="0" * 64,
            signature=None,
        ))
        await db.commit()

        result = await _check_manifest_hash_drift(db)
        assert result.status == Status.warning
        assert result.severity == Severity.warning
        assert result.details["drift_findings"] == 1
        assert result.details["signature_tampered"] == 0

    @pytest.mark.asyncio
    async def test_fails_when_signed_and_tampered(self, db, monkeypatch):
        """Phase 2 win: a row with a persisted signature that no longer
        verifies promotes from warning to fail. The loader already refuses
        these rows; the audit surfaces the active denial."""
        from app.services.security_audit import _check_manifest_hash_drift
        from app.services.manifest_signing import sign_skill_payload
        from app.db.models import Skill
        import hashlib

        monkeypatch.setattr(
            "app.services.manifest_signing.settings.ENCRYPTION_KEY", "k"
        )
        # Row was signed over "original" content, but the body says
        # "tampered" — verify_skill_row returns False.
        sig = sign_skill_payload("original", [])
        db.add(Skill(
            id="s1", name="s1", content="tampered",
            content_hash=hashlib.sha256(b"tampered").hexdigest(),
            signature=sig,
        ))
        await db.commit()

        result = await _check_manifest_hash_drift(db)
        assert result.status == Status.fail
        assert result.severity == Severity.critical
        assert result.details["signature_tampered"] == 1
        assert "trust-current-state" in (result.recommendation or "")


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
    async def test_returns_35_checks(self, db, monkeypatch):
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

        assert len(result.checks) == 35
        assert result.score >= 0
        assert result.score <= 100
        assert "pass" in result.summary
        assert "fail" in result.summary
        # Verify all check IDs are unique
        ids = [c.id for c in result.checks]
        assert len(ids) == len(set(ids))
        assert "worksurface_isolation_static" in ids
        assert "inbound_callback_security" in ids
        assert "widget_db_sql_authorizer" in ids
        assert "machine_control_tool_gates" in ids
        assert "browser_live_pairing_surface" in ids
        assert "machine_control_lease_state" in ids
        assert "widget_token_revocations" in ids
