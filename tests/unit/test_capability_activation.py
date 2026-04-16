"""Unit tests for the activate_capability tool and context assembly integration."""
import contextlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.capability_session import _sessions


from app.agent.capability_session import _approved

@pytest.fixture(autouse=True)
def clear_sessions():
    _sessions.clear()
    _approved.clear()
    yield
    _sessions.clear()
    _approved.clear()


# ---------------------------------------------------------------------------
# Helper: mock carapace registry
# ---------------------------------------------------------------------------

_MOCK_REGISTRY = {
    "code-review": {
        "id": "code-review",
        "name": "Code Review",
        "description": "PR analysis, best practices, security checks",
        "system_prompt_fragment": "You are a code review expert. Focus on correctness, security, and best practices.",
        "skills": [{"id": "code-review-checklist", "mode": "pinned"}],
        "local_tools": ["exec_command"],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": ["development"],
    },
    "data-analyst": {
        "id": "data-analyst",
        "name": "Data Analyst",
        "description": "SQL, visualization, statistical methods",
        "system_prompt_fragment": "You are a data analyst.",
        "skills": [],
        "local_tools": [],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": ["analysis"],
    },
    "disabled-cap": {
        "id": "disabled-cap",
        "name": "Disabled Capability",
        "description": "This is globally disabled",
        "system_prompt_fragment": "",
        "skills": [],
        "local_tools": [],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": [],
    },
}


def _apply_patches(patches):
    """Enter a list of context managers via ExitStack and return the stack."""
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _registry_patches():
    return [
        patch("app.agent.carapaces.get_carapace", side_effect=lambda cid: _MOCK_REGISTRY.get(cid)),
        patch("app.agent.carapaces.list_carapaces", return_value=list(_MOCK_REGISTRY.values())),
    ]


def _ctx_patches(correlation_id=None, bot_id="test-bot", channel_id=None):
    return [
        patch("app.agent.context.current_correlation_id", MagicMock(get=lambda _=None: correlation_id)),
        patch("app.agent.context.current_bot_id", MagicMock(get=lambda _=None: bot_id)),
        patch("app.agent.context.current_channel_id", MagicMock(get=lambda _=None: channel_id)),
    ]


# ---------------------------------------------------------------------------
# Tool: activate_capability
# ---------------------------------------------------------------------------

