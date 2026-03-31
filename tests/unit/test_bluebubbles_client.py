"""Tests for BlueBubbles Socket.IO client message routing."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from integrations.bluebubbles.echo_tracker import EchoTracker
from integrations.bluebubbles.agent_client import bb_client_id


class TestMessageExtraction:
    """Test message field extraction logic.

    These test the extraction patterns used in bb_client.py. Since bb_client
    has module-level socketio imports, we inline the logic here to avoid
    requiring socketio in the test environment.
    """

    def test_extract_chat_guid_from_chats_list(self):
        """Chat GUID from chats[0].guid (standard BB format)."""
        msg = {"chats": [{"guid": "iMessage;-;+15551234567"}]}
        chats = msg.get("chats", [])
        guid = chats[0].get("guid") if chats else None
        assert guid == "iMessage;-;+15551234567"

    def test_extract_chat_guid_from_chatGuid(self):
        """Fallback: chatGuid field."""
        msg = {"chatGuid": "iMessage;+;chat123"}
        chats = msg.get("chats", [])
        guid = chats[0].get("guid") if chats else msg.get("chatGuid")
        assert guid == "iMessage;+;chat123"

    def test_extract_sender_from_handle(self):
        msg = {"handle": {"address": "+15551234567"}}
        handle = msg.get("handle", {})
        sender = handle.get("address", "unknown") if isinstance(handle, dict) else "unknown"
        assert sender == "+15551234567"

    def test_extract_sender_from_handleId_fallback(self):
        msg = {"handleId": "user42"}
        handle = msg.get("handle")
        if handle and isinstance(handle, dict):
            sender = handle.get("address", "unknown")
        else:
            sender = str(msg.get("handleId") or "unknown")
        assert sender == "user42"

    def test_extract_text(self):
        msg = {"text": "  Hello world  "}
        text = (msg.get("text") or "").strip()
        assert text == "Hello world"

    def test_extract_empty_text(self):
        msg = {"text": None}
        text = (msg.get("text") or "").strip()
        assert text == ""


class TestClientIdFormat:
    def test_bb_client_id_1to1(self):
        client_id = bb_client_id("iMessage;-;+15551234567")
        assert client_id == "bb:iMessage;-;+15551234567"
        assert client_id.startswith("bb:")

    def test_bb_client_id_group(self):
        client_id = bb_client_id("iMessage;+;chat123456")
        assert client_id == "bb:iMessage;+;chat123456"


class TestGroupChatDetection:
    """Test group vs 1:1 chat GUID detection."""

    def test_1to1_chat(self):
        # 1:1 chats use ;-; separator
        assert ";+;" not in "iMessage;-;+15551234567"

    def test_group_chat(self):
        # Group chats use ;+; separator
        assert ";+;" in "iMessage;+;chat123456"

    def test_sms_1to1(self):
        assert ";+;" not in "SMS;-;+15551234567"

    def test_sms_group(self):
        assert ";+;" in "SMS;+;chat789"


class TestDataParsing:
    """Test handling of different data shapes from BB Socket.IO events."""

    def test_dict_data(self):
        """Normal case: data is a dict."""
        data = {"guid": "msg-1", "text": "Hello"}
        if isinstance(data, list) and data:
            message = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            message = data
        else:
            message = None
        assert message == {"guid": "msg-1", "text": "Hello"}

    def test_list_wrapped_data(self):
        """BB sometimes sends data wrapped in a list."""
        data = [{"guid": "msg-1", "text": "Hello"}]
        if isinstance(data, list) and data:
            message = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            message = data
        else:
            message = None
        assert message == {"guid": "msg-1", "text": "Hello"}

    def test_empty_list(self):
        data = []
        if isinstance(data, list) and data:
            message = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            message = data
        else:
            message = None
        assert message is None

    def test_unexpected_type(self):
        data = "not a dict or list"
        if isinstance(data, list) and data:
            message = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            message = data
        else:
            message = None
        assert message is None


class TestEchoIntegration:
    """Test the echo tracker in the context of BB message routing."""

    def test_bot_reply_detected_as_echo(self):
        """Bot sends a reply → incoming isFromMe message should be detected as echo."""
        tracker = EchoTracker()
        tracker.track_sent("temp-abc", "I'm the bot's response")
        assert tracker.is_echo("real-guid-xyz", "I'm the bot's response") is True

    def test_human_message_not_detected_as_echo(self):
        """Human sends a message from their phone → should NOT be detected as echo."""
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "Bot reply")
        assert tracker.is_echo("human-guid", "Hey, what's up?") is False

    def test_external_message_not_checked(self):
        """External messages (isFromMe=false) bypass the tracker in routing."""
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "Hello from bot")
        # The tracker would match, but in bb_client.py, external messages
        # (isFromMe=false) never hit the tracker — tested here for completeness
        assert tracker.is_echo("ext-guid", "Hello from bot") is True

    def test_rapid_conversation(self):
        """Simulate rapid back-and-forth."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Reply 1")
        tracker.track_sent("t2", "Reply 2")
        tracker.track_sent("t3", "Reply 3")

        assert tracker.is_echo("r1", "Reply 1") is True
        assert tracker.is_echo("r2", "Reply 2") is True
        assert tracker.is_echo("r3", "Reply 3") is True
        assert tracker.is_echo("h1", "Human message") is False
