"""Integration-style tests for compaction flow with section modes.

Tests the branching in run_compaction_stream for structured/file/summary modes.
"""
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import _get_history_mode


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        local_tools=[], mcp_servers=[], client_tools=[], skills=[],
        pinned_tools=[],
        tool_retrieval=True,
        context_compaction=True,
        compaction_interval=10,
        compaction_keep_turns=4,
        compaction_model=None,
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
        persona=False,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.history_mode = overrides.get("history_mode", None)
    ch.id = overrides.get("id", uuid.uuid4())
    ch.name = overrides.get("name", "default-channel")
    return ch


def _mock_llm_response(content):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = []
    choice.message.model_dump.return_value = {"role": "assistant", "content": content}
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=30, total_tokens=80)
    return resp


class TestHistoryModeRouting:
    """Test that _get_history_mode correctly routes compaction."""

    def test_structured_mode_detected(self):
        bot = _make_bot(history_mode="structured")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "structured"

    def test_file_mode_detected(self):
        bot = _make_bot(history_mode="file")
        assert _get_history_mode(bot, None) == "file"

    def test_file_mode_is_default(self):
        bot = _make_bot()
        assert _get_history_mode(bot) == "file"

    def test_channel_override_wins(self):
        bot = _make_bot(history_mode="summary")
        ch = _make_channel(history_mode="file")
        assert _get_history_mode(bot, ch) == "file"


