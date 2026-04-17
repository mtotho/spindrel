"""Temporal framing for the assembled LLM context.

Produces a single, plain-English "current time" system message that includes:

* the local date/time, weekday, and day-part (morning / afternoon / evening / night),
* how long it has been since the most recent user message,
* conditionally, how long it has been since the most recent non-user activity
  (only when that activity post-dates the most recent user message),
* when a meaningful gap or day-change has occurred, resolved references for
  relative-time phrases ("overnight", "tonight", "today", "tomorrow", ...)
  pulled from recent turns,
* a re-anchoring reminder so remaining relative references are re-evaluated
  against the current date.

The caller is responsible for sourcing prior messages + timestamps from the
database. This module has no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


_DAY_PARTS = (
    (5, 11, "morning"),
    (12, 16, "afternoon"),
    (17, 20, "evening"),
)


def format_day_part(dt: datetime) -> str:
    """Return '<Weekday> <part>', e.g. 'Friday morning', 'Thursday night'."""
    weekday = dt.strftime("%A")
    h = dt.hour
    for lo, hi, name in _DAY_PARTS:
        if lo <= h <= hi:
            return f"{weekday} {name}"
    return f"{weekday} night"


def format_relative(delta: timedelta) -> str:
    """Compact relative-time string: '~3m', '~45m', '~2h', '~2h 15m', '~1d 4h', '~6d'."""
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    if total < 60:
        return "~<1m"
    minutes = total // 60
    if minutes < 60:
        return f"~{minutes}m"
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        if rem_min == 0:
            return f"~{hours}h"
        return f"~{hours}h {rem_min}m"
    days = hours // 24
    rem_hours = hours % 24
    if rem_hours == 0:
        return f"~{days}d"
    return f"~{days}d {rem_hours}h"


def _format_anchor(dt_local: datetime) -> str:
    """Short absolute reference for a past message, e.g. 'Thursday 06:54 PM'."""
    return dt_local.strftime("%A %I:%M %p").lstrip("0")


# Phrases and the logic for resolving them against the current time.
# Ordered by length-desc so multi-word phrases match before their prefixes
# ("this morning" before "morning", etc.).
_PHRASE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("overnight",      re.compile(r"\bovernight\b", re.IGNORECASE)),
    ("tonight",        re.compile(r"\btonight\b", re.IGNORECASE)),
    ("this_morning",   re.compile(r"\bthis morning\b", re.IGNORECASE)),
    ("this_afternoon", re.compile(r"\bthis afternoon\b", re.IGNORECASE)),
    ("this_evening",   re.compile(r"\bthis evening\b", re.IGNORECASE)),
    ("today",          re.compile(r"\btoday\b", re.IGNORECASE)),
    ("tomorrow",       re.compile(r"\btomorrow\b", re.IGNORECASE)),
    ("yesterday",      re.compile(r"\byesterday\b", re.IGNORECASE)),
)

# When should Layer-2 resolution kick in at all? Skip when the previous turn
# was very recent and same-day — no relative-time reference has shifted meaning.
_RESOLUTION_MIN_GAP = timedelta(hours=4)

# When the gap is this large OR the day changed, the block leads with a
# prominent ⚠️ warning line and an explicit "prior context may be stale"
# imperative — empirically the unadorned "Most recent user message: ..." line
# blends into other system metadata and gets skimmed past.
_LARGE_GAP_THRESHOLD = timedelta(hours=4)


def _resolve_phrase(phrase_type: str, said_dt: datetime, now: datetime) -> str | None:
    """Return an explanation of how a relative-time phrase has shifted, or None
    when the phrase hasn't drifted enough from when it was said to need a hint.
    """
    days_elapsed = (now.date() - said_dt.date()).days

    if phrase_type == "overnight":
        if days_elapsed >= 1:
            return "that overnight has now passed; we are past it."
        return None

    if phrase_type == "tonight":
        if days_elapsed >= 1:
            return f"\"tonight\" referred to {said_dt.strftime('%A')} night, which has now passed."
        return None

    if phrase_type in ("this_morning", "this_afternoon", "this_evening"):
        part = phrase_type.replace("this_", "")
        if days_elapsed >= 1:
            return f"\"this {part}\" referred to {said_dt.strftime('%A')} {part}, which has now passed."
        return None

    if phrase_type == "today":
        if days_elapsed == 1:
            return f"\"today\" as used earlier = {said_dt.strftime('%A')} (yesterday)."
        if days_elapsed >= 2:
            return f"\"today\" as used earlier = {said_dt.strftime('%A')} ({days_elapsed}d ago)."
        return None

    if phrase_type == "tomorrow":
        target_date = said_dt.date() + timedelta(days=1)
        diff = (now.date() - target_date).days  # how many days past "that tomorrow" we are
        if diff == 0:
            return "\"tomorrow\" as used earlier = today."
        if diff == 1:
            return f"\"tomorrow\" as used earlier = {target_date.strftime('%A')} (yesterday)."
        if diff >= 2:
            return f"\"tomorrow\" as used earlier = {target_date.strftime('%A')} ({diff}d ago)."
        return None  # still in the future relative to now

    if phrase_type == "yesterday":
        target_date = said_dt.date() - timedelta(days=1)
        diff = (now.date() - target_date).days
        if diff >= 2:
            return f"\"yesterday\" as used earlier = {target_date.strftime('%A')} ({diff}d ago)."
        return None

    return None


@dataclass(frozen=True)
class ScanMessage:
    """One message from the DB flattened for Layer-2 scanning."""
    role: str            # "user" | "assistant" | other — other roles skipped
    content: str
    created_at: datetime  # tz-aware
    is_human: bool        # False for bot-sent or heartbeat user-role messages
    is_self: bool = True  # True when the assistant message was authored by the
                          # bot currently running; False for sibling-bot turns
                          # in a multi-bot session (affects attribution voice).


def find_resolved_references(
    *,
    recent_messages: list[ScanMessage],
    now_local: datetime,
    max_lines: int = 5,
) -> list[str]:
    """Return bullet lines for relative-time phrases in recent turns whose
    referents have shifted since they were uttered.

    De-duplicated by phrase type: the most-recent occurrence wins.
    """
    if not recent_messages:
        return []

    tz = now_local.tzinfo
    # Newest first so "most recent occurrence wins" is just "first seen".
    ordered = sorted(recent_messages, key=lambda m: m.created_at, reverse=True)
    seen: set[str] = set()
    bullets: list[str] = []

    for msg in ordered:
        if msg.role not in ("user", "assistant"):
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        said_dt = msg.created_at.astimezone(tz) if tz else msg.created_at
        for phrase_type, pat in _PHRASE_PATTERNS:
            if phrase_type in seen:
                continue
            m = pat.search(content)
            if not m:
                continue
            resolution = _resolve_phrase(phrase_type, said_dt, now_local)
            if resolution is None:
                # No drift — still mark as seen so an older occurrence doesn't
                # get chosen over a recent no-op.
                seen.add(phrase_type)
                continue
            surface = m.group(0).lower()
            if msg.role == "assistant":
                who = "you" if msg.is_self else "another bot"
            elif msg.is_human:
                who = "the user"
            else:
                who = "another bot"
            bullets.append(
                f"  • \"{surface}\" ({who}, {_format_anchor(said_dt)}) — {resolution}"
            )
            seen.add(phrase_type)
            if len(bullets) >= max_lines:
                return bullets
    return bullets


@dataclass(frozen=True)
class TemporalBlockInputs:
    now_local: datetime
    now_utc: datetime
    last_human_dt: datetime | None
    last_non_human_dt: datetime | None  # any non-user message (assistant, tool, heartbeat, ...)
    recent_messages: list[ScanMessage] = field(default_factory=list)


def _should_scan_for_resolutions(inputs: TemporalBlockInputs) -> bool:
    """Gate Layer-2: only scan when there's a meaningful gap or day change."""
    now = inputs.now_local
    candidates = [d for d in (inputs.last_human_dt, inputs.last_non_human_dt) if d is not None]
    if not candidates:
        return False
    prev = max(candidates)
    if prev.tzinfo is not None:
        prev = prev.astimezone(now.tzinfo) if now.tzinfo else prev
    gap = now - prev
    if gap >= _RESOLUTION_MIN_GAP:
        return True
    if prev.date() != now.date():
        return True
    return False


