"""Tests for BlueBubbles sender metadata passed through inject_message.

Verifies that the webhook handler correctly populates extra_metadata
with sender_id, sender_display_name, is_from_me, and binding_display_name
so the UI can show proper attribution for BB messages.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures (shared with test_bluebubbles_wake_word.py patterns)
# ---------------------------------------------------------------------------

def _bb_webhook_payload(
    text: str = "hello",
    chat_guid: str = "iMessage;-;+15551234567",
    is_from_me: bool = False,
    msg_guid: str = "msg-meta-001",
    sender: str = "+15559999999",
    handle_extra: dict | None = None,
) -> dict:
    data = {
        "guid": msg_guid,
        "text": text,
        "isFromMe": is_from_me,
        "chats": [{"guid": chat_guid}],
    }
    if not is_from_me:
        handle = {"address": sender}
        if handle_extra:
            handle.update(handle_extra)
        data["handle"] = handle
    return {"type": "new-message", "data": data}


def _make_channel(require_mention: bool = True, bot_id: str = "default"):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.bot_id = bot_id
    ch.require_mention = require_mention
    ch.active_session_id = None
    return ch


def _make_binding(channel_id, client_id="bb:iMessage;-;+15551234567",
                  dispatch_config=None, display_name=None):
    b = MagicMock()
    b.channel_id = channel_id
    b.client_id = client_id
    b.dispatch_config = dispatch_config
    b.display_name = display_name
    return b


_WEBHOOK_TOKEN = "test-webhook-token"


def _mock_bb_settings(wake_words="atlas", webhook_token=_WEBHOOK_TOKEN):
    s = MagicMock()
    s.BLUEBUBBLES_SERVER_URL = "http://bb:1234"
    s.BLUEBUBBLES_PASSWORD = "bb-pw"
    s.BB_DEFAULT_BOT = "atlas"
    s.BB_WAKE_WORDS = wake_words
    s.BB_WEBHOOK_TOKEN = webhook_token
    s.BB_ECHO_SUPPRESS_WINDOW = 8.0
    return s


def _webhook_request(payload: dict) -> AsyncMock:
    request = AsyncMock()
    request.json.return_value = payload
    request.query_params = {"token": _WEBHOOK_TOKEN}
    return request


def _standard_patches(channel, binding, session_id, mock_utils, bb_settings=None):
    """Return a list of patch context managers for the standard webhook mocks."""
    return [
        patch("integrations.bluebubbles.router.shared_tracker"),
        patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id",
              return_value=[(channel, binding)]),
        patch("integrations.bluebubbles.router.ensure_active_session",
              return_value=session_id),
        patch("integrations.bluebubbles.router._bot_wake_words",
              return_value=["atlas"]),
        patch("integrations.bluebubbles.config.settings",
              bb_settings or _mock_bb_settings()),
    ]


class TestSenderMetadata:
    """Verify extra_metadata is passed to inject_message with correct sender info."""

    @pytest.fixture(autouse=True)
    def _bypass_guid_dedup(self):
        with patch("integrations.bluebubbles.router._guid_dedup") as mock_dedup:
            mock_dedup.check_and_record.return_value = False
            mock_dedup.save_to_db = AsyncMock()
            yield

    @pytest.fixture(autouse=True)
    def _skip_db_loading(self):
        """Skip the lazy DB state loading in webhook handler."""
        from integrations.bluebubbles import router as _router_mod
        _router_mod._echo_state_loaded["done"] = True
        yield
        _router_mod._echo_state_loaded.clear()

    @pytest.mark.asyncio
    async def test_external_message_uses_binding_display_name(self):
        """External message uses binding display_name as sender when no contact info."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=False)
        binding = _make_binding(ch.id, display_name="Group Chat")
        session_id = uuid.uuid4()
        request = _webhook_request(_bb_webhook_payload(
            text="hey there", sender="+15559999999",
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._bot_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_own_content.return_value = False
            mock_tracker.is_echo.return_value = False
            mock_tracker.in_reply_cooldown.return_value = False
            mock_tracker.is_circuit_open.return_value = False
            mock_tracker.in_echo_suppress.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            result = await webhook(request, db)

        assert result["status"] == "processed"
        call_kwargs = mock_utils.inject_message.call_args
        meta = call_kwargs.kwargs["extra_metadata"]
        assert meta["sender_id"] == "bb:+15559999999"
        # Binding display_name preferred over raw phone number
        assert meta["sender_display_name"] == "Group Chat"
        assert meta["is_from_me"] is False
        assert meta["binding_display_name"] == "Group Chat"

    @pytest.mark.asyncio
    async def test_from_me_has_no_sender_display_name(self):
        """isFromMe messages should NOT have sender_display_name (UI shows 'You')."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=True)
        binding = _make_binding(ch.id, display_name="Jane Doe")
        session_id = uuid.uuid4()
        request = _webhook_request(_bb_webhook_payload(
            text="send this", is_from_me=True,
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._bot_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_own_content.return_value = False
            mock_tracker.is_echo.return_value = False
            mock_tracker.in_reply_cooldown.return_value = False
            mock_tracker.is_circuit_open.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            result = await webhook(request, db)

        assert result["status"] == "processed"
        call_kwargs = mock_utils.inject_message.call_args
        meta = call_kwargs.kwargs["extra_metadata"]
        assert meta["is_from_me"] is True
        assert "sender_display_name" not in meta
        assert meta["binding_display_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_handle_with_contact_name(self):
        """Handle with firstName/lastName → sender_display_name is the full name."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=False)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()
        request = _webhook_request(_bb_webhook_payload(
            text="hello", sender="+15559999999",
            handle_extra={"firstName": "Jane", "lastName": "Doe"},
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._bot_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_own_content.return_value = False
            mock_tracker.is_echo.return_value = False
            mock_tracker.in_reply_cooldown.return_value = False
            mock_tracker.is_circuit_open.return_value = False
            mock_tracker.in_echo_suppress.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            await webhook(request, db)

        meta = mock_utils.inject_message.call_args.kwargs["extra_metadata"]
        assert meta["sender_display_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_handle_with_display_name(self):
        """Handle with displayName field → preferred over firstName/lastName."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=False)
        binding = _make_binding(ch.id)
        session_id = uuid.uuid4()
        request = _webhook_request(_bb_webhook_payload(
            text="hi", sender="+15559999999",
            handle_extra={"displayName": "J. Doe", "firstName": "Jane"},
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._bot_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_own_content.return_value = False
            mock_tracker.is_echo.return_value = False
            mock_tracker.in_reply_cooldown.return_value = False
            mock_tracker.is_circuit_open.return_value = False
            mock_tracker.in_echo_suppress.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            await webhook(request, db)

        meta = mock_utils.inject_message.call_args.kwargs["extra_metadata"]
        assert meta["sender_display_name"] == "J. Doe"

    @pytest.mark.asyncio
    async def test_no_binding_display_name_falls_back_to_address(self):
        """Binding without display_name → sender falls back to handle address."""
        from integrations.bluebubbles.router import webhook

        ch = _make_channel(require_mention=False)
        binding = _make_binding(ch.id, display_name=None)
        session_id = uuid.uuid4()
        request = _webhook_request(_bb_webhook_payload(
            text="hey", sender="+15559999999",
        ))
        db = AsyncMock()

        with patch("integrations.bluebubbles.router.shared_tracker") as mock_tracker, \
             patch("integrations.bluebubbles.router.resolve_all_channels_by_client_id", return_value=[(ch, binding)]), \
             patch("integrations.bluebubbles.router.ensure_active_session", return_value=session_id), \
             patch("integrations.bluebubbles.router.utils") as mock_utils, \
             patch("integrations.bluebubbles.router._bot_wake_words", return_value=["atlas"]), \
             patch("integrations.bluebubbles.config.settings", _mock_bb_settings()):
            mock_tracker.is_own_content.return_value = False
            mock_tracker.is_echo.return_value = False
            mock_tracker.in_reply_cooldown.return_value = False
            mock_tracker.is_circuit_open.return_value = False
            mock_tracker.in_echo_suppress.return_value = False
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            await webhook(request, db)

        meta = mock_utils.inject_message.call_args.kwargs["extra_metadata"]
        assert "binding_display_name" not in meta
        # Falls back to raw handle address when no binding display name
        assert meta["sender_display_name"] == "+15559999999"


class TestFormatHandleName:
    """Unit tests for _format_handle_name helper."""

    def test_first_and_last(self):
        from integrations.bluebubbles.router import _format_handle_name
        assert _format_handle_name({"firstName": "Jane", "lastName": "Doe"}) == "Jane Doe"

    def test_first_only(self):
        from integrations.bluebubbles.router import _format_handle_name
        assert _format_handle_name({"firstName": "Jane"}) == "Jane"

    def test_last_only(self):
        from integrations.bluebubbles.router import _format_handle_name
        assert _format_handle_name({"lastName": "Doe"}) == "Doe"

    def test_empty(self):
        from integrations.bluebubbles.router import _format_handle_name
        assert _format_handle_name({}) is None

    def test_whitespace_only(self):
        from integrations.bluebubbles.router import _format_handle_name
        assert _format_handle_name({"firstName": "  ", "lastName": ""}) is None


class TestInjectMessageExtraMetadata:
    """Verify inject_message merges extra_metadata into stored message."""

    @pytest.mark.asyncio
    async def test_extra_metadata_merged(self):
        """extra_metadata fields appear in the stored message metadata."""
        from integrations.utils import inject_message
        from app.db.models import Message

        session_id = uuid.uuid4()
        mock_session = MagicMock()
        mock_session.channel_id = uuid.uuid4()
        mock_session.bot_id = "test"
        mock_session.client_id = "bb:test"
        mock_session.dispatch_config = None

        mock_msg = MagicMock(spec=Message)
        mock_msg.id = uuid.uuid4()

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_session)
        # Mock the SELECT query for the just-stored message
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_msg
        db.execute = AsyncMock(return_value=mock_result)

        with patch("integrations.utils.store_passive_message", new_callable=AsyncMock) as mock_store:
            await inject_message(
                session_id, "hello", "bluebubbles",
                extra_metadata={"sender_id": "bb:+1555", "is_from_me": False},
                db=db,
            )

            mock_store.assert_called_once()
            stored_metadata = mock_store.call_args[0][3]  # 4th positional arg
            assert stored_metadata["source"] == "bluebubbles"
            assert stored_metadata["sender_id"] == "bb:+1555"
            assert stored_metadata["is_from_me"] is False

    @pytest.mark.asyncio
    async def test_no_extra_metadata(self):
        """Without extra_metadata, only source is stored."""
        from integrations.utils import inject_message
        from app.db.models import Message

        session_id = uuid.uuid4()
        mock_session = MagicMock()
        mock_session.channel_id = uuid.uuid4()
        mock_session.bot_id = "test"
        mock_session.client_id = "bb:test"
        mock_session.dispatch_config = None

        mock_msg = MagicMock(spec=Message)
        mock_msg.id = uuid.uuid4()

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_session)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_msg
        db.execute = AsyncMock(return_value=mock_result)

        with patch("integrations.utils.store_passive_message", new_callable=AsyncMock) as mock_store:
            await inject_message(session_id, "hello", "github", db=db)

            stored_metadata = mock_store.call_args[0][3]
            assert stored_metadata == {"source": "github"}
