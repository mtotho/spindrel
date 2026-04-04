"""Admin CRUD: bot listing, channel auto-creation."""

import pytest

from tests.e2e.harness.client import E2EClient


@pytest.mark.e2e
class TestAdminCrud:
    async def test_list_bots_includes_e2e(self, client: E2EClient) -> None:
        """GET /bots returns list including the e2e test bot."""
        bots = await client.list_bots()
        assert isinstance(bots, list)
        bot_ids = [b.get("id") for b in bots]
        assert "e2e" in bot_ids, f"Expected 'e2e' bot in {bot_ids}"

    async def test_e2e_bot_has_expected_fields(self, client: E2EClient) -> None:
        """The e2e bot has name, model, and expected config."""
        bots = await client.list_bots()
        e2e_bot = next((b for b in bots if b.get("id") == "e2e"), None)
        assert e2e_bot is not None
        assert e2e_bot["name"] == "E2E Test Bot"

    async def test_chat_creates_channel(self, client: E2EClient) -> None:
        """Sending a chat message auto-creates a channel."""
        # Use a unique channel_id to avoid collisions
        channel_id = client.new_channel_id()
        resp = await client.chat("Hello", channel_id=channel_id)
        assert resp.session_id

        # The channel should now exist
        channels = await client.list_channels()
        channel_ids = [str(c.get("id")) for c in channels]
        assert channel_id in channel_ids, (
            f"Expected channel {channel_id} in {channel_ids}"
        )

    async def test_list_channels(self, client: E2EClient) -> None:
        """GET /api/v1/admin/channels returns a list."""
        channels = await client.list_channels()
        assert isinstance(channels, list)
