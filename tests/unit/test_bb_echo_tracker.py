"""Tests for BlueBubbles echo tracker — echo detection, cooldown, circuit breaker, GUID dedup."""
import json
import time

import pytest

from integrations.bluebubbles.echo_tracker import EchoTracker


def _make_tracker(**kwargs):
    """Create a fresh EchoTracker (no DB persistence in unit tests)."""
    return EchoTracker(**kwargs)


class TestEchoDetection:
    """Basic echo detection via GUID and text hash."""

    def test_guid_match(self):
        tracker = _make_tracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello world", chat_guid="chat1")
        assert tracker.is_echo("temp-123", "hello world") is True

    def test_text_hash_match(self):
        tracker = _make_tracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello world", chat_guid="chat1")
        # Different GUID but same text → still an echo
        assert tracker.is_echo("real-456", "hello world") is True

    def test_not_echo(self):
        tracker = _make_tracker(ttl=60.0)
        tracker.track_sent("temp-123", "bot response", chat_guid="chat1")
        assert tracker.is_echo("real-456", "different text from human") is False

    def test_ttl_expiry(self):
        tracker = _make_tracker(ttl=0.01)  # 10ms TTL
        tracker.track_sent("temp-123", "hello", chat_guid="chat1")
        time.sleep(0.02)
        assert tracker.is_echo("temp-123", "hello") is False

    def test_echo_consumed_once(self):
        tracker = _make_tracker(ttl=60.0)
        tracker.track_sent("temp-123", "hello", chat_guid="chat1")
        assert tracker.is_echo("temp-123", "hello") is True
        # Second call should not match (entry consumed)
        assert tracker.is_echo("temp-123", "hello") is False


class TestReplyCooldown:
    """Per-chat reply cooldown prevents isFromMe loops."""

    def test_cooldown_active_after_send(self):
        tracker = _make_tracker()
        tracker.track_sent("temp-1", "response", chat_guid="chat1")
        assert tracker.in_reply_cooldown("chat1") is True

    def test_cooldown_not_active_for_other_chat(self):
        tracker = _make_tracker()
        tracker.track_sent("temp-1", "response", chat_guid="chat1")
        assert tracker.in_reply_cooldown("chat2") is False

    def test_cooldown_empty_chat_guid(self):
        tracker = _make_tracker()
        assert tracker.in_reply_cooldown("") is False

    def test_no_cooldown_without_chat_guid(self):
        """track_sent without chat_guid doesn't create cooldown."""
        tracker = _make_tracker()
        tracker.track_sent("temp-1", "response")
        assert tracker.in_reply_cooldown("chat1") is False


class TestCircuitBreaker:
    """Circuit breaker prevents infinite bot loops."""

    def test_circuit_closed_initially(self):
        tracker = _make_tracker()
        assert tracker.is_circuit_open("chat1") is False

    def test_circuit_opens_after_max_replies(self):
        tracker = _make_tracker()
        for i in range(5):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is True

    def test_circuit_stays_closed_under_limit(self):
        tracker = _make_tracker()
        for i in range(4):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is False

    def test_circuit_per_chat(self):
        tracker = _make_tracker()
        for i in range(5):
            tracker.track_sent(f"temp-{i}", f"msg-{i}", chat_guid="chat1")
        assert tracker.is_circuit_open("chat1") is True
        assert tracker.is_circuit_open("chat2") is False

    def test_circuit_empty_chat_guid(self):
        tracker = _make_tracker()
        assert tracker.is_circuit_open("") is False


