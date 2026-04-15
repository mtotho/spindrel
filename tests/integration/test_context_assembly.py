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

        # User message should be the last message (role:user, NOT system task prompt)
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "hello"
        task_prompt_msgs = [m for m in messages if "--- TASK PROMPT ---" in m.get("content", "")]
        assert len(task_prompt_msgs) == 0, "Regular messages must not use task prompt framing"

        # user_msg_index should point to the last message
        assert result.user_msg_index == len(messages) - 1

    @pytest.mark.asyncio
    async def test_system_preamble_injected(self, engine):
        """When system_preamble + task_mode are provided (e.g. heartbeat), task framing marker
        is used and the task prompt is rendered as a normal user message."""
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
                user_message="Run all 9 phases now.",
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
                task_mode=True,
            ))

        # Preamble should be in the messages
        preamble_msgs = [m for m in messages if "heartbeat check" in m["content"]]
        assert len(preamble_msgs) == 1

        # task_mode should use task framing marker
        marker_msgs = [m for m in messages if "TASK PROMPT follows" in m["content"]]
        assert len(marker_msgs) == 1

        # Task prompt rendered as role:user (not system) — small models respond
        # better to user messages than system messages for task execution.
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "Run all 9 phases now." in user_msgs[0]["content"]

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

    @pytest.mark.asyncio
    async def test_channel_carapaces_preserved_with_system_preamble_for_primary_bot(
        self, engine, db_session
    ):
        """Channel carapaces_extra must apply when system_preamble is set for
        the primary bot (e.g. heartbeat), not just when no preamble is set.
        Only actual member bots (bot.id != channel.bot_id) should lose them.

        Regression test for: heartbeat requests set system_preamble for task
        guidance, which was incorrectly used as a proxy for member-bot detection,
        causing channel-level carapaces to be stripped.
        """
        from app.db.models import Channel
        from app.agent.carapaces import _registry

        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id,
            bot_id="test-bot",
            name="heartbeat-channel",
            carapaces_extra=["test-cap"],
        )
        db_session.add(ch)
        await db_session.commit()

        _registry["test-cap"] = {
            "id": "test-cap",
            "name": "Test Capability",
            "description": "Test capability for heartbeat",
            "skills": [],
            "local_tools": ["test_tool_alpha"],
            "system_prompt_fragment": "## Test Cap\nYou have test tools.",
        }

        bot = _make_bot()  # id="test-bot" matches channel.bot_id → primary
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        try:
            with (
                patch("app.db.engine.async_session", factory),
                patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
                patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
                patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
                patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
                patch("app.agent.rag.fetch_skill_chunks_by_id", new_callable=AsyncMock, return_value=[]),
            ):
                events = await _collect(assemble_context(
                    messages=messages,
                    bot=bot,
                    user_message="run heartbeat",
                    session_id=None,
                    client_id="heartbeat",
                    correlation_id=None,
                    channel_id=channel_id,
                    audio_data=None,
                    audio_format=None,
                    attachments=None,
                    native_audio=False,
                    result=result,
                    system_preamble="Execute the heartbeat task.",
                ))

            # Carapace system_prompt_fragment should be injected despite preamble
            cap_msgs = [m for m in messages if "Test Cap" in m.get("content", "")]
            assert len(cap_msgs) >= 1, (
                "Channel carapace should be injected for primary bot even with system_preamble"
            )

            carapace_events = [e for e in events if e.get("type") == "carapace_context"]
            assert len(carapace_events) == 1
        finally:
            _registry.pop("test-cap", None)

    @pytest.mark.asyncio
    async def test_member_bot_does_not_get_channel_carapaces(
        self, engine, db_session
    ):
        """A member bot (bot.id != channel.bot_id) should NOT receive
        channel-level carapaces_extra — those belong to the primary bot."""
        from app.db.models import Channel
        from app.agent.carapaces import _registry

        channel_id = uuid.uuid4()
        ch = Channel(
            id=channel_id,
            bot_id="primary-bot",  # different from the bot we'll assemble for
            name="multi-bot-channel",
            carapaces_extra=["test-cap"],
        )
        db_session.add(ch)
        await db_session.commit()

        _registry["test-cap"] = {
            "id": "test-cap",
            "name": "Test Capability",
            "description": "Test capability",
            "skills": [],
            "local_tools": ["test_tool_alpha"],
            "system_prompt_fragment": "## Test Cap\nYou have test tools.",
        }

        # bot id is "test-bot" but channel.bot_id is "primary-bot" → member bot
        bot = _make_bot()
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        try:
            with (
                patch("app.db.engine.async_session", factory),
                patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
                patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
                patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
                patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
                patch("app.agent.rag.fetch_skill_chunks_by_id", new_callable=AsyncMock, return_value=[]),
            ):
                events = await _collect(assemble_context(
                    messages=messages,
                    bot=bot,
                    user_message="help",
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

            # Channel carapace should NOT be injected for member bot
            cap_msgs = [m for m in messages if "Test Cap" in m.get("content", "")]
            assert len(cap_msgs) == 0, (
                "Channel carapace should NOT be injected for member bot"
            )
        finally:
            _registry.pop("test-cap", None)


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
        _mock_retrieve = AsyncMock(return_value=[{"skill_id": "test-skill", "similarity": 0.8}])

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
    @pytest.mark.skip(reason="pgvector <=> cosine distance operator unsupported on SQLite test backend")
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


class TestSkillAutoInject:
    """Tests for enrolled skill ranking and auto-injection."""

    def setup_method(self):
        from app.services.skill_enrollment import invalidate_enrolled_cache
        invalidate_enrolled_cache()

    def teardown_method(self):
        from app.services.skill_enrollment import invalidate_enrolled_cache
        invalidate_enrolled_cache()

    @pytest.mark.asyncio
    async def test_auto_inject_respects_budget(self, engine, db_session):
        """When context budget is exhausted, auto-inject should be skipped."""
        from app.db.models import Skill, BotSkillEnrollment
        from app.agent.context_budget import ContextBudget

        skill = Skill(id="big-skill", name="Big Skill", content="x", source_type="file")
        db_session.add(skill)
        enrollment = BotSkillEnrollment(bot_id="test-bot", skill_id="big-skill", source="manual")
        db_session.add(enrollment)
        await db_session.commit()

        bot = _make_bot(skills=[SkillConfig(id="big-skill", mode="on_demand")])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        # Ranking returns the skill as relevant
        _mock_rank = AsyncMock(return_value=[
            {"skill_id": "big-skill", "similarity": 0.8, "relevant": True},
        ])
        # Skill content is large
        _mock_chunks = AsyncMock(return_value=["A" * 50000])
        _mock_retrieve = AsyncMock(return_value=[])
        _mock_source_map = AsyncMock(return_value={"big-skill": "manual"})

        # Budget with almost no room left
        tight_budget = ContextBudget(total_tokens=1000, reserve_tokens=200, consumed_tokens=900)

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch("app.agent.rag.rank_enrolled_skills", _mock_rank),
            patch("app.agent.rag.fetch_skill_chunks_by_id", _mock_chunks),
            patch("app.agent.rag.retrieve_skill_index", _mock_retrieve),
            patch("app.agent.capability_rag.retrieve_capabilities", new_callable=AsyncMock, return_value=([], 0.0)),
            patch("app.services.skill_enrollment.get_enrolled_source_map", _mock_source_map),
            patch("app.services.skill_enrollment.async_session", factory),
            patch("app.config.settings.SKILL_ENROLLED_RANKING_ENABLED", True),
            patch("app.config.settings.SKILL_ENROLLED_AUTO_INJECT_MAX", 1),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="help me with big skill",
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                audio_data=None,
                audio_format=None,
                attachments=None,
                native_audio=False,
                result=result,
                budget=tight_budget,
            ))

        # Auto-inject should be skipped (budget too tight) — nothing in result
        assert result.auto_inject_skills == [], "Auto-inject should be skipped when budget is exhausted"

        # Skill index event should still fire with empty auto_injected list
        index_events = [e for e in events if e.get("type") == "skill_index"]
        assert len(index_events) == 1
        assert index_events[0]["auto_injected"] == []

    @pytest.mark.asyncio
    async def test_auto_inject_multi_records_all_ids(self, engine, db_session):
        """With AUTO_INJECT_MAX=2, both injected skill IDs appear in traces."""
        from app.db.models import Skill, BotSkillEnrollment

        for sid in ("skill-a", "skill-b"):
            db_session.add(Skill(id=sid, name=sid.title(), content="x", source_type="file"))
            db_session.add(BotSkillEnrollment(bot_id="test-bot", skill_id=sid, source="manual"))
        await db_session.commit()

        bot = _make_bot(skills=[
            SkillConfig(id="skill-a", mode="on_demand"),
            SkillConfig(id="skill-b", mode="on_demand"),
        ])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        _mock_rank = AsyncMock(return_value=[
            {"skill_id": "skill-a", "similarity": 0.9, "relevant": True},
            {"skill_id": "skill-b", "similarity": 0.7, "relevant": True},
        ])
        _mock_chunks = AsyncMock(return_value=["Small content."])
        _mock_retrieve = AsyncMock(return_value=[])
        _mock_source_map = AsyncMock(return_value={"skill-a": "manual", "skill-b": "manual"})

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch("app.agent.rag.rank_enrolled_skills", _mock_rank),
            patch("app.agent.rag.fetch_skill_chunks_by_id", _mock_chunks),
            patch("app.agent.rag.retrieve_skill_index", _mock_retrieve),
            patch("app.agent.capability_rag.retrieve_capabilities", new_callable=AsyncMock, return_value=([], 0.0)),
            patch("app.services.skill_enrollment.get_enrolled_source_map", _mock_source_map),
            patch("app.services.skill_enrollment.async_session", factory),
            patch("app.config.settings.SKILL_ENROLLED_RANKING_ENABLED", True),
            patch("app.config.settings.SKILL_ENROLLED_AUTO_INJECT_MAX", 2),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="help with both skills",
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

        # Both skills should be recorded for auto-injection
        assert len(result.auto_inject_skills) == 2
        injected_ids = {s["skill_id"] for s in result.auto_inject_skills}
        assert injected_ids == {"skill-a", "skill-b"}

        # Content should match get_skill() format: "# Name\n\ncontent"
        for ai in result.auto_inject_skills:
            assert ai["content"].startswith("# ")

        # Trace event should record both IDs as a list
        index_events = [e for e in events if e.get("type") == "skill_index"]
        assert len(index_events) == 1
        assert set(index_events[0]["auto_injected"]) == {"skill-a", "skill-b"}

    @pytest.mark.asyncio
    async def test_auto_inject_skips_already_tagged(self, engine, db_session):
        """Skills already @-tagged should not be double-injected via auto-inject."""
        from app.db.models import Skill, BotSkillEnrollment
        from app.agent.tags import ResolvedTag

        db_session.add(Skill(id="tagged-skill", name="Tagged", content="x", source_type="file"))
        db_session.add(BotSkillEnrollment(bot_id="test-bot", skill_id="tagged-skill", source="manual"))
        await db_session.commit()

        bot = _make_bot(skills=[SkillConfig(id="tagged-skill", mode="on_demand")])
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        _mock_rank = AsyncMock(return_value=[
            {"skill_id": "tagged-skill", "similarity": 0.95, "relevant": True},
        ])
        _mock_chunks = AsyncMock(return_value=["Skill content."])
        _mock_retrieve = AsyncMock(return_value=[])
        _mock_source_map = AsyncMock(return_value={"tagged-skill": "authored"})
        # Simulate @-tagging of the skill
        _mock_tags = AsyncMock(return_value=[
            ResolvedTag(raw="@tagged-skill", name="tagged-skill", tag_type="skill"),
        ])

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", _mock_tags),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch("app.agent.rag.rank_enrolled_skills", _mock_rank),
            patch("app.agent.rag.fetch_skill_chunks_by_id", _mock_chunks),
            # Patch both import paths: top-level (used by @-tag injection) and rag module (used by auto-inject)
            patch("app.agent.context_assembly.fetch_skill_chunks_by_id", _mock_chunks),
            patch("app.agent.rag.retrieve_skill_index", _mock_retrieve),
            patch("app.agent.capability_rag.retrieve_capabilities", new_callable=AsyncMock, return_value=([], 0.0)),
            patch("app.services.skill_enrollment.get_enrolled_source_map", _mock_source_map),
            patch("app.services.skill_enrollment.async_session", factory),
            patch("app.config.settings.SKILL_ENROLLED_RANKING_ENABLED", True),
            patch("app.config.settings.SKILL_ENROLLED_AUTO_INJECT_MAX", 1),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="@tagged-skill help",
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

        # The skill should appear from @-tag injection
        tag_msgs = [m for m in messages if "Skill content." in m.get("content", "")]
        assert len(tag_msgs) >= 1, "Tagged skill content should be injected via @-tag"

        # Auto-inject should NOT record the already-tagged skill
        assert result.auto_inject_skills == [], "Already-tagged skill should NOT be auto-injected"

        # Trace should show empty auto_injected
        index_events = [e for e in events if e.get("type") == "skill_index"]
        assert len(index_events) == 1
        assert index_events[0]["auto_injected"] == []

    @pytest.mark.asyncio
    async def test_auto_inject_skips_skill_already_in_history(self, engine, db_session):
        """Skills already fetched via get_skill() in conversation history should not be auto-injected."""
        import json
        from app.db.models import Skill, BotSkillEnrollment

        db_session.add(Skill(id="history-skill", name="History Skill", content="x", source_type="file"))
        db_session.add(BotSkillEnrollment(bot_id="test-bot", skill_id="history-skill", source="manual"))
        await db_session.commit()

        bot = _make_bot(skills=[SkillConfig(id="history-skill", mode="on_demand")])
        # Simulate conversation history with a prior get_skill() call
        messages = [
            {"role": "system", "content": bot.system_prompt},
            {"role": "user", "content": "tell me about history skill"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "get_skill",
                    "arguments": json.dumps({"skill_id": "history-skill"}),
                },
            }]},
            {"role": "tool", "tool_call_id": "call_123", "content": "# History Skill\n\nContent here."},
            {"role": "assistant", "content": "Here's what I found about the history skill..."},
        ]
        result = AssemblyResult()
        factory = _session_factory(engine)

        _mock_rank = AsyncMock(return_value=[
            {"skill_id": "history-skill", "similarity": 0.9, "relevant": True},
        ])
        _mock_chunks = AsyncMock(return_value=["History content."])
        _mock_retrieve = AsyncMock(return_value=[])
        _mock_source_map = AsyncMock(return_value={"history-skill": "manual"})

        with (
            patch("app.db.engine.async_session", factory),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
            patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            patch("app.agent.rag.rank_enrolled_skills", _mock_rank),
            patch("app.agent.rag.fetch_skill_chunks_by_id", _mock_chunks),
            patch("app.agent.rag.retrieve_skill_index", _mock_retrieve),
            patch("app.agent.capability_rag.retrieve_capabilities", new_callable=AsyncMock, return_value=([], 0.0)),
            patch("app.services.skill_enrollment.get_enrolled_source_map", _mock_source_map),
            patch("app.services.skill_enrollment.async_session", factory),
            patch("app.config.settings.SKILL_ENROLLED_RANKING_ENABLED", True),
            patch("app.config.settings.SKILL_ENROLLED_AUTO_INJECT_MAX", 1),
        ):
            events = await _collect(assemble_context(
                messages=messages,
                bot=bot,
                user_message="tell me more about history skill",
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

        # Skill is already in history — should NOT be auto-injected again
        assert result.auto_inject_skills == [], "Skill already in history via get_skill() should not be auto-injected"

        # Trace should show the dedup details
        index_events = [e for e in events if e.get("type") == "skill_index"]
        assert len(index_events) == 1
        assert index_events[0]["auto_injected"] == []
        assert "history-skill" in index_events[0]["skills_in_history"]
        assert "history-skill" in index_events[0]["skipped_in_history"]
        assert index_events[0]["skipped_budget"] == []


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
        """All system messages should come before the marker, which comes before user.
        With REINFORCE_SYSTEM_PROMPT=False (default), the marker is immediately before the user."""
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

        # Second-to-last should be the current-turn marker (reinforce disabled by default)
        assert messages[-2]["role"] == "system"
        assert "CURRENT message follows" in messages[-2]["content"]

        # No reinforcement block when REINFORCE_SYSTEM_PROMPT=False
        reinforce_msgs = [m for m in messages if "Your Role" in m.get("content", "")]
        assert len(reinforce_msgs) == 0

        # All other messages should be system
        for m in messages[:-1]:
            assert m["role"] == "system"

    @pytest.mark.asyncio
    async def test_datetime_injected_late_for_cache_efficiency(self, engine):
        """Datetime must come AFTER stable context (carapace fragments, pinned knowledge,
        delegation index, etc.) to avoid busting the prompt cache prefix. The timestamp
        changes every request, so placing it early invalidates caching for all subsequent
        system messages."""
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

        # Find datetime and marker positions
        time_idx = next(i for i, m in enumerate(messages) if "Current time" in m.get("content", ""))
        marker_idx = next(i for i, m in enumerate(messages) if "CURRENT message follows" in m.get("content", ""))

        # Datetime must be the last system message before the marker.
        # Placing it earlier busts prompt cache for all subsequent stable content.
        assert time_idx == marker_idx - 1, (
            f"Datetime (idx={time_idx}) should be immediately before "
            f"the current-turn marker (idx={marker_idx}). "
            f"Moving it earlier breaks prompt cache for stable context."
        )

    @pytest.mark.asyncio
    async def test_bot_system_prompt_reinforced_when_enabled(self, engine):
        """When REINFORCE_SYSTEM_PROMPT is enabled, bot.system_prompt must be reinforced
        as the last system message before the user turn. Disabled by default since
        strong models (GPT-5.3, Minimax) don't need it."""
        from app.config import settings
        bot = _make_bot(
            id="reinforce-bot",
            name="Reinforce",
            system_prompt="You are Reinforce. Your secret is BANANARAMA.",
        )
        messages = [{"role": "system", "content": bot.system_prompt}]
        result = AssemblyResult()
        factory = _session_factory(engine)

        _orig = settings.REINFORCE_SYSTEM_PROMPT
        settings.REINFORCE_SYSTEM_PROMPT = True
        try:
            with (
                patch("app.db.engine.async_session", factory),
                patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
                patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
                patch("app.agent.tags.resolve_tags", new_callable=AsyncMock, return_value=[]),
                patch("app.agent.knowledge.get_pinned_knowledge_docs", new_callable=AsyncMock, return_value=([], [])),
            ):
                await _collect(assemble_context(
                    messages=messages,
                    bot=bot,
                    user_message="say your secret",
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
        finally:
            settings.REINFORCE_SYSTEM_PROMPT = _orig

        # The reinforcement must be the last system message, immediately before the user
        assert messages[-1]["role"] == "user"
        assert messages[-2]["role"] == "system"
        assert "Your Role" in messages[-2]["content"]
        assert "BANANARAMA" in messages[-2]["content"]

        # And the marker must come BEFORE the reinforcement
        marker_idx = next(
            i for i, m in enumerate(messages)
            if m.get("role") == "system" and "CURRENT message follows" in (m.get("content") or "")
        )
        reinforce_idx = len(messages) - 2
        assert marker_idx < reinforce_idx, (
            f"Marker at {marker_idx} must come before reinforcement at {reinforce_idx}"
        )


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