class TestActivateCapabilityTool:
    @pytest.mark.asyncio
    async def test_activate_valid_capability(self):
        from app.tools.local.capabilities import activate_capability

        corr_id = uuid.uuid4()
        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=corr_id)):
            result = json.loads(await activate_capability(id="code-review", reason="User wants a code review"))

        assert result["status"] == "activated"
        assert result["id"] == "code-review"
        assert result["name"] == "Code Review"
        assert "instructions" in result
        assert "code review expert" in result["instructions"]
        assert "tools_next_turn" in result

    @pytest.mark.asyncio
    async def test_activate_nonexistent(self):
        from app.tools.local.capabilities import activate_capability

        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=uuid.uuid4())):
            result = json.loads(await activate_capability(id="nonexistent"))

        assert "error" in result
        assert "not found" in result["error"]
        assert "available" in result

    @pytest.mark.asyncio
    async def test_activate_empty_id(self):
        from app.tools.local.capabilities import activate_capability

        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=uuid.uuid4())):
            result = json.loads(await activate_capability(id=""))

        assert "error" in result

    @pytest.mark.asyncio
    async def test_activate_globally_disabled(self):
        from app.tools.local.capabilities import activate_capability

        mock_settings = MagicMock()
        mock_settings.CAPABILITIES_DISABLED = "disabled-cap,other"

        with _apply_patches(
            _registry_patches()
            + _ctx_patches(correlation_id=uuid.uuid4())
            + [patch("app.config.settings", mock_settings)]
        ):
            result = json.loads(await activate_capability(id="disabled-cap"))

        assert "error" in result
        assert "globally disabled" in result["error"]

    @pytest.mark.asyncio
    async def test_activate_channel_disabled(self):
        from app.tools.local.capabilities import activate_capability

        channel_id = uuid.uuid4()
        mock_ch = MagicMock()
        mock_ch.carapaces_disabled = ["code-review"]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_ch)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with _apply_patches(
            _registry_patches()
            + _ctx_patches(correlation_id=uuid.uuid4(), channel_id=channel_id)
            + [patch("app.db.engine.async_session", return_value=mock_session_ctx)]
        ):
            result = json.loads(await activate_capability(id="code-review"))

        assert "error" in result
        assert "disabled on this channel" in result["error"]

    @pytest.mark.asyncio
    async def test_activate_already_active(self):
        from app.tools.local.capabilities import activate_capability
        from app.agent.capability_session import activate

        corr_id = uuid.uuid4()
        activate(str(corr_id), "code-review")

        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=corr_id)):
            result = json.loads(await activate_capability(id="code-review"))

        assert result["status"] == "already_active"

    @pytest.mark.asyncio
    async def test_session_persistence(self):
        """Activation persists in session store across multiple calls."""
        from app.tools.local.capabilities import activate_capability
        from app.agent.capability_session import get_activated

        corr_id = uuid.uuid4()

        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=corr_id)):
            await activate_capability(id="code-review", reason="review")
            await activate_capability(id="data-analyst", reason="analysis")

        assert get_activated(str(corr_id)) == {"code-review", "data-analyst"}

    @pytest.mark.asyncio
    async def test_no_session_still_works(self):
        """Activation without correlation_id still returns fragment (ephemeral)."""
        from app.tools.local.capabilities import activate_capability

        with _apply_patches(_registry_patches() + _ctx_patches(correlation_id=None)):
            result = json.loads(await activate_capability(id="code-review"))

        assert result["status"] == "activated"
        assert "instructions" in result

    @pytest.mark.asyncio
    async def test_capability_without_fragment(self):
        """Capability with empty fragment still activates, no instructions key."""
        from app.tools.local.capabilities import activate_capability

        empty_frag = dict(_MOCK_REGISTRY["data-analyst"])
        empty_frag["system_prompt_fragment"] = ""

        with _apply_patches(
            [
                patch("app.agent.carapaces.get_carapace", return_value=empty_frag),
                patch("app.agent.carapaces.list_carapaces", return_value=[empty_frag]),
            ]
            + _ctx_patches(correlation_id=uuid.uuid4())
        ):
            result = json.loads(await activate_capability(id="data-analyst"))

        assert result["status"] == "activated"
        assert "instructions" not in result


# ---------------------------------------------------------------------------
# Context Assembly: capability index + session merge
# ---------------------------------------------------------------------------

def _ns_replace(obj, **kwargs):
    """Drop-in replacement for dataclasses.replace that works on SimpleNamespace."""
    d = vars(obj).copy()
    d.update(kwargs)
    return SimpleNamespace(**d)


def _make_bot(carapaces=None):
    ws_indexing = SimpleNamespace(
        enabled=False, patterns=[], similarity_threshold=0.3,
        top_k=10, watch=False, cooldown_seconds=60,
        embedding_model=None, segments=None,
    )
    ws = SimpleNamespace(enabled=False, indexing=ws_indexing)
    return SimpleNamespace(
        id="test_bot",
        name="Test Bot",
        user_id=None,
        model="test-model",
        system_prompt="You are helpful.",
        shared_workspace_id="ws-1",
        shared_workspace_role="worker",
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        memory_scheme=None,
        local_tools=["exec_command"],
        pinned_tools=[],
        skills=[],
        skill_ids=[],
        client_tools=[],
        mcp_servers=[],
        carapaces=carapaces or [],
        delegate_bots=[],
        tool_retrieval=False,
        tool_discovery=False,
        tool_similarity_threshold=None,
        context_pruning=None,
        api_permissions=None,
        persona=False,
        audio_input=None,
        channel_workspace_enabled=False,
        filesystem_indexes=None,
        memory=None,
    )


