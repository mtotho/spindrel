"""Tests for safety-tier → policy-engine bridge.

Covers:
- Tier gating: exec_capable/control_plane auto-require approval when no rule matches
- Fallthrough: readonly/mutating/unknown use global default
- Explicit rules override tier defaults
- Session allows bypass tier gating
- API: settings, tiers endpoint, test response with tier field
- Approvals: safety_tier field on ApprovalOut
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tool_policies import (
    PolicyDecision,
    _TIER_DEFAULTS,
    evaluate_tool_policy,
    invalidate_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(rules: list | None = None) -> AsyncMock:
    """Return a mock AsyncSession whose execute returns the given rules.

    The chain is: (await db.execute(stmt)).scalars().all() → rules
    `await db.execute(...)` returns a coroutine result, but `.scalars()` and
    `.all()` are synchronous calls on that result, so we use MagicMock.
    """
    rules = rules or []
    db = AsyncMock(spec=AsyncSession)
    # await db.execute(stmt) returns execute_result
    execute_result = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = rules
    execute_result.scalars.return_value = scalars_result
    db.execute.return_value = execute_result
    # expunge is synchronous
    db.expunge = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Tier gating tests
# ---------------------------------------------------------------------------

class TestTierGating:
    """When no explicit rule matches, safety tier determines default action."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        invalidate_cache()
        yield
        invalidate_cache()

    @pytest.mark.asyncio
    async def test_exec_capable_requires_approval_when_default_not_allow(self):
        """exec_capable tool → require_approval when tier gating is on and default != allow."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "deny"
            decision = await evaluate_tool_policy(db, "bot1", "exec_command", {})
        assert decision.action == "require_approval"
        assert decision.tier == "exec_capable"
        assert "exec_capable" in decision.reason

    @pytest.mark.asyncio
    async def test_control_plane_requires_approval_when_default_not_allow(self):
        """control_plane tool → require_approval when tier gating is on and default != allow."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="control_plane"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "deny"
            decision = await evaluate_tool_policy(db, "bot1", "manage_stacks", {})
        assert decision.action == "require_approval"
        assert decision.tier == "control_plane"

    @pytest.mark.asyncio
    async def test_exec_capable_respects_default_allow(self):
        """exec_capable tool → allow when default_action='allow' (tier gating skipped)."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "exec_command", {})
        assert decision.action == "allow"
        assert decision.tier is None

    @pytest.mark.asyncio
    async def test_control_plane_respects_default_allow(self):
        """control_plane tool → allow when default_action='allow' (tier gating skipped)."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "manage_stacks", {})
        assert decision.action == "allow"
        assert decision.tier is None

    @pytest.mark.asyncio
    async def test_readonly_uses_global_default(self):
        """readonly tool → falls through to global default."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="readonly"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "web_search", {})
        assert decision.action == "allow"
        assert decision.tier is None

    @pytest.mark.asyncio
    async def test_mutating_uses_global_default(self):
        """mutating tool → falls through to global default."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="mutating"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "deny"
            decision = await evaluate_tool_policy(db, "bot1", "save_memory", {})
        assert decision.action == "deny"
        assert decision.tier is None

    @pytest.mark.asyncio
    async def test_unknown_tier_uses_global_default(self):
        """Unregistered tool (unknown tier) → falls through to global default."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="unknown"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "mystery_tool", {})
        assert decision.action == "allow"
        assert decision.tier is None


class TestTierOverrides:
    """Explicit rules and config overrides take precedence."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        invalidate_cache()
        yield
        invalidate_cache()

    @pytest.mark.asyncio
    async def test_explicit_allow_overrides_tier(self):
        """An explicit allow rule for an exec_capable tool → allow (rule wins)."""
        rule = _make_rule(tool_name="exec_command", action="allow", priority=100)
        db = _make_db([rule])
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "deny"
            decision = await evaluate_tool_policy(db, "bot1", "exec_command", {})
        assert decision.action == "allow"
        assert decision.rule_id == str(rule.id)
        # Tier should not be set when a rule matches
        assert decision.tier is None

    @pytest.mark.asyncio
    async def test_explicit_deny_overrides_tier(self):
        """An explicit deny rule → deny (rule wins over tier default)."""
        rule = _make_rule(tool_name="exec_command", action="deny", priority=100, reason="blocked")
        db = _make_db([rule])
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = True
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "exec_command", {})
        assert decision.action == "deny"
        assert decision.rule_id == str(rule.id)

    @pytest.mark.asyncio
    async def test_tier_gating_disabled(self):
        """TOOL_POLICY_TIER_GATING=False → exec_capable uses global default."""
        db = _make_db()
        with (
            patch("app.services.tool_policies.settings") as mock_settings,
            patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"),
        ):
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(db, "bot1", "exec_command", {})
        assert decision.action == "allow"
        assert decision.tier is None


