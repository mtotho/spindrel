"""Tests for the shared retry engine: _compute_backoff, _classify_error, _retry_single_model."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import (
    EmptyChoicesError,
    _classify_error,
    _compute_backoff,
    _retry_single_model,
    _run_with_fallback_chain,
    _model_cooldowns,
)


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        LLM_MAX_RETRIES=3,
        LLM_RATE_LIMIT_INITIAL_WAIT=90,
        LLM_RETRY_INITIAL_WAIT=2.0,
        LLM_FALLBACK_COOLDOWN_SECONDS=300,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _rate_limit_error():
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    return openai.RateLimitError(message="rate limited", response=resp, body=None)


def _timeout_error():
    return openai.APITimeoutError(request=MagicMock())


def _connection_error():
    return openai.APIConnectionError(request=MagicMock())


def _bad_request_error(msg="bad request"):
    resp = MagicMock()
    resp.status_code = 400
    resp.headers = {}
    return openai.BadRequestError(message=msg, response=resp, body=None)


def _tools_not_supported_error():
    return _bad_request_error("tools are not supported by this model")


def _internal_server_error(msg="internal error"):
    resp = MagicMock()
    resp.status_code = 500
    resp.headers = {}
    return openai.InternalServerError(message=msg, response=resp, body=None)


def _non_transient_500():
    return _internal_server_error("bad_request: invalid params")


# ---------------------------------------------------------------------------
# _compute_backoff
# ---------------------------------------------------------------------------

class TestComputeBackoff:
    def test_bounded_by_floor_and_max(self):
        """Jitter stays within [base*0.5, min(cap, base * 2^attempt)]."""
        for _ in range(100):
            val = _compute_backoff(2.0, 0, cap=300.0)
            assert 1.0 <= val <= 2.0  # floor = 2.0 * 0.5 = 1.0

    def test_exponential_growth(self):
        """Upper bound doubles with each attempt."""
        for _ in range(100):
            val = _compute_backoff(2.0, 3, cap=300.0)
            assert 1.0 <= val <= 16.0  # floor = 1.0, upper = 2 * 2^3 = 16

    def test_cap_applied(self):
        """Cap prevents unbounded growth."""
        for _ in range(100):
            val = _compute_backoff(90.0, 10, cap=300.0)
            assert 45.0 <= val <= 300.0  # floor = 45.0

    def test_rate_limit_base(self):
        """Rate limit base (90s) produces correct ranges with floor."""
        for _ in range(50):
            val = _compute_backoff(90.0, 0, cap=300.0)
            assert 45.0 <= val <= 90.0  # floor = 45.0

    def test_always_above_floor(self):
        """Backoff is always >= base * 0.5 (prevents near-zero waits)."""
        for attempt in range(10):
            for _ in range(20):
                val = _compute_backoff(2.0, attempt)
                assert val >= 1.0  # floor = 2.0 * 0.5


# ---------------------------------------------------------------------------
# _classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_rate_limit(self):
        cl = _classify_error(_rate_limit_error(), has_tools=True)
        assert cl.retryable is True
        assert cl.base_wait == 90  # LLM_RATE_LIMIT_INITIAL_WAIT

    def test_timeout(self):
        cl = _classify_error(_timeout_error(), has_tools=False)
        assert cl.retryable is True
        assert cl.base_wait == 2.0

    def test_connection_error(self):
        cl = _classify_error(_connection_error(), has_tools=False)
        assert cl.retryable is True

    def test_empty_choices(self):
        cl = _classify_error(EmptyChoicesError("empty"), has_tools=False)
        assert cl.retryable is True
        assert cl.base_wait == 2.0

    def test_tools_not_supported(self):
        cl = _classify_error(_tools_not_supported_error(), has_tools=True)
        assert cl.retry_without_tools is True
        assert cl.retryable is False

    def test_tools_not_supported_no_tools(self):
        """When has_tools=False, tools-not-supported is a regular BadRequest."""
        cl = _classify_error(_tools_not_supported_error(), has_tools=False)
        assert cl.retry_without_tools is False
        assert cl.retryable is False

    def test_regular_bad_request(self):
        cl = _classify_error(_bad_request_error("invalid json"), has_tools=True)
        assert cl.retryable is False
        assert cl.retry_without_tools is False

    def test_non_transient_500(self):
        cl = _classify_error(_non_transient_500(), has_tools=False)
        assert cl.skip_to_fallback is True
        assert cl.retryable is False

    def test_transient_500(self):
        cl = _classify_error(_internal_server_error("gateway timeout"), has_tools=False)
        assert cl.retryable is True
        assert cl.skip_to_fallback is False

    def test_transient_500_with_400_in_number(self):
        """A 500 whose message contains '400' as part of a larger number should be transient."""
        cl = _classify_error(_internal_server_error("timed out after 14000ms"), has_tools=False)
        assert cl.retryable is True
        assert cl.skip_to_fallback is False, "bare '400' substring matched inside '14000'"

    def test_transient_500_port_number(self):
        """A 500 referencing a port like 24001 should not trigger non-transient detection."""
        cl = _classify_error(_internal_server_error("connection refused on port 24001"), has_tools=False)
        assert cl.retryable is True
        assert cl.skip_to_fallback is False

    def test_non_transient_500_status_code_400(self):
        """A wrapped 400 status code should still be detected as non-transient."""
        cl = _classify_error(_internal_server_error('upstream returned status 400'), has_tools=False)
        assert cl.skip_to_fallback is True

    def test_unknown_error(self):
        cl = _classify_error(RuntimeError("unknown"), has_tools=False)
        assert cl.retryable is False


# ---------------------------------------------------------------------------
# _retry_single_model
# ---------------------------------------------------------------------------

class TestRetrySingleModel:
    async def test_success_on_first_try(self):
        attempt_fn = AsyncMock(return_value="ok")
        with patch("app.agent.llm.settings", _mock_settings()):
            result = await _retry_single_model(attempt_fn, "test", False, 3)
        assert result == "ok"
        assert attempt_fn.await_count == 1

    async def test_retries_on_transient_error(self):
        attempt_fn = AsyncMock(side_effect=[_timeout_error(), _timeout_error(), "ok"])
        with patch("app.agent.llm.settings", _mock_settings()), \
             patch("app.agent.llm._compute_backoff", return_value=0):
            result = await _retry_single_model(attempt_fn, "test", False, 3)
        assert result == "ok"
        assert attempt_fn.await_count == 3

    async def test_raises_after_max_retries(self):
        attempt_fn = AsyncMock(side_effect=_timeout_error())
        with patch("app.agent.llm.settings", _mock_settings(LLM_MAX_RETRIES=2)), \
             patch("app.agent.llm._compute_backoff", return_value=0):
            with pytest.raises(openai.APITimeoutError):
                await _retry_single_model(attempt_fn, "test", False, 2)
        assert attempt_fn.await_count == 3  # 1 initial + 2 retries

    async def test_non_retryable_error_propagates_immediately(self):
        attempt_fn = AsyncMock(side_effect=_bad_request_error("invalid"))
        with patch("app.agent.llm.settings", _mock_settings()):
            with pytest.raises(openai.BadRequestError):
                await _retry_single_model(attempt_fn, "test", False, 3)
        assert attempt_fn.await_count == 1

    async def test_tools_not_supported_retries_without_tools(self):
        attempt_fn = AsyncMock(side_effect=_tools_not_supported_error())
        no_tools_fn = AsyncMock(return_value="ok_no_tools")
        with patch("app.agent.llm.settings", _mock_settings()):
            result = await _retry_single_model(
                attempt_fn, "test", True, 3,
                retry_without_tools_fn=no_tools_fn,
            )
        assert result == "ok_no_tools"

    async def test_non_transient_500_raises_immediately(self):
        attempt_fn = AsyncMock(side_effect=_non_transient_500())
        with patch("app.agent.llm.settings", _mock_settings()):
            with pytest.raises(openai.InternalServerError):
                await _retry_single_model(attempt_fn, "test", False, 3)
        assert attempt_fn.await_count == 1

    async def test_events_emitted_on_retry(self):
        attempt_fn = AsyncMock(side_effect=[_rate_limit_error(), "ok"])
        events = []
        with patch("app.agent.llm.settings", _mock_settings()), \
             patch("app.agent.llm._compute_backoff", return_value=0):
            await _retry_single_model(attempt_fn, "mymodel", False, 3, on_event=events.append)
        assert len(events) == 1
        assert events[0]["type"] == "llm_retry"
        assert events[0]["reason"] == "rate_limited"
        assert events[0]["model"] == "mymodel"

    async def test_rate_limit_uses_correct_base_wait(self):
        """Rate limit errors use LLM_RATE_LIMIT_INITIAL_WAIT for backoff."""
        attempt_fn = AsyncMock(side_effect=[_rate_limit_error(), "ok"])
        backoff_calls = []
        original_compute = _compute_backoff

        def track_backoff(base, attempt, cap=300.0):
            backoff_calls.append(base)
            return 0  # no actual wait

        with patch("app.agent.llm.settings", _mock_settings(LLM_RATE_LIMIT_INITIAL_WAIT=90)), \
             patch("app.agent.llm._compute_backoff", side_effect=track_backoff):
            await _retry_single_model(attempt_fn, "test", False, 3)
        assert backoff_calls[0] == 90


# ---------------------------------------------------------------------------
# _run_with_fallback_chain
# ---------------------------------------------------------------------------

class TestRunWithFallbackChain:
    def _patched(self, global_fallbacks=None):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            with patch("app.agent.llm.settings", _mock_settings()), \
                 patch("app.agent.llm._compute_backoff", return_value=0), \
                 patch("app.services.server_config.get_global_fallback_models",
                       return_value=global_fallbacks or []):
                yield
        return _ctx()

    async def test_primary_success(self):
        def make_attempt(m, pid, mp):
            return AsyncMock(return_value="primary_ok")

        def make_no_tools(m, pid, mp):
            return AsyncMock()

        with self._patched():
            result = await _run_with_fallback_chain(
                "primary", None, None, False, None,
                make_attempt, make_no_tools, 3,
            )
        assert result == "primary_ok"

    async def test_fallback_used_after_primary_failure(self):
        call_count = {"n": 0}

        def make_attempt(m, pid, mp):
            async def _fn():
                call_count["n"] += 1
                if m == "primary":
                    raise _timeout_error()
                return f"ok_{m}"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        with self._patched():
            result = await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fallback1"}],
                make_attempt, make_no_tools, 0,  # max_retries=0 for fast test
            )
        assert result == "ok_fallback1"

    async def test_events_collected(self):
        def make_attempt(m, pid, mp):
            async def _fn():
                if m == "primary":
                    raise _timeout_error()
                return "ok"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        events = []
        with self._patched():
            await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb"}],
                make_attempt, make_no_tools, 0,
                on_event=events.append,
            )
        types = [e["type"] for e in events]
        assert "llm_fallback" in types

    async def test_all_fail_raises_last_exc(self):
        def make_attempt(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        with self._patched():
            with pytest.raises(openai.APITimeoutError):
                await _run_with_fallback_chain(
                    "primary", None, None, False,
                    [{"model": "fb1"}],
                    make_attempt, make_no_tools, 0,
                )

    async def test_cooldown_skips_primary_to_fallback(self):
        """When primary model is in cooldown, it's skipped and fallback is used."""
        from datetime import datetime, timedelta, timezone
        _model_cooldowns["primary"] = (
            datetime.now(timezone.utc) + timedelta(minutes=10),
            "fb",
            None,
        )

        def make_attempt(m, pid, mp):
            async def _fn():
                return f"ok_{m}"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock()

        events = []
        with self._patched():
            result = await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb"}],
                make_attempt, make_no_tools, 3,
                on_event=events.append,
            )
        assert result == "ok_fb"

    async def test_cooldown_sets_on_fallback(self):
        """When primary fails and fallback succeeds, primary gets a cooldown entry."""
        def make_attempt(m, pid, mp):
            async def _fn():
                if m == "primary":
                    raise _timeout_error()
                return f"ok_{m}"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        with self._patched():
            await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb"}],
                make_attempt, make_no_tools, 0,
            )
        # Primary should now have a cooldown entry (expires, fallback_model, provider_id)
        assert "primary" in _model_cooldowns
        expires, fb_model, fb_provider = _model_cooldowns["primary"]
        assert fb_model == "fb"

    async def test_bad_request_fallback_does_not_set_cooldown(self):
        """Request-shape 400s may fallback once but must not poison the model globally."""
        def make_attempt(m, pid, mp):
            async def _fn():
                if m == "primary":
                    raise _bad_request_error("The image data you provided does not represent a valid image")
                return f"ok_{m}"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_bad_request_error("still bad"))

        with self._patched():
            result = await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb"}],
                make_attempt, make_no_tools, 0,
            )
        assert result == "ok_fb"
        assert "primary" not in _model_cooldowns

    async def test_global_fallbacks_used(self):
        """Global fallback models are appended to caller's fallback list."""
        def make_attempt(m, pid, mp):
            async def _fn():
                if m in ("primary", "fb_local"):
                    raise _timeout_error()
                return f"ok_{m}"
            return _fn

        def make_no_tools(m, pid, mp):
            return AsyncMock(side_effect=_timeout_error())

        with self._patched(global_fallbacks=[{"model": "global_fb"}]):
            result = await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb_local"}],
                make_attempt, make_no_tools, 0,
            )
        assert result == "ok_global_fb"

    async def test_auth_error_skips_fallback_chain(self):
        """AuthenticationError is not in _FALLBACK_TRIGGER_ERRORS, so it propagates immediately."""
        resp = MagicMock()
        resp.status_code = 401
        resp.headers = {}
        auth_err = openai.AuthenticationError(message="bad key", response=resp, body=None)

        def make_attempt(m, pid, mp):
            return AsyncMock(side_effect=auth_err)

        def make_no_tools(m, pid, mp):
            return AsyncMock()

        with self._patched():
            with pytest.raises(openai.AuthenticationError):
                await _run_with_fallback_chain(
                    "primary", None, None, False,
                    [{"model": "fb"}],
                    make_attempt, make_no_tools, 0,
                )

    async def test_model_access_auth_error_uses_fallback_chain(self):
        """Model-specific access denial is a model failure, not a bad-key failure."""
        resp = MagicMock()
        resp.status_code = 401
        resp.headers = {}
        auth_err = openai.AuthenticationError(
            message="key not allowed to access model. code=key_model_access_denied",
            response=resp,
            body=None,
        )
        calls = []

        def make_attempt(m, pid, mp):
            calls.append(m)
            if m == "primary":
                return AsyncMock(side_effect=auth_err)
            return AsyncMock(return_value=f"ok:{m}")

        def make_no_tools(m, pid, mp):
            return AsyncMock()

        with self._patched():
            result = await _run_with_fallback_chain(
                "primary", None, None, False,
                [{"model": "fb"}],
                make_attempt, make_no_tools, 0,
            )
        assert result == "ok:fb"
        assert calls == ["primary", "fb"]
