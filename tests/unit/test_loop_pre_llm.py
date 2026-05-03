from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.loop_helpers import PromptBudgetGate
from app.agent.loop_pre_llm import LoopPreLlmIterationDone, stream_loop_pre_llm_iteration
from app.agent.loop_state import LoopRunContext, LoopRunState


def _ctx(*, correlation_id=None, session_id=None):
    return LoopRunContext(
        bot=BotConfig(
            id="bot-1",
            name="Test Bot",
            model="gpt-4",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(),
        ),
        session_id=session_id,
        client_id="client-1",
        correlation_id=correlation_id,
        channel_id=None,
        compaction=False,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


def _settings(**overrides):
    defaults = dict(
        IN_LOOP_PRUNING_ENABLED=False,
        CONTEXT_PRUNING_MIN_LENGTH=200,
        CONTEXT_BUDGET_RESERVE_RATIO=0.15,
        IN_LOOP_PRUNING_PRESSURE_THRESHOLD=0.8,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _SessionLocks:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled

    def is_cancel_requested(self, session_id):
        return self.cancelled


async def _collect(**overrides):
    state = overrides.pop("state", LoopRunState(messages=[{"role": "user", "content": "hi"}]))
    outputs = [
        item async for item in stream_loop_pre_llm_iteration(
            ctx=overrides.pop("ctx", _ctx()),
            state=state,
            iteration=overrides.pop("iteration", 0),
            model=overrides.pop("model", "gpt-4"),
            effective_provider_id=overrides.pop("effective_provider_id", "openai"),
            tools_param=overrides.pop("tools_param", None),
            tool_choice=overrides.pop("tool_choice", None),
            activated_list=overrides.pop("activated_list", []),
            effective_allowed=overrides.pop("effective_allowed", None),
            context_profile_name=overrides.pop("context_profile_name", None),
            run_started_at=overrides.pop("run_started_at", 0.0),
            soft_max_llm_calls=overrides.pop("soft_max_llm_calls", 0),
            soft_current_prompt_tokens=overrides.pop("soft_current_prompt_tokens", 0),
            target_seconds=overrides.pop("target_seconds", 0),
            in_loop_keep_iterations=overrides.pop("in_loop_keep_iterations", 2),
            in_loop_pruning_mode=overrides.pop("in_loop_pruning_mode", "pressure"),
            settings_obj=overrides.pop("settings_obj", _settings()),
            session_lock_manager=overrides.pop("session_lock_manager", _SessionLocks()),
            merge_activated_tools_fn=overrides.pop("merge_activated_tools_fn", lambda active, tools, choice, allowed, **kw: (tools, choice)),
            prune_in_loop_tool_results_fn=overrides.pop("prune_in_loop_tool_results_fn", lambda *args, **kwargs: {}),
            should_prune_in_loop_fn=overrides.pop("should_prune_in_loop_fn", lambda *args, **kwargs: (False, 0.0)),
            check_prompt_budget_guard_fn=overrides.pop("check_prompt_budget_guard_fn", lambda **kwargs: PromptBudgetGate([], False, 0)),
            record_trace_event_fn=overrides.pop("record_trace_event_fn", lambda **kwargs: kwargs),
            safe_create_task_fn=overrides.pop("safe_create_task_fn", lambda task: None),
            late_input_drain_fn=overrides.pop("late_input_drain_fn", None),
            sleep_fn=overrides.pop("sleep_fn", lambda seconds: None),
            monotonic_fn=overrides.pop("monotonic_fn", lambda: 0.0),
            message_prompt_chars_fn=overrides.pop("message_prompt_chars_fn", lambda message: len(str(message.get("content") or ""))),
            classify_sys_msg_fn=overrides.pop("classify_sys_msg_fn", lambda content: "system"),
            get_model_context_window_fn=overrides.pop("get_model_context_window_fn", lambda model, provider_id: 0),
        )
    ]
    assert not overrides
    return outputs, state


@pytest.mark.asyncio
async def test_cancel_requested_returns_without_budget_work():
    session_id = uuid4()

    outputs, _ = await _collect(
        ctx=_ctx(session_id=session_id),
        session_lock_manager=_SessionLocks(cancelled=True),
        check_prompt_budget_guard_fn=lambda **kwargs: pytest.fail("budget gate should not run after cancellation"),
    )

    assert outputs == [
        {"type": "cancelled"},
        LoopPreLlmIterationDone(tools_param=None, tool_choice=None, return_loop=True),
    ]


@pytest.mark.asyncio
async def test_activated_tools_are_merged_and_allowed_before_llm_call():
    new_tool = {"type": "function", "function": {"name": "dynamic_lookup"}}
    allowed = {"get_tool_info"}

    def _merge(active, tools, choice, effective_allowed, **kwargs):
        effective_allowed.add(active[0]["function"]["name"])
        return (tools or []) + active, "auto"

    outputs, _ = await _collect(
        tools_param=[{"type": "function", "function": {"name": "get_tool_info"}}],
        tool_choice="auto",
        activated_list=[new_tool],
        effective_allowed=allowed,
        merge_activated_tools_fn=_merge,
    )

    done = outputs[-1]
    assert isinstance(done, LoopPreLlmIterationDone)
    assert done.tools_param[-1]["function"]["name"] == "dynamic_lookup"
    assert done.tool_choice == "auto"
    assert "dynamic_lookup" in allowed


@pytest.mark.asyncio
async def test_activated_tool_surface_update_is_traced():
    trace_tasks = []
    new_tool = {"type": "function", "function": {"name": "dynamic_lookup"}}

    def _merge(active, tools, choice, effective_allowed, **kwargs):
        return (tools or []) + active, "auto"

    outputs, _ = await _collect(
        ctx=_ctx(correlation_id=uuid4()),
        tools_param=[{"type": "function", "function": {"name": "get_tool_info"}}],
        tool_choice="auto",
        activated_list=[new_tool],
        effective_allowed={"get_tool_info"},
        merge_activated_tools_fn=_merge,
        safe_create_task_fn=trace_tasks.append,
    )

    update = outputs[0]
    assert update["type"] == "tool_surface_update"
    assert update["reason"] == "activated_tools"
    assert update["added_tools"] == ["dynamic_lookup"]
    assert update["tools"] == ["get_tool_info", "dynamic_lookup"]
    assert trace_tasks[0]["event_type"] == "tool_surface_update"


@pytest.mark.asyncio
async def test_heartbeat_soft_budget_prunes_appends_prompt_and_continues_loop():
    trace_tasks = []

    def _prune(*args, **kwargs):
        return {
            "pruned_count": 1,
            "chars_saved": 200,
            "iterations_pruned": [0],
            "tool_call_args_pruned": 0,
            "tool_call_arg_chars_saved": 0,
        }

    outputs, state = await _collect(
        ctx=_ctx(correlation_id=uuid4()),
        iteration=1,
        context_profile_name="heartbeat",
        soft_max_llm_calls=1,
        settings_obj=_settings(IN_LOOP_PRUNING_ENABLED=True),
        prune_in_loop_tool_results_fn=_prune,
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
        monotonic_fn=lambda: 2.0,
        check_prompt_budget_guard_fn=lambda **kwargs: pytest.fail("budget gate should not run on soft-budget continue"),
    )

    event_types = [item.get("type") for item in outputs if isinstance(item, dict)]
    assert event_types == ["heartbeat_budget_pressure", "context_pruning"]
    assert outputs[-1] == LoopPreLlmIterationDone(
        tools_param=None,
        tool_choice="none",
    )
    assert state.soft_budget_slimmed is True
    assert state.messages[-1]["role"] == "system"
    assert len(trace_tasks) == 2


@pytest.mark.asyncio
async def test_pressure_pruning_emits_event_and_records_trace_before_budget_gate():
    trace_tasks = []

    def _prune(*args, **kwargs):
        return {
            "pruned_count": 2,
            "chars_saved": 400,
            "iterations_pruned": [0],
            "tool_call_args_pruned": 1,
            "tool_call_arg_chars_saved": 50,
        }

    outputs, _ = await _collect(
        ctx=_ctx(correlation_id=uuid4()),
        iteration=1,
        settings_obj=_settings(IN_LOOP_PRUNING_ENABLED=True),
        should_prune_in_loop_fn=lambda *args, **kwargs: (True, 0.91),
        prune_in_loop_tool_results_fn=_prune,
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
        get_model_context_window_fn=lambda model, provider_id: 1000,
    )

    pruning = [item for item in outputs if isinstance(item, dict) and item.get("type") == "context_pruning"][0]
    assert pruning["triggered_by"] == "pressure"
    assert pruning["tool_call_args_pruned"] == 1
    assert trace_tasks[0]["event_type"] == "context_pruning"
    assert isinstance(outputs[-1], LoopPreLlmIterationDone)


@pytest.mark.asyncio
async def test_context_breakdown_trace_and_rate_limit_wait_run_before_done():
    trace_tasks = []
    slept = []

    async def _sleep(seconds):
        slept.append(seconds)

    outputs, _ = await _collect(
        ctx=_ctx(correlation_id=uuid4()),
        state=LoopRunState(messages=[
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "hi"},
        ]),
        check_prompt_budget_guard_fn=lambda **kwargs: PromptBudgetGate(
            events=[{"type": "rate_limit_wait", "wait_seconds": 3}],
            should_return=False,
            wait_seconds=3,
        ),
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
        sleep_fn=_sleep,
    )

    assert trace_tasks[0]["event_type"] == "context_breakdown"
    assert outputs[0] == {"type": "rate_limit_wait", "wait_seconds": 3}
    assert slept == [3]
    assert isinstance(outputs[-1], LoopPreLlmIterationDone)


@pytest.mark.asyncio
async def test_prompt_budget_return_marks_loop_return():
    outputs, _ = await _collect(
        check_prompt_budget_guard_fn=lambda **kwargs: PromptBudgetGate(
            events=[{"type": "error", "code": "context_window_exceeded"}],
            should_return=True,
            wait_seconds=0,
        ),
    )

    assert outputs == [
        {"type": "error", "code": "context_window_exceeded"},
        LoopPreLlmIterationDone(tools_param=None, tool_choice=None, return_loop=True),
    ]


@pytest.mark.asyncio
async def test_late_chat_burst_is_appended_before_budget_gate():
    message_id = uuid4()
    task_id = uuid4()
    trace_tasks = []
    budget_seen = {}
    absorbed = SimpleNamespace(
        task_id=task_id,
        message_ids=[message_id],
        messages=[SimpleNamespace(id=message_id, content="also check the graph", attachments=[])],
        attachment_payloads=[],
        attachments_by_message_id={},
        session_scoped=False,
        task_scheduled_age_seconds=1.25,
    )

    async def _drain(*, iteration):
        assert iteration == 0
        return absorbed

    def _budget(**kwargs):
        budget_seen["messages"] = list(kwargs["messages"])
        return PromptBudgetGate([], False, 0)

    outputs, state = await _collect(
        ctx=_ctx(correlation_id=uuid4(), session_id=uuid4()),
        late_input_drain_fn=_drain,
        check_prompt_budget_guard_fn=_budget,
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
    )

    assert isinstance(outputs[-1], LoopPreLlmIterationDone)
    late_user = state.messages[-1]
    assert late_user["role"] == "user"
    assert late_user["content"] == "also check the graph"
    assert late_user["_skip_persist"] is True
    assert late_user["_internal_kind"] == "late_chat_burst"
    assert late_user["_source_message_id"] == str(message_id)
    assert budget_seen["messages"][-1] is late_user
    trace = [task for task in trace_tasks if task["event_type"] == "late_chat_burst_absorbed"][0]
    assert trace["event_type"] == "late_chat_burst_absorbed"
    assert trace["event_name"] == "pre_llm"
    assert trace["count"] == 1
    assert trace["data"]["task_id"] == str(task_id)
    assert trace["data"]["message_ids"] == [str(message_id)]
    assert "also check" not in str(trace["data"])


@pytest.mark.asyncio
async def test_late_chat_burst_trace_excludes_attachment_content():
    message_id = uuid4()
    attachment_id = uuid4()
    trace_tasks = []
    absorbed = SimpleNamespace(
        task_id=uuid4(),
        message_ids=[message_id],
        messages=[SimpleNamespace(id=message_id, content="use this image", attachments=[])],
        attachment_payloads=[{
            "type": "image",
            "content": "base64-secret",
            "attachment_id": str(attachment_id),
        }],
        attachments_by_message_id={
            message_id: [{
                "type": "image",
                "content": "base64-secret",
                "mime_type": "image/png",
                "attachment_id": str(attachment_id),
            }]
        },
        session_scoped=True,
        task_scheduled_age_seconds=3.0,
    )

    async def _drain(*, iteration):
        return absorbed

    _, state = await _collect(
        ctx=_ctx(correlation_id=uuid4(), session_id=uuid4()),
        late_input_drain_fn=_drain,
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
    )

    late_user = state.messages[-1]
    assert isinstance(late_user["content"], list)
    assert late_user["content"][0]["text"].startswith("use this image")
    assert late_user["content"][1]["image_url"]["url"].endswith("base64-secret")
    trace_data = [
        task for task in trace_tasks
        if task["event_type"] == "late_chat_burst_absorbed"
    ][0]["data"]
    assert trace_data["attachment_count"] == 1
    assert trace_data["session_scoped"] is True
    assert "base64-secret" not in str(trace_data)
    assert "content" not in trace_data


@pytest.mark.asyncio
async def test_late_chat_burst_failure_records_trace_and_continues():
    trace_tasks = []

    async def _drain(*, iteration):
        raise RuntimeError("db unavailable")

    outputs, state = await _collect(
        ctx=_ctx(correlation_id=uuid4(), session_id=uuid4()),
        late_input_drain_fn=_drain,
        record_trace_event_fn=lambda **kwargs: kwargs,
        safe_create_task_fn=trace_tasks.append,
    )

    assert isinstance(outputs[-1], LoopPreLlmIterationDone)
    assert state.messages == [{"role": "user", "content": "hi"}]
    trace = [
        task for task in trace_tasks
        if task["event_type"] == "late_chat_burst_absorb_failed"
    ][0]
    assert trace["data"] == {
        "iteration": 1,
        "error_type": "RuntimeError",
    }
