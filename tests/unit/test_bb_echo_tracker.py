"""Tests for BlueBubbles echo tracker — echo detection, cooldown, circuit breaker."""
import time

import pytest

from integrations.bluebubbles.echo_tracker import EchoTracker


class TestEchoDetection:
    """Basic echo detection via GUID and text hash."""

    def test_guid_match(self):
        tracker = EchoTracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello world", chat_guid="chat1")
        assert tracker.is_echo("temp-123", "hello world") is True

    def test_text_hash_match(self):
        tracker = EchoTracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello world", chat_guid="chat1")
        # Different GUID but same text → still an echo
        assert tracker.is_echo("real-456", "hello world") is True

    def test_not_echo(self):
        tracker = EchoTracker(ttl=60.0)
        tracker.track_sent("temp-123", "bot response", chat_guid="chat1")
        assert tracker.is_echo("real-456", "different text from human") is False

    def test_ttl_expiry(self):
        tracker = EchoTracker(ttl=0.01)  # 10ms TTL
        tracker.track_sent("temp-123", "hello", chat_guid="chat1")
        time.sleep(0.02)
        assert tracker.is_echo("temp-123", "hello") is False

    def test_echo_consumed_once(self):
        tracker = EchoTracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello", chat_guid="chat1")
        assert tracker.is_echo("temp-123", "hello") is True
        # Second call should not match (entry consumed)
        assert tracker.is_echo("temp-123", "hello") is False


class TestReplyCooldown:
    """Per-chat reply cooldown prevents isFromMe loops."""

    def test_cooldown_active_after_send(self):
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "response", chat_guid="chat1")
        assert tracker.in_reply_cooldown("chat1") is True

    def test_cooldown_not_active_for_other_chat(self):
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "response", chat_guid="chat1")
        assert tracker.in_reply_cooldown("chat2") is False

    def test_cooldown_empty_chat_guid(self):
        tracker = EchoTracker()
        assert tracker.in_reply_cooldown("") is False

    def test_no_cooldown_without_chat_guid(self):
        """track_sent without chat_guid doesn't create cooldown."""
        tracker = EchoTracker()
        tracker.track_sent("temp-1", "response")
        assert tracker.in_reply_cooldown("chat1") is False


class TestCircuitBreaker:
    """Circuit breaker prevents infinite bot loops."""

    def test_circuit_closed_initially(self):
        tracker = EchoTracker()
        assert tracker.is_circuit_open("chat1") is False

    def test_circuit_opens_after_max_replies(self):
        tracker = EchoTracker()
        for i in range(5):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is True

    def test_circuit_stays_closed_under_limit(self):
        tracker = EchoTracker()
        for i in range(4):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is False

    def test_circuit_per_chat(self):
        tracker = EchoTracker()
        for i in range(5):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is True
        assert tracker.is_circuit_open("chat2") is False

    def test_circuit_empty_chat_guid(self):
        tracker = EchoTracker()
        assert tracker.is_circuit_open("") is False
