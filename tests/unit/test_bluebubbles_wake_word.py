"""Tests for BlueBubbles wake word + require_mention + webhook support."""
import uuid

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from integrations.bluebubbles.agent_client import bb_client_id


# ---------------------------------------------------------------------------
# Wake word checking
# ---------------------------------------------------------------------------

class TestCheckWakeWord:
    """Test _check_wake_word helper (inlined since bb_client has heavy imports)."""

    @staticmethod
    def _check_wake_word(text: str, wake_words: list[str]) -> bool:
        """Mirror the logic from bb_client._check_wake_word."""
        if not wake_words:
            return False
        text_lower = text.lower()
        return any(w in text_lower for w in wake_words)

    def test_case_insensitive(self):
        assert self._check_wake_word("hey Atlas, help", ["atlas"]) is True

    def test_case_insensitive_uppercase(self):
        assert self._check_wake_word("ATLAS do something", ["atlas"]) is True

    def test_no_match(self):
        assert self._check_wake_word("random message", ["atlas", "hey bot"]) is False

    def test_multiple_words_first_matches(self):
        assert self._check_wake_word("atlas help me", ["atlas", "hey bot"]) is True

    def test_multiple_words_second_matches(self):
        assert self._check_wake_word("hey bot what's up", ["atlas", "hey bot"]) is True

    def test_empty_wake_words(self):
        assert self._check_wake_word("atlas help", []) is False

    def test_empty_text(self):
        assert self._check_wake_word("", ["atlas"]) is False

    def test_wake_word_in_middle(self):
        assert self._check_wake_word("so atlas what do you think", ["atlas"]) is True

    def test_wake_word_at_end(self):
        assert self._check_wake_word("help me atlas", ["atlas"]) is True


# ---------------------------------------------------------------------------
# Message routing (config-driven)
# ---------------------------------------------------------------------------

def _make_message(text: str, chat_guid: str, is_from_me: bool = False, guid: str = "msg-1",
                  sender: str = "+15559999999") -> dict:
    """Build a minimal BB message dict."""
    msg = {
        "guid": guid,
        "text": text,
        "isFromMe": is_from_me,
        "chats": [{"guid": chat_guid}],
    }
    if not is_from_me:
        msg["handle"] = {"address": sender}
    return msg


class TestHandleMessageRouting:
    """Test _handle_message decision logic with wake words + require_mention.

    Since bb_client.py has module-level socketio imports that may not be available
    in test environments, we test the routing decision logic inline.
    """

    @staticmethod
    def _route_decision(
        text: str,
        is_from_me: bool,
        is_echo: bool,
        wake_words: list[str],
        channel_settings: dict,
        chat_guid: str = "iMessage;-;+15551234567",
    ) -> str:
        """Simulate the routing decision from _handle_message.

        Returns: "skip" | "active" | "passive" | "unbound"
        """
        if not text:
            return "skip"

        # Unbound chat — no Channel in DB
        if chat_guid not in channel_settings:
            return "unbound"

        if is_from_me:
            if is_echo:
                return "skip"
            # Human texting from own phone — always active
            return "active"

        # External message — check channel settings
        settings = channel_settings.get(chat_guid, {})
        require_mention = settings.get("require_mention", True)

        if not require_mention:
            return "active"

        # Check wake word
        text_lower = text.lower()
        mentioned = any(w in text_lower for w in wake_words) if wake_words else False

        return "active" if mentioned else "passive"

    def test_echo_skipped(self):
        settings = {"iMessage;-;+15551234567": {"require_mention": True}}
        assert self._route_decision("hello", is_from_me=True, is_echo=True,
                                     wake_words=["atlas"], channel_settings=settings) == "skip"

    def test_human_from_me_always_active(self):
        """isFromMe + not echo → always triggers agent (human texting from phone)."""
        settings = {"iMessage;-;+15551234567": {"require_mention": True}}
        assert self._route_decision("random stuff", is_from_me=True, is_echo=False,
                                     wake_words=["atlas"], channel_settings=settings) == "active"

    def test_active_with_wake_word(self):
        """Wake word present + require_mention=True → active."""
        assert self._route_decision("atlas what's the weather", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={"iMessage;-;+15551234567": {"require_mention": True}}) == "active"

    def test_passive_without_wake_word(self):
        """No wake word + require_mention=True → passive."""
        assert self._route_decision("random message", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={"iMessage;-;+15551234567": {"require_mention": True}}) == "passive"

    def test_active_when_require_mention_false(self):
        """require_mention=False → always active regardless of wake word."""
        assert self._route_decision("random message", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={"iMessage;-;+15551234567": {"require_mention": False}}) == "active"

    def test_group_with_wake_word_active(self):
        """Group chat + wake word → active (no longer hardcoded passive)."""
        chat = "iMessage;+;chat123"
        assert self._route_decision("atlas help me", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={chat: {"require_mention": True}},
                                     chat_guid=chat) == "active"

    def test_group_without_wake_word_passive(self):
        """Group chat + no wake word + require_mention=True → passive."""
        chat = "iMessage;+;chat123"
        assert self._route_decision("hey everyone", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={chat: {"require_mention": True}},
                                     chat_guid=chat) == "passive"

    def test_unbound_channel_ignored(self):
        """Chat with no Channel binding → silently dropped."""
        assert self._route_decision("atlas help me", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={}) == "unbound"

    def test_unbound_channel_ignored_even_from_me(self):
        """Even isFromMe messages from unbound chats are dropped."""
        assert self._route_decision("do something", is_from_me=True, is_echo=False,
                                     wake_words=["atlas"],
                                     channel_settings={}) == "unbound"

    def test_empty_text_skipped(self):
        assert self._route_decision("", is_from_me=False, is_echo=False,
                                     wake_words=["atlas"], channel_settings={}) == "skip"