class TestSessionAllowBypassesTier:
    """Session allows bypass tier gating entirely (checked in _check_tool_policy)."""

    def test_session_allow_bypasses_tier_gating(self):
        """Previously approved tool returns None from _check_tool_policy (bypasses everything)."""
        from app.agent.session_allows import _allows, add_session_allow

        _allows.clear()
        add_session_allow("corr-abc", "exec_command")

        # The session allow check happens in _check_tool_policy (tool_dispatch.py),
        # not in evaluate_tool_policy. We test the component directly.
        from app.agent.session_allows import is_session_allowed
        assert is_session_allowed("corr-abc", "exec_command") is True
        _allows.clear()


class TestPolicyDecisionTierField:
    """PolicyDecision.tier is populated correctly."""

    def test_tier_decision_includes_tier_field(self):
        d = PolicyDecision(action="require_approval", reason="tier gating", tier="exec_capable")
        assert d.tier == "exec_capable"

    def test_tier_field_defaults_to_none(self):
        d = PolicyDecision(action="allow", reason="no rule")
        assert d.tier is None


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

class TestPolicySettingsAPI:
    """Settings endpoint includes tier_gating field."""

    def test_settings_includes_tier_gating(self):
        """PolicySettingsOut accepts and returns tier_gating field."""
        from app.routers.api_v1_tool_policies import PolicySettingsOut
        out = PolicySettingsOut(default_action="allow", enabled=True, tier_gating=True)
        assert out.tier_gating is True

    def test_update_tier_gating(self):
        """PolicySettingsUpdate accepts tier_gating."""
        from app.routers.api_v1_tool_policies import PolicySettingsUpdate
        body = PolicySettingsUpdate(tier_gating=False)
        assert body.tier_gating is False

    def test_test_endpoint_includes_tier(self):
        """PolicyTestResponse includes tier field."""
        from app.routers.api_v1_tool_policies import PolicyTestResponse
        resp = PolicyTestResponse(
            action="require_approval",
            reason="tier gating",
            tier="exec_capable",
        )
        assert resp.tier == "exec_capable"


class TestTiersEndpoint:
    """GET /tiers returns tool→tier mapping."""

    def test_tiers_endpoint_response_format(self):
        """Verify the tiers endpoint returns the expected structure."""
        from app.tools.registry import get_all_tool_tiers
        tiers = get_all_tool_tiers()
        # Should return a dict (may be empty in test env without loaded tools)
        assert isinstance(tiers, dict)


class TestApprovalSafetyTier:
    """ApprovalOut includes safety_tier field."""

    def test_approval_out_has_safety_tier(self):
        from app.routers.api_v1_approvals import ApprovalOut
        assert "safety_tier" in ApprovalOut.model_fields


class TestTierDefaults:
    """Verify the _TIER_DEFAULTS constant is correct."""

    def test_exec_capable_mapped(self):
        assert _TIER_DEFAULTS["exec_capable"] == "require_approval"

    def test_control_plane_mapped(self):
        assert _TIER_DEFAULTS["control_plane"] == "require_approval"

    def test_readonly_not_mapped(self):
        assert "readonly" not in _TIER_DEFAULTS

    def test_mutating_not_mapped(self):
        assert "mutating" not in _TIER_DEFAULTS