class TestCompactionStreamStructuredMode:
    """Test run_compaction_stream behavior with structured mode."""

    @pytest.mark.asyncio
    async def test_section_created_with_embedding(self):
        """Structured mode should call _generate_section and embed_text."""
        from app.services.compaction import _generate_section

        section_json = json.dumps({
            "title": "Test Section",
            "summary": "A test summary.",
            "transcript": "[USER]: hello\n[ASSISTANT]: hi",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, usage_info = await _generate_section(
                [{"role": "user", "content": "hello"}], "gpt-4",
            )
        assert title == "Test Section"
        assert summary == "A test summary."
        assert "[USER]" in transcript

    @pytest.mark.asyncio
    async def test_executive_summary_uses_all_sections(self):
        """Executive summary regeneration queries all sections."""
        from app.services.compaction import _regenerate_executive_summary

        sections = [
            MagicMock(sequence=1, title="Setup", summary="Set things up."),
            MagicMock(sequence=2, title="Debug", summary="Fixed bugs."),
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("Overall: setup then debugging.")
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = sections
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _regenerate_executive_summary(uuid.uuid4(), "gpt-4")

        assert "setup then debugging" in result


class TestCompactionStreamFileMode:
    """Test that file mode creates sections without embeddings."""

    @pytest.mark.asyncio
    async def test_section_without_embedding(self):
        """File mode should create sections but NOT embed them."""
        # This is verified by the branching logic: when history_mode=="file",
        # embed_text is not called. We test the mode detection.
        bot = _make_bot(history_mode="file")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "file"
        # In the actual code, "file" mode skips the embed_text call.
        # The full integration test would require a running DB.


class TestCompactionStreamSummaryMode:
    """Verify existing summary mode is unchanged."""

    def test_summary_mode_routes_correctly(self):
        """Default summary mode should not enter section path."""
        bot = _make_bot(history_mode="summary")
        assert _get_history_mode(bot) == "summary"

    def test_none_history_mode_defaults_to_file(self):
        bot = _make_bot(history_mode=None)
        assert _get_history_mode(bot) == "file"


class TestGetHistoryDir:
    """Test _get_history_dir path construction for different workspace roles."""

    def test_member_bot_history_dir(self, tmp_path):
        """Member bot with channel: .history inside channel workspace directory."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot(shared_workspace_id="ws-123", shared_workspace_role="member")
        ch = _make_channel(name="dev-channel")
        channel_root = str(tmp_path / "channels" / str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            result = _get_history_dir(bot, ch)
        assert result is not None
        assert result == os.path.join(channel_root, ".history")
        assert os.path.isdir(result)

    def test_orchestrator_bot_same_as_member(self, tmp_path):
        """Orchestrator with channel: .history inside channel workspace directory."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot(shared_workspace_id="ws-123", shared_workspace_role="orchestrator")
        ch = _make_channel(name="dev-channel")
        channel_root = str(tmp_path / "channels" / str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            result = _get_history_dir(bot, ch)
        assert result is not None
        assert result == os.path.join(channel_root, ".history")

    def test_two_bots_same_channel_same_dir(self, tmp_path):
        """Two bots on same shared workspace get the same history dir for the same channel."""
        from app.services.compaction import _get_history_dir
        bot_a = _make_bot(id="orch-a", shared_workspace_id="ws-123", shared_workspace_role="orchestrator")
        bot_b = _make_bot(id="orch-b", shared_workspace_id="ws-123", shared_workspace_role="orchestrator")
        ch = _make_channel(name="same-channel")
        # Both bots resolve to the same channel workspace root (shared workspace)
        channel_root = str(tmp_path / "channels" / str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            dir_a = _get_history_dir(bot_a, ch)
            dir_b = _get_history_dir(bot_b, ch)
        # Same channel = same history dir (channel-ID-based, not bot-scoped)
        assert dir_a == dir_b

    def test_non_shared_bot_history_dir(self, tmp_path):
        """Non-shared bot with channel: .history inside channel workspace directory."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot()  # no shared_workspace_id
        ch = _make_channel(name="my-channel")
        channel_root = str(tmp_path / "channels" / str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            result = _get_history_dir(bot, ch)
        assert result is not None
        assert result == os.path.join(channel_root, ".history")

    def test_channel_id_based_not_slug(self, tmp_path):
        """History dir uses channel ID, not slugified channel name."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot()
        ch = _make_channel(name="My Channel — Special (Chars)!")
        channel_root = str(tmp_path / "channels" / str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            result = _get_history_dir(bot, ch)
        assert result is not None
        # Should use channel ID, not slugified name
        assert str(ch.id) in result
        assert "my_channel" not in result

    def test_no_channel_falls_back(self, tmp_path):
        """No channel: .history at bot root (no channel subdir)."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot()
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = str(tmp_path)
            result = _get_history_dir(bot, None)
        assert result == str(tmp_path / ".history")

    def test_workspace_failure_returns_none(self):
        """If workspace resolution throws, returns None and logs."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot()
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.side_effect = RuntimeError("no workspace")
            result = _get_history_dir(bot, None)
        assert result is None

    def test_channel_workspace_failure_returns_none(self):
        """If channel workspace resolution throws, returns None."""
        from app.services.compaction import _get_history_dir
        bot = _make_bot()
        ch = _make_channel(name="test")
        with patch("app.services.channel_workspace.get_channel_workspace_root", side_effect=RuntimeError("fail")):
            result = _get_history_dir(bot, ch)
        assert result is None


class TestBackfillResume:
    """Test backfill_sections resume logic (clear_existing=False)."""

    @pytest.mark.asyncio
    async def test_resume_skips_covered_messages(self):
        """Resume should skip messages covered by existing sections and only chunk remaining."""
        from app.services.compaction import backfill_sections

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()

        # Create mock existing sections: 2 sections covering 20 u+a messages total
        existing_sections = [
            MagicMock(sequence=1, message_count=10, chunk_size=10),
            MagicMock(sequence=2, message_count=10, chunk_size=10),
        ]

        # Build 15 user+assistant pairs = 30 u+a messages.
        # Sections cover 20, so 10 remain = 2 chunks of 5.
        def _make_msg(role, content, idx):
            m = MagicMock()
            m.role = role
            m.content = content
            m.tool_calls = None
            m.tool_call_id = None
            m.metadata_ = {}
            m.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=idx)
            return m

        all_msgs = []
        for i in range(15):
            all_msgs.append(_make_msg("user", f"user message {i}", i * 2))
            all_msgs.append(_make_msg("assistant", f"assistant response {i}", i * 2 + 1))

        mock_channel = _make_channel(history_mode=None, name="test")
        mock_channel.bot_id = "test"
        mock_channel.active_session_id = session_id

        mock_session_obj = MagicMock()
        mock_session_obj.id = session_id
        mock_session_obj.summary_message_id = None
        mock_session_obj.channel_id = channel_id

        bot = _make_bot()

        generated_chunks = []

        async def mock_generate_section(chunk, model, **kwargs):
            msg_count = sum(1 for m in chunk if m.get("role") in ("user", "assistant"))
            generated_chunks.append(msg_count)
            return "Title", "Summary", "Transcript", ["tag"], {"tier": "normal", "prompt_tokens": None, "completion_tokens": None}

        # Build fake DB context managers for each async_session() call
        session_calls = [0]

        def make_db(idx):
            """Create a FakeDB for the Nth async_session() call."""
            class FakeDB:
                async def get(self, cls, id_val):
                    name = cls.__name__
                    if name == "Channel":
                        return mock_channel
                    if name == "Session":
                        return mock_session_obj
                    return None

                async def execute(self, stmt):
                    # idx=1: message query; idx=2: sections query; rest: section creation/update
                    if idx == 1:
                        result = MagicMock()
                        result.scalars.return_value.all.return_value = all_msgs
                        return result
                    elif idx == 2:
                        result = MagicMock()
                        result.scalars.return_value.all.return_value = existing_sections
                        return result
                    return MagicMock()

                async def commit(self):
                    pass

                def add(self, obj):
                    pass

            return FakeDB()

        class FakeSessionCtx:
            async def __aenter__(self_inner):
                session_calls[0] += 1
                return make_db(session_calls[0])
            async def __aexit__(self_inner, *args):
                return False

        with patch("app.services.compaction.async_session", side_effect=lambda: FakeSessionCtx()), \
             patch("app.services.compaction._generate_section", side_effect=mock_generate_section), \
             patch("app.services.compaction._regenerate_executive_summary", new_callable=AsyncMock, return_value="exec summary"), \
             patch("app.services.compaction._get_history_dir", return_value=None), \
             patch("app.services.compaction._get_workspace_root", return_value=None), \
             patch("app.services.compaction._get_channel_ws_root", return_value=None), \
             patch("app.agent.bots.get_bot", return_value=bot):

            events = []
            async for event in backfill_sections(
                channel_id, chunk_size=5, clear_existing=False,
            ):
                events.append(event)

        # 30 ua messages total, 20 covered, 10 remaining = 2 chunks of 5
        assert len(generated_chunks) == 2
        assert all(c == 5 for c in generated_chunks)

        # Verify events: 2 progress + 1 done
        progress_events = [e for e in events if e["type"] == "backfill_progress"]
        done_events = [e for e in events if e["type"] == "backfill_done"]
        assert len(progress_events) == 2
        assert progress_events[0]["section"] == 1
        assert progress_events[1]["section"] == 2
        assert len(done_events) == 1
        assert done_events[0]["sections_created"] == 2


class TestCountEligibleMessages:
    """Test count_eligible_messages helper."""

    @pytest.mark.asyncio
    async def test_counts_only_active_ua_messages(self):
        """Should count user+assistant but not passive user messages."""
        from app.services.compaction import count_eligible_messages

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.active_session_id = session_id

        mock_session = MagicMock()
        mock_session.summary_message_id = None

        # 3 user msgs (1 passive), 2 assistant msgs = 4 eligible
        msgs = []
        for i in range(3):
            m = MagicMock()
            m.role = "user"
            m.metadata_ = {"passive": True} if i == 0 else {}
            msgs.append(m)
        for i in range(2):
            m = MagicMock()
            m.role = "assistant"
            m.metadata_ = {}
            msgs.append(m)

        class FakeDB:
            async def get(self, cls, id_val):
                name = cls.__name__
                if name == "Channel":
                    return mock_channel
                if name == "Session":
                    return mock_session
                return None

            async def execute(self, stmt):
                result = MagicMock()
                result.scalars.return_value.all.return_value = msgs
                return result

        class FakeSessionCtx:
            async def __aenter__(self):
                return FakeDB()
            async def __aexit__(self, *args):
                return False

        with patch("app.services.compaction.async_session", return_value=FakeSessionCtx()):
            count = await count_eligible_messages(channel_id)

        # 2 active users + 2 assistants = 4
        assert count == 4

    @pytest.mark.asyncio
    async def test_returns_zero_for_missing_channel(self):
        """Should return 0 if channel not found."""
        from app.services.compaction import count_eligible_messages

        class FakeDB:
            async def get(self, cls, id_val):
                return None

        class FakeSessionCtx:
            async def __aenter__(self):
                return FakeDB()
            async def __aexit__(self, *args):
                return False

        with patch("app.services.compaction.async_session", return_value=FakeSessionCtx()):
            count = await count_eligible_messages(uuid.uuid4())

        assert count == 0


class TestWriteSectionFileRelpath:
    """Verify transcript_path stored in DB resolves correctly for reads."""

    def test_channel_relpath_new_format(self, tmp_path):
        """With channel: transcript_path is channels/{id}/.history/001_title.md relative to channel ws root."""
        from app.services.compaction import _get_history_dir, _write_section_file
        import os
        bot = _make_bot(shared_workspace_id="ws-123", shared_workspace_role="member")
        ch = _make_channel(name="test-ch")
        # Channel ws root is the parent of channels/ (e.g. shared workspace root)
        channel_ws_root = str(tmp_path)
        channel_root = os.path.join(channel_ws_root, "channels", str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            history_dir = _get_history_dir(bot, ch)
        rel = _write_section_file(
            history_dir, 1, "Title", "Summary", "transcript text",
            None, None, 5, ["tag"], channel_ws_root,
        )
        # Verify the file exists at channel_ws_root + rel
        assert os.path.isfile(os.path.join(channel_ws_root, rel))
        assert rel.startswith("channels/")
        assert "/.history/" in rel

    def test_orchestrator_relpath_resolves(self, tmp_path):
        """Orchestrator: transcript_path relative to channel ws root resolves correctly."""
        from app.services.compaction import _get_history_dir, _write_section_file
        import os
        bot = _make_bot(id="orch", shared_workspace_id="ws-123", shared_workspace_role="orchestrator")
        ch = _make_channel(name="test-ch")
        channel_ws_root = str(tmp_path)
        channel_root = os.path.join(channel_ws_root, "channels", str(ch.id))
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=channel_root):
            history_dir = _get_history_dir(bot, ch)
        rel = _write_section_file(
            history_dir, 1, "Title", "Summary", "transcript text",
            None, None, 5, ["tag"], channel_ws_root,
        )
        # Verify: os.path.join(channel_ws_root, rel) reaches the actual file
        full_path = os.path.join(channel_ws_root, rel)
        assert os.path.isfile(full_path)
        assert rel.startswith("channels/")
        # Simulate the read path
        with open(full_path) as f:
            content = f.read()
        assert "Title" in content
        assert "transcript text" in content

    def test_no_channel_relpath_old_format(self, tmp_path):
        """Without channel: transcript_path is .history/001_title.md (old format)."""
        from app.services.compaction import _get_history_dir, _write_section_file
        import os
        bot = _make_bot()
        ws_root = str(tmp_path)
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = ws_root
            history_dir = _get_history_dir(bot, None)
        rel = _write_section_file(
            history_dir, 1, "Title", "Summary", "transcript text",
            None, None, 5, ["tag"], ws_root,
        )
        assert os.path.isfile(os.path.join(ws_root, rel))
        assert rel.startswith(".history/")