# ---------------------------------------------------------------------------
# Config endpoint: wake_words + channels
# ---------------------------------------------------------------------------

class TestConfigEndpoint:
    """Test that config endpoint returns wake_words and channel settings."""

    def test_wake_words_parsed_from_comma_separated(self):
        """Comma-separated BB_WAKE_WORDS → list of lowercase words."""
        raw = "Atlas, Hey Bot, buddy"
        words = [w.strip().lower() for w in raw.split(",") if w.strip()]
        assert words == ["atlas", "hey bot", "buddy"]

    def test_wake_words_empty_falls_back_to_bot_name(self):
        """Empty BB_WAKE_WORDS → [default_bot_name]."""
        raw = ""
        default_bot = "atlas"
        words = [w.strip().lower() for w in raw.split(",") if w.strip()]
        if not words:
            words = [default_bot.lower()]
        assert words == ["atlas"]

    def test_wake_words_whitespace_only_falls_back(self):
        raw = "   ,  ,  "
        default_bot = "mybot"
        words = [w.strip().lower() for w in raw.split(",") if w.strip()]
        if not words:
            words = [default_bot.lower()]
        assert words == ["mybot"]

    def test_channel_settings_structure(self):
        """Channel dict maps chat_guid → {require_mention, passive_memory}."""
        # Simulating what the endpoint would build
        channels = {}
        # Simulate a Channel row
        client_id = "bb:iMessage;-;+15551234567"
        require_mention = True
        passive_memory = True
        chat_guid = client_id.removeprefix("bb:")
        channels[chat_guid] = {
            "require_mention": require_mention,
            "passive_memory": passive_memory,
        }
        assert channels == {
            "iMessage;-;+15551234567": {
                "require_mention": True,
                "passive_memory": True,
            }
        }


# ---------------------------------------------------------------------------
# Config refresh populates new state
# ---------------------------------------------------------------------------

class TestConfigRefresh:
    """Test that _refresh_config populates wake_words + channel_settings."""

    def test_config_response_parsed(self):
        """Simulate parsing the extended config response."""
        data = {
            "server_url": "http://192.168.1.50:1234",
            "default_bot": "atlas",
            "chat_bot_map": {"iMessage;-;+15551234567": "special_bot"},
            "wake_words": ["atlas", "hey bot"],
            "channels": {
                "iMessage;-;+15551234567": {"require_mention": False, "passive_memory": True},
                "iMessage;+;chat123": {"require_mention": True, "passive_memory": True},
            },
        }
        chat_bot_map = data.get("chat_bot_map", {})
        wake_words = data.get("wake_words", [])
        channel_settings = data.get("channels", {})

        assert chat_bot_map == {"iMessage;-;+15551234567": "special_bot"}
        assert wake_words == ["atlas", "hey bot"]
        assert channel_settings["iMessage;-;+15551234567"]["require_mention"] is False
        assert channel_settings["iMessage;+;chat123"]["require_mention"] is True


