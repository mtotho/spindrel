"""Heartbeat tool-surface determinism tests.

Heartbeat surfaces are deterministic: pinned ∪ tagged ∪ injected always
survive; enrolled tools are added in priority order while under both
count + token caps; retrieval narrows only the over-cap remainder; and
the discovery hatches (`get_tool_info`, `search_tools`,
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


async def _run(bot: BotConfig, *, schemas: dict, **patch_kwargs) -> AssemblyResult:
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


class TestHeartbeatEnrolledBudget:
    """Enrolled tools are added in priority order while under cap.
    Caps overflow → retrieval narrows the remainder, never the pin set."""

    @pytest.mark.asyncio
    async def test_enrolled_under_cap_all_included(self):
        bot = _bot(local_tools=["a", "b", "c"])
        enrolled = ["a", "b", "c"]
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        exposed = {t["function"]["name"] for t in result.pre_selected_tools or []}
        assert {"a", "b", "c"} <= exposed
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert set(hb["enrolled_included"]) == {"a", "b", "c"}
        assert hb["enrolled_dropped_for_budget"] == []
        assert "warning" not in hb or hb.get("warning") is None

    @pytest.mark.asyncio
    async def test_enrolled_over_count_cap_retrieval_narrows_remainder(self):
        # 30 enrolled, default cap is 25 → 5 spill into retrieval narrowing.
        enrolled = [f"tool_{i:02d}" for i in range(30)]
        bot = _bot(local_tools=enrolled)
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        # Retrieval picks 2 of the 5 dropped tools.
        retrieved = [_schema("tool_27"), _schema("tool_28")]
        result = await _run(bot, schemas=schemas, enrolled=enrolled, retrieved=retrieved)
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert len(hb["enrolled_included"]) == 25
        assert set(hb["enrolled_dropped_for_budget"]) == {
            "tool_25",
            "tool_26",
            "tool_27",
            "tool_28",
            "tool_29",
        }
        assert set(hb["enrolled_recovered_via_retrieval"]) == {"tool_27", "tool_28"}
        assert set(hb["enrolled_dropped_after_retrieval"]) == {
            "tool_25",
            "tool_26",
            "tool_29",
        }

    @pytest.mark.asyncio
    async def test_pinned_never_compete_in_retrieval(self):
        """Pinned tools survive even when the enrolled set overflows."""
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
    async def test_warning_when_no_curated_pins_and_overflow(self):
        enrolled = [f"e_{i:02d}" for i in range(40)]
        bot = _bot(local_tools=enrolled)  # NO pinned_tools
        schemas = {n: _schema(n) for n in enrolled + ["get_tool_info", "run_script"]}
        result = await _run(bot, schemas=schemas, enrolled=enrolled)
        hb = result.tool_discovery_info["heartbeat_surface"]
        assert hb.get("warning") == "heartbeat_no_curated_pins"


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
        # run_script is composition, not discovery — keep it.
        assert "run_script" in exposed

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
            "enrolled_dropped_for_budget",
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
        assert "list_tool_signatures" in exposed
        # Heartbeat-specific trace block must NOT appear on chat surfaces.
        assert "heartbeat_surface" not in result.tool_discovery_info