async def _mock_retrieve_capabilities(query, excluded_ids=None, *, top_k=None, threshold=None):
    """Mock retrieve_capabilities that returns all non-excluded registry entries."""
    excluded = excluded_ids or set()
    results = []
    for c in _MOCK_REGISTRY.values():
        if c["id"] in excluded:
            continue
        results.append({
            "id": c["id"],
            "name": c.get("name", c["id"]),
            "description": c.get("description") or "",
            "similarity": 0.8,
        })
    best_sim = 0.8 if results else 0.0
    return results, best_sim


def _assembly_patches(mock_settings_attrs=None):
    """Common patches for context assembly tests."""
    attrs = {
        "CAPABILITIES_DISABLED": "",
        "CONTEXT_PRUNING_ENABLED": False,
        "TIMEZONE": "UTC",
        "TOOL_POLICY_ENABLED": False,
    }
    if mock_settings_attrs:
        attrs.update(mock_settings_attrs)

    mock_settings = MagicMock(**attrs)

    return [
        patch("app.agent.carapaces.list_carapaces", return_value=list(_MOCK_REGISTRY.values())),
        patch("app.agent.capability_rag.retrieve_capabilities", side_effect=_mock_retrieve_capabilities),
        patch("app.agent.context_assembly.settings", mock_settings),
        patch("app.agent.context_assembly._get_bot_authored_skill_ids", new_callable=AsyncMock, return_value=[]),
        patch("app.agent.context_assembly._get_core_skill_ids", new_callable=AsyncMock, return_value=[]),
        patch("app.agent.context_assembly._dc_replace", side_effect=_ns_replace),
    ]


async def _run_assembly(bot, user_message="test", correlation_id=None):
    """Run assemble_context and return (events, messages)."""
    from app.agent.context_assembly import assemble_context, AssemblyResult
    messages = [{"role": "system", "content": "You are helpful."}]
    result = AssemblyResult()
    events = []
    async for evt in assemble_context(
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=None,
        client_id=None,
        correlation_id=correlation_id,
        channel_id=None,
        audio_data=None,
        audio_format=None,
        attachments=None,
        native_audio=False,
        result=result,
    ):
        events.append(evt)
    return events, messages


