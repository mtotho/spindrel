"""Unit tests for BlueBubbles integration tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_settings():
    """Patch settings so tools think BB is configured."""
    with patch("integrations.bluebubbles.tools.bluebubbles.settings") as mock_settings:
        mock_settings.BLUEBUBBLES_SERVER_URL = "http://bb.local:1234"
        mock_settings.BLUEBUBBLES_PASSWORD = "test-pass"
        yield mock_settings


@pytest.fixture()
def _mock_unconfigured(_mock_settings):
    """Override to simulate missing config."""
    _mock_settings.BLUEBUBBLES_SERVER_URL = ""
    _mock_settings.BLUEBUBBLES_PASSWORD = ""


# ---------------------------------------------------------------------------
# bb_list_chats
# ---------------------------------------------------------------------------


class TestBbListChats:
    @pytest.mark.asyncio
    async def test_returns_chats(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_list_chats

        fake_chats = [
            {
                "guid": "iMessage;-;+15551234567",
                "displayName": "Alice",
                "participants": [{"address": "+15551234567", "displayName": "Alice"}],
                "lastMessage": {"text": "Hey there!"},
                "isGroup": False,
            },
            {
                "guid": "iMessage;+;chat999",
                "displayName": "",
                "participants": [
                    {"address": "+15559876543", "displayName": "Bob"},
                    {"address": "+15551111111", "displayName": None},
                ],
                "lastMessage": {"text": "Group message"},
                "isGroup": True,
            },
        ]

        with patch("integrations.bluebubbles.bb_api.query_chats", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = fake_chats
            result = json.loads(await bb_list_chats(limit=10, offset=0))

        assert result["count"] == 2
        assert result["chats"][0]["guid"] == "iMessage;-;+15551234567"
        assert result["chats"][0]["display_name"] == "Alice"
        assert result["chats"][0]["last_message"] == "Hey there!"
        assert result["chats"][1]["is_group"] is True
        assert "Bob" in result["chats"][1]["participants"]

    @pytest.mark.asyncio
    async def test_not_configured(self, _mock_unconfigured):
        from integrations.bluebubbles.tools.bluebubbles import bb_list_chats

        result = json.loads(await bb_list_chats())
        assert "error" in result
        assert "not configured" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_api_error(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_list_chats

        with patch("integrations.bluebubbles.bb_api.query_chats", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = httpx.ConnectError("Connection refused")
            result = json.loads(await bb_list_chats())

        assert "error" in result


# ---------------------------------------------------------------------------
# bb_get_messages
# ---------------------------------------------------------------------------


class TestBbGetMessages:
    @pytest.mark.asyncio
    async def test_returns_messages(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_get_messages

        fake_messages = [
            {
                "text": "Hello!",
                "handle": {"address": "+15551234567", "displayName": "Alice"},
                "isFromMe": False,
                "dateCreated": 1711900000000,
                "attachments": [],
            },
            {
                "text": "Hi Alice",
                "handle": {},
                "isFromMe": True,
                "dateCreated": 1711900060000,
                "attachments": [],
            },
        ]

        with patch("integrations.bluebubbles.bb_api.get_chat_messages", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = fake_messages
            result = json.loads(await bb_get_messages("iMessage;-;+15551234567", limit=10))

        assert result["count"] == 2
        assert result["chat_guid"] == "iMessage;-;+15551234567"
        assert result["messages"][0]["sender"] == "Alice"
        assert result["messages"][0]["text"] == "Hello!"
        assert result["messages"][1]["sender"] == "me"
        assert result["messages"][1]["is_from_me"] is True

    @pytest.mark.asyncio
    async def test_not_configured(self, _mock_unconfigured):
        from integrations.bluebubbles.tools.bluebubbles import bb_get_messages

        result = json.loads(await bb_get_messages("iMessage;-;+15551234567"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_offset_pagination(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_get_messages

        with patch("integrations.bluebubbles.bb_api.get_chat_messages", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"text": "Older msg", "handle": {}, "isFromMe": False, "dateCreated": 1711800000000, "attachments": []}]
            result = json.loads(await bb_get_messages("iMessage;-;+15551234567", limit=10, offset=25))

        assert result["count"] == 1
        # Verify offset was passed through to the API
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs.get("offset") == 25

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_get_messages

        with patch("integrations.bluebubbles.bb_api.get_chat_messages", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = json.loads(await bb_get_messages("iMessage;-;+15551234567"))

        assert result["count"] == 0
        assert result["messages"] == []


# ---------------------------------------------------------------------------
# bb_send_message
# ---------------------------------------------------------------------------


class TestBbSendMessage:
    @pytest.mark.asyncio
    async def test_send_success(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_send_message

        with patch("integrations.bluebubbles.bb_api.send_text", new_callable=AsyncMock) as mock_send, \
             patch("integrations.bluebubbles.tools.bluebubbles.shared_tracker") as mock_tracker:
            mock_tracker.save_to_db = AsyncMock()
            mock_send.return_value = {"status": 200, "message": "Message sent"}
            result = json.loads(await bb_send_message("iMessage;-;+15551234567", "Hello!"))

        assert result["ok"] is True
        assert result["chat_guid"] == "iMessage;-;+15551234567"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_send_message

        with patch("integrations.bluebubbles.bb_api.send_text", new_callable=AsyncMock) as mock_send, \
             patch("integrations.bluebubbles.tools.bluebubbles.shared_tracker") as mock_tracker:
            mock_tracker.save_to_db = AsyncMock()
            mock_send.return_value = None
            result = json.loads(await bb_send_message("iMessage;-;+15551234567", "Hello!"))

        assert "error" in result
        assert "None" in result["error"] or "not" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_not_configured(self, _mock_unconfigured):
        from integrations.bluebubbles.tools.bluebubbles import bb_send_message

        result = json.loads(await bb_send_message("iMessage;-;+15551234567", "Hello!"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_track_sent_called(self):
        """bb_send_message must call shared_tracker.track_sent for echo detection."""
        from integrations.bluebubbles.tools.bluebubbles import bb_send_message

        with patch("integrations.bluebubbles.bb_api.send_text", new_callable=AsyncMock) as mock_send, \
             patch("integrations.bluebubbles.tools.bluebubbles.shared_tracker") as mock_tracker:
            mock_tracker.save_to_db = AsyncMock()
            mock_send.return_value = {"status": 200, "message": "Sent"}
            await bb_send_message("iMessage;-;+15551234567", "Test message")

        mock_tracker.track_sent.assert_called_once()
        call_args = mock_tracker.track_sent.call_args
        # Should pass the message text and chat_guid
        assert call_args.args[1] == "Test message"
        assert call_args.kwargs["chat_guid"] == "iMessage;-;+15551234567"

    @pytest.mark.asyncio
    async def test_track_sent_called_before_send(self):
        """track_sent should be called BEFORE send_text (so echo detection is ready)."""
        from integrations.bluebubbles.tools.bluebubbles import bb_send_message

        call_order = []

        async def _fake_send(*a, **kw):
            call_order.append("send")
            return {"status": 200}

        with patch("integrations.bluebubbles.bb_api.send_text", new_callable=AsyncMock, side_effect=_fake_send), \
             patch("integrations.bluebubbles.tools.bluebubbles.shared_tracker") as mock_tracker:
            mock_tracker.save_to_db = AsyncMock()
            def _fake_track(*a, **kw):
                call_order.append("track")
            mock_tracker.track_sent.side_effect = _fake_track
            await bb_send_message("iMessage;-;+15551234567", "Hello!")

        assert call_order == ["track", "send"]


# ---------------------------------------------------------------------------
# bb_server_info
# ---------------------------------------------------------------------------


class TestBbServerInfo:
    @pytest.mark.asyncio
    async def test_server_reachable(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_server_info

        fake_info = {
            "data": {
                "os_version": "14.3",
                "server_version": "1.9.0",
                "private_api": True,
                "helper_connected": True,
                "proxy_service": "Cloudflare",
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_info

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = json.loads(await bb_server_info())

        assert result["connected"] is True
        assert result["os_version"] == "14.3"
        assert result["server_version"] == "1.9.0"
        assert result["private_api"] is True

    @pytest.mark.asyncio
    async def test_server_non_200(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_server_info

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = json.loads(await bb_server_info())

        assert result["connected"] is False
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_server_unreachable(self):
        from integrations.bluebubbles.tools.bluebubbles import bb_server_info

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value = mock_client

            result = json.loads(await bb_server_info())

        assert result["connected"] is False
        assert "unreachable" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_not_configured(self, _mock_unconfigured):
        from integrations.bluebubbles.tools.bluebubbles import bb_server_info

        result = json.loads(await bb_server_info())
        assert "error" in result


# ---------------------------------------------------------------------------
# Config settings
# ---------------------------------------------------------------------------


class TestConfigSettings:
    def test_settings_uses_db_cache(self):
        with patch("app.services.integration_settings.get_value") as mock_get:
            mock_get.return_value = "http://from-db:1234"
            from integrations.bluebubbles.config import _get
            result = _get("BLUEBUBBLES_SERVER_URL")
            assert result == "http://from-db:1234"
            mock_get.assert_called_with("bluebubbles", "BLUEBUBBLES_SERVER_URL", "")

    def test_settings_falls_back_to_env(self):
        # Simulate ImportError by hiding the module
        import sys
        saved = sys.modules.get("app.services.integration_settings")
        sys.modules["app.services.integration_settings"] = None  # type: ignore[assignment]
        try:
            # _get caches the import, so reimport the module to reset
            import importlib
            import integrations.bluebubbles.config as cfg_mod
            importlib.reload(cfg_mod)
            with patch.dict("os.environ", {"BLUEBUBBLES_SERVER_URL": "http://from-env:5678"}):
                result = cfg_mod._get("BLUEBUBBLES_SERVER_URL")
                assert result == "http://from-env:5678"
        finally:
            if saved is not None:
                sys.modules["app.services.integration_settings"] = saved
            else:
                sys.modules.pop("app.services.integration_settings", None)
            # Reload to restore normal behavior
            import importlib
            import integrations.bluebubbles.config as cfg_mod2
            importlib.reload(cfg_mod2)