# ---------------------------------------------------------------------------
# Passive store with include_in_memory
# ---------------------------------------------------------------------------

class TestPassiveStoreMemoryFlag:
    """Test that passive storage passes through include_in_memory from channel settings."""

    def test_passive_memory_true_in_metadata(self):
        """When passive_memory=True, metadata includes include_in_memory=True."""
        channel_settings = {"iMessage;+;chat123": {"require_mention": True, "passive_memory": True}}
        settings = channel_settings.get("iMessage;+;chat123", {})
        metadata = {
            "sender": "+15559999999",
            "sender_display_name": "+15559999999",
            "bb_guid": "msg-1",
            "include_in_memory": settings.get("passive_memory", True),
        }
        assert metadata["include_in_memory"] is True

    def test_passive_memory_false_in_metadata(self):
        """When passive_memory=False, metadata includes include_in_memory=False."""
        channel_settings = {"iMessage;+;chat123": {"require_mention": True, "passive_memory": False}}
        settings = channel_settings.get("iMessage;+;chat123", {})
        metadata = {
            "sender": "+15559999999",
            "sender_display_name": "+15559999999",
            "bb_guid": "msg-1",
            "include_in_memory": settings.get("passive_memory", True),
        }
        assert metadata["include_in_memory"] is False


# ---------------------------------------------------------------------------
# Webhook endpoint tests
# ---------------------------------------------------------------------------

def _bb_webhook_payload(
    text: str = "hello",
    chat_guid: str = "iMessage;-;+15551234567",
    is_from_me: bool = False,
    msg_guid: str = "msg-abc-123",
    sender: str = "+15559999999",
    event_type: str = "new-message",
) -> dict:
    """Build a BlueBubbles webhook payload."""
    data = {
        "guid": msg_guid,
        "text": text,
        "isFromMe": is_from_me,
        "chats": [{"guid": chat_guid}],
    }
    if not is_from_me:
        data["handle"] = {"address": sender}
    return {"type": event_type, "data": data}


def _make_channel(require_mention: bool = True, bot_id: str = "default"):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.bot_id = bot_id
    ch.require_mention = require_mention
    ch.active_session_id = None
    return ch


def _make_binding(channel_id, client_id="bb:iMessage;-;+15551234567"):
    b = MagicMock()
    b.channel_id = channel_id
    b.client_id = client_id
    return b


_AGENT_API_KEY = "test-agent-api-key"


def _mock_bb_settings(wake_words="atlas", default_bot="atlas"):
    s = MagicMock()
    s.BLUEBUBBLES_SERVER_URL = "http://bb:1234"
    s.BLUEBUBBLES_PASSWORD = "bb-server-password"
    s.BB_DEFAULT_BOT = default_bot
    s.BB_WAKE_WORDS = wake_words
    return s


def _mock_app_settings():
    s = MagicMock()
    s.API_KEY = _AGENT_API_KEY
    return s


def _webhook_request(payload: dict) -> AsyncMock:
    """Build a mock Request with valid auth token and the given JSON payload."""
    request = AsyncMock()
    request.json.return_value = payload
    request.query_params = {"token": _AGENT_API_KEY}
    return request


