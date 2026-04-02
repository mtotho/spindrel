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
