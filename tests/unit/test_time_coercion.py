"""Tests for the ISO 8601 canonicalization helper.

Pins the contract: widget-primitive timestamps normalize to ISO 8601 UTC
with a ``Z`` suffix, regardless of which native format the integration tool
produced. Loud failure on garbage input.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.time_coercion import to_iso_z, to_iso_z_or_none


# ── Passthrough ──


def test_none_passes_through():
    assert to_iso_z(None) is None


# ── Epoch seconds ──


def test_epoch_seconds_int():
    # 2026-04-23T14:00:00Z → 1776952800
    assert to_iso_z(1776952800) == "2026-04-23T14:00:00Z"


def test_epoch_seconds_float():
    # Float seconds are truncated to seconds (microseconds dropped).
    assert to_iso_z(1776952800.7) == "2026-04-23T14:00:00Z"


def test_epoch_zero_is_unix_epoch():
    assert to_iso_z(0) == "1970-01-01T00:00:00Z"


# ── Epoch milliseconds ──


def test_epoch_milliseconds():
    # Same instant as the seconds case, but in ms.
    assert to_iso_z(1776952800_000) == "2026-04-23T14:00:00Z"


def test_epoch_ms_threshold_boundary():
    """At exactly 1e12, the helper switches to ms interpretation."""
    # 10**12 ms = 2001-09-09T01:46:40Z
    assert to_iso_z(10**12) == "2001-09-09T01:46:40Z"


# ── ISO 8601 strings ──


def test_iso_string_with_z_suffix():
    assert to_iso_z("2026-04-23T14:00:12Z") == "2026-04-23T14:00:12Z"


def test_iso_string_with_offset():
    # +02:00 → 12:00:12Z when normalized to UTC
    assert to_iso_z("2026-04-23T14:00:12+02:00") == "2026-04-23T12:00:12Z"


def test_iso_string_naive_assumed_utc():
    """No timezone suffix — the helper assumes UTC rather than picking up
    the runner's local timezone. Stability of output is the priority."""
    assert to_iso_z("2026-04-23T14:00:12") == "2026-04-23T14:00:12Z"


def test_iso_string_with_microseconds_drops_them():
    assert to_iso_z("2026-04-23T14:00:12.987654Z") == "2026-04-23T14:00:12Z"


# ── datetime objects ──


def test_datetime_aware_utc():
    dt = datetime(2026, 4, 23, 14, 0, 12, tzinfo=timezone.utc)
    assert to_iso_z(dt) == "2026-04-23T14:00:12Z"


def test_datetime_aware_other_tz_converts():
    tz_plus_two = timezone(timedelta(hours=2))
    dt = datetime(2026, 4, 23, 14, 0, 12, tzinfo=tz_plus_two)
    assert to_iso_z(dt) == "2026-04-23T12:00:12Z"


def test_datetime_naive_assumed_utc():
    dt = datetime(2026, 4, 23, 14, 0, 12)
    assert to_iso_z(dt) == "2026-04-23T14:00:12Z"


# ── Rejection cases ──


def test_rejects_empty_string():
    with pytest.raises(ValueError):
        to_iso_z("")


def test_rejects_whitespace_string():
    with pytest.raises(ValueError):
        to_iso_z("   ")


def test_rejects_garbage_string():
    with pytest.raises(ValueError) as exc:
        to_iso_z("last tuesday")
    assert "ISO 8601" in str(exc.value)


def test_rejects_nan():
    with pytest.raises(ValueError):
        to_iso_z(float("nan"))


def test_rejects_bool():
    """``bool`` is an ``int`` subclass in Python — guard explicitly."""
    with pytest.raises(ValueError):
        to_iso_z(True)


def test_rejects_unsupported_type():
    with pytest.raises(ValueError) as exc:
        to_iso_z([1, 2, 3])
    assert "unsupported" in str(exc.value)


# ── Lenient variant ──


def test_to_iso_z_or_none_returns_none_on_bad_input():
    assert to_iso_z_or_none("garbage") is None


def test_to_iso_z_or_none_passes_through_good_input():
    assert to_iso_z_or_none(1776952800) == "2026-04-23T14:00:00Z"


def test_to_iso_z_or_none_none_stays_none():
    assert to_iso_z_or_none(None) is None