class TestDBPersistence:
    """Reply state persists to DB and survives 'restarts' (via load/save)."""

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self):
        """Saved reply timestamps are loaded back on 'restart'."""
        t1 = EchoTracker()
        t1.track_sent("t1", "msg1", chat_guid="chat-A")
        t1.track_sent("t2", "msg2", chat_guid="chat-A")
        t1.track_sent("t3", "msg3", chat_guid="chat-B")

        assert t1.in_reply_cooldown("chat-A") is True
        assert t1.in_reply_cooldown("chat-B") is True

        # Simulate round-trip via JSON (what DB persistence does)
        serialized = json.dumps(dict(t1._chat_replies))

        t2 = EchoTracker()
        data = json.loads(serialized)
        for chat_guid, timestamps in data.items():
            t2._chat_replies[chat_guid] = timestamps

        assert t2.in_reply_cooldown("chat-A") is True
        assert t2.in_reply_cooldown("chat-B") is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_survives_round_trip(self):
        """Circuit breaker state persists across round-trips."""
        t1 = EchoTracker()
        for i in range(5):
            t1.track_sent(f"t{i}", f"msg{i}", chat_guid="chat-loop")
        assert t1.is_circuit_open("chat-loop") is True

        # Simulate round-trip
        serialized = json.dumps(dict(t1._chat_replies))
        t2 = EchoTracker()
        data = json.loads(serialized)
        for chat_guid, timestamps in data.items():
            t2._chat_replies[chat_guid] = timestamps

        assert t2.is_circuit_open("chat-loop") is True

    def test_stale_timestamps_filtered(self):
        """Timestamps older than the circuit breaker window are ignored."""
        tracker = EchoTracker()
        old_ts = time.time() - 600  # 10 minutes ago
        tracker._chat_replies["chat-old"] = [old_ts, old_ts + 1]
        # Stale timestamps shouldn't count
        assert tracker.in_reply_cooldown("chat-old") is False
        assert tracker.is_circuit_open("chat-old") is False

    @pytest.mark.asyncio
    async def test_sent_content_survives_round_trip(self):
        """Sent content hashes persist across simulated restarts."""
        t1 = EchoTracker()
        t1.track_sent("t1", "Bot response one", chat_guid="chat-A")
        t1.track_sent("t2", "Bot response two", chat_guid="chat-B")

        assert t1.is_own_content("chat-A", "Bot response one") is True
        assert t1.is_own_content("chat-B", "Bot response two") is True

        # Simulate round-trip via JSON (what DB persistence does)
        serialized = json.dumps(dict(t1._sent_content))

        t2 = EchoTracker()
        data = json.loads(serialized)
        now = time.time()
        for chat_guid, hashes in data.items():
            recent = {h: ts for h, ts in hashes.items() if now - ts < t2.ttl}
            if recent:
                t2._sent_content[chat_guid] = recent

        assert t2.is_own_content("chat-A", "Bot response one") is True
        assert t2.is_own_content("chat-B", "Bot response two") is True
        assert t2.is_own_content("chat-A", "Something else") is False

    @pytest.mark.asyncio
    async def test_stale_sent_content_filtered_on_load(self):
        """Sent content older than TTL is discarded on load."""
        tracker = EchoTracker()
        old_ts = time.time() - 600  # 10 minutes ago (> 5 min TTL)
        from integrations.bluebubbles.echo_tracker import _text_hash
        tracker._sent_content["chat-old"] = {_text_hash("old msg"): old_ts}
        # Stale content shouldn't match
        assert tracker.is_own_content("chat-old", "old msg") is False


class TestGuidDedup:
    """GUID dedup prevents replay storms across restarts."""

    def _make_dedup(self, max_size=100):
        """Create a _GuidDedup."""
        from integrations.bluebubbles.router import _GuidDedup
        return _GuidDedup(max_size=max_size)

    def test_first_seen_returns_false(self):
        dedup = self._make_dedup()
        assert dedup.check_and_record("guid-1") is False

    def test_second_seen_returns_true(self):
        dedup = self._make_dedup()
        dedup.check_and_record("guid-1")
        assert dedup.check_and_record("guid-1") is True

    def test_different_guids_independent(self):
        dedup = self._make_dedup()
        dedup.check_and_record("guid-1")
        assert dedup.check_and_record("guid-2") is False

    def test_evicts_oldest_when_full(self):
        dedup = self._make_dedup(max_size=3)
        dedup.check_and_record("a")
        dedup.check_and_record("b")
        dedup.check_and_record("c")
        dedup.check_and_record("d")  # should evict "a"
        # "a" was evicted, "b"/"c"/"d" remain
        assert "a" not in dedup._seen
        assert "b" in dedup._seen
        assert "d" in dedup._seen