def _is_large_gap(prev_dt: datetime, now_local: datetime) -> bool:
    """True when the gap warrants a prominent warning (≥4h or day changed)."""
    tz = now_local.tzinfo
    prev = prev_dt.astimezone(tz) if tz else prev_dt
    if (now_local - prev) >= _LARGE_GAP_THRESHOLD:
        return True
    return prev.date() != now_local.date()


def build_current_time_block(inputs: TemporalBlockInputs) -> str:
    """Compose the full Current time + conversation-gap system message.

    Plain language on purpose — every supported provider (strong frontier models,
    7B local models, older chat endpoints) reads it the same way.

    When the gap since the last user message is large (≥4h or day-crossed),
    the block leads with a ⚠️ warning line rather than burying the fact in
    line 2. This is deliberate — the plain "Most recent user message: ..." line
    was empirically skimmed past by a frontier model, which then answered the
    new message as if continuing a days-old thread.
    """
    now_local = inputs.now_local
    now_utc = inputs.now_utc
    tz = now_local.tzinfo

    lines: list[str] = []

    # Determine the "primary prior" — last human if present, else last any.
    primary_prior: datetime | None = None
    if inputs.last_human_dt is not None:
        primary_prior = inputs.last_human_dt.astimezone(tz) if tz else inputs.last_human_dt
    elif inputs.last_non_human_dt is not None:
        primary_prior = inputs.last_non_human_dt.astimezone(tz) if tz else inputs.last_non_human_dt

    large_gap = primary_prior is not None and _is_large_gap(primary_prior, now_local)

    # ⚠️ PROMINENT HEADER — only when gap is large. Leads the block so the
    # model can't skim past "Most recent user message" buried in line 2.
    if large_gap and primary_prior is not None:
        gap = now_local - primary_prior
        lines.append(
            f"⚠️ TIME GAP: {format_relative(gap)} since the last user turn "
            f"({_format_anchor(primary_prior)}). This conversation resumed after a pause — "
            f"earlier channel history, tool results, and retrieved context MAY BE STALE. "
            f"Do not assume the current message continues the prior topic without checking."
        )

    # Standard head line.
    lines.append(
        f"Current time: {now_local.strftime('%Y-%m-%d %H:%M %Z')} "
        f"({now_utc.strftime('%H:%M UTC')}), {format_day_part(now_local)}."
    )

    if inputs.last_human_dt is not None:
        hdt = inputs.last_human_dt.astimezone(tz) if tz else inputs.last_human_dt
        gap = now_local - hdt
        lines.append(
            f"Most recent user message: {format_relative(gap)} ago ({_format_anchor(hdt)})."
        )
        if (
            inputs.last_non_human_dt is not None
            and inputs.last_non_human_dt > inputs.last_human_dt
        ):
            ndt = inputs.last_non_human_dt.astimezone(tz) if tz else inputs.last_non_human_dt
            ngap = now_local - ndt
            lines.append(
                f"Most recent non-user activity: {format_relative(ngap)} ago ({_format_anchor(ndt)})."
            )
    elif inputs.last_non_human_dt is not None:
        ndt = inputs.last_non_human_dt.astimezone(tz) if tz else inputs.last_non_human_dt
        ngap = now_local - ndt
        lines.append(
            f"Most recent activity in this conversation: {format_relative(ngap)} ago ({_format_anchor(ndt)})."
        )

    # Layer 2: resolved references for relative-time phrases.
    if _should_scan_for_resolutions(inputs) and inputs.recent_messages:
        bullets = find_resolved_references(
            recent_messages=inputs.recent_messages,
            now_local=now_local,
        )
        if bullets:
            lines.append("")
            lines.append("Relative-time references from earlier turns that may have shifted:")
            lines.extend(bullets)

    # Re-anchoring reminder — only when there IS a prior turn to re-interpret.
    if inputs.last_human_dt is not None or inputs.last_non_human_dt is not None:
        lines.append(
            "Re-anchor any remaining relative-time references against the current date before acting."
        )

    return "\n".join(lines)


__all__ = [
    "ScanMessage",
    "TemporalBlockInputs",
    "build_current_time_block",
    "find_resolved_references",
    "format_day_part",
    "format_relative",
]
