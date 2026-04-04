"""Tests for BlueBubbles echo tracker (bot/user disambiguation)."""
import time
from unittest.mock import patch

import pytest

from integrations.bluebubbles.echo_tracker import EchoTracker, _text_hash


class TestTextHash:
    def test_deterministic(self):
        assert _text_hash("hello") == _text_hash("hello")

    def test_different_inputs(self):
        assert _text_hash("hello") != _text_hash("world")

    def test_returns_16_chars(self):
        assert len(_text_hash("test message")) == 16


class TestEchoTracker:
    def test_track_and_detect_by_guid(self):
        tracker = EchoTracker()
        tracker.track_sent("guid-123", "Hello!")
        assert tracker.is_echo("guid-123", "Hello!") is True

    def test_track_and_detect_by_text_hash(self):
        """Fallback: GUID differs but text matches."""
        tracker = EchoTracker()
        tracker.track_sent("temp-guid", "Hello!")
        # BB may assign a different actual GUID
        assert tracker.is_echo("real-guid-456", "Hello!") is True

    def test_non_echo_message(self):
        tracker = EchoTracker()
        tracker.track_sent("guid-1", "Bot says hi")
        assert tracker.is_echo("guid-2", "Human says hi") is False

    def test_empty_tracker(self):
        tracker = EchoTracker()
        assert tracker.is_echo("any-guid", "any text") is False

    def test_guid_match_removes_entry(self):
        """After matching by GUID, the entry is consumed."""
        tracker = EchoTracker()
        tracker.track_sent("guid-1", "Hello")
        assert tracker.is_echo("guid-1", "Hello") is True
        # Second check should not match
        assert tracker.is_echo("guid-1", "Hello") is False

    def test_hash_match_removes_both_entries(self):
        """After matching by hash, both GUID and hash entries are removed."""
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "Hello")
        assert tracker.is_echo("different-guid", "Hello") is True
        # Both should be gone now
        assert tracker.is_echo("temp-1", "Hello") is False

    def test_ttl_eviction(self):
        """Entries expire after TTL."""
        tracker = EchoTracker(ttl=0.1)
        tracker.track_sent("guid-1", "Hello")
        time.sleep(0.15)
        assert tracker.is_echo("guid-1", "Hello") is False

    def test_multiple_messages(self):
        tracker = EchoTracker()
        tracker.track_sent("g1", "Message one")
        tracker.track_sent("g2", "Message two")
        tracker.track_sent("g3", "Message three")

        assert tracker.is_echo("g2", "Message two") is True
        assert tracker.is_echo("g1", "Message one") is True
        assert tracker.is_echo("g3", "Message three") is True

    def test_same_text_different_sends(self):
        """If the same text is sent twice, the hash entry is overwritten
        but both GUIDs should still work."""
        tracker = EchoTracker()
        tracker.track_sent("g1", "Same text")
        tracker.track_sent("g2", "Same text")

        # GUID match for g1 should still work
        assert tracker.is_echo("g1", "Same text") is True
        # g2 should also match by GUID
        assert tracker.is_echo("g2", "Same text") is True

    def test_eviction_only_removes_expired(self):
        """Fresh entries survive eviction of old ones."""
        tracker = EchoTracker(ttl=0.1)
        tracker.track_sent("old", "Old message")
        time.sleep(0.15)
        tracker.track_sent("new", "New message")
        # old is expired, new is fresh
        assert tracker.is_echo("old", "Old message") is False
        assert tracker.is_echo("new", "New message") is True


