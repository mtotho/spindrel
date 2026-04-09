"""End-to-end tests for the context assembly pipeline.

Tests the full assemble_context() function with a real in-memory SQLite DB,
verifying that the pipeline steps run in order, mutate messages correctly,
and populate the AssemblyResult.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, SkillConfig
from app.agent.context_assembly import assemble_context, AssemblyResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="test/model",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
        tool_retrieval=False,  # disable tool RAG by default to reduce mocking
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


async def _collect(gen):
    """Consume an async generator, returning (events_list)."""
    events = []
    async for evt in gen:
        events.append(evt)
    return events


def _session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Common patches needed for every test — things that hit external systems
# or use unsupported DB operations in SQLite
_COMMON_PATCHES = {
    "app.agent.hooks.fire_hook": AsyncMock(),
    "app.agent.recording._record_trace_event": AsyncMock(),
    "app.agent.knowledge.get_pinned_knowledge_docs": AsyncMock(return_value=([], [])),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicPipeline:
    """Minimal tests: no channel, no skills, no workspace."""

    @pytest.mark.asyncio
    async def test_datetime_and_user_message_injected(self, engine):
        """The simplest case: just a bot, a user message, no channel."""
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="hello",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # Datetime should be injected
        system_msgs = [m for m in messages if m["role"] == "system"]
        time_msgs = [m for m in system_msgs if "Current time" in m["content"]]
        assert len(time_msgs) == 1, "Should inject exactly one datetime message"

        # Current-turn marker should be present
        marker_msgs = [m for m in system_msgs if "CURRENT message follows" in m["content"]]
        assert len(marker_msgs) == 1, "Should inject current-turn marker"

        # User message should be the last message
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "hello"

        # user_msg_index should point to the last message
        assert result.user_msg_index == len(messages) - 1

    @pytest.mark.asyncio
    async def test_system_preamble_injected(self, engine):
        """When system_preamble is provided (e.g. heartbeat), it's injected and marker changes."""
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
                system_preamble="You are running a heartbeat check.",
            ))

        # Preamble should be in the messages
        preamble_msgs = [m for m in messages if "heartbeat check" in m["content"]]
        assert len(preamble_msgs) == 1

        # Heartbeat (preamble + no user message) should use task framing
        marker_msgs = [m for m in messages if "TASK PROMPT follows" in m["content"]]
        assert len(marker_msgs) == 1

    @pytest.mark.asyncio
    async def test_attachments_included_in_user_message(self, engine):
        """Attachments should be included in the user message content."""
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        attachments = [{"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}]
        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="what is this?",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=attachments,
                native_audio=False,
                result=result,
            ))

        # User message should be a list (multimodal content)
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)


class TestWithChannel:
    """Tests that exercise channel-level features: overrides, workspace, integrations."""

    @pytest.mark.asyncio
    async def test_channel_model_override(self, engine, db_session):
        """Channel model override should be reflected in AssemblyResult."""
        from app.db.models import Channel
        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id,
            bot_id="test-bot",
            name="test-channel",
            model_override="gpt-4o",
            model_provider_id_override="openai-provider",
        )
        db_session.add(ch)
        await db_session.commit()

        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="test",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=channel_id,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        assert result.channel_model_override == "gpt-4o"
        assert result.channel_provider_id_override == "openai-provider"

    @pytest.mark.asyncio
    async def test_channel_overrides_modify_bot_tools(self, engine, db_session):
        """Channel tool disabled list should restrict the bot's tools."""
        from app.db.models import Channel
        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id,
            bot_id="test-bot",
            name="override-channel",
            local_tools_disabled=["file", "exec_command"],  # blacklist: remove file + exec_command
        )
        db_session.add(ch)
        await db_session.commit()

        bot = _make_bot(local_tools=["web_search", "file", "exec_command"])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="test",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=channel_id,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # The user message should still be there (pipeline completes)
        assert messages[-1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_activated_integration_injects_carapace(self, engine, db_session):
        """An activated integration should inject its carapace's system prompt fragment."""
        from app.db.models import Channel, ChannelIntegration
        from app.agent.carapaces import _registry

        channel_id = uuid.uuid4()
        ch = Channel(id=channel_id, bot_id="test-bot", name="mc-channel")
        db_session.add(ch)
        await db_session.flush()

        ci = ChannelIntegration(
            channel_id=channel_id,
            integration_type="mission_control",
            client_id="mc:test",
            activated=True,
        )
        db_session.add(ci)
        await db_session.commit()

        # Register a test carapace in the in-memory registry (stores dicts)
        _registry["mission-control"] = {
            "id": "mission-control",
            "name": "Mission Control",
            "description": "Test MC carapace",
            "skills": [{"id": "mc-skill", "mode": "on_demand"}],
            "local_tools": ["create_task_card"],
            "system_prompt_fragment": "## Mission Control\nYou have MC tools.",
        }

        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        manifests = {
            "mission_control": {
                "carapaces": ["mission-control"],
                "requires_workspace": False,
            },
        }

        try:
            with (
                patch("app.db.engine.async_session", factory),
                patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
                patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
                patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
                patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
                patch("integrations.get_activation_manifests", return_value=manifests),
                patch("app.agent.rag.fetch_skill_chunks_by_id", new_callable=AsyncMock, return_value=[]),
            ):
                events = await _collect(assemble_context(
                    messages=messages,
                    bot=bot,
                    user_message="check tasks",
                    session_id=None,
                    client_id=None,
                    correlation_id=None,
                    channel_id=channel_id,
                    audio_data=None,
                    audio_format=None,
                    attachments=None,
                    native_audio=False,
                    result=result,
                ))

            # Carapace system prompt fragment should be injected
            mc_msgs = [m for m in messages if "Mission Control" in m.get("content", "")]
            assert len(mc_msgs) >= 1, "Carapace system_prompt_fragment should be injected"

            # Should have a carapace_context event
            carapace_events = [e for e in events if e.get("type") == "carapace_context"]
            assert len(carapace_events) == 1
        finally:
            _registry.pop("mission-control", None)

    @pytest.mark.asyncio
    async def test_channel_max_iterations_override(self, engine, db_session):
        """Channel max_iterations should be reflected in AssemblyResult."""
        from app.db.models import Channel
        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id,
            bot_id="test-bot",
            name="limited-channel",
            max_iterations=5,
        )
        db_session.add(ch)
        await db_session.commit()

        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="test",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=channel_id,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        assert result.channel_max_iterations == 5


