"""Tests for app.services.temporal_context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.temporal_context import (
    ScanMessage,
    TemporalBlockInputs,
    build_current_time_block,
    find_resolved_references,
    format_day_part,
    format_relative,
)


EASTERN = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# format_day_part
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hour, expected",
    [
        (4, "night"),
        (5, "morning"),
        (11, "morning"),
        (12, "afternoon"),
        (16, "afternoon"),
        (17, "evening"),
        (20, "evening"),
        (21, "night"),
        (23, "night"),
        (0, "night"),
    ],
)
def test_format_day_part_buckets(hour: int, expected: str) -> None:
    dt = datetime(2026, 4, 17, hour, 30, tzinfo=EASTERN)  # Friday
    assert format_day_part(dt) == f"Friday {expected}"


# ---------------------------------------------------------------------------
# format_relative
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "seconds, expected",
    [
        (10, "~<1m"),
        (59, "~<1m"),
        (60, "~1m"),
        (60 * 45, "~45m"),
        (60 * 60, "~1h"),
        (60 * 60 * 2 + 60 * 15, "~2h 15m"),
        (60 * 60 * 23 + 60 * 59, "~23h 59m"),
        (60 * 60 * 24, "~1d"),
        (60 * 60 * 28, "~1d 4h"),
        (60 * 60 * 24 * 6, "~6d"),
    ],
)
def test_format_relative_table(seconds: int, expected: str) -> None:
    assert format_relative(timedelta(seconds=seconds)) == expected


def test_format_relative_negative_clamped() -> None:
    assert format_relative(timedelta(seconds=-120)) == "~<1m"


# ---------------------------------------------------------------------------
# build_current_time_block — shapes
# ---------------------------------------------------------------------------

def _now_fri_morning() -> tuple[datetime, datetime]:
    now_local = datetime(2026, 4, 17, 6, 26, tzinfo=EASTERN)
    now_utc = now_local.astimezone(timezone.utc)
    return now_local, now_utc


def test_block_no_prior_turns_just_head() -> None:
    now_local, now_utc = _now_fri_morning()
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=None,
        last_non_human_dt=None,
    ))
    lines = block.split("\n")
    assert len(lines) == 1
    assert lines[0].startswith("Current time:")
    assert "Friday morning" in lines[0]


def test_block_human_only_three_lines() -> None:
    now_local, now_utc = _now_fri_morning()
    hdt = datetime(2026, 4, 16, 18, 54, tzinfo=EASTERN)  # Thu 6:54 PM
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=hdt,
        last_non_human_dt=None,
    ))
    assert "Most recent user message: ~11h 32m ago (Thursday 06:54 PM)" in block
    assert "Most recent non-user activity" not in block
    assert "Re-anchor" in block


def test_block_non_human_newer_includes_activity_line() -> None:
    now_local, now_utc = _now_fri_morning()
    hdt = datetime(2026, 4, 15, 19, 12, tzinfo=EASTERN)  # Wed 7:12 PM
    ndt = datetime(2026, 4, 17, 4, 26, tzinfo=EASTERN)   # Fri 4:26 AM
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=hdt,
        last_non_human_dt=ndt,
    ))
    assert "Most recent user message:" in block
    assert "Most recent non-user activity: ~2h ago (Friday 04:26 AM)" in block


def test_block_non_human_older_suppresses_activity_line() -> None:
    now_local, now_utc = _now_fri_morning()
    hdt = datetime(2026, 4, 17, 6, 20, tzinfo=EASTERN)   # Fri 6:20 AM (fresh)
    ndt = datetime(2026, 4, 16, 18, 54, tzinfo=EASTERN)  # Thu 6:54 PM (older)
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=hdt,
        last_non_human_dt=ndt,
    ))
    assert "Most recent non-user activity" not in block


def test_block_heartbeat_only_no_human() -> None:
    now_local, now_utc = _now_fri_morning()
    ndt = datetime(2026, 4, 17, 5, 26, tzinfo=EASTERN)
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=None,
        last_non_human_dt=ndt,
    ))
    assert "Most recent activity in this conversation: ~1h ago" in block
    assert "Most recent user message" not in block


# ---------------------------------------------------------------------------
# find_resolved_references
# ---------------------------------------------------------------------------

def _msg(role: str, content: str, dt: datetime, is_human: bool = True) -> ScanMessage:
    return ScanMessage(role=role, content=content, created_at=dt, is_human=is_human)


def test_resolve_overnight_crumb_scenario() -> None:
    """The exact failure case — bot said 'overnight' Thu PM, now Fri AM."""
    now_local, _ = _now_fri_morning()
    prior = datetime(2026, 4, 16, 18, 54, tzinfo=EASTERN)
    msgs = [
        _msg("assistant", "She's on track to peak beautifully overnight.", prior, is_human=False),
    ]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    assert "overnight" in bullets[0]
    assert "that overnight has now passed" in bullets[0]
    assert "you" in bullets[0]  # attributed to the assistant


def test_resolve_tomorrow_becomes_today() -> None:
    now_local, _ = _now_fri_morning()  # Fri
    prior = datetime(2026, 4, 16, 15, 0, tzinfo=EASTERN)  # Thu afternoon
    msgs = [_msg("user", "I'll bake tomorrow", prior, is_human=True)]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    assert "\"tomorrow\" as used earlier = today" in bullets[0]
    assert "the user" in bullets[0]


def test_resolve_today_becomes_yesterday() -> None:
    now_local, _ = _now_fri_morning()  # Fri
    prior = datetime(2026, 4, 16, 10, 0, tzinfo=EASTERN)  # Thu morning
    msgs = [_msg("user", "I'll handle it today", prior, is_human=True)]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    assert "Thursday (yesterday)" in bullets[0]


def test_resolve_this_morning_past() -> None:
    now_local, _ = _now_fri_morning()
    prior = datetime(2026, 4, 16, 9, 30, tzinfo=EASTERN)  # Thu morning
    msgs = [_msg("assistant", "I fed her this morning", prior, is_human=False)]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    assert "Thursday morning" in bullets[0]
    assert "has now passed" in bullets[0]


def test_resolve_skips_same_day_same_reference() -> None:
    """Same-day 'today' reference doesn't need resolution."""
    now_local = datetime(2026, 4, 17, 14, 0, tzinfo=EASTERN)  # Fri afternoon
    prior = datetime(2026, 4, 17, 10, 0, tzinfo=EASTERN)      # Fri morning
    msgs = [_msg("user", "I'll deal with it today", prior)]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert bullets == []


