"""Compatibility adapter for chat turn-context imports.

Canonical context preparation lives in ``app.services.turn_context``.
"""
from app.services.turn_context import (  # noqa: F401
    BotContext,
    _apply_user_attribution,
    _build_identity_preamble,
    _compose_workspace_upload_context,
    _inject_member_config,
    _inject_thread_context_blocks,
    _rewrite_history_for_member_bot,
    prepare_bot_context,
)