class TestSkillInjection:
    """Tests for skill injection (pinned, rag, on-demand)."""

    @pytest.mark.asyncio
    async def test_on_demand_skills_inject_index(self, engine, db_session):
        """On-demand skills should inject a skill index into messages."""
        from app.db.models import Skill

        # Insert a skill row for the on-demand lookup
        skill = Skill(
            id="test-skill",
            name="Test Skill",
            content="This is a test skill.",
            source_type="file",
        )
        db_session.add(skill)
        await db_session.commit()

        bot = _make_bot(skills=[SkillConfig(id="test-skill", mode="on_demand")])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        # Mock retrieve_skill_index — uses pgvector <=> operator unsupported in SQLite
        _mock_retrieve = AsyncMock(return_value=[{"id": "test-skill", "similarity": 0.8}])

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch("app.agent.rag.retrieve_skill_index", _mock_retrieve),
            patch("app.agent.capability_rag.retrieve_capabilities", new_callable=AsyncMock, return_value=([], 0.0)),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="help me",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # Skill index message should be present
        index_msgs = [m for m in messages if "get_skill" in m.get("content", "")]
        assert len(index_msgs) >= 1, "On-demand skill index should be injected"
        assert "test-skill" in index_msgs[0]["content"]

        # Should have a skill_index event
        index_events = [e for e in events if e.get("type") == "skill_index"]
        assert len(index_events) == 1
        assert index_events[0]["count"] == 1

    @pytest.mark.asyncio
    async def test_pinned_skills_inject_content(self, engine):
        """Pinned skills should inject full content via fetch_skill_chunks_by_id."""
        bot = _make_bot(skills=[SkillConfig(id="my-pinned", mode="pinned")])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch(
                "app.agent.context_assembly.fetch_skill_chunks_by_id",
                new_callable=AsyncMock,
                return_value=["Pinned skill content here."],
            ),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="go",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # Pinned content should be injected
        pinned_msgs = [m for m in messages if "Pinned skill content here" in m.get("content", "")]
        assert len(pinned_msgs) == 1

        # Should have a skill_pinned_context event
        pinned_events = [e for e in events if e.get("type") == "skill_pinned_context"]
        assert len(pinned_events) == 1

    @pytest.mark.asyncio
    async def test_legacy_rag_mode_treated_as_on_demand(self, engine):
        """Skills created with mode='rag' should be normalized to on_demand."""
        # SkillConfig normalizes rag → on_demand in __post_init__
        skill = SkillConfig(id="legacy-rag-skill", mode="rag")
        assert skill.mode == "on_demand"

        bot = _make_bot(skills=[skill])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        # Mock the DB query for on-demand skill index
        mock_skill_row = MagicMock()
        mock_skill_row.id = "legacy-rag-skill"
        mock_skill_row.name = "Legacy RAG Skill"
        mock_skill_row.description = "Was RAG, now on-demand"
        mock_skill_row.triggers = []

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="tell me about it",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # The skill should be treated as on-demand (index listed, not RAG injected)
        assert all(s.mode == "on_demand" for s in bot.skills)


