"""Tests for carapace delegation — delegating to carapaces, not just bots.

Covers:
- Resolution: resolve_carapaces collects delegates, deduplicates, inherits from includes
- Delegate index: carapace delegates appear in context, bot takes precedence on conflict
- Tool resolution: delegate_to_agent resolves carapace IDs, bot-first precedence, permission check
- Deferred delegation: Task created with correct execution_config.carapaces and parent's bot_id
- Immediate delegation: bot config cloned with carapace overlay
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.carapaces import (
    DelegateEntry,
    ResolvedCarapace,
    _registry,
    resolve_carapaces,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure a clean registry for each test."""
    _registry.clear()
    yield
    _registry.clear()


def _make_carapace(
    id: str,
    *,
    local_tools=None,
    mcp_tools=None,
    pinned_tools=None,
    system_prompt_fragment=None,
    includes=None,
    delegates=None,
):
    return {
        "id": id,
        "name": id,
        "description": f"Description of {id}",
        "local_tools": local_tools or [],
        "mcp_tools": mcp_tools or [],
        "pinned_tools": pinned_tools or [],
        "system_prompt_fragment": system_prompt_fragment,
        "includes": includes or [],
        "delegates": delegates or [],
        "tags": [],
        "source_path": None,
        "source_type": "manual",
        "content_hash": None,
    }


def _make_bot(**overrides):
    defaults = dict(
        id="parent-bot",
        name="Parent",
        model="gpt-4",
        system_prompt="You are a parent bot.",
        delegate_bots=["child-bot"],
        carapaces=["orchestrator"],
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# Resolution: delegates collected during resolve_carapaces
# ---------------------------------------------------------------------------

class TestResolveDelegates:
    def test_single_carapace_with_delegates(self):
        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[
                {"id": "qa", "type": "carapace", "description": "QA expert"},
                {"id": "code-review", "type": "carapace", "description": "Code reviewer"},
            ],
        )
        result = resolve_carapaces(["orchestrator"])
        assert len(result.delegates) == 2
        assert result.delegates[0].id == "qa"
        assert result.delegates[0].type == "carapace"
        assert result.delegates[0].description == "QA expert"
        assert result.delegates[0].source_carapace == "orchestrator"
        assert result.delegates[1].id == "code-review"

    def test_delegates_deduplicated(self):
        """If two carapaces declare the same delegate, first one wins."""
        _registry["a"] = _make_carapace(
            "a",
            delegates=[{"id": "qa", "type": "carapace", "description": "From A"}],
        )
        _registry["b"] = _make_carapace(
            "b",
            delegates=[{"id": "qa", "type": "carapace", "description": "From B"}],
        )
        result = resolve_carapaces(["a", "b"])
        assert len(result.delegates) == 1
        assert result.delegates[0].description == "From A"  # first wins

    def test_delegates_inherited_from_includes(self):
        """Delegates from included carapaces are inherited transitively."""
        _registry["base"] = _make_carapace(
            "base",
            delegates=[{"id": "helper", "type": "bot", "description": "Helper bot"}],
        )
        _registry["top"] = _make_carapace(
            "top",
            includes=["base"],
            delegates=[{"id": "qa", "type": "carapace", "description": "QA"}],
        )
        result = resolve_carapaces(["top"])
        delegate_ids = [d.id for d in result.delegates]
        assert "helper" in delegate_ids
        assert "qa" in delegate_ids
        # helper comes from base (resolved via include first), then qa from top
        assert delegate_ids.index("helper") < delegate_ids.index("qa")

    def test_delegates_inherited_dedup_across_includes(self):
        """If both the parent and included carapace declare the same delegate, dedup."""
        _registry["base"] = _make_carapace(
            "base",
            delegates=[{"id": "qa", "type": "carapace", "description": "From base"}],
        )
        _registry["top"] = _make_carapace(
            "top",
            includes=["base"],
            delegates=[{"id": "qa", "type": "carapace", "description": "From top"}],
        )
        result = resolve_carapaces(["top"])
        assert len(result.delegates) == 1
        # base is resolved first (depth-first), so base's version wins
        assert result.delegates[0].description == "From base"

    def test_no_delegates_field(self):
        """Carapace without delegates field should work fine."""
        _registry["simple"] = _make_carapace("simple", local_tools=["file"])
        result = resolve_carapaces(["simple"])
        assert result.delegates == []

    def test_bot_type_delegates(self):
        """Delegates can be of type 'bot'."""
        _registry["c"] = _make_carapace(
            "c",
            delegates=[{"id": "researcher", "type": "bot", "description": "Research bot"}],
        )
        result = resolve_carapaces(["c"])
        assert result.delegates[0].type == "bot"

    def test_delegate_default_type_is_carapace(self):
        """If type is omitted, default to 'carapace'."""
        _registry["c"] = _make_carapace(
            "c",
            delegates=[{"id": "qa", "description": "QA"}],
        )
        result = resolve_carapaces(["c"])
        assert result.delegates[0].type == "carapace"


