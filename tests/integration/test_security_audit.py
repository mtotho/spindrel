"""Integration test for the security audit endpoint."""
from unittest.mock import patch

import pytest

from .conftest import AUTH_HEADERS


@pytest.mark.asyncio
async def test_security_audit_endpoint(client):
    with patch("app.services.security_audit.is_encryption_enabled", return_value=False), \
         patch("app.services.security_audit.get_all_tool_tiers", return_value={"t": "readonly"}), \
         patch("app.services.security_audit.list_bots") as mock_bots, \
         patch("app.services.security_audit.get_configured_server_count", return_value=0):
        from unittest.mock import MagicMock
        bot = MagicMock()
        bot.id = "test-bot"
        bot.local_tools = []
        bot.host_exec.enabled = False
        mock_bots.return_value = [bot]

        resp = await client.get("/api/v1/admin/security-audit", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data
    assert "summary" in data
    assert "score" in data
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) == 18
    assert isinstance(data["score"], int)
    # Every check has required fields
    for check in data["checks"]:
        assert "id" in check
        assert "category" in check
        assert "severity" in check
        assert "status" in check
        assert "message" in check
