"""Unit tests for memory flush system and RAG pipeline fixes.

Covers:
- Memory flush resolution (enabled, model, prompt fallback)
- Embedding cache (per-request deduplication)
- Executive summary auto-regeneration threshold
- Tool call context in compaction summaries
- Head+tail truncation for tool result summarization
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        persona=False,
        history_mode="summary",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.name = overrides.get("name", "test-channel")
    ch.client_id = overrides.get("client_id", "test-client")
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_model_provider_id = overrides.get("compaction_model_provider_id", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.history_mode = overrides.get("history_mode", None)
    ch.trigger_heartbeat_before_compaction = overrides.get("trigger_heartbeat_before_compaction", None)
    ch.memory_flush_enabled = overrides.get("memory_flush_enabled", None)
    ch.memory_flush_model = overrides.get("memory_flush_model", None)
    ch.memory_flush_model_provider_id = overrides.get("memory_flush_model_provider_id", None)
    ch.memory_flush_prompt = overrides.get("memory_flush_prompt", None)
    ch.memory_flush_prompt_template_id = overrides.get("memory_flush_prompt_template_id", None)
    ch.memory_flush_workspace_file_path = overrides.get("memory_flush_workspace_file_path", None)
    ch.memory_flush_workspace_id = overrides.get("memory_flush_workspace_id", None)
    return ch


class TestMaintenanceToolSurfaces:
    @pytest.mark.asyncio
    async def test_memory_hygiene_surface_is_metadata_selected_without_semantic_retrieval(self):
        from app.agent.context_assembly import (
            AssemblyLedger,
            AssemblyStageState,
            _run_tool_retrieval,
        )

        def schema(name: str) -> dict:
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        by_capability = {
            "memory.read": [schema("get_memory_file")],
            "memory.write": [schema("memory")],
            "workspace_memory.write": [schema("file")],
            "conversation_history.read": [schema("read_conversation_history")],
            "subsessions.read": [schema("list_sub_sessions"), schema("read_sub_session")],
            "skill.write": [schema("manage_bot_skill")],
        }

        def schemas_by_metadata(*, capability=None, **kwargs):
            return list(by_capability.get(capability, []))

        def names_by_metadata(*, capability=None, **kwargs):
            return [
                item["function"]["name"]
                for item in by_capability.get(capability, [])
            ]

        bot = _make_bot(id="", tool_retrieval=False, local_tools=[])
        state = AssemblyStageState()
        retrieve_tools = AsyncMock(return_value=([schema("web_search")], 0.9, []))

        with (
            patch(
                "app.agent.context_assembly._all_tool_schemas_by_name",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.agent.context_assembly.get_local_tool_schemas_by_metadata",
                side_effect=schemas_by_metadata,
            ),
            patch(
                "app.agent.context_assembly.get_local_tool_names_by_metadata",
                side_effect=names_by_metadata,
            ),
            patch("app.agent.context_assembly.retrieve_tools", retrieve_tools),
        ):
            events = [
                event async for event in _run_tool_retrieval(
                    messages=[],
                    bot=bot,
                    user_message="scheduled hygiene",
                    ch_row=None,
                    state=state,
                    correlation_id=None,
                    session_id=None,
                    client_id=None,
                    context_profile=SimpleNamespace(name="memory_hygiene"),
                    tool_surface_policy="strict",
                    required_tool_names=None,
                    ledger=AssemblyLedger(),
                )
            ]

        exposed_names = {
            tool["function"]["name"] for tool in (state.pre_selected_tools or [])
        }
        assert {
            "get_memory_file",
            "memory",
            "file",
            "read_conversation_history",
            "list_sub_sessions",
            "read_sub_session",
            "manage_bot_skill",
        }.issubset(exposed_names)
        assert "web_search" not in exposed_names
        assert state.authorized_names == exposed_names
        assert state.tool_discovery_info["tool_surface"] == "memory_hygiene"
        assert state.tool_discovery_info["tool_retrieval_enabled"] is False
        assert events == []
        retrieve_tools.assert_not_awaited()


# ===================================================================
# Memory flush resolution tests
# ===================================================================

class TestMemoryFlushResolution:

    def test_resolve_memory_flush_enabled_channel_override(self):
        from app.services.compaction import _resolve_memory_flush_enabled
        bot = _make_bot()
        ch = _make_channel(memory_flush_enabled=True)
        assert _resolve_memory_flush_enabled(bot, ch) is True

    def test_resolve_memory_flush_disabled_channel_override(self):
        from app.services.compaction import _resolve_memory_flush_enabled
        bot = _make_bot()
        ch = _make_channel(memory_flush_enabled=False)
        assert _resolve_memory_flush_enabled(bot, ch) is False

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_global_default(self, mock_settings):
        from app.services.compaction import _resolve_memory_flush_enabled
        mock_settings.MEMORY_FLUSH_ENABLED = True
        bot = _make_bot()
        ch = _make_channel(memory_flush_enabled=None)
        assert _resolve_memory_flush_enabled(bot, ch) is True

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_no_channel(self, mock_settings):
        from app.services.compaction import _resolve_memory_flush_enabled
        mock_settings.MEMORY_FLUSH_ENABLED = False
        bot = _make_bot()
        assert _resolve_memory_flush_enabled(bot, None) is False

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_auto_enable_workspace_files(self, mock_settings):
        """workspace-files bots get memory flush auto-enabled."""
        from app.services.compaction import _resolve_memory_flush_enabled
        mock_settings.MEMORY_FLUSH_ENABLED = False
        bot = _make_bot(memory_scheme="workspace-files")
        ch = _make_channel(memory_flush_enabled=None)
        assert _resolve_memory_flush_enabled(bot, ch) is True

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_auto_enable_no_channel(self, mock_settings):
        """workspace-files auto-enable works even without a channel object."""
        from app.services.compaction import _resolve_memory_flush_enabled
        mock_settings.MEMORY_FLUSH_ENABLED = False
        bot = _make_bot(memory_scheme="workspace-files")
        assert _resolve_memory_flush_enabled(bot, None) is True

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_channel_override_beats_auto_enable(self, mock_settings):
        """Channel-level disable overrides workspace-files auto-enable."""
        from app.services.compaction import _resolve_memory_flush_enabled
        mock_settings.MEMORY_FLUSH_ENABLED = False
        bot = _make_bot(memory_scheme="workspace-files")
        ch = _make_channel(memory_flush_enabled=False)
        assert _resolve_memory_flush_enabled(bot, ch) is False

    def test_resolve_memory_flush_model_channel_override(self):
        from app.services.compaction import _get_memory_flush_model
        bot = _make_bot()
        ch = _make_channel(memory_flush_model="claude-3-opus")
        assert _get_memory_flush_model(bot, ch) == "claude-3-opus"

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_model_global(self, mock_settings):
        from app.services.compaction import _get_memory_flush_model
        mock_settings.MEMORY_FLUSH_MODEL = "gemini/gemini-2.5-flash"
        bot = _make_bot()
        ch = _make_channel(memory_flush_model=None)
        assert _get_memory_flush_model(bot, ch) == "gemini/gemini-2.5-flash"

    @patch("app.services.compaction.settings")
    def test_resolve_memory_flush_model_falls_back_to_bot(self, mock_settings):
        from app.services.compaction import _get_memory_flush_model
        mock_settings.MEMORY_FLUSH_MODEL = ""
        bot = _make_bot(model="gpt-4o")
        ch = _make_channel(memory_flush_model=None)
        assert _get_memory_flush_model(bot, ch) == "gpt-4o"


# ===================================================================
# Embedding cache tests
# ===================================================================

class TestEmbeddingCache:

    def test_clear_embed_cache(self):
        from app.agent.embeddings import clear_embed_cache, _get_cache
        clear_embed_cache()
        cache = _get_cache()
        assert cache == {}

    def test_get_cache_creates_new(self):
        from app.agent.embeddings import _embed_cache, _get_cache
        # Reset to ensure no existing cache
        try:
            _embed_cache.set({})
        except Exception:
            pass
        cache = _get_cache()
        assert isinstance(cache, dict)

    @pytest.mark.asyncio
    async def test_embed_text_caches_results(self):
        from app.agent.embeddings import embed_text, clear_embed_cache

        clear_embed_cache()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        with patch("app.agent.embeddings._client") as mock_client:
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)

            # First call — hits API
            result1 = await embed_text("hello world")
            assert result1 == [0.1, 0.2, 0.3]
            assert mock_client.embeddings.create.call_count == 1

            # Second identical call — should hit cache
            result2 = await embed_text("hello world")
            assert result2 == [0.1, 0.2, 0.3]
            assert mock_client.embeddings.create.call_count == 1  # no extra API call

    @pytest.mark.asyncio
    async def test_embed_text_different_texts_not_cached(self):
        from app.agent.embeddings import embed_text, clear_embed_cache

        clear_embed_cache()
        mock_response_1 = MagicMock()
        mock_response_1.data = [MagicMock(embedding=[0.1, 0.2])]
        mock_response_2 = MagicMock()
        mock_response_2.data = [MagicMock(embedding=[0.3, 0.4])]

        with patch("app.agent.embeddings._client") as mock_client:
            mock_client.embeddings.create = AsyncMock(
                side_effect=[mock_response_1, mock_response_2]
            )

            result1 = await embed_text("hello")
            result2 = await embed_text("world")
            assert result1 == [0.1, 0.2]
            assert result2 == [0.3, 0.4]
            assert mock_client.embeddings.create.call_count == 2


# ===================================================================
# Tool context in compaction summaries
# ===================================================================

class TestToolContextInSummaries:

    def test_assistant_tool_calls_included(self):
        from app.services.compaction import _messages_for_summary

        messages = [
            {"role": "user", "content": "Search for cats"},
            {
                "role": "assistant",
                "content": "Let me search for you.",
                "tool_calls": [
                    {"function": {"name": "web_search", "arguments": '{"q":"cats"}'}},
                ],
            },
            {"role": "tool", "content": "Found 10 results about cats", "name": "web_search"},
            {"role": "assistant", "content": "I found 10 results about cats."},
        ]
        result = _messages_for_summary(messages)

        # Should have 4 entries: user, assistant+tool, tool result, assistant
        assert len(result) == 4
        assert result[0]["content"] == "Search for cats"
        assert "[Used tools: web_search]" in result[1]["content"]
        assert "Let me search for you." in result[1]["content"]
        assert "[Tool result from web_search:" in result[2]["content"]
        assert result[3]["content"] == "I found 10 results about cats."

    def test_assistant_only_tool_calls_no_content(self):
        from app.services.compaction import _messages_for_summary

        messages = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "save_memory", "arguments": "{}"}},
                ],
            },
        ]
        result = _messages_for_summary(messages)
        assert len(result) == 2
        assert "[Used tools: save_memory]" in result[1]["content"]

    def test_tool_result_truncated_at_200_chars(self):
        from app.services.compaction import _messages_for_summary

        long_result = "x" * 500
        messages = [
            {"role": "user", "content": "run it"},
            {"role": "tool", "content": long_result, "name": "exec"},
        ]
        result = _messages_for_summary(messages)
        tool_msg = result[1]
        assert "..." in tool_msg["content"]
        # The truncated content should be around 200 chars
        assert len(tool_msg["content"]) < 250

    def test_passive_messages_still_excluded(self):
        from app.services.compaction import _messages_for_summary

        messages = [
            {"role": "user", "content": "Hey from bob", "_metadata": {"passive": True, "sender_id": "bob"}},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = _messages_for_summary(messages)
        # Passive goes into system context, active stays
        assert result[0]["role"] == "system"
        assert "bob" in result[0]["content"]
        assert result[1]["content"] == "Hello"
        assert result[2]["content"] == "Hi!"


# ===================================================================
# Head+tail truncation for tool result summarization
# ===================================================================

class TestHeadTailTruncation:

    @pytest.mark.asyncio
    async def test_short_content_not_truncated(self):
        from app.agent.llm import _summarize_tool_result

        short = "hello world"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="summary"))]

        with patch("app.services.providers.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_client

            result = await _summarize_tool_result("test", short, "model", 300)
            # Check the prompt sent to the LLM contains the full content
            call_args = mock_client.chat.completions.create.call_args
            prompt = call_args.kwargs["messages"][0]["content"]
            assert "hello world" in prompt
            assert "chars omitted" not in prompt

    @pytest.mark.asyncio
    async def test_long_content_uses_head_tail(self):
        from app.agent.llm import _summarize_tool_result

        # Create content larger than 12000 chars
        long_content = "HEAD" * 2500 + "MIDDLE" * 2000 + "TAIL" * 1500
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="summary"))]

        with patch("app.services.providers.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_client

            result = await _summarize_tool_result("test", long_content, "model", 300)
            call_args = mock_client.chat.completions.create.call_args
            prompt = call_args.kwargs["messages"][0]["content"]
            assert "chars omitted" in prompt
            # Should contain beginning and end
            assert "HEAD" in prompt
            assert "TAIL" in prompt


# ===================================================================
# Server settings schema validity for new settings
# ===================================================================

class TestMemoryFlushServerSettings:

    def test_memory_flush_settings_in_schema(self):
        from app.services.server_settings import SETTINGS_SCHEMA
        from app.config import Settings

        for key in ["MEMORY_FLUSH_ENABLED", "MEMORY_FLUSH_MODEL", "MEMORY_FLUSH_DEFAULT_PROMPT", "PREVIOUS_SUMMARY_INJECT_CHARS"]:
            assert key in SETTINGS_SCHEMA, f"{key} not in SETTINGS_SCHEMA"
            assert key in Settings.model_fields, f"{key} not in Settings"

    def test_memory_flush_settings_group(self):
        from app.services.server_settings import SETTINGS_SCHEMA

        for key in ["MEMORY_FLUSH_ENABLED", "MEMORY_FLUSH_MODEL", "MEMORY_FLUSH_DEFAULT_PROMPT", "PREVIOUS_SUMMARY_INJECT_CHARS"]:
            assert SETTINGS_SCHEMA[key]["group"] == "Memory & Learning"


# ===================================================================
# Sentence-boundary truncation
# ===================================================================

class TestTruncateAtSentence:

    def test_short_text_unchanged(self):
        from app.services.compaction import _truncate_at_sentence
        assert _truncate_at_sentence("Hello world.", 100) == "Hello world."

    def test_truncates_at_period(self):
        from app.services.compaction import _truncate_at_sentence
        text = "First sentence. Second sentence. Third sentence that goes on and on."
        result = _truncate_at_sentence(text, 35)
        assert result == "First sentence. Second sentence."

    def test_truncates_at_exclamation(self):
        from app.services.compaction import _truncate_at_sentence
        text = "Wow! That is amazing! Something else entirely here."
        result = _truncate_at_sentence(text, 25)
        assert result == "Wow! That is amazing!"

    def test_truncates_at_question_mark(self):
        from app.services.compaction import _truncate_at_sentence
        text = "Is it good? I think so. More stuff."
        result = _truncate_at_sentence(text, 15)
        assert result == "Is it good?"

    def test_no_sentence_boundary_falls_back(self):
        from app.services.compaction import _truncate_at_sentence
        text = "A very long word without any punctuation at all"
        result = _truncate_at_sentence(text, 20)
        assert result == "A very long word wit\u2026"
        assert len(result) <= 21  # 20 chars + ellipsis

    def test_heartbeat_version_matches(self):
        from app.services.heartbeat import _truncate_at_sentence
        text = "First sentence. Second sentence. Third long one."
        result = _truncate_at_sentence(text, 35)
        assert result == "First sentence. Second sentence."

    def test_heartbeat_previous_conclusion_chars_in_schema(self):
        from app.services.server_settings import SETTINGS_SCHEMA
        from app.config import Settings
        assert "HEARTBEAT_PREVIOUS_CONCLUSION_CHARS" in SETTINGS_SCHEMA
        assert "HEARTBEAT_PREVIOUS_CONCLUSION_CHARS" in Settings.model_fields
        assert SETTINGS_SCHEMA["HEARTBEAT_PREVIOUS_CONCLUSION_CHARS"]["group"] == "Heartbeat"

    def test_legacy_trigger_heartbeat_removed_from_schema(self):
        from app.services.server_settings import SETTINGS_SCHEMA
        assert "TRIGGER_HEARTBEAT_BEFORE_COMPACTION" not in SETTINGS_SCHEMA


# ===================================================================
# Memory flush provider_id resolution
# ===================================================================

class TestRunMemoryFlushProviderId:
    """`_run_memory_flush` must resolve provider_id from the chosen model
    when no explicit channel override is set, instead of blindly inheriting
    `bot.model_provider_id`.

    Surfaced 2026-04-11 by the correlation_id contamination investigation:
    a `gemini-2.5-flash-lite` memory-flush model paired with `mini-max` (the
    bot's native provider) produced nonsense `model @ provider` rows in
    `usage_logs`, breaking cost attribution and provider-level metrics.
    """

    def _stub_db_session(self, mock_session_factory, channel_id):
        """Wire async_session() → AsyncMock context manager with a stubbed db.get."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=MagicMock(summary=None, channel_id=channel_id))
        mock_db.execute = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        return mock_db

    @pytest.mark.asyncio
    async def test_resolves_provider_from_settings_when_no_channel_override(self):
        from app.services import compaction
        # memory_scheme="workspace-files" makes the function take the static-prompt
        # branch and skip resolve_prompt entirely — keeps the test focused on the
        # provider resolution arm.
        bot = _make_bot(model_provider_id="mini-max", memory_scheme="workspace-files")
        ch = _make_channel(memory_flush_enabled=True, memory_flush_model_provider_id=None)

        with patch.object(compaction, "_get_memory_flush_model", return_value="gemini-2.5-flash-lite"), \
             patch("app.services.compaction.settings") as mock_settings, \
             patch("app.services.compaction.async_session") as mock_session_factory, \
             patch("app.agent.loop.run", new=AsyncMock()) as mock_run:
            mock_settings.MEMORY_FLUSH_MODEL_PROVIDER_ID = "gemini"
            mock_settings.MEMORY_SCHEME_FLUSH_PROMPT = ""
            mock_settings.PREVIOUS_SUMMARY_INJECT_CHARS = 500
            self._stub_db_session(mock_session_factory, ch.id)
            mock_run.return_value = MagicMock(response="ok")

            await compaction._run_memory_flush(
                channel=ch,
                bot=bot,
                session_id=uuid.uuid4(),
                messages=[{"role": "user", "content": "hi"}],
                correlation_id=uuid.uuid4(),
            )

            assert mock_run.await_count == 1
            kwargs = mock_run.await_args.kwargs
            assert kwargs["model_override"] == "gemini-2.5-flash-lite"
            assert kwargs["provider_id_override"] == "gemini", (
                "Provider must come from MEMORY_FLUSH_MODEL_PROVIDER_ID setting, not "
                f"bot.model_provider_id (mini-max). Got: {kwargs['provider_id_override']}"
            )

    @pytest.mark.asyncio
    async def test_resolves_provider_from_selected_model_when_no_explicit_override(self):
        from app.services import compaction
        bot = _make_bot(model_provider_id="mini-max", memory_scheme="workspace-files")
        ch = _make_channel(memory_flush_enabled=True, memory_flush_model_provider_id=None)

        with patch.object(compaction, "_get_memory_flush_model", return_value="gpt-5.3-codex-spark"), \
             patch("app.services.compaction.settings") as mock_settings, \
             patch("app.services.providers.resolve_provider_for_model", return_value="chatgpt-subscription") as mock_resolve, \
             patch("app.services.compaction.async_session") as mock_session_factory, \
             patch("app.agent.loop.run", new=AsyncMock()) as mock_run:
            mock_settings.MEMORY_FLUSH_MODEL_PROVIDER_ID = ""
            mock_settings.MEMORY_SCHEME_FLUSH_PROMPT = ""
            mock_settings.PREVIOUS_SUMMARY_INJECT_CHARS = 500
            self._stub_db_session(mock_session_factory, ch.id)
            mock_run.return_value = MagicMock(response="ok")

            await compaction._run_memory_flush(
                channel=ch,
                bot=bot,
                session_id=uuid.uuid4(),
                messages=[{"role": "user", "content": "hi"}],
                correlation_id=uuid.uuid4(),
            )

            mock_resolve.assert_called_once_with("gpt-5.3-codex-spark")
            kwargs = mock_run.await_args.kwargs
            assert kwargs["provider_id_override"] == "chatgpt-subscription"

    @pytest.mark.asyncio
    async def test_channel_override_wins_over_model_resolution(self):
        from app.services import compaction
        bot = _make_bot(model_provider_id="mini-max", memory_scheme="workspace-files")
        ch = _make_channel(
            memory_flush_enabled=True,
            memory_flush_model_provider_id="explicit-override",
        )

        with patch.object(compaction, "_get_memory_flush_model", return_value="gemini-2.5-flash-lite"), \
             patch("app.services.providers.resolve_provider_for_model", return_value="gemini") as mock_resolve, \
             patch("app.services.compaction.async_session") as mock_session_factory, \
             patch("app.agent.loop.run", new=AsyncMock()) as mock_run:
            self._stub_db_session(mock_session_factory, ch.id)
            mock_run.return_value = MagicMock(response="ok")

            await compaction._run_memory_flush(
                channel=ch,
                bot=bot,
                session_id=uuid.uuid4(),
                messages=[{"role": "user", "content": "hi"}],
                correlation_id=uuid.uuid4(),
            )

            # Channel override is truthy → short-circuits the resolver call.
            mock_resolve.assert_not_called()
            kwargs = mock_run.await_args.kwargs
            assert kwargs["provider_id_override"] == "explicit-override"

    @pytest.mark.asyncio
    async def test_falls_back_to_bot_provider_when_resolver_returns_none(self):
        from app.services import compaction
        bot = _make_bot(model_provider_id="mini-max", memory_scheme="workspace-files")
        ch = _make_channel(memory_flush_enabled=True, memory_flush_model_provider_id=None)

        with patch.object(compaction, "_get_memory_flush_model", return_value="custom-unknown-model"), \
             patch("app.services.providers.resolve_provider_for_model", return_value=None), \
             patch("app.services.compaction.async_session") as mock_session_factory, \
             patch("app.agent.loop.run", new=AsyncMock()) as mock_run:
            self._stub_db_session(mock_session_factory, ch.id)
            mock_run.return_value = MagicMock(response="ok")

            await compaction._run_memory_flush(
                channel=ch,
                bot=bot,
                session_id=uuid.uuid4(),
                messages=[{"role": "user", "content": "hi"}],
                correlation_id=uuid.uuid4(),
            )

            kwargs = mock_run.await_args.kwargs
            assert kwargs["provider_id_override"] == "mini-max", (
                "When the resolver can't map the model, fall back to the bot's "
                "native provider rather than passing None."
            )


class TestCompactionProviderResolution:
    def test_resolves_provider_from_selected_compaction_model(self):
        from app.services import compaction

        bot = _make_bot(
            model="gpt-5.4",
            model_provider_id="chatgpt-subscription",
            compaction_model=None,
            compaction_model_provider_id=None,
        )
        ch = _make_channel(compaction_model="gpt-5.3-codex-spark")

        with patch("app.services.providers.resolve_provider_for_model", return_value="codex-provider") as mock_resolve:
            provider = compaction._get_compaction_provider(bot, ch)

        mock_resolve.assert_called_once_with("gpt-5.3-codex-spark")
        assert provider == "codex-provider"

    def test_explicit_compaction_provider_wins(self):
        from app.services import compaction

        bot = _make_bot(model_provider_id="chatgpt-subscription")
        ch = _make_channel(
            compaction_model="gpt-5.3-codex-spark",
            compaction_model_provider_id="explicit-provider",
        )

        with patch("app.services.providers.resolve_provider_for_model") as mock_resolve:
            provider = compaction._get_compaction_provider(bot, ch)

        mock_resolve.assert_not_called()
        assert provider == "explicit-provider"
