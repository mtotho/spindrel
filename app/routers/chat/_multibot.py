"""Compatibility adapter for channel member-turn imports.

Canonical member-bot routing and fanout lives in
``app.services.channel_member_turns``.
"""
from app.services.channel_member_turns import (  # noqa: F401
    _MEMBER_MENTION_MAX_DEPTH,
    _background_tasks,
    _detect_member_mentions,
    _maybe_route_to_member_bot,
    _run_member_bot_reply,
    _trigger_member_bot_replies,
    background_tasks,
    detect_member_mentions,
    maybe_route_to_member_bot,
    run_member_bot_reply,
    trigger_member_bot_replies,
)
