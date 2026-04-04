"""Tests for per-channel agent run throttle."""
import time

from app.services.channel_throttle import (
    _channel_runs,
    _last_throttle_log,
    configure,
    is_throttled,
    record_run,
    status,
)


def _reset():
    """Clear global state between tests."""
    _channel_runs.clear()
    _last_throttle_log.clear()
    configure(max_runs=10, window=300.0)


class TestChannelThrottle:

    def setup_method(self):
        _reset()

    def test_not_throttled_initially(self):
        assert is_throttled("ch-1") is False

    def test_throttled_after_max_runs(self):
        configure(max_runs=3, window=300.0)
        for _ in range(3):
            record_run("ch-1")
        assert is_throttled("ch-1") is True

    def test_not_throttled_under_limit(self):
        configure(max_runs=5, window=300.0)
        for _ in range(4):
            record_run("ch-1")
        assert is_throttled("ch-1") is False

    def test_per_channel_isolation(self):
        configure(max_runs=2, window=300.0)
        record_run("ch-1")
        record_run("ch-1")
        assert is_throttled("ch-1") is True
        assert is_throttled("ch-2") is False

    def test_window_expiry(self):
        configure(max_runs=2, window=0.01)  # 10ms window
        record_run("ch-1")
        record_run("ch-1")
        assert is_throttled("ch-1") is True
        time.sleep(0.02)
        assert is_throttled("ch-1") is False

    def test_record_run_does_not_check(self):
        """record_run just records, doesn't block."""
        configure(max_runs=1, window=300.0)
        record_run("ch-1")
        # Should still be able to record more
        record_run("ch-1")
        assert is_throttled("ch-1") is True

    def test_status(self):
        configure(max_runs=5, window=300.0)
        record_run("ch-1")
        record_run("ch-1")
        s = status("ch-1")
        assert s["recent_runs"] == 2
        assert s["max_runs"] == 5
        assert s["throttled"] is False

    def test_status_throttled(self):
        configure(max_runs=2, window=300.0)
        record_run("ch-1")
        record_run("ch-1")
        s = status("ch-1")
        assert s["throttled"] is True