# ---------------------------------------------------------------------------
# Delegate tool: delegate_to_agent resolves carapace IDs
# ---------------------------------------------------------------------------

class TestDelegateToAgentCarapace:
    @pytest.mark.asyncio
    async def test_carapace_delegation_creates_task(self):
        """When bot_id matches a carapace (not a bot), creates a task with
        execution_config.carapaces and parent's bot_id."""
        from app.tools.local.delegation import delegate_to_agent
        from app.agent.context import (
            current_bot_id,
            current_session_id,
            current_client_id,
            current_channel_id,
            current_dispatch_type,
            current_dispatch_config,
        )

        parent_bot = _make_bot(
            delegate_bots=["child-bot"],
            carapaces=["orchestrator"],
        )

        # Set up the carapace registry: orchestrator declares qa as delegate
        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[{"id": "qa", "type": "carapace", "description": "QA expert"}],
        )
        _registry["qa"] = _make_carapace("qa")

        session_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        current_bot_id.set("parent-bot")
        current_session_id.set(session_id)
        current_client_id.set("slack:C123")
        current_channel_id.set(channel_id)
        current_dispatch_type.set("slack")
        current_dispatch_config.set({"channel_id": "C123"})

        mock_deferred = AsyncMock(return_value="task-123")

        with patch("app.agent.bots.get_bot", return_value=parent_bot), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            mock_svc.run_deferred = mock_deferred
            result = await delegate_to_agent(bot_id="qa", prompt="Run QA checks")

        assert "task-123" in result
        assert "carapace" in result.lower()

        # Verify the call to run_deferred
        call_kwargs = mock_deferred.call_args
        assert call_kwargs.kwargs["delegate_bot_id"] == "parent-bot"  # parent's bot_id
        assert call_kwargs.kwargs["carapace_ids"] == ["qa"]
        assert call_kwargs.kwargs["prompt"] == "Run QA checks"

    @pytest.mark.asyncio
    async def test_bot_takes_precedence_over_carapace(self):
        """When bot_id matches both a bot and a carapace, bot wins."""
        from app.tools.local.delegation import delegate_to_agent
        from app.agent.context import (
            current_bot_id,
            current_session_id,
            current_client_id,
            current_channel_id,
            current_dispatch_type,
            current_dispatch_config,
        )

        parent_bot = _make_bot(delegate_bots=["qa"])

        # qa exists as both a bot and a carapace
        _registry["qa"] = _make_carapace("qa")

        fake_qa_bot = _make_bot(id="qa", name="QA Bot")

        current_bot_id.set("parent-bot")
        current_session_id.set(uuid.uuid4())
        current_client_id.set("slack:C123")
        current_channel_id.set(uuid.uuid4())
        current_dispatch_type.set("slack")
        current_dispatch_config.set({"channel_id": "C123"})

        mock_deferred = AsyncMock(return_value="task-456")

        with patch("app.agent.bots.get_bot", return_value=parent_bot), \
             patch("app.agent.bots.resolve_bot_id", return_value=fake_qa_bot), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            mock_svc.run_deferred = mock_deferred
            result = await delegate_to_agent(bot_id="qa", prompt="Run tests")

        assert "task-456" in result
        # Should be standard bot delegation (no carapace_ids)
        call_kwargs = mock_deferred.call_args
        assert call_kwargs.kwargs["delegate_bot_id"] == "qa"
        assert call_kwargs.kwargs.get("carapace_ids") is None

    @pytest.mark.asyncio
    async def test_carapace_not_in_delegates_rejected(self):
        """Carapace must be in the delegates list of an active carapace."""
        from app.tools.local.delegation import delegate_to_agent
        from app.agent.context import (
            current_bot_id,
            current_session_id,
            current_client_id,
            current_channel_id,
            current_dispatch_type,
            current_dispatch_config,
        )

        parent_bot = _make_bot(
            delegate_bots=[],
            carapaces=["orchestrator"],
        )

        # orchestrator does NOT declare 'rogue' as a delegate
        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[{"id": "qa", "type": "carapace"}],
        )
        _registry["rogue"] = _make_carapace("rogue")

        current_bot_id.set("parent-bot")
        current_session_id.set(uuid.uuid4())
        current_client_id.set("slack:C123")
        current_channel_id.set(uuid.uuid4())
        current_dispatch_type.set("slack")
        current_dispatch_config.set({"channel_id": "C123"})

        with patch("app.agent.bots.get_bot", return_value=parent_bot), \
             patch("app.agent.bots.resolve_bot_id", return_value=None):
            result = await delegate_to_agent(bot_id="rogue", prompt="Hack stuff")

        data = json.loads(result)
        assert "error" in data
        assert "not in the delegates list" in data["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_bot_and_carapace(self):
        """When bot_id matches neither a bot nor a carapace, error."""
        from app.tools.local.delegation import delegate_to_agent
        from app.agent.context import (
            current_bot_id,
            current_session_id,
            current_client_id,
            current_channel_id,
            current_dispatch_type,
            current_dispatch_config,
        )

        parent_bot = _make_bot(delegate_bots=["child-bot"])

        current_bot_id.set("parent-bot")
        current_session_id.set(uuid.uuid4())
        current_client_id.set("slack:C123")
        current_channel_id.set(uuid.uuid4())
        current_dispatch_type.set("slack")
        current_dispatch_config.set({"channel_id": "C123"})

        with patch("app.agent.bots.get_bot", return_value=parent_bot), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.agent.bots.list_bots", return_value=[]):
            result = await delegate_to_agent(bot_id="nonexistent", prompt="test")

        data = json.loads(result)
        assert "error" in data
        assert "No bot or carapace" in data["error"]


# ---------------------------------------------------------------------------
# Deferred delegation: Task created with execution_config.carapaces
# ---------------------------------------------------------------------------

class TestDeferredCarapaceDelegation:
    @pytest.mark.asyncio
    async def test_execution_config_has_carapaces(self):
        """run_deferred with carapace_ids sets execution_config.carapaces on the Task."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        db = AsyncMock()
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.delegation.async_session", return_value=cm):
            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="parent-bot",
                prompt="Run QA",
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123"},
                scheduled_at=None,
                carapace_ids=["qa"],
            )

        db.add.assert_called_once()
        task = db.add.call_args[0][0]
        assert task.execution_config == {"carapaces": ["qa"]}
        assert task.bot_id == "parent-bot"

    @pytest.mark.asyncio
    async def test_no_carapace_ids_no_execution_config(self):
        """run_deferred without carapace_ids has no execution_config."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        db = AsyncMock()
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.delegation.async_session", return_value=cm):
            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="Do something",
                dispatch_type="none",
                dispatch_config={},
                scheduled_at=None,
            )

        task = db.add.call_args[0][0]
        assert task.execution_config is None