class TestCapabilityContextAssembly:
    """Test capability index injection and session merge in context assembly."""

    @pytest.mark.asyncio
    async def test_capability_index_injected(self):
        """When non-active carapaces exist, inject capability index."""
        bot = _make_bot(carapaces=[])
        with _apply_patches(_assembly_patches()):
            events, messages = await _run_assembly(bot, "Help me review some code")

        cap_events = [e for e in events if e.get("type") == "capability_index"]
        assert len(cap_events) == 1
        assert cap_events[0]["count"] == 3

        cap_messages = [m for m in messages if "Available capabilities" in m.get("content", "")]
        assert len(cap_messages) == 1
        assert "activate_capability" in cap_messages[0]["content"]
        assert "code-review" in cap_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_capability_index_excludes_active(self):
        """Active carapaces should not appear in the index."""
        bot = _make_bot(carapaces=["code-review"])
        patches = _assembly_patches()
        patches.append(patch("app.agent.carapaces.resolve_carapaces", return_value=SimpleNamespace(
            skills=[], local_tools=[], mcp_tools=[], pinned_tools=[],
            system_prompt_fragments=[], delegates=[],
        )))

        with _apply_patches(patches):
            events, messages = await _run_assembly(bot)

        cap_events = [e for e in events if e.get("type") == "capability_index"]
        assert len(cap_events) == 1
        assert cap_events[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_capability_index_respects_global_disable(self):
        """Globally disabled carapaces should not appear in the index."""
        bot = _make_bot()
        with _apply_patches(_assembly_patches({"CAPABILITIES_DISABLED": "disabled-cap"})):
            events, messages = await _run_assembly(bot)

        cap_events = [e for e in events if e.get("type") == "capability_index"]
        assert len(cap_events) == 1
        assert cap_events[0]["count"] == 2

        cap_messages = [m for m in messages if "Available capabilities" in m.get("content", "")]
        assert "disabled-cap" not in cap_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_session_capabilities_merged(self):
        """Session-activated capabilities should be merged into bot's carapace list."""
        from app.agent.capability_session import activate

        corr_id = uuid.uuid4()
        activate(str(corr_id), "code-review")

        bot = _make_bot(carapaces=[])
        patches = _assembly_patches()
        mock_resolve = MagicMock(return_value=SimpleNamespace(
            skills=[], local_tools=[], mcp_tools=[], pinned_tools=[],
            system_prompt_fragments=["You are a code review expert."], delegates=[],
        ))
        patches.append(patch("app.agent.carapaces.resolve_carapaces", mock_resolve))

        with _apply_patches(patches):
            events, messages = await _run_assembly(bot, "review my code", correlation_id=corr_id)

        merge_events = [e for e in events if e.get("type") == "session_capabilities_merged"]
        assert len(merge_events) == 1
        assert "code-review" in merge_events[0]["ids"]

        mock_resolve.assert_called_once()
        assert "code-review" in mock_resolve.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_index_when_all_active(self):
        """When all carapaces are already active, no capability index is injected."""
        bot = _make_bot(carapaces=["code-review", "data-analyst", "disabled-cap"])
        patches = _assembly_patches()
        patches.append(patch("app.agent.carapaces.resolve_carapaces", return_value=SimpleNamespace(
            skills=[], local_tools=[], mcp_tools=[], pinned_tools=[],
            system_prompt_fragments=[], delegates=[],
        )))

        with _apply_patches(patches):
            events, _ = await _run_assembly(bot)

        cap_events = [e for e in events if e.get("type") == "capability_index"]
        assert len(cap_events) == 0

    @pytest.mark.asyncio
    async def test_activate_capability_tool_injected(self):
        """activate_capability tool should be added when index is shown."""
        bot = _make_bot(carapaces=[])
        with _apply_patches(_assembly_patches()):
            events, _ = await _run_assembly(bot)

        cap_events = [e for e in events if e.get("type") == "capability_index"]
        assert len(cap_events) == 1


# ---------------------------------------------------------------------------
# Approval gate in tool_dispatch
# ---------------------------------------------------------------------------

def _dispatch_kwargs(
    *,
    name="activate_capability",
    args='{"id": "code-review", "reason": "review"}',
    correlation_id=None,
    bot_id="test-bot",
    skip_policy=False,
):
    """Build kwargs for dispatch_tool_call with sensible defaults."""
    return dict(
        name=name,
        args=args,
        tool_call_id="tc-1",
        bot_id=bot_id,
        bot_memory=None,
        session_id=uuid.uuid4(),
        client_id="client-1",
        correlation_id=correlation_id or uuid.uuid4(),
        channel_id=uuid.uuid4(),
        iteration=0,
        provider_id=None,
        summarize_enabled=False,
        summarize_threshold=10000,
        summarize_model="test",
        summarize_max_tokens=1000,
        summarize_exclude=set(),
        compaction=False,
        skip_policy=skip_policy,
    )


def _gate_patches(
    *,
    capability_approval="required",
    bot_carapaces=None,
    session_approved=False,
    policy_enabled=False,
):
    """Patches for testing the capability approval gate in dispatch."""
    mock_settings = MagicMock()
    mock_settings.CAPABILITY_APPROVAL = capability_approval
    mock_settings.TOOL_POLICY_ENABLED = policy_enabled
    # Numeric attributes referenced after the gate; comparing MagicMocks raises TypeError.
    mock_settings.TOOL_RESULT_HARD_CAP = 0
    mock_settings.CONTEXT_PRUNING_MIN_LENGTH = 200
    mock_settings.KNOWLEDGE_SIMILARITY_THRESHOLD = 0.5
    # Wall-clock guard wraps the local/MCP dispatch via asyncio.wait_for —
    # needs a real number so the comparison in wait_for doesn't blow up.
    mock_settings.TOOL_DISPATCH_TIMEOUT = 5.0

    bot_cfg = SimpleNamespace(carapaces=bot_carapaces or [])
    cap_data = _MOCK_REGISTRY.get("code-review")

    patches = [
        patch("app.agent.tool_dispatch.settings", mock_settings),
        patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
        patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
        patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
        patch("app.agent.bots.get_bot", return_value=bot_cfg),
        patch("app.agent.carapaces.get_carapace", return_value=cap_data),
        patch("app.agent.capability_session.is_approved", return_value=session_approved),
        patch(
            "app.agent.tool_dispatch._create_approval_record",
            new_callable=AsyncMock,
            return_value="approval-123",
        ),
    ]
    return patches


class TestCapabilityApprovalGate:
    @pytest.mark.asyncio
    async def test_approval_required_creates_record(self):
        """When CAPABILITY_APPROVAL=required, unpinned & unapproved cap triggers approval."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs()
        with _apply_patches(_gate_patches()):
            result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is True
        assert result.approval_id == "approval-123"
        assert result.approval_timeout == 300
        assert "Code Review" in (result.approval_reason or "")
        assert result.tool_event.get("_capability", {}).get("id") == "code-review"

    @pytest.mark.asyncio
    async def test_approval_skipped_when_pinned(self):
        """Capability in bot.carapaces is pre-approved — no approval gate."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs()
        with _apply_patches(_gate_patches(bot_carapaces=["code-review"])):
            # Will proceed to actual tool dispatch — mock the local tool call
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"status": "activated"}'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_approval_skipped_when_session_approved(self):
        """After approve(), same cap in same session skips the gate."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs()
        with _apply_patches(_gate_patches(session_approved=True)):
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"status": "activated"}'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_approval_skipped_when_mode_none(self):
        """CAPABILITY_APPROVAL=none disables the gate entirely."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs()
        with _apply_patches(_gate_patches(capability_approval="none")):
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"status": "activated"}'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_approval_skipped_when_no_correlation_id(self):
        """No correlation_id → gate doesn't fire (can't track sessions)."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs(correlation_id=None)
        kwargs["correlation_id"] = None
        with _apply_patches(_gate_patches()):
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"status": "activated"}'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_approval_includes_capability_metadata(self):
        """tool_event should include _capability dict with id, name, description, counts."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs()
        with _apply_patches(_gate_patches()):
            result = await dispatch_tool_call(**kwargs)

        cap = result.tool_event.get("_capability")
        assert cap is not None
        assert cap["id"] == "code-review"
        assert cap["name"] == "Code Review"
        assert cap["description"] == "PR analysis, best practices, security checks"
        assert cap["tools_count"] == 1  # ["exec_command"]
        assert "skills_count" not in cap  # skills are not a carapace concept

    @pytest.mark.asyncio
    async def test_approval_skipped_on_skip_policy(self):
        """When skip_policy=True (re-dispatch after approval), gate doesn't fire."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs(skip_policy=True)
        with _apply_patches(_gate_patches()):
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"status": "activated"}'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_non_capability_tool_not_gated(self):
        """Regular tools (not activate_capability) bypass the capability gate."""
        from app.agent.tool_dispatch import dispatch_tool_call
        kwargs = _dispatch_kwargs(name="exec_command", args='{"command": "ls"}')
        with _apply_patches(_gate_patches()):
            with patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='"ok"'):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_approval_notification_includes_metadata(self):
        """_create_approval_record should be called with extra_metadata containing _capability."""
        from app.agent.tool_dispatch import dispatch_tool_call

        kwargs = _dispatch_kwargs()
        mock_create = AsyncMock(return_value="approval-123")

        with _apply_patches(_gate_patches()):
            with patch("app.agent.tool_dispatch._create_approval_record", mock_create):
                result = await dispatch_tool_call(**kwargs)

        assert result.needs_approval is True
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert "extra_metadata" in call_kwargs
        cap = call_kwargs["extra_metadata"]["_capability"]
        assert cap["id"] == "code-review"
        assert cap["name"] == "Code Review"
        assert cap["tools_count"] == 1
        assert "skills_count" not in cap
