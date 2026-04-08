"""Admin CRUD: bot listing, channel auto-creation."""

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.config import E2EConfig


@pytest.mark.e2e
class TestAdminCrud:
    async def test_list_bots_includes_configured_bot(self, client: E2EClient) -> None:
        """GET /bots returns list including the configured test bot."""
        bots = await client.list_bots()
        assert isinstance(bots, list)
        bot_ids = [b.get("id") for b in bots]
        assert client.default_bot_id in bot_ids, (
            f"Expected '{client.default_bot_id}' bot in {bot_ids}"
        )

    async def test_configured_bot_has_expected_fields(self, client: E2EClient) -> None:
        """The configured test bot has name and model."""
        bots = await client.list_bots()
        bot = next((b for b in bots if b.get("id") == client.default_bot_id), None)
        assert bot is not None
        assert bot.get("name"), "Bot should have a name"
        assert bot.get("model"), "Bot should have a model"

    async def test_chat_creates_channel(self, client: E2EClient, e2e_config: E2EConfig) -> None:
        """Sending a chat message auto-creates a channel."""
        channel_id = client.new_channel_id()
        resp = await client.chat("Hello", channel_id=channel_id)
        assert resp.session_id

        if e2e_config.is_external:
            # External mode: channel routing depends on client_id,
            # so new channel_id may not appear in admin list. Just verify chat worked.
            return

        # Compose mode: verify channel was created with our ID
        r = await client.get(f"/api/v1/admin/channels/{channel_id}")
        assert r.status_code == 200, f"Expected channel {channel_id} to exist, got {r.status_code}"

    async def test_list_channels(self, client: E2EClient) -> None:
        """GET /api/v1/admin/channels returns a list."""
        channels = await client.list_channels()
        assert isinstance(channels, list)
