"""LLM-facing formatting for user turns from ingest metadata.

Integrations persist the user-authored text verbatim into ``Message.content``.
Routing/identity context (sender name, platform mention token, thread summary,
etc.) lives in ``Message.metadata_``. The functions here are the single place
that turns that metadata into per-turn text the LLM sees — so the shape is
consistent across every integration and the persisted content never drifts
from "what the human actually said".

See ``docs/integrations/message-ingest-contract.md`` for the contract every
integration follows.
"""
from __future__ import annotations

from typing import Mapping


def compose_attribution_prefix(meta: Mapping | None) -> str | None:
    """Build the ``[Speaker]:`` prefix for a user message from its metadata.

    Returns ``None`` when no attribution is warranted (no ``sender_display_name``).

    When ``mention_token`` is present, the prefix includes it so the agent has a
    verbatim token it can echo back to tag the user on platforms that require
    platform-native syntax (e.g. Slack needs ``<@U123>`` — plain ``@Alice`` does
    not notify).
    """
    if not meta:
        return None
    sender_name = meta.get("sender_display_name")
    if not sender_name:
        return None
    mention_token = meta.get("mention_token")
    if mention_token:
        return f"[{sender_name} ({mention_token})]:"
    return f"[{sender_name}]:"


def compose_thread_context_block(meta: Mapping | None) -> str | None:
    """Return an LLM-facing system block from a user turn's ``thread_context``.

    Integrations that have prior-message context beyond the chat channel
    (e.g. Slack thread summaries) put a ready-to-read block in
    ``metadata.thread_context``; this helper returns it verbatim (stripped)
    or ``None`` if absent. The caller injects it as a system message adjacent
    to the user turn.
    """
    if not meta:
        return None
    block = meta.get("thread_context")
    if not block or not isinstance(block, str):
        return None
    stripped = block.strip()
    return stripped or None
