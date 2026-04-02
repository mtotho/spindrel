"""Tests for app.agent.loop_cycle_detection."""

import pytest

from app.agent.loop_cycle_detection import (
    ToolCallSignature,
    detect_cycle,
    make_signature,
)


# ---------------------------------------------------------------------------
# make_signature
# ---------------------------------------------------------------------------

class TestMakeSignature:
    def test_same_inputs_produce_equal_signatures(self):
        s1 = make_signature("web_search", '{"query": "hello"}')
        s2 = make_signature("web_search", '{"query": "hello"}')
        assert s1 == s2

    def test_different_args_produce_different_signatures(self):
        s1 = make_signature("web_search", '{"query": "hello"}')
        s2 = make_signature("web_search", '{"query": "world"}')
        assert s1 != s2

    def test_different_names_produce_different_signatures(self):
        s1 = make_signature("web_search", '{"query": "hello"}')
        s2 = make_signature("file_read", '{"query": "hello"}')
        assert s1 != s2

    def test_signature_is_hashable(self):
        sig = make_signature("tool", '{}')
        assert hash(sig)  # does not raise
        # Can be used in sets
        s = {sig, sig}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# detect_cycle
# ---------------------------------------------------------------------------

class TestDetectCycle:
    def test_empty_trace(self):
        assert detect_cycle([]) is None

    def test_single_call(self):
        assert detect_cycle([make_signature("a", "{}")]) is None

    def test_two_different_calls(self):
        trace = [make_signature("a", "{}"), make_signature("b", "{}")]
        assert detect_cycle(trace) is None

    def test_no_cycle_varied_calls(self):
        """Four distinct calls — no repeating pattern."""
        trace = [
            make_signature("a", '{"x":1}'),
            make_signature("b", '{"x":2}'),
            make_signature("c", '{"x":3}'),
            make_signature("d", '{"x":4}'),
        ]
        assert detect_cycle(trace) is None

    # -- Single-call cycles (length 1) require min_reps+1 = 3 repetitions --

    def test_single_call_two_reps_no_detect(self):
        """Two identical calls should NOT trigger (could be a legitimate retry)."""
        sig = make_signature("web_search", '{"q":"test"}')
        assert detect_cycle([sig, sig]) is None

    def test_single_call_three_reps_detected(self):
        """Three identical calls → cycle length 1 detected."""
        sig = make_signature("web_search", '{"q":"test"}')
        assert detect_cycle([sig, sig, sig]) == 1

    def test_single_call_four_reps_detected(self):
        sig = make_signature("web_search", '{"q":"test"}')
        assert detect_cycle([sig, sig, sig, sig]) == 1

    # -- Multi-call cycles (length >= 2) require min_reps = 2 repetitions --

    def test_two_call_cycle(self):
        """AB AB → cycle length 2."""
        a = make_signature("search", '{"q":"x"}')
        b = make_signature("read", '{"f":"y"}')
        assert detect_cycle([a, b, a, b]) == 2

    def test_three_call_cycle(self):
        """ABC ABC → cycle length 3."""
        a = make_signature("a", "{}")
        b = make_signature("b", "{}")
        c = make_signature("c", "{}")
        assert detect_cycle([a, b, c, a, b, c]) == 3

    def test_seven_call_cycle_real_world(self):
        """Simulate the real-world 7-tool cycle from the motivating incident."""
        tools = [make_signature(f"tool_{i}", f'{{"step":{i}}}') for i in range(7)]
        # 2 full reps = 14 calls
        trace = tools * 2
        assert detect_cycle(trace) == 7

    def test_seven_call_cycle_three_reps(self):
        """7-tool cycle × 3.5 reps (the actual incident had ~25 calls ≈ 3.5×7)."""
        tools = [make_signature(f"tool_{i}", f'{{"step":{i}}}') for i in range(7)]
        trace = tools * 3 + tools[:4]  # 25 calls
        assert detect_cycle(trace) == 7

    def test_cycle_starting_mid_trace(self):
        """Non-repeating prefix followed by a cycle should still detect."""
        prefix = [make_signature("setup", '{"init":true}')]
        sig = make_signature("stuck", '{"retry":1}')
        trace = prefix + [sig, sig, sig]
        assert detect_cycle(trace) == 1

    def test_cycle_with_varied_prefix(self):
        """Several unique calls, then a 2-call cycle."""
        a = make_signature("alpha", "{}")
        b = make_signature("beta", "{}")
        x = make_signature("loop_a", "{}")
        y = make_signature("loop_b", "{}")
        trace = [a, b, x, y, x, y]
        assert detect_cycle(trace) == 2

    # -- Custom min_reps --

    def test_custom_min_reps_single(self):
        """With min_reps=3, single-call needs 4 repetitions."""
        sig = make_signature("x", "{}")
        assert detect_cycle([sig, sig, sig], min_reps=3) is None
        assert detect_cycle([sig, sig, sig, sig], min_reps=3) == 1

    def test_custom_min_reps_multi(self):
        """With min_reps=3, multi-call cycle needs 3 full reps."""
        a = make_signature("a", "{}")
        b = make_signature("b", "{}")
        assert detect_cycle([a, b, a, b], min_reps=3) is None
        assert detect_cycle([a, b, a, b, a, b], min_reps=3) == 2

    # -- Edge cases --

    def test_almost_cycle_one_difference(self):
        """Pattern that looks like a cycle but has one different call."""
        a = make_signature("a", "{}")
        b = make_signature("b", "{}")
        c = make_signature("c", "{}")
        trace = [a, b, a, c]  # not a real cycle
        assert detect_cycle(trace) is None

    def test_shortest_detectable_multi_cycle(self):
        """Minimum length for a 2-call cycle: exactly 4 calls."""
        a = make_signature("a", "{}")
        b = make_signature("b", "{}")
        assert detect_cycle([a, b, a, b]) == 2
        # 3 calls is not enough
        assert detect_cycle([a, b, a]) is None