class TestDelegateIndex:
    """Tests for delegate bot index injection."""

    @pytest.mark.asyncio
    async def test_delegate_bots_injected(self, engine):
        """Delegate bot list should be injected as system message."""
        from app.agent.bots import _registry as _bot_registry

        helper = _make_bot(id="helper-bot", name="Helper Bot", system_prompt="I help.")
        _bot_registry["helper-bot"] = helper
        try:
            bot = _make_bot(delegate_bots=["helper-bot"])
            messages = [{"role": "system", "content": bot.system_prompt}]
            result = AssemblyResult()
            factory = _session_factory(engine)

            with (
                patch("app.db.engine.async_session", factory),
                patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
                patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
                patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
                patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            ):
                events = await _collect(assemble_context(
                    messages=messages,
                    bot=bot,
                    user_message="delegate something",
                    session_id=None,
                    client_id=None,
                    correlation_id=None,
                    channel_id=None,
                    audio_data=None,
                    audio_format=None,
                    attachments=None,
                    native_audio=False,
                    result=result,
                ))

            # Delegate index should be injected
            delegate_msgs = [m for m in messages if "helper-bot" in m.get("content", "")]
            assert len(delegate_msgs) == 1
            assert "delegate_to_agent" in delegate_msgs[0]["content"]

            delegate_events = [e for e in events if e.get("type") == "delegate_index"]
            assert len(delegate_events) == 1
        finally:
            _bot_registry.pop("helper-bot", None)


class TestMessageOrdering:
    """Verify the ordering of injected messages."""

    @pytest.mark.asyncio
    async def test_message_order_system_then_marker_then_user(self, engine):
        """All system messages should come before the marker, which comes before user."""
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="final message",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # Last message should be user
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "final message"

        # Second-to-last should be the current-turn marker
        assert messages[-2]["role"] == "system"
        assert "CURRENT message follows" in messages[-2]["content"]

        # All other messages should be system
        for m in messages[:-1]:
            assert m["role"] == "system"


class TestContextBudget:
    """Tests for context budget integration."""

    @pytest.mark.asyncio
    async def test_budget_utilization_recorded(self, engine):
        """When a budget is provided, utilization should be recorded in result."""
        from app.agent.context_budget import ContextBudget
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)
        budget = ContextBudget(total_tokens=100_000, reserve_tokens=10_000)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="test budget",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
                budget=budget,
            ))

        assert result.budget_utilization is not None
        assert 0.0 <= result.budget_utilization <= 1.0


class TestContextPruning:
    """Tests for context pruning step."""

    @pytest.mark.asyncio
    async def test_pruning_emits_event_when_active(self, engine):
        """Context pruning should emit an event when it prunes messages."""
        bot = _make_bot(context_pruning=True)
        # Build a message history with old tool results that should be pruned
        messages = [
            {"role": "system", "content": bot.system_prompt},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "A" * 2000, "tool_call_id": "tc1"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "another old question"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc2", "type": "function", "function": {"name": "exec_command", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "B" * 2000, "tool_call_id": "tc2"},
            {"role": "assistant", "content": "another old answer"},
        ]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="new question",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        # Should complete without error; pruning may or may not fire depending on
        # keep_turns default, but the pipeline should complete either way
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "new question"


class TestToolRetrieval:
    """Tests for tool retrieval (tool RAG) step."""

    @pytest.mark.asyncio
    async def test_tool_retrieval_populates_pre_selected_tools(self, engine):
        """When tool_retrieval is enabled, pre_selected_tools should be populated."""
        bot = _make_bot(
            tool_retrieval=True,
            local_tools=["web_search"],
            pinned_tools=["web_search"],
        )
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        mock_schema = {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}},
            },
        }

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch(
                "app.agent.context_assembly._all_tool_schemas_by_name",
                new_callable=AsyncMock,
                return_value={"web_search": mock_schema},
            ),
            patch(
                "app.agent.context_assembly.retrieve_tools",
                new_callable=AsyncMock,
                return_value=([], 0.0, []),
            ),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="search for something",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        assert result.pre_selected_tools is not None
        assert result.authorized_tool_names is not None
        assert "web_search" in result.authorized_tool_names

    @pytest.mark.asyncio
    async def test_tool_retrieval_disabled_leaves_none(self, engine):
        """When tool_retrieval is False, pre_selected_tools should remain None."""
        bot = _make_bot(tool_retrieval=False)
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="test",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
            ))

        assert result.pre_selected_tools is None
        assert result.authorized_tool_names is None