class TestTextHashNormalization:
    """Text hashing must be whitespace-insensitive to match webhook .strip()."""

    def test_trailing_newline_matches(self):
        """LLM responses often have trailing newlines; webhook strips them."""
        assert _text_hash("Hello world\n") == _text_hash("Hello world")

    def test_trailing_whitespace_matches(self):
        assert _text_hash("Hello world  \n\n") == _text_hash("Hello world")

    def test_leading_whitespace_matches(self):
        assert _text_hash("  Hello world") == _text_hash("Hello world")

    def test_mixed_whitespace_matches(self):
        assert _text_hash("\n  Hello world  \n") == _text_hash("Hello world")

    def test_interior_whitespace_preserved(self):
        """Only leading/trailing whitespace is stripped, not interior."""
        assert _text_hash("Hello  world") != _text_hash("Hello world")


class TestIsOwnContent:
    """Content-based echo detection — works regardless of is_from_me."""

    def test_detects_recently_sent_text(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response here", chat_guid="chat-A")
        assert tracker.is_own_content("chat-A", "Bot response here") is True

    def test_ignores_different_text(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response", chat_guid="chat-A")
        assert tracker.is_own_content("chat-A", "Human message") is False

    def test_scoped_to_chat(self):
        """Only matches within the same chat."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response", chat_guid="chat-A")
        assert tracker.is_own_content("chat-A", "Bot response") is True
        assert tracker.is_own_content("chat-B", "Bot response") is False

    def test_survives_is_echo_pop(self):
        """is_own_content still works even after is_echo pops the entry."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response", chat_guid="chat-A")
        # is_echo pops the hash entry
        assert tracker.is_echo("t1", "Bot response") is True
        # is_own_content should STILL detect it (non-popped cache)
        assert tracker.is_own_content("chat-A", "Bot response") is True

    def test_handles_whitespace_normalization(self):
        """Trailing whitespace in tracked text matches stripped echo."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response\n\n", chat_guid="chat-A")
        assert tracker.is_own_content("chat-A", "Bot response") is True

    def test_expires_after_ttl(self):
        tracker = EchoTracker(ttl=0.05)
        tracker.track_sent("t1", "Bot response", chat_guid="chat-A")
        time.sleep(0.1)
        assert tracker.is_own_content("chat-A", "Bot response") is False

    def test_empty_chat_guid_returns_false(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response", chat_guid="chat-A")
        assert tracker.is_own_content("", "Bot response") is False

    def test_no_chat_guid_on_track_skips(self):
        """If track_sent was called without chat_guid, is_own_content won't match."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot response")  # no chat_guid
        assert tracker.is_own_content("chat-A", "Bot response") is False

    def test_multiple_messages_same_chat(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "First response", chat_guid="chat-A")
        tracker.track_sent("t2", "Second response", chat_guid="chat-A")
        assert tracker.is_own_content("chat-A", "First response") is True
        assert tracker.is_own_content("chat-A", "Second response") is True
        assert tracker.is_own_content("chat-A", "Third response") is False


class TestInEchoSuppress:
    """Echo suppress — short window to catch echoed wake word triggers."""

    def test_within_window(self):
        """Returns True when we replied within the 15s window."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "Bot reply with wonky word", chat_guid="chat-A")
        assert tracker.in_echo_suppress("chat-A") is True

    def test_outside_window(self):
        """Returns False when reply was longer ago than the suppress window."""
        tracker = EchoTracker()
        # Inject a reply timestamp older than the suppress window
        tracker._chat_replies["chat-A"] = [time.time() - 20.0]
        assert tracker.in_echo_suppress("chat-A") is False

    def test_no_replies(self):
        """Returns False when no replies have been sent to this chat."""
        tracker = EchoTracker()
        assert tracker.in_echo_suppress("chat-A") is False

    def test_empty_chat_guid(self):
        """Returns False for empty chat_guid."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "reply", chat_guid="chat-A")
        assert tracker.in_echo_suppress("") is False

    def test_different_chat(self):
        """Suppress is scoped to the specific chat."""
        tracker = EchoTracker()
        tracker.track_sent("t1", "reply", chat_guid="chat-A")
        assert tracker.in_echo_suppress("chat-A") is True
        assert tracker.in_echo_suppress("chat-B") is False
