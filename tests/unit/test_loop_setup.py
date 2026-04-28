from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.loop_setup import LoopSetupDone, stream_loop_setup


def _bot():
    return BotConfig(
        id="bot-1",
        name="Test Bot",
        model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )


def _config(**overrides):
    defaults = dict(
        effective_max_iterations=5,
        max_iterations_source="global",
        model="gpt-4",
        provider_id=None,
        effective_model_params={"temperature": 0.2},
        summarize_settings=object(),
        in_loop_keep_iterations=2,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _tool_state(**overrides):
    defaults = dict(
        all_tools=[{"type": "function", "function": {"name": "search"}}],
        tools_param=[{"type": "function", "function": {"name": "search"}}],
        tool_choice="auto",
        effective_allowed={"search"},
        has_manage_bot_skill=False,
        activated_list=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def _collect(**overrides):
    async def _default_resolve_loop_tools(*args, **kwargs):
        return _tool_state()

    async def _default_inject_opening_skill_nudges(**kwargs):
        return None

    outputs = [
        item async for item in stream_loop_setup(
            messages=overrides.pop("messages", [{"role": "user", "content": "hi"}]),
            bot=overrides.pop("bot", _bot()),
            session_id=overrides.pop("session_id", None),
            client_id=overrides.pop("client_id", "client-1"),
            correlation_id=overrides.pop("correlation_id", None),
            channel_id=overrides.pop("channel_id", None),
            compaction=overrides.pop("compaction", False),
            native_audio=overrides.pop("native_audio", False),
            user_msg_index=overrides.pop("user_msg_index", None),
            turn_start=overrides.pop("turn_start", 0),
            max_iterations=overrides.pop("max_iterations", None),
            model_override=overrides.pop("model_override", None),
            provider_id_override=overrides.pop("provider_id_override", None),
            context_profile_name=overrides.pop("context_profile_name", None),
            run_control_policy=overrides.pop("run_control_policy", None),
            pre_selected_tools=overrides.pop("pre_selected_tools", None),
            authorized_tool_names=overrides.pop("authorized_tool_names", None),
            settings_obj=overrides.pop("settings_obj", object()),
            resolve_loop_config_fn=overrides.pop("resolve_loop_config_fn", lambda *args, **kwargs: _config()),
            resolve_loop_tools_fn=overrides.pop("resolve_loop_tools_fn", _default_resolve_loop_tools),
            get_local_tool_schemas_fn=overrides.pop("get_local_tool_schemas_fn", object()),
            fetch_mcp_tools_fn=overrides.pop("fetch_mcp_tools_fn", object()),
            get_client_tool_schemas_fn=overrides.pop("get_client_tool_schemas_fn", object()),
            merge_tool_schemas_fn=overrides.pop("merge_tool_schemas_fn", object()),
            resolve_provider_for_model_fn=overrides.pop("resolve_provider_for_model_fn", lambda model: "openai"),
            inject_opening_skill_nudges_fn=overrides.pop("inject_opening_skill_nudges_fn", _default_inject_opening_skill_nudges),
            record_trace_event_fn=overrides.pop("record_trace_event_fn", lambda **kwargs: kwargs),
            safe_create_task_fn=overrides.pop("safe_create_task_fn", lambda task: None),
            monotonic_fn=overrides.pop("monotonic_fn", lambda: 123.0),
        )
    ]
    assert not overrides
    return outputs


@pytest.mark.asyncio
async def test_setup_resolves_provider_and_injects_opening_nudges():
    nudge_calls = []

    async def _nudge(**kwargs):
        nudge_calls.append(kwargs)

    async def _tools(*args, **kwargs):
        return _tool_state(has_manage_bot_skill=True)

    outputs = await _collect(
        inject_opening_skill_nudges_fn=_nudge,
        resolve_provider_for_model_fn=lambda model: "resolved-provider",
        resolve_loop_tools_fn=_tools,
    )

    done = outputs[-1]
    assert isinstance(done, LoopSetupDone)
    assert done.effective_provider_id == "resolved-provider"
    assert done.has_manage_bot_skill is True
    assert done.run_control.run_started_at == 123.0
    assert nudge_calls[0]["has_manage_bot_skill"] is True


@pytest.mark.asyncio
async def test_heartbeat_tool_surface_event_and_trace_are_emitted_before_done():
    trace_tasks = []
    corr = uuid4()

    outputs = await _collect(
        correlation_id=corr,
        context_profile_name="heartbeat",
        run_control_policy={
            "tool_surface": "focused_escape",
            "continuation_mode": "stateless",
            "hard_max_llm_calls": 4,
        },
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
    )

    assert outputs[0]["type"] == "tool_surface_summary"
    assert outputs[0]["tool_count"] == 1
    assert outputs[0]["tool_surface"] == "focused_escape"
    assert outputs[0]["effective_max_iterations"] == 4
    assert trace_tasks[0]["event_type"] == "tool_surface_summary"
    assert isinstance(outputs[-1], LoopSetupDone)
    assert outputs[-1].effective_max_iterations == 4


@pytest.mark.asyncio
async def test_hard_cap_min_applies_for_non_global_or_non_heartbeat_runs():
    outputs = await _collect(
        context_profile_name="standard",
        run_control_policy={"hard_max_llm_calls": 3},
        resolve_loop_config_fn=lambda *args, **kwargs: _config(
            effective_max_iterations=8,
            max_iterations_source="explicit",
        ),
    )

    done = outputs[-1]
    assert isinstance(done, LoopSetupDone)
    assert done.effective_max_iterations == 3


@pytest.mark.asyncio
async def test_explicit_provider_skips_provider_resolution():
    def _resolve_provider(model):
        raise AssertionError("provider resolution should not run when config has provider")

    outputs = await _collect(
        resolve_loop_config_fn=lambda *args, **kwargs: _config(provider_id="configured-provider"),
        resolve_provider_for_model_fn=_resolve_provider,
    )

    assert outputs[-1].effective_provider_id == "configured-provider"
