"""Phase I — Integration Ingest Contract Hardening.

Targets seams from plan rippling-giggling-bachman.md Phase I:

I.2  ``_metadata`` leak past strip phase — prepare_bot_context must remove
     all ``_metadata`` keys before returning messages to the LLM caller.

I.3  Pipeline step ordering — attribute/thread_context injected before strip;
     exact sequence locked in by this test so a reorder breaks a test not prod.

I.4  Empty-string ``sender_display_name`` → no attribution prefix applied.
     Existing tests cover None and missing key; this adds the empty-string case.

I.5  Double-attribution drift with different sender name — if content already
     has ``[Alice]: hi`` and metadata says ``sender_display_name="Alicia"``,
     the idempotency guard fails and the message becomes ``[Alicia]: [Alice]: hi``.
     Pinned as current behavior (name-drift bug); logged to Loose Ends.

I.6  Non-string ``thread_context`` (bool / int) silently ignored — no system
     block, no exception.

I.8  ``IngestMessageMetadata`` ``extra="allow"`` silently accepts typos —
     ``sender_displayname`` (missing underscore) parses but is ignored;
     composed prefix is empty.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agent.message_formatting import (
    compose_attribution_prefix,
    compose_thread_context_block,
)
from app.services.turn_context import (
    _apply_user_attribution,
    _inject_thread_context_blocks,
)
from app.schemas.chat import IngestMessageMetadata


# ===========================================================================
# I.2 — _metadata stripped from all messages after prepare_bot_context
# ===========================================================================


@pytest.mark.asyncio
class TestMetadataLeakPastStrip:
    """prepare_bot_context must remove every ``_metadata`` key from its
    returned ``messages`` list.  No path (primary / routed / member) should
    ever hand the LLM a message with ``_metadata`` in it.
    """

    async def test_primary_bot_path_strips_all_metadata(self):
        """Primary bot path: _apply_user_attribution + _inject_thread_context_blocks
        run on messages that carry _metadata; strip_metadata_keys must remove them.
        """
        from app.services.turn_context import prepare_bot_context

        bot = SimpleNamespace(
            id="primary-bot",
            name="Primary",
            persona=None,
            shared_workspace_id=None,
        )

        messages = [
            {
                "role": "user",
                "content": "hello",
                "_metadata": {
                    "sender_display_name": "Alice",
                    "sender_type": "human",
                    "source": "web",
                    "sender_id": "web:u1",
                    "thread_context": "some prior context",
                },
            },
            {
                "role": "assistant",
                "content": "reply",
                "_metadata": {"sender_id": "bot:primary-bot"},
            },
        ]

        ctx = await prepare_bot_context(
            messages=messages,
            bot=bot,
            primary_bot_id="primary-bot",
            channel_id=None,
        )

        for i, msg in enumerate(ctx.messages):
            assert "_metadata" not in msg, (
                f"Message {i} (role={msg.get('role')!r}) still has _metadata after "
                f"prepare_bot_context — strip_metadata_keys failed: {msg}"
            )

    async def test_mixed_messages_all_stripped(self):
        """Multiple user/assistant messages all lose _metadata."""
        from app.services.turn_context import prepare_bot_context

        bot = SimpleNamespace(
            id="primary-bot",
            name="Primary",
            persona=None,
            shared_workspace_id=None,
        )

        messages = [
            {"role": "user", "content": "a", "_metadata": {"sender_display_name": "A", "source": "x", "sender_id": "x:1", "sender_type": "human"}},
            {"role": "assistant", "content": "b", "_metadata": {"sender_id": "bot:primary-bot"}},
            {"role": "user", "content": "c", "_metadata": {"sender_display_name": "A", "source": "x", "sender_id": "x:1", "sender_type": "human"}},
        ]

        ctx = await prepare_bot_context(
            messages=messages,
            bot=bot,
            primary_bot_id="primary-bot",
            channel_id=None,
        )

        leaked = [m for m in ctx.messages if "_metadata" in m]
        assert leaked == [], (
            f"_metadata leaked past strip in {len(leaked)} message(s): {leaked}"
        )

    async def test_messages_without_metadata_survive_strip(self):
        """Messages that never had _metadata are returned intact."""
        from app.services.turn_context import prepare_bot_context

        bot = SimpleNamespace(
            id="primary-bot",
            name="Primary",
            persona=None,
            shared_workspace_id=None,
        )

        messages = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "hello"},
        ]

        ctx = await prepare_bot_context(
            messages=messages,
            bot=bot,
            primary_bot_id="primary-bot",
            channel_id=None,
        )

        assert any(m["role"] == "user" for m in ctx.messages), (
            "User message disappeared from result"
        )


# ===========================================================================
# I.3 — Pipeline step ordering
# ===========================================================================


@pytest.mark.asyncio
class TestPipelineStepOrdering:
    """Invariant: attribution BEFORE thread_context injection BEFORE strip.

    The spec (prepare_bot_context docstring) says:
        4. _rewrite_history_for_member_bot
        5. _apply_user_attribution
        5b. _inject_thread_context_blocks
        6. strip_metadata_keys
        7. _inject_member_config

    We instrument each step to record its call position and assert the
    sequence.  Catches accidental reorders — the functions are adjacent
    enough that a cut-paste bug could silently break the contract.
    """

    async def test_attribution_before_thread_context_before_strip(self):
        """Steps 5/5b/6 execute in the documented order."""
        from app.services import turn_context as ctx_mod
        from app.services import sessions as sessions_mod

        call_order: list[str] = []

        orig_attr = ctx_mod._apply_user_attribution
        orig_thread = ctx_mod._inject_thread_context_blocks
        orig_strip = sessions_mod.strip_metadata_keys

        def _track_attr(messages):
            call_order.append("attribution")
            orig_attr(messages)

        def _track_thread(messages):
            call_order.append("thread_context")
            orig_thread(messages)

        def _track_strip(messages):
            call_order.append("strip")
            return orig_strip(messages)

        bot = SimpleNamespace(
            id="primary-bot",
            name="Primary",
            persona=None,
            shared_workspace_id=None,
        )
        messages = [
            {
                "role": "user",
                "content": "hello",
                "_metadata": {
                    "sender_display_name": "Alice",
                    "source": "web",
                    "sender_id": "web:u1",
                    "sender_type": "human",
                    "thread_context": "prior summary",
                },
            },
        ]

        with (
            patch.object(ctx_mod, "_apply_user_attribution", _track_attr),
            patch.object(ctx_mod, "_inject_thread_context_blocks", _track_thread),
            # strip_metadata_keys is imported locally inside prepare_bot_context
            # so patching the source module attribute intercepts it at call time.
            patch.object(sessions_mod, "strip_metadata_keys", _track_strip),
        ):
            from app.services.turn_context import prepare_bot_context
            await prepare_bot_context(
                messages=messages,
                bot=bot,
                primary_bot_id="primary-bot",
                channel_id=None,
            )

        assert call_order == ["attribution", "thread_context", "strip"], (
            f"Step ordering violated: expected attribution→thread_context→strip, "
            f"got {call_order}"
        )


# ===========================================================================
# I.4 — Empty-string sender_display_name → no prefix
# ===========================================================================


class TestEmptySenderDisplayName:
    """Empty-string ``sender_display_name`` must produce no attribution prefix.

    Existing tests cover None and missing-key; this adds the empty-string case
    to prevent bare ``[]:`` prefix regressions.
    """

    def test_compose_attribution_prefix_empty_string_returns_none(self):
        result = compose_attribution_prefix({"sender_display_name": ""})
        assert result is None

    def test_apply_attribution_empty_string_no_prefix(self):
        msgs = [
            {
                "role": "user",
                "content": "hello",
                "_metadata": {"sender_display_name": ""},
            }
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "hello", (
            "Empty sender_display_name must not produce a bare []: prefix"
        )

    def test_apply_attribution_whitespace_only_name_no_prefix(self):
        """Whitespace-only name: truthy in Python but semantically empty.

        Current behavior: truthy whitespace IS a valid name, so
        compose_attribution_prefix returns "[   ]:" which is ugly.
        Pinning the current contract — if normalization is added later,
        update this test.
        """
        prefix = compose_attribution_prefix({"sender_display_name": "   "})
        # Current behavior: whitespace name IS used (no strip in composer).
        # This is a documentation pin, not an endorsement.
        assert prefix == "[   ]:"  # "pinning current contract — whitespace used as-is"


# ===========================================================================
# I.5 — Double-attribution drift with different sender name
# ===========================================================================


class TestDoubleAttributionDrift:
    """Regression guard for the I.5 fix (2026-04-23).

    The old guard only checked the CURRENT sender's name, so when metadata
    carried a renamed user (``Alice`` → ``Alicia``) and the stored content
    already had ``[Alice]: hi``, the guard missed and produced
    ``[Alicia]: [Alice]: hi`` — double prefix with mismatched names.

    The fix replaces the single-name check with a generic regex
    ``^\\[[^\\]]+\\]:\\s`` that matches ANY existing attribution prefix —
    first attribution wins, so the stored prefix stays intact and no
    second prefix is prepended.
    """

    def test_different_sender_name_first_attribution_wins(self):
        """Metadata-name drift (``Alice`` → ``Alicia``) must NOT double-prefix.

        Before the fix: content became ``[Alicia]: [Alice]: hi``.
        After the fix: the existing ``[Alice]:`` prefix is detected by
        ``_ATTRIBUTION_PREFIX_RE`` and the new prefix is skipped.
        """
        msgs = [
            {
                "role": "user",
                "content": "[Alice]: hi",
                "_metadata": {"sender_display_name": "Alicia"},
            }
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Alice]: hi"

    def test_existing_mention_token_prefix_also_respected(self):
        """Mention-token shape ``[Alice (<@U123>)]:`` also counts as an
        existing attribution prefix — the regex must match the bracketed
        span regardless of internal punctuation."""
        msgs = [
            {
                "role": "user",
                "content": "[Alice (<@U123>)]: hi",
                "_metadata": {"sender_display_name": "Alicia"},
            }
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Alice (<@U123>)]: hi"

    def test_same_sender_name_remains_idempotent(self):
        """Same name with existing prefix: stays untouched — this is correct."""
        msgs = [
            {
                "role": "user",
                "content": "[Alice]: hi",
                "_metadata": {"sender_display_name": "Alice"},
            }
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Alice]: hi"

    def test_mention_token_upgrade_legacy_prefix_still_idempotent(self):
        """Existing ``[Alice]: hi`` with new mention_token for Alice → no double prefix.

        The legacy guard catches this: prefix = "[Alice (<@U1>)]:" differs from
        legacy_prefix = "[Alice]:", but content DOES start with legacy_prefix
        → guard fires → no change.
        """
        msgs = [
            {
                "role": "user",
                "content": "[Alice]: hi",
                "_metadata": {
                    "sender_display_name": "Alice",
                    "mention_token": "<@U1>",
                },
            }
        ]
        _apply_user_attribution(msgs)
        # The legacy guard catches same-name + mention_token upgrade → no double prefix.
        assert msgs[0]["content"] == "[Alice]: hi"


# ===========================================================================
# I.6 — Non-string thread_context silently ignored
# ===========================================================================


class TestNonStringThreadContext:
    """Non-string values in ``thread_context`` must be silently ignored.

    ``compose_thread_context_block`` guards with ``isinstance(block, str)``
    (line 51 in message_formatting.py).  This pins the type-tolerance
    contract — booleans, ints, dicts from a misconfigured integration must
    not cause exceptions or inject a system block.
    """

    def test_bool_thread_context_returns_none(self):
        assert compose_thread_context_block({"thread_context": False}) is None
        assert compose_thread_context_block({"thread_context": True}) is None

    def test_int_thread_context_returns_none(self):
        assert compose_thread_context_block({"thread_context": 123}) is None
        assert compose_thread_context_block({"thread_context": 0}) is None

    def test_dict_thread_context_returns_none(self):
        assert compose_thread_context_block({"thread_context": {"key": "value"}}) is None

    def test_list_thread_context_returns_none(self):
        assert compose_thread_context_block({"thread_context": ["line 1", "line 2"]}) is None

    def test_inject_skips_non_string_thread_context(self):
        """_inject_thread_context_blocks does not insert a system block for
        non-string thread_context values — no exception either.
        """
        msgs = [
            {
                "role": "user",
                "content": "question",
                "_metadata": {"sender_display_name": "Alice", "thread_context": False},
            }
        ]
        _inject_thread_context_blocks(msgs)
        assert len(msgs) == 1, (
            "Non-string thread_context=False caused a system block to be inserted"
        )


# ===========================================================================
# I.8 — IngestMessageMetadata extra="allow" accepts typos silently
# ===========================================================================


class TestIngestMetadataTypoAccepted:
    """``extra="allow"`` means a typo in field names is silently swallowed.

    ``sender_displayname`` (missing underscore) parses without error but is
    not picked up as ``sender_display_name``, so the attribution prefix is
    empty — the LLM never sees a speaker label.

    This is a known weakness in the schema design (documented in the ingest
    contract); this test pins it so the behavior is explicit if we ever
    switch to ``extra="forbid"`` and break integrations that send extras.
    """

    def test_typo_field_accepted_without_error(self):
        """A typo key parses successfully — no ValidationError."""
        meta = IngestMessageMetadata(
            source="slack",
            sender_id="slack:U1",
            sender_display_name="Alice",  # correct field
            sender_type="human",
            sender_displayname="Alice-typo",  # typo field — extra key
        )
        # The correct field is set.
        assert meta.sender_display_name == "Alice"
        # The typo field is accessible via model_extra (not as an attribute).
        assert meta.model_extra.get("sender_displayname") == "Alice-typo"

    def test_typo_only_no_correct_field_means_no_prefix(self):
        """If ONLY the typo key is sent (no real sender_display_name),
        IngestMessageMetadata raises because sender_display_name is required.

        This pins that the schema at least validates required fields even
        with extra="allow".
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="sender_display_name"):
            IngestMessageMetadata(
                source="slack",
                sender_id="slack:U1",
                sender_displayname="Alice-typo",  # only typo, no real field
                sender_type="human",
            )

    def test_compose_prefix_ignores_typo_key(self):
        """compose_attribution_prefix uses plain dict lookup — a raw dict
        with only the typo key produces no prefix (acts like missing name).
        """
        typo_meta = {
            "source": "slack",
            "sender_id": "slack:U1",
            "sender_displayname": "Alice",  # typo: missing _display_
            "sender_type": "human",
        }
        result = compose_attribution_prefix(typo_meta)
        assert result is None, (
            "Typo key 'sender_displayname' must not produce a prefix — "
            "only 'sender_display_name' (with underscore) is recognized"
        )