# ---------------------------------------------------------------------------
# Immediate delegation: bot cloned with carapace overlay
# ---------------------------------------------------------------------------

class TestImmediateCarapaceDelegation:
    @pytest.mark.asyncio
    async def test_carapace_ids_clone_bot(self):
        """run_immediate with carapace_ids clones the bot config with those carapaces."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot(delegate_bots=["parent-bot"], carapaces=["orchestrator"])
        delegate = _make_bot(id="parent-bot", carapaces=[])

        captured_bot = {}

        async def fake_stream(messages, bot, prompt, **kw):
            captured_bot["carapaces"] = bot.carapaces
            yield {"type": "response", "text": "done", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=delegate), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"):
            s.DELEGATION_MAX_DEPTH = 5
            result = await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="parent-bot",
                prompt="Run QA",
                dispatch_type=None,
                dispatch_config=None,
                depth=0,
                root_session_id=uuid.uuid4(),
                carapace_ids=["qa"],
            )

        assert result == "done"
        assert captured_bot["carapaces"] == ["qa"]

    @pytest.mark.asyncio
    async def test_carapace_ids_bypass_delegate_bots_check(self):
        """Carapace delegation doesn't require delegate_bots to be set."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        # parent has no delegate_bots — would normally fail for bot delegation
        parent = _make_bot(delegate_bots=[], carapaces=["orchestrator"])
        delegate = _make_bot(id="parent-bot", carapaces=[])

        async def fake_stream(messages, bot, prompt, **kw):
            yield {"type": "response", "text": "done", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=delegate), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"):
            s.DELEGATION_MAX_DEPTH = 5
            # Should NOT raise despite empty delegate_bots
            result = await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="parent-bot",
                prompt="Run QA",
                dispatch_type=None,
                dispatch_config=None,
                depth=0,
                root_session_id=uuid.uuid4(),
                carapace_ids=["qa"],
            )

        assert result == "done"


# ---------------------------------------------------------------------------
# Registry: _carapace_to_dict includes delegates
# ---------------------------------------------------------------------------

class TestCarapaceToDict:
    def test_includes_delegates(self):
        from app.agent.carapaces import _carapace_to_dict
        from app.db.models import Carapace as CarapaceRow

        row = CarapaceRow(
            id="test",
            name="Test",
            description="Test carapace",
            local_tools=[],
            mcp_tools=[],
            pinned_tools=[],
            includes=[],
            delegates=[{"id": "qa", "type": "carapace", "description": "QA"}],
            tags=[],
            source_type="manual",
        )
        d = _carapace_to_dict(row)
        assert d["delegates"] == [{"id": "qa", "type": "carapace", "description": "QA"}]
        # The dict should not expose a `skills` key — skills are not a carapace concept
        assert "skills" not in d

    def test_delegates_defaults_empty(self):
        from app.agent.carapaces import _carapace_to_dict
        from app.db.models import Carapace as CarapaceRow

        row = CarapaceRow(
            id="test",
            name="Test",
            local_tools=[],
            mcp_tools=[],
            pinned_tools=[],
            includes=[],
            delegates=None,
            tags=[],
            source_type="manual",
        )
        d = _carapace_to_dict(row)
        assert d["delegates"] == []
