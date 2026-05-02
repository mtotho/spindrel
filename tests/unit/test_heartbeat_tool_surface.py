"""Heartbeat tool-surface determinism tests.

Heartbeat surfaces are deterministic: pinned ∪ tagged ∪ required tools always
survive; general bot enrolled tools are ignored; and the discovery hatches
(`get_tool_info`, `search_tools`,
`list_tool_signatures`) never appear on heartbeat surfaces. The
`discovery_summary` trace event reports each step so operators can see
which tools the heartbeat saw and why.

Test-first: these lock in the contract documented in
`docs/architecture-decisions.md` heartbeat-tool-surface entry and the
plan at `~/.claude/plans/radiant-enchanting-castle.md`.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.bots import BotConfig
from app.agent.context_assembly import AssemblyResult, assemble_context
from app.agent.context_budget import ContextBudget


def _bot(**overrides) -> BotConfig:
    defaults = dict(
        id="bot-haos",
        name="Haos Bot",
        model="gpt-4o",
        system_prompt="System.",
        local_tools=[],
        mcp_servers=[],
        client_tools=[],
        skills=[],
        pinned_tools=[],
        tool_retrieval=True,
        tool_discovery=True,
        memory_scheme=None,
        history_mode=None,
        filesystem_indexes=[],
        delegate_bots=[],
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": name, "parameters": {}},
    }


def _patches(*, enrolled: list[str] | None = None, retrieved: list[dict] | None = None):
    return [
        patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
        patch("app.agent.recording._record_trace_event", new_callable=AsyncMock),
        patch(
            "app.agent.context_assembly._get_bot_authored_skill_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("app.services.skill_enrollment.enroll_many", new_callable=AsyncMock, return_value=0),
        patch(
            "app.services.skill_enrollment.get_enrolled_skill_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.skill_enrollment.get_enrolled_source_map",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("app.agent.context_assembly.resolve_tags", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.agent.rag.retrieve_skill_index",
            new_callable=AsyncMock,
            return_value=([], 0.0, []),
        ),
        patch(
            "app.services.widget_handler_tools.list_widget_handler_tools",
            new_callable=AsyncMock,
            return_value=([], None),
        ),
        patch(
            "app.services.tool_enrollment.get_enrolled_tool_names",
            new_callable=AsyncMock,
            return_value=enrolled or [],
        ),
        patch(
            "app.agent.context_assembly.retrieve_tools",
            new_callable=AsyncMock,
            return_value=(retrieved or [], 0.0, []),
        ),
        patch("app.agent.context_assembly.get_client_tool_schemas", return_value=[]),
        patch("app.agent.context_assembly.get_mcp_server_for_tool", return_value=None),
    ]


async def _drain(gen) -> list[dict]:
    events = []
    async for ev in gen:
        events.append(ev)
    return events


async def _run(
    bot: BotConfig,
    *,
    schemas: dict,
    required_tool_names: list[str] | None = None,
    **patch_kwargs,
) -> AssemblyResult:
    result = AssemblyResult()
    budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
    patches = _patches(**patch_kwargs) + [
        patch(
            "app.agent.context_assembly._all_tool_schemas_by_name",
            new_callable=AsyncMock,
            return_value=schemas,
        ),
        patch(
            "app.agent.context_assembly.get_local_tool_schemas",
            side_effect=lambda names: [schemas[n] for n in names if n in schemas],
        ),
    ]
    for p in patches:
        p.start()
    try:
        await _drain(
            assemble_context(
                messages=[{"role": "system", "content": "System."}],
                bot=bot,
                user_message="heartbeat tick",
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
                context_profile_name="heartbeat",
                tool_surface_policy="focused_escape",
                required_tool_names=required_tool_names,
            )
        )
    finally:
        for p in patches:
            p.stop()
    return result


class TestHeartbeatPinnedTools:
    """Pinned/tagged/injected tools always survive on heartbeat surfaces."""

    @pytest.mark.asyncio
    async def test_pinned_aggregator_callable_without_get_tool_info(self):
        """The exact bug from trace e0874e14: arr_heartbeat_snapshot is
        pinned, heartbeat fires, snapshot must be exposed without forcing
        a get_tool_info round-trip."""
        bot = _bot(
            local_tools=["arr_heartbeat_snapshot", "qbit_torrents", "sonarr_calendar"],
            pinned_tools=["arr_heartbeat_snapshot"],
        )
        schemas = {
            n: _schema(n)
            for n in (
                "arr_heartbeat_snapshot",
                "qbit_torrents",
                "sonarr_calendar",
                "get_tool_info",
                "search_tools",
                "list_tool_signatures",
                "run_script",
            )
        }
        result = await _run(bot, schemas=schemas)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "arr_heartbeat_snapshot" in exposed
        # Trace must record it as an explicit pin, not retrieval-recovered.
        hb = result.tool_discovery_info.get("heartbeat_surface")
        assert hb is not None, "heartbeat_surface trace block must be populated"
        assert "arr_heartbeat_snapshot" in hb["pin_set"]


class TestHeartbeatEnrolledTools:
    """General enrolled tools are learned from chat/task use and are not a
    heartbeat tool source."""

    @pytest.mark.asyncio
    async def test_enrolled_tools_are_ignored_even_under_cap(self):
        bot = _bot(local_tools=["a", "b", "c"])
        enrolled = ["a", "b", "c"]
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert exposed == set()
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb["enrolled_included"] == []
        assert set(hb["enrolled_ignored"]) == {"a", "b", "c"}
        assert hb["enrolled_dropped_for_budget"] == []
        assert hb.get("warning") == "heartbeat_no_required_or_curated_tools"

    @pytest.mark.asyncio
    async def test_enrolled_over_count_cap_does_not_trigger_retrieval(self):
        enrolled = [f"tool_{i:02d}" for i in range(30)]
        bot = _bot(local_tools=enrolled)
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        retrieved = [_schema("tool_27"), _schema("tool_28")]
        result = await _run(bot, schemas=schemas, enrolled=enrolled, retrieved=retrieved)
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb["enrolled_included"] == []
        assert set(hb["enrolled_ignored"]) == set(enrolled)
        assert hb["enrolled_dropped_for_budget"] == []
        assert hb["enrolled_recovered_via_retrieval"] == []
        assert hb["retrieval_ran"] is False

    @pytest.mark.asyncio
    async def test_pinned_survives_when_enrolled_set_is_ignored(self):
        enrolled = [f"e_{i:02d}" for i in range(40)]
        pinned = ["arr_heartbeat_snapshot"]
        bot = _bot(local_tools=enrolled + pinned, pinned_tools=pinned)
        schemas = {
            n: _schema(n)
            for n in enrolled + pinned + ["get_tool_info", "run_script"]
        }
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "arr_heartbeat_snapshot" in exposed
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert "arr_heartbeat_snapshot" in hb["pin_set"]
        assert "arr_heartbeat_snapshot" not in hb["enrolled_included"]
        assert "arr_heartbeat_snapshot" not in hb["enrolled_dropped_for_budget"]

    @pytest.mark.asyncio
    async def test_warning_when_no_required_or_curated_tools(self):
        enrolled = [f"e_{i:02d}" for i in range(40)]
        bot = _bot(local_tools=enrolled)  # NO pinned_tools
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb.get("warning") == "heartbeat_no_required_or_curated_tools"


class TestHeartbeatDiscoveryHatchesSuppressed:
    """`get_tool_info`, `search_tools`, `list_tool_signatures` never on
    heartbeat surfaces, regardless of budget headroom."""

    @pytest.mark.asyncio
    async def test_no_discovery_hatches_under_budget(self):
        bot = _bot(local_tools=["foo"], pinned_tools=["foo"])
        schemas = {
            n: _schema(n)
            for n in (
                "foo",
                "get_tool_info",
                "search_tools",
                "list_tool_signatures",
                "run_script",
            )
        }
        result = await _run(bot, schemas=schemas)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "get_tool_info" not in exposed
        assert "search_tools" not in exposed
        assert "list_tool_signatures" not in exposed
        assert "run_script" not in exposed

    @pytest.mark.asyncio
    async def test_run_script_only_when_explicitly_required(self):
        bot = _bot(local_tools=[])
        schemas = {"run_script": _schema("run_script")}
        result = await _run(bot, schemas=schemas, required_tool_names=["run_script"])
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert exposed == {"run_script"}
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb["pin_set"] == ["run_script"]
        assert hb["required_tools"] == ["run_script"]

    @pytest.mark.asyncio
    async def test_auto_injected_baseline_pins_filtered_from_heartbeat(self):
        """Regression for trace 83c24f74: chat baseline pins must not become
        heartbeat schema pins."""
        baseline = [
            "search_memory",
            "get_memory_file",
            "memory",
            "manage_bot_skill",
            "get_skill",
            "get_skill_list",
            "list_agent_capabilities",
            "run_agent_doctor",
            "list_channels",
            "read_conversation_history",
            "list_sub_sessions",
            "read_sub_session",
            "file",
            "search_channel_archive",
            "search_channel_workspace",
            "search_channel_knowledge",
            "search_bot_knowledge",
            "list_api_endpoints",
            "call_api",
        ]
        bot = _bot(
            local_tools=baseline + ["arr_heartbeat_snapshot"],
            pinned_tools=baseline + ["arr_heartbeat_snapshot"],
        )
        schemas = {
            n: _schema(n)
            for n in baseline + ["arr_heartbeat_snapshot", "run_script"]
        }
        with patch("app.agent.context_assembly.auto_injected_pin_names", return_value=frozenset(baseline)):
            result = await _run(bot, schemas=schemas)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "arr_heartbeat_snapshot" in exposed
        assert exposed.isdisjoint(set(baseline))
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb["pin_set"] == ["arr_heartbeat_snapshot"]
        assert set(hb["baseline_pins_filtered"]) == set(baseline)

    @pytest.mark.asyncio
    async def test_no_discovery_hatches_with_overflow(self):
        enrolled = [f"e_{i:02d}" for i in range(40)]
        bot = _bot(local_tools=enrolled)
        schemas = {
            n: _schema(n)
            for n in enrolled + [
                "get_tool_info",
                "search_tools",
                "list_tool_signatures",
                "run_script",
            ]
        }
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "get_tool_info" not in exposed
        assert "search_tools" not in exposed
        assert "list_tool_signatures" not in exposed
        assert exposed == set()


class TestHeartbeatRetrievalSkip:
    """Retrieval doesn't run when the explicit pin set already covers the
    surface — no embedding lottery for heartbeats."""

    @pytest.mark.asyncio
    async def test_retrieve_tools_not_invoked_when_pinned_sufficient(self):
        bot = _bot(
            local_tools=["arr_heartbeat_snapshot"],
            pinned_tools=["arr_heartbeat_snapshot"],
        )
        schemas = {
            n: _schema(n) for n in ("arr_heartbeat_snapshot", "get_tool_info", "run_script")
        }
        retrieve_mock = AsyncMock(return_value=([], 0.0, []))
        with patch("app.agent.context_assembly.retrieve_tools", retrieve_mock):
            extra_patches = [
                p for p in _patches(enrolled=[]) if "retrieve_tools" not in str(p)
            ]
            result = AssemblyResult()
            budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
            extra_patches += [
                patch(
                    "app.agent.context_assembly._all_tool_schemas_by_name",
                    new_callable=AsyncMock,
                    return_value=schemas,
                ),
                patch(
                    "app.agent.context_assembly.get_local_tool_schemas",
                    side_effect=lambda names: [schemas[n] for n in names if n in schemas],
                ),
            ]
            for p in extra_patches:
                p.start()
            try:
                await _drain(
                    assemble_context(
                        messages=[{"role": "system", "content": "System."}],
                        bot=bot,
                        user_message="heartbeat tick",
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
                        context_profile_name="heartbeat",
                        tool_surface_policy="focused_escape",
                    )
                )
            finally:
                for p in extra_patches:
                    p.stop()
        retrieve_mock.assert_not_called()
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb["retrieval_ran"] is False


class TestHeartbeatTraceDeterminism:
    """The discovery_summary trace block must be stable for identical
    inputs — no nondeterminism from dict ordering or set iteration."""

    @pytest.mark.asyncio
    async def test_two_runs_same_inputs_produce_same_trace(self):
        enrolled = [f"e_{i:02d}" for i in range(30)]
        bot = _bot(local_tools=enrolled, pinned_tools=["e_00"])
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        r1 = await _run(bot, schemas=schemas, enrolled=enrolled)
        r2 = await _run(bot, schemas=schemas, enrolled=enrolled)
        hb1 = r1.tool_discovery_info["heartbeat_surface"]
        hb2 = r2.tool_discovery_info["heartbeat_surface"]
        # Compare the ordered fields explicitly.
        for key in (
            "pin_set",
            "enrolled_included",
            "enrolled_ignored",
        ):
            assert hb1[key] == hb2[key], f"non-deterministic field {key!r}"


class TestChatRegressionGuard:
    """Chat origin keeps all three discovery tools available — the
    Phase 1 change only touches heartbeat surfaces."""

    @pytest.mark.asyncio
    async def test_chat_keeps_get_tool_info(self):
        bot = _bot(local_tools=["foo"])
        schemas = {
            n: _schema(n)
            for n in (
                "foo",
                "get_tool_info",
                "search_tools",
                "list_tool_signatures",
                "run_script",
                "get_skill",
                "get_skill_list",
            )
        }
        result = AssemblyResult()
        budget = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
        patches = _patches(enrolled=[], retrieved=[_schema("foo")]) + [
            patch(
                "app.agent.context_assembly._all_tool_schemas_by_name",
                new_callable=AsyncMock,
                return_value=schemas,
            ),
            patch(
                "app.agent.context_assembly.get_local_tool_schemas",
                side_effect=lambda names: [schemas[n] for n in names if n in schemas],
            ),
            patch(
                "app.agent.context_assembly.get_local_tool_schemas_by_metadata",
                side_effect=lambda domain, exposure: [
                    schemas[n] for n in ("get_tool_info",)
                    if domain == "tool_schema" and exposure == "ambient" and n in schemas
                ] + [
                    schemas[n] for n in ("search_tools",)
                    if domain == "tool_discovery" and exposure == "ambient" and n in schemas
                ] + [
                    schemas[n] for n in ("get_skill", "get_skill_list")
                    if domain == "skill_access" and exposure == "ambient" and n in schemas
                ],
            ),
        ]
        for p in patches:
            p.start()
        try:
            await _drain(
                assemble_context(
                    messages=[{"role": "system", "content": "System."}],
                    bot=bot,
                    user_message="chat",
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
                    context_profile_name="chat",
                    tool_surface_policy="full",
                )
            )
        finally:
            for p in patches:
                p.stop()
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert "get_tool_info" in exposed
        assert "search_tools" in exposed
        assert "list_tool_signatures" not in exposed
        # Heartbeat-specific trace block must NOT appear on chat surfaces.
        assert "heartbeat_surface" not in result.tool_discovery_info