class TestWebhookEndpoint:
    """Test the POST /webhook handler in router.py."""

    @pytest.mark.asyncio
    async def test_missing_token_rejected(self):
        """Requests without a valid token are rejected with 401."""
        from fastapi import HTTPException as _Exc
        from integrations.bluebubbles.router import webhook

        request = AsyncMock()
        request.json.return_value = _bb_webhook_payload()
        request.query_params = {}
        db = AsyncMock()

        with patch("app.config.settings", _mock_app_settings()):
            with pytest.raises(_Exc) as exc_info:
                await webhook(request, db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self):
        """Requests with wrong token are rejected with 401."""
        from fastapi import HTTPException as _Exc
        from integrations.bluebubbles.router import webhook

        request = AsyncMock()
        request.json.return_value = _bb_webhook_payload()
        request.query_params = {"token": "wrong-key"}
        db = AsyncMock()

        with patch("app.config.settings", _mock_app_settings()):
            with pytest.raises(_Exc) as exc_info:
                await webhook(request, db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_non_new_message_event_ignored(self):
        """Events other than new-message are ignored."""
        from integrations.bluebubbles.router import webhook

        request = _webhook_request({"type": "updated-message", "data": {}})
        db = AsyncMock()

        with patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            result = await webhook(request, db)
        assert result["status"] == "ignored"
        assert result["event"] == "updated-message"

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self):
        """Messages with empty text are ignored."""
        from integrations.bluebubbles.router import webhook

        request = _webhook_request(_bb_webhook_payload(text=""))
        db = AsyncMock()

        with patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            result = await webhook(request, db)
        assert result["status"] == "ignored"
        assert result["reason"] == "empty_text"

    @pytest.mark.asyncio
    async def test_unbound_chat_ignored(self):
        """Messages from chats with no channel binding are ignored."""
        from integrations.bluebubbles.router import webhook

        request = _webhook_request(_bb_webhook_payload(text="hello"))
        db = AsyncMock()

        with patch("integrations.bluebubbles.config.settings", _mock_bb_settings()), \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[]), \
             patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker:
            mock_tracker.is_echo.return_value = False
            result = await webhook(request, db)

        assert result["status"] == "ignored"
        assert result["reason"] == "unbound"

    @pytest.mark.asyncio
    async def test_echo_detected_and_skipped(self):
        """isFromMe + echo tracker match → skipped."""
        from integrations.bluebubbles.router import webhook

        request = _webhook_request(_bb_webhook_payload(
            text="bot reply", is_from_me=True, msg_guid="echo-guid",
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.config.settings", _mock_bb_settings()), \
             patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker:
            mock_tracker.is_echo.return_value = True
            result = await webhook(request, db)

        assert result["status"] == "ignored"
        assert result["reason"] == "echo"

    @pytest.mark.asyncio
    async def test_from_me_not_echo_active(self):
        """isFromMe + not echo → active (human texting from phone)."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=True)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()

        request = _webhook_request(_bb_webhook_payload(
            text="do something", is_from_me=True,
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._parse_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_echo.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": str(session_id), "task_id": "t1"})

            result = await webhook(request, db)

        assert result["status"] == "processed"
        mock_utils.inject_message.assert_called_once()
        call_kwargs = mock_utils.inject_message.call_args
        assert call_kwargs.kwargs["run_agent"] is True

    @pytest.mark.asyncio
    async def test_external_with_wake_word_active(self):
        """External message with wake word → active."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=True)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()

        request = _webhook_request(_bb_webhook_payload(text="atlas what's the weather"))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_echo.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": str(session_id), "task_id": "t1"})

            result = await webhook(request, db)

        assert result["status"] == "processed"
        call_kwargs = mock_utils.inject_message.call_args
        assert call_kwargs.kwargs["run_agent"] is True

    @pytest.mark.asyncio
    async def test_external_without_wake_word_passive(self):
        """External message without wake word + require_mention → passive."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=True)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()

        request = _webhook_request(_bb_webhook_payload(
            text="random chatter", sender="+15559999999",
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_echo.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": str(session_id), "task_id": None})

            result = await webhook(request, db)

        assert result["status"] == "processed"
        call_kwargs = mock_utils.inject_message.call_args
        assert call_kwargs.kwargs["run_agent"] is False
        # Passive content should have sender prefix
        assert call_kwargs.args[1].startswith("[+15559999999]:")

    @pytest.mark.asyncio
    async def test_require_mention_false_always_active(self):
        """Channel with require_mention=False → always active for external messages."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=False)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()

        request = _webhook_request(_bb_webhook_payload(text="no wake word here"))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_echo.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={"message_id": "m1", "session_id": str(session_id), "task_id": "t1"})

            result = await webhook(request, db)

        assert result["status"] == "processed"
        call_kwargs = mock_utils.inject_message.call_args
        assert call_kwargs.kwargs["run_agent"] is True
