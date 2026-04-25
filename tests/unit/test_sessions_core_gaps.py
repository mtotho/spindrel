"""Phase B.1 sweep: core-gap unit tests for app.services.sessions.

Targets (Test Audit - Core Gaps, gentle-spinning-bird.md Phase B.1):
  #1  persist_turn outbox enqueue atomicity (lines 597–630)
  #6  _sanitize_tool_messages — misordered repair + orphan edge cases
  #13 _load_messages — compaction mode paths (watermark fallback, structured, file)
  #27 store_dispatch_echo — self-skip + passive_memory guard

#18 (_filter_old_heartbeats): already pinned in test_session_helpers.py (10+ cases).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bot_cfg(**overrides):
    from app.agent.bots import BotConfig
    defaults = dict(
        id="test-bot",
        name="Test",
        model="gpt-4",
        system_prompt="You are a test bot.",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# _sanitize_tool_messages — #6 misordered/orphan edge cases
# ---------------------------------------------------------------------------

class TestSanitizeToolMessagesGaps:
    """Edge cases not covered by the three happy-path tests in test_sessions.py."""

    def test_misordered_result_reinserted_after_call(self):
        """Tool result appearing BEFORE its assistant tool_call is moved after it."""
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},  # before call
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "tc1", "function": {"name": "t"}}]},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(messages)
        call_idx = next(
            i for i, m in enumerate(result)
            if m.get("tool_calls") and any(tc.get("id") == "tc1" for tc in m["tool_calls"])
        )
        tool_idx = next(
            i for i, m in enumerate(result)
            if m.get("role") == "tool" and m.get("tool_call_id") == "tc1"
        )
        assert tool_idx > call_idx, "tool result must follow its tool_call after repair"

    def test_all_tool_calls_orphaned_content_preserved(self):
        """Assistant message whose only tool_call is orphaned keeps its text content."""
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "I tried a tool.",
                "tool_calls": [{"id": "tc1", "function": {"name": "t"}}],
            },
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(messages)
        contents = [m.get("content") for m in result if m.get("role") == "assistant"]
        assert "I tried a tool." in contents, "orphaned-call assistant content must survive"
        for m in result:
            if m.get("content") == "I tried a tool.":
                assert not m.get("tool_calls"), "tool_calls must be stripped when all calls are orphaned"

    def test_multiple_misordered_pairs_all_corrected(self):
        """Two misordered result/call sequences are both reinserted correctly."""
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "go"},
            {"role": "tool", "tool_call_id": "tc1", "content": "r1"},
            {"role": "tool", "tool_call_id": "tc2", "content": "r2"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "tc1", "function": {"name": "f1"}}]},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "tc2", "function": {"name": "f2"}}]},
        ]
        result = _sanitize_tool_messages(messages)
        for tc_id in ("tc1", "tc2"):
            call_idx = next(
                i for i, m in enumerate(result)
                if m.get("tool_calls") and any(tc.get("id") == tc_id for tc in m["tool_calls"])
            )
            res_idx = next(
                i for i, m in enumerate(result) if m.get("tool_call_id") == tc_id
            )
            assert res_idx > call_idx, f"{tc_id}: result ({res_idx}) must follow call ({call_idx})"

    def test_empty_list_returns_empty(self):
        from app.services.sessions import _sanitize_tool_messages
        assert _sanitize_tool_messages([]) == []

    def test_no_tool_messages_returns_input_unchanged(self):
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert _sanitize_tool_messages(messages) == messages

    def test_orphan_result_and_valid_pair_coexist(self):
        """One orphan result is stripped; a valid call+result pair is untouched."""
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "orphan", "content": "stray"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "tc1", "function": {"name": "t"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "valid result"},
        ]
        result = _sanitize_tool_messages(messages)
        tool_ids = [m.get("tool_call_id") for m in result if m.get("role") == "tool"]
        assert "orphan" not in tool_ids
        assert "tc1" in tool_ids


# ---------------------------------------------------------------------------
# persist_turn outbox enqueue — #1 atomicity
# ---------------------------------------------------------------------------

class TestPersistTurnOutboxEnqueue:
    """persist_turn outbox enqueue branch (lines 597–630)."""

    def _make_db(self, channel_row=None):
        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(return_value=channel_row)
        return db

    @pytest.mark.asyncio
    async def test_enqueue_called_once_per_persisted_record(self):
        """With a valid channel, enqueue is called once per non-system message."""
        from app.services.sessions import persist_turn

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        bot = _make_bot_cfg()
        db = self._make_db(channel_row=MagicMock())
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[("slack", MagicMock())])), \
             patch("app.services.outbox.enqueue",
                   new_callable=AsyncMock) as mock_enqueue, \
             patch("app.domain.message.Message.from_orm", return_value=MagicMock()):
            await persist_turn(db, session_id, bot, messages, from_index=0, channel_id=channel_id)

        assert mock_enqueue.await_count == 2, "enqueue must be called once per persisted record"

    @pytest.mark.asyncio
    async def test_enqueue_not_called_when_channel_row_not_found(self):
        """db.get returning None for the channel skips outbox entirely."""
        from app.services.sessions import persist_turn

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        bot = _make_bot_cfg()
        db = self._make_db(channel_row=None)
        messages = [{"role": "user", "content": "hello"}]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock()) as mock_resolve, \
             patch("app.services.outbox.enqueue",
                   new_callable=AsyncMock) as mock_enqueue:
            await persist_turn(db, session_id, bot, messages, from_index=0, channel_id=channel_id)

        mock_resolve.assert_not_awaited()
        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueue_error_propagates_no_swallow(self):
        """An enqueue failure is not swallowed — the caller sees the exception."""
        from app.services.sessions import persist_turn

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        bot = _make_bot_cfg()
        db = self._make_db(channel_row=MagicMock())
        messages = [{"role": "user", "content": "hello"}]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[("slack", MagicMock())])), \
             patch("app.services.outbox.enqueue",
                   new=AsyncMock(side_effect=RuntimeError("enqueue failed"))), \
             patch("app.domain.message.Message.from_orm", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="enqueue failed"):
                await persist_turn(db, session_id, bot, messages, from_index=0,
                                   channel_id=channel_id)

    @pytest.mark.asyncio
    async def test_no_outbox_when_no_channel_id(self):
        """Without channel_id the outbox branch is never entered."""
        from app.services.sessions import persist_turn

        session_id = uuid.uuid4()
        bot = _make_bot_cfg()
        db = self._make_db()
        messages = [{"role": "user", "content": "hello"}]

        with patch("app.services.outbox.enqueue",
                   new_callable=AsyncMock) as mock_enqueue:
            await persist_turn(db, session_id, bot, messages, from_index=0)

        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_only_non_system_messages_are_enqueued(self):
        """System messages are not persisted and therefore not enqueued."""
        from app.services.sessions import persist_turn

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        bot = _make_bot_cfg()
        db = self._make_db(channel_row=MagicMock())
        messages = [
            {"role": "system", "content": "context"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "more context"},
        ]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[("slack", MagicMock())])), \
             patch("app.services.outbox.enqueue",
                   new_callable=AsyncMock) as mock_enqueue, \
             patch("app.domain.message.Message.from_orm", return_value=MagicMock()):
            await persist_turn(db, session_id, bot, messages, from_index=0, channel_id=channel_id)

        assert mock_enqueue.await_count == 1, "only the one user message triggers enqueue"


# ---------------------------------------------------------------------------
# _load_messages compaction paths — #13
# ---------------------------------------------------------------------------

class TestLoadMessagesCompactionPaths:
    """Dark/smoke paths in _load_messages compaction branch (lines 374–440)."""

    @pytest.mark.asyncio
    async def test_watermark_missing_falls_back_to_full_history_with_summary(
        self, db_session, bot_registry
    ):
        """summary_message_id pointing to a missing message → fallback: all history + summary."""
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-wm", context_compaction=True, history_mode="memory")
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-wm",
            summary="Past events summary.",
            summary_message_id=uuid.uuid4(),  # points to nothing
        )
        db_session.add(sess)
        msg = Message(
            id=uuid.uuid4(),
            session_id=sess.id,
            role="user",
            content="hello from history",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(msg)
        await db_session.flush()

        result = await _load_messages(db_session, sess)

        contents = [m.get("content", "") or "" for m in result]
        assert any("Past events summary." in c for c in contents), "summary must be injected"
        assert any("hello from history" in c for c in contents), "recent messages included"

    @pytest.mark.asyncio
    async def test_file_mode_with_channel_id_skips_summary_injection(
        self, db_session, bot_registry
    ):
        """history_mode=file + session has a channel_id → no summary block in output."""
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-fm", context_compaction=True, history_mode="file")
        wm_id = uuid.uuid4()
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-fm",
            channel_id=uuid.uuid4(),  # truthy channel → file+channel → no summary
            summary="Should not appear.",
            summary_message_id=wm_id,
        )
        db_session.add(sess)
        watermark = Message(
            id=wm_id,
            session_id=sess.id,
            role="system",
            content="watermark",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watermark)
        await db_session.flush()

        result = await _load_messages(db_session, sess)

        contents = [m.get("content", "") or "" for m in result]
        assert not any("Should not appear." in c for c in contents), \
            "file+channel mode must NOT inject summary"

    @pytest.mark.asyncio
    async def test_structured_mode_injects_executive_summary(
        self, db_session, bot_registry
    ):
        """history_mode=structured → messages include 'Executive summary' prefix."""
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-str", context_compaction=True, history_mode="structured")
        wm_id = uuid.uuid4()
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-str",
            summary="Structured summary content.",
            summary_message_id=wm_id,
        )
        db_session.add(sess)
        watermark = Message(
            id=wm_id,
            session_id=sess.id,
            role="system",
            content="watermark",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watermark)
        await db_session.flush()

        result = await _load_messages(db_session, sess)

        contents = [m.get("content", "") or "" for m in result]
        assert any("Executive summary" in c for c in contents), \
            "structured mode must inject executive summary prefix"
        assert any("Structured summary content." in c for c in contents)

    @pytest.mark.asyncio
    async def test_non_file_non_structured_mode_injects_standard_summary(
        self, db_session, bot_registry
    ):
        """history_mode other than file/structured → 'Summary of the conversation so far'."""
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-mem", context_compaction=True, history_mode="memory")
        wm_id = uuid.uuid4()
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-mem",
            summary="Memory mode summary.",
            summary_message_id=wm_id,
        )
        db_session.add(sess)
        watermark = Message(
            id=wm_id,
            session_id=sess.id,
            role="system",
            content="watermark",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watermark)
        await db_session.flush()

        result = await _load_messages(db_session, sess)

        contents = [m.get("content", "") or "" for m in result]
        assert any("Summary of the conversation so far" in c for c in contents), \
            "non-file/non-structured mode must inject standard summary prefix"
        assert any("Memory mode summary." in c for c in contents)

    @pytest.mark.asyncio
    async def test_hidden_pipeline_rows_excluded_from_model_history(
        self, db_session, bot_registry
    ):
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-hidden", context_compaction=False)
        base_time = datetime.now(timezone.utc)
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-hidden",
        )
        db_session.add(sess)
        db_session.add_all([
            Message(
                session_id=sess.id,
                role="user",
                content="visible user",
                metadata_={},
                created_at=base_time,
            ),
            Message(
                session_id=sess.id,
                role="assistant",
                content="internal pipeline",
                metadata_={"hidden": True, "pipeline_step": True},
                created_at=base_time + timedelta(microseconds=1),
            ),
            Message(
                session_id=sess.id,
                role="assistant",
                content="visible assistant",
                metadata_={},
                created_at=base_time + timedelta(microseconds=2),
            ),
        ])
        await db_session.flush()

        result = await _load_messages(db_session, sess)
        contents = [m.get("content", "") or "" for m in result]
        assert "visible user" in contents
        assert "visible assistant" in contents
        assert "internal pipeline" not in contents

    @pytest.mark.asyncio
    async def test_older_assistant_history_reloads_from_compact_turn_body(
        self, db_session, bot_registry
    ):
        from app.db.models import Message, Session
        from app.services.sessions import _load_messages

        bot_registry.register("bot-compact", context_compaction=False)
        base_time = datetime.now(timezone.utc)
        sess = Session(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="bot-compact",
        )
        db_session.add(sess)
        db_session.add_all([
            Message(
                session_id=sess.id,
                role="user",
                content="do the thing",
                metadata_={},
                created_at=base_time,
            ),
            Message(
                session_id=sess.id,
                role="assistant",
                content="Verbose detail. " * 80,
                metadata_={
                    "assistant_turn_body": {
                        "version": 1,
                        "items": [
                            {"id": "text:1", "kind": "text", "text": "Ran the check."},
                            {"id": "tool:call-1", "kind": "tool_call", "toolCallId": "call-1"},
                            {"id": "text:2", "kind": "text", "text": "Found one issue."},
                        ],
                    },
                },
                tool_calls=[{"id": "call-1", "function": {"name": "file", "arguments": "{}"}}],
                created_at=base_time + timedelta(microseconds=1),
            ),
            Message(
                session_id=sess.id,
                role="assistant",
                content="Most recent assistant stays verbatim.",
                metadata_={},
                created_at=base_time + timedelta(microseconds=2),
            ),
        ])
        await db_session.flush()

        result = await _load_messages(db_session, sess)
        assistant_contents = [m.get("content", "") for m in result if m.get("role") == "assistant"]
        assert "Ran the check. [Used tool: file] Found one issue." in assistant_contents
        assert "Most recent assistant stays verbatim." in assistant_contents
        assert not any(content == "Verbose detail. " * 80 for content in assistant_contents)


# ---------------------------------------------------------------------------
# store_dispatch_echo — #27 self-skip + passive_memory guard
# ---------------------------------------------------------------------------

class TestStoreDispatchEcho:
    """Dark paths in store_dispatch_echo (lines 740–801)."""

    @staticmethod
    def _async_session_ctx(mock_db):
        """Wrap mock_db in an async context manager factory."""
        @asynccontextmanager
        async def _factory():
            yield mock_db
        return _factory

    @pytest.mark.asyncio
    async def test_early_return_on_empty_text(self):
        """Empty text → returns immediately, async_session never opened."""
        from app.services.sessions import store_dispatch_echo

        with patch("app.services.sessions.async_session") as mock_factory:
            await store_dispatch_echo(uuid.uuid4(), "slack:C123", "bot-a", "")

        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_early_return_on_whitespace_text(self):
        """Whitespace-only text → same early exit."""
        from app.services.sessions import store_dispatch_echo

        with patch("app.services.sessions.async_session") as mock_factory:
            await store_dispatch_echo(uuid.uuid4(), "slack:C123", "bot-a", "   \n  ")

        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_early_return_on_none_session_id(self):
        """None session_id → returns immediately, async_session never opened."""
        from app.services.sessions import store_dispatch_echo

        with patch("app.services.sessions.async_session") as mock_factory:
            await store_dispatch_echo(None, "slack:C123", "bot-a", "hello")

        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_self_skip_when_session_owned_by_posting_bot(self):
        """posting_bot_id == session.bot_id → store_passive_message is NOT called."""
        from app.services.sessions import store_dispatch_echo

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.bot_id = "bot-a"
        mock_db.get = AsyncMock(return_value=mock_session)

        with patch("app.services.sessions.async_session",
                   self._async_session_ctx(mock_db)), \
             patch("app.services.sessions.store_passive_message",
                   new_callable=AsyncMock) as mock_spm:
            await store_dispatch_echo(uuid.uuid4(), "slack:C123", "bot-a", "hello world")

        mock_spm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passive_memory_false_suppresses_echo(self):
        """Channel with passive_memory=False → store_passive_message is NOT called."""
        from app.services.sessions import store_dispatch_echo

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.bot_id = "bot-b"   # different from posting bot
        mock_session.channel_id = None
        mock_db.get = AsyncMock(return_value=mock_session)

        mock_channel = MagicMock()
        mock_channel.passive_memory = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_channel
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.sessions.async_session",
                   self._async_session_ctx(mock_db)), \
             patch("app.services.sessions.store_passive_message",
                   new_callable=AsyncMock) as mock_spm:
            await store_dispatch_echo(uuid.uuid4(), "slack:C456", "bot-x", "hello world")

        mock_spm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passive_memory_true_calls_store_passive_message(self):
        """Channel with passive_memory=True → echo is stored."""
        from app.services.sessions import store_dispatch_echo

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.bot_id = "bot-c"   # different from posting bot
        mock_session.channel_id = None
        mock_db.get = AsyncMock(return_value=mock_session)

        mock_channel = MagicMock()
        mock_channel.passive_memory = True
        mock_channel.id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_channel
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.sessions.async_session",
                   self._async_session_ctx(mock_db)), \
             patch("app.services.sessions.store_passive_message",
                   new_callable=AsyncMock) as mock_spm, \
             patch("app.agent.bots.get_bot", side_effect=KeyError("not in registry")):
            await store_dispatch_echo(uuid.uuid4(), "slack:C789", "bot-x", "hello from bot-x")

        mock_spm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_integration_client_id_skips_channel_lookup(self):
        """A non-integration client_id (no colon prefix) bypasses the Channel lookup."""
        from app.services.sessions import store_dispatch_echo

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.bot_id = "bot-d"
        mock_session.channel_id = None
        mock_db.get = AsyncMock(return_value=mock_session)

        with patch("app.services.sessions.async_session",
                   self._async_session_ctx(mock_db)), \
             patch("app.services.sessions.store_passive_message",
                   new_callable=AsyncMock) as mock_spm, \
             patch("app.agent.bots.get_bot", side_effect=KeyError("not in registry")):
            # "direct" has no integration prefix → is_integration_client_id returns False
            await store_dispatch_echo(uuid.uuid4(), "direct", "bot-x", "hello")

        # execute should NOT be called (no channel lookup)
        mock_db.execute.assert_not_awaited()
        # store_passive_message IS called (no passive_memory gate for non-integration)
        mock_spm.assert_awaited_once()


# ---------------------------------------------------------------------------
# stage_turn_messages — malformed delegate_to_agent argument JSON
# ---------------------------------------------------------------------------
#
# Bug class previously hidden behind `_build_message_metadata`'s silent
# `except (json.JSONDecodeError, TypeError): pass`: a truncated streaming
# response produces a tool_call with non-decodable `arguments`, the
# delegation entry vanishes from metadata, and the parent loses track of
# the delegate. After Cluster 15 follow-up (`session_writes.py`), the
# parser logs a WARNING and skips just the malformed entry — the row
# itself still persists, and other delegations in the same call list
# still land.

class TestStageTurnMessagesMalformedDelegations:
    """Pin: malformed delegate_to_agent args don't kill the row, log loudly."""

    def _ctx(self, **overrides):
        from datetime import datetime, timezone
        from app.services.session_writes import TurnContext

        defaults = dict(
            session_id=uuid.uuid4(),
            bot=_make_bot_cfg(),
            correlation_id=uuid.uuid4(),
            msg_metadata=None,
            is_heartbeat=False,
            hide_messages=False,
            pre_user_msg_id=None,
            now=datetime.now(timezone.utc),
        )
        defaults.update(overrides)
        return TurnContext(**defaults)

    def test_malformed_args_skip_entry_but_row_lands(self, caplog):
        from app.services.session_writes import stage_turn_messages

        db = MagicMock()
        ctx = self._ctx()
        messages = [
            {
                "role": "assistant",
                "content": "calling delegate",
                "tool_calls": [
                    {
                        "id": "tc-bad",
                        "function": {"name": "delegate_to_agent", "arguments": "{not json"},
                    },
                ],
            },
        ]

        with caplog.at_level("WARNING", logger="app.services.session_writes"):
            staged = stage_turn_messages(db, ctx, messages)

        assert len(staged.records) == 1, "row must persist even when delegation parse fails"
        meta = staged.records[0].metadata_
        assert "delegations" not in meta, "malformed entry must be dropped from metadata"
        assert any("Malformed delegate_to_agent" in rec.message for rec in caplog.records), (
            "parser failure must surface as a WARNING, not silent pass"
        )
        db.add.assert_called_once()

    def test_partial_failure_preserves_other_delegations(self, caplog):
        """One malformed call in a list does not erase the well-formed sibling."""
        import json as _json
        from app.services.session_writes import stage_turn_messages

        db = MagicMock()
        ctx = self._ctx()
        good_args = _json.dumps({"bot_id": "child-bot", "prompt": "do thing"})
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc-bad",
                        "function": {"name": "delegate_to_agent", "arguments": "garbage{"},
                    },
                    {
                        "id": "tc-good",
                        "function": {"name": "delegate_to_agent", "arguments": good_args},
                    },
                ],
            },
        ]

        with caplog.at_level("WARNING", logger="app.services.session_writes"):
            staged = stage_turn_messages(db, ctx, messages)

        meta = staged.records[0].metadata_
        delegations = meta.get("delegations", [])
        assert len(delegations) == 1, "well-formed delegation survives sibling parse failure"
        assert delegations[0]["bot_id"] == "child-bot"
        assert any("Malformed delegate_to_agent" in rec.message for rec in caplog.records)

    def test_non_object_args_also_skipped(self, caplog):
        """JSON that parses to a non-object (e.g. list, string, null) is also skipped."""
        from app.services.session_writes import stage_turn_messages

        db = MagicMock()
        ctx = self._ctx()
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc-array",
                        "function": {"name": "delegate_to_agent", "arguments": "[1, 2, 3]"},
                    },
                ],
            },
        ]

        with caplog.at_level("WARNING", logger="app.services.session_writes"):
            staged = stage_turn_messages(db, ctx, messages)

        meta = staged.records[0].metadata_
        assert "delegations" not in meta
        assert any("non-object" in rec.message for rec in caplog.records)
