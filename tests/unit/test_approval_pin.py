"""Unit tests for pin_capability in the approval decide endpoint."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_approval_row(bot_id="test-bot", tool_name="activate_capability", status="pending"):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.bot_id = bot_id
    row.tool_name = tool_name
    row.tool_type = "local"
    row.status = status
    row.decided_by = None
    row.decided_at = None
    row.correlation_id = uuid.uuid4()
    row.arguments = {"id": "code-review"}
    row.policy_rule_id = None
    row.reason = "Bot wants to activate 'Code Review' capability"
    row.session_id = uuid.uuid4()
    row.channel_id = uuid.uuid4()
    row.client_id = "client-1"
    row.dispatch_type = None
    row.dispatch_metadata = None
    row.timeout_seconds = 300
    row.created_at = datetime.now(timezone.utc)
    # Allow attribute setting like a real ORM row
    type(row).__setattr__ = lambda self, name, value: object.__setattr__(self, name, value)
    return row


def _make_bot_row(bot_id="test-bot", carapaces=None):
    row = MagicMock()
    row.id = bot_id
    row.carapaces = list(carapaces or [])
    type(row).__setattr__ = lambda self, name, value: object.__setattr__(self, name, value)
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPinCapability:
    @pytest.mark.asyncio
    async def test_pin_capability_adds_to_bot_carapaces(self):
        """POST decide with pin_capability adds the capability to bot's carapaces list."""
        from app.routers.api_v1_approvals import decide_approval, DecideRequest

        approval_row = _make_approval_row()
        bot_row = _make_bot_row(carapaces=["existing-cap"])

        # db.get is called twice: once for ToolApproval, once for BotRow
        call_count = [0]
        async def mock_get(model, id_):
            call_count[0] += 1
            if call_count[0] == 1:
                return approval_row  # ToolApproval
            return bot_row  # Bot

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = DecideRequest(approved=True, decided_by="test:user", pin_capability="code-review")

        with patch("app.agent.approval_pending.resolve_approval", return_value=True), \
             patch("app.agent.session_allows.add_session_allow"), \
             patch("app.agent.bots.reload_bots", new_callable=AsyncMock) as mock_reload:
            resp = await decide_approval(
                approval_id=approval_row.id,
                body=body,
                _auth=None,
                db=mock_db,
            )

        assert resp.capability_pinned == "code-review"
        assert "code-review" in bot_row.carapaces
        assert "existing-cap" in bot_row.carapaces
        mock_reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_pin_capability_idempotent(self):
        """Already pinned capability should not create a duplicate."""
        from app.routers.api_v1_approvals import decide_approval, DecideRequest

        approval_row = _make_approval_row()
        bot_row = _make_bot_row(carapaces=["code-review", "other"])

        call_count = [0]
        async def mock_get(model, id_):
            call_count[0] += 1
            if call_count[0] == 1:
                return approval_row
            return bot_row

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = DecideRequest(approved=True, decided_by="test:user", pin_capability="code-review")

        with patch("app.agent.approval_pending.resolve_approval", return_value=True), \
             patch("app.agent.session_allows.add_session_allow"), \
             patch("app.agent.bots.reload_bots", new_callable=AsyncMock):
            resp = await decide_approval(
                approval_id=approval_row.id,
                body=body,
                _auth=None,
                db=mock_db,
            )

        assert resp.capability_pinned == "code-review"
        assert bot_row.carapaces.count("code-review") == 1

    @pytest.mark.asyncio
    async def test_pin_capability_reloads_bots(self):
        """Pinning a capability should trigger reload_bots()."""
        from app.routers.api_v1_approvals import decide_approval, DecideRequest

        approval_row = _make_approval_row()
        bot_row = _make_bot_row()

        call_count = [0]
        async def mock_get(model, id_):
            call_count[0] += 1
            if call_count[0] == 1:
                return approval_row
            return bot_row

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = DecideRequest(approved=True, decided_by="test:user", pin_capability="code-review")

        with patch("app.agent.approval_pending.resolve_approval", return_value=True), \
             patch("app.agent.session_allows.add_session_allow"), \
             patch("app.agent.bots.reload_bots", new_callable=AsyncMock) as mock_reload:
            await decide_approval(
                approval_id=approval_row.id,
                body=body,
                _auth=None,
                db=mock_db,
            )

        mock_reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_pin_capability_ignored_on_deny(self):
        """pin_capability should be ignored when approved=False."""
        from app.routers.api_v1_approvals import decide_approval, DecideRequest

        approval_row = _make_approval_row()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=approval_row)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = DecideRequest(approved=False, decided_by="test:user", pin_capability="code-review")

        with patch("app.agent.approval_pending.resolve_approval", return_value=True):
            resp = await decide_approval(
                approval_id=approval_row.id,
                body=body,
                _auth=None,
                db=mock_db,
            )

        assert resp.capability_pinned is None
        assert approval_row.status == "denied"