# ---------------------------------------------------------------------------
# Helpers for rule mocking
# ---------------------------------------------------------------------------

class _FakeRule:
    """Minimal object matching ToolPolicyRule interface for tests."""
    def __init__(self, *, tool_name="*", action="allow", priority=100,
                 bot_id=None, conditions=None, reason=None, approval_timeout=300):
        self.id = uuid.uuid4()
        self.tool_name = tool_name
        self.action = action
        self.priority = priority
        self.bot_id = bot_id
        self.conditions = conditions or {}
        self.reason = reason
        self.approval_timeout = approval_timeout
        self.enabled = True
        self.created_at = None


def _make_rule(**kwargs) -> _FakeRule:
    return _FakeRule(**kwargs)


# ---------------------------------------------------------------------------
# Origin-kind gating tests (autonomous-run defaults + rule matching)
# ---------------------------------------------------------------------------

class TestOriginKindGating:
    """autonomous contexts (heartbeat/task/subagent/hygiene) default-require
    approval for destructive file ops and exec_command; chat stays allow."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        invalidate_cache()
        yield
        invalidate_cache()

    @pytest.mark.asyncio
    async def test_overwrite_from_heartbeat_requires_approval(self):
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "overwrite"},
                origin_kind="heartbeat",
            )
        assert decision.action == "require_approval"
        assert "autonomous" in decision.reason.lower() or "heartbeat" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_overwrite_from_chat_allowed(self):
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "overwrite"},
                origin_kind="chat",
            )
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_overwrite_from_none_origin_treated_as_chat(self):
        """None origin defaults to interactive chat behavior (allow)."""
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "overwrite"},
                origin_kind=None,
            )
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_delete_from_autonomous_requires_approval(self):
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            for origin in ("heartbeat", "task", "subagent", "hygiene"):
                decision = await evaluate_tool_policy(
                    db, "bot1", "file", {"operation": "delete"},
                    origin_kind=origin,
                )
                assert decision.action == "require_approval", f"failed for origin={origin}"

    @pytest.mark.asyncio
    async def test_read_from_autonomous_not_gated(self):
        """Read ops are never destructive — autonomous default does not fire."""
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "read"},
                origin_kind="heartbeat",
            )
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_exec_command_from_autonomous_requires_approval(self):
        db = _make_db()
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "exec_command", {"command": "ls"},
                origin_kind="heartbeat",
            )
        assert decision.action == "require_approval"

    @pytest.mark.asyncio
    async def test_explicit_allow_rule_beats_autonomous_default(self):
        """A user-installed allow rule still wins over autonomous defaults."""
        rule = _make_rule(
            tool_name="file", action="allow", priority=50,
            conditions={"arguments": {"operation": {"in": ["overwrite"]}}},
        )
        db = _make_db([rule])
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "overwrite"},
                origin_kind="heartbeat",
            )
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_origin_kind_condition_in_rule(self):
        """Rules can explicitly target origin_kind via conditions."""
        rule = _make_rule(
            tool_name="file", action="deny", priority=50,
            conditions={"origin_kind": {"in": ["heartbeat"]}},
        )
        db = _make_db([rule])
        with patch("app.services.tool_policies.settings") as mock_settings:
            mock_settings.TOOL_POLICY_TIER_GATING = False
            mock_settings.TOOL_POLICY_DEFAULT_ACTION = "allow"
            # Heartbeat origin: rule matches → deny
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "read"},
                origin_kind="heartbeat",
            )
            assert decision.action == "deny"
            # Chat origin: rule does NOT match → allow
            decision = await evaluate_tool_policy(
                db, "bot1", "file", {"operation": "read"},
                origin_kind="chat",
            )
            assert decision.action == "allow"