def test_resolve_dedupes_by_phrase_type_most_recent_wins() -> None:
    now_local, _ = _now_fri_morning()
    older = datetime(2026, 4, 15, 10, 0, tzinfo=EASTERN)  # Wed
    newer = datetime(2026, 4, 16, 15, 0, tzinfo=EASTERN)  # Thu
    msgs = [
        _msg("user", "maybe tomorrow", older, is_human=True),
        _msg("assistant", "okay, I can help tomorrow", newer, is_human=False),
    ]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    # newer occurrence (Thursday) should win → "tomorrow" = today
    assert "\"tomorrow\" as used earlier = today" in bullets[0]
    assert "you" in bullets[0]  # assistant voice


def test_resolve_sibling_bot_attributed_as_another_bot() -> None:
    """In a multi-bot session, a sibling bot's assistant turn must NOT read as 'you'."""
    now_local, _ = _now_fri_morning()
    prior = datetime(2026, 4, 16, 18, 54, tzinfo=EASTERN)
    msgs = [
        ScanMessage(
            role="assistant",
            content="She'll peak beautifully overnight.",
            created_at=prior,
            is_human=False,
            is_self=False,  # different bot authored this turn
        ),
    ]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    assert len(bullets) == 1
    assert "another bot" in bullets[0]
    assert "(you," not in bullets[0]


def test_resolve_multiple_phrase_types_all_surfaced() -> None:
    now_local, _ = _now_fri_morning()
    prior = datetime(2026, 4, 16, 18, 0, tzinfo=EASTERN)
    msgs = [
        _msg("assistant", "peaks overnight, bake tomorrow, check tonight", prior, is_human=False),
    ]
    bullets = find_resolved_references(recent_messages=msgs, now_local=now_local)
    kinds = " ".join(bullets).lower()
    assert "overnight" in kinds
    assert "tomorrow" in kinds
    assert "tonight" in kinds
    assert len(bullets) == 3


# ---------------------------------------------------------------------------
# build_current_time_block with Layer-2 integration
# ---------------------------------------------------------------------------

def test_block_layer2_skipped_when_gap_small_same_day() -> None:
    now_local, now_utc = _now_fri_morning()
    hdt = datetime(2026, 4, 17, 6, 20, tzinfo=EASTERN)  # 6 min ago, same day
    msgs = [_msg("user", "I'll bake tomorrow", hdt, is_human=True)]
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=hdt,
        last_non_human_dt=None,
        recent_messages=msgs,
    ))
    assert "Relative-time references" not in block


def test_block_layer2_engages_when_day_changed() -> None:
    now_local, now_utc = _now_fri_morning()
    hdt = datetime(2026, 4, 16, 18, 54, tzinfo=EASTERN)
    msgs = [
        _msg("assistant", "She'll peak beautifully overnight.", hdt, is_human=False),
    ]
    block = build_current_time_block(TemporalBlockInputs(
        now_local=now_local,
        now_utc=now_utc,
        last_human_dt=None,
        last_non_human_dt=hdt,
        recent_messages=msgs,
    ))
    assert "Relative-time references from earlier turns that may have shifted:" in block
    assert "overnight" in block
    assert "that overnight has now passed" in block
