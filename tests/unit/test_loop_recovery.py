import json

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.llm import AccumulatedMessage
from app.agent.loop_recovery import LoopRecoveryDone, stream_loop_recovery
from app.agent.loop_state import LoopRunContext, LoopRunState


def _ctx():
    return LoopRunContext(
        bot=BotConfig(
            id="bot-1",
            name="Test Bot",
            model="gpt-4",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(),
        ),
        session_id=None,
        client_id="client-1",
        correlation_id=None,
        channel_id=None,
        compaction=False,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


async def _collect(**overrides):
    state = overrides.pop("state", LoopRunState(messages=[{"role": "assistant", "content": "done"}]))
    outputs = [
        item async for item in stream_loop_recovery(
            accumulated_msg=overrides.pop("accumulated_msg", AccumulatedMessage(content="done")),
            ctx=overrides.pop("ctx", _ctx()),
            state=state,
            iteration=overrides.pop("iteration", 0),
            model=overrides.pop("model", "gpt-4"),
            tools_param=overrides.pop("tools_param", None),
            effective_provider_id=overrides.pop("effective_provider_id", "openai"),
            fallback_models=overrides.pop("fallback_models", None),
            effective_allowed=overrides.pop("effective_allowed", None),
            recover_tool_calls_from_text_fn=overrides.pop("recover_tool_calls_from_text_fn", lambda *args: None),
            handle_no_tool_calls_path_fn=overrides.pop("handle_no_tool_calls_path_fn", _no_tool_path),
            llm_call_fn=overrides.pop("llm_call_fn", object()),
        )
    ]
    assert not overrides
    return outputs, state


async def _no_tool_path(**kwargs):
    yield {"type": "response", "text": kwargs["accumulated_msg"].content or ""}


@pytest.mark.asyncio
async def test_existing_tool_calls_skip_no_tool_path():
    async def _fail_no_tool(**kwargs):
        raise AssertionError("no-tool path should not run when tool calls exist")
        yield {}

    msg = AccumulatedMessage(
        content=None,
        tool_calls=[{
            "id": "tc_1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }],
    )

    outputs, _ = await _collect(
        accumulated_msg=msg,
        handle_no_tool_calls_path_fn=_fail_no_tool,
    )

    assert outputs == [LoopRecoveryDone(has_tool_calls=True)]


@pytest.mark.asyncio
async def test_recovered_tool_calls_continue_to_tool_iteration():
    def _recover(accumulated_msg, messages, effective_allowed):
        accumulated_msg.tool_calls = [{
            "id": "tc_1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }]

    async def _fail_no_tool(**kwargs):
        raise AssertionError("no-tool path should not run after recovery")
        yield {}

    outputs, _ = await _collect(
        accumulated_msg=AccumulatedMessage(content='{"name":"search"}'),
        effective_allowed={"search"},
        recover_tool_calls_from_text_fn=_recover,
        handle_no_tool_calls_path_fn=_fail_no_tool,
    )

    assert outputs == [LoopRecoveryDone(has_tool_calls=True)]


@pytest.mark.asyncio
async def test_no_tool_path_events_are_forwarded_then_return_loop():
    async def _no_tool(**kwargs):
        yield {"type": "warning", "code": "empty_response"}
        yield {"type": "response", "text": "forced"}

    outputs, _ = await _collect(
        accumulated_msg=AccumulatedMessage(content="done"),
        handle_no_tool_calls_path_fn=_no_tool,
    )

    assert outputs == [
        {"type": "warning", "code": "empty_response"},
        {"type": "response", "text": "forced"},
        LoopRecoveryDone(has_tool_calls=False, return_loop=True),
    ]


@pytest.mark.asyncio
async def test_plan_mode_structured_question_card_synthesizes_tool_call():
    async def _fail_no_tool(**kwargs):
        raise AssertionError("plan-mode question-card recovery should continue to tool iteration")
        yield {}

    state = LoopRunState(messages=[
        {
            "role": "system",
            "content": "Plan mode is active. If the user explicitly asks for a structured question card, you must use ask_plan_questions.",
        },
        {
            "role": "user",
            "content": (
                "Use a structured question card titled 'Quality readiness questions' "
                "because there is no target subsystem, success signal, mutation scope, or verification expectation."
            ),
        },
        {
            "role": "assistant",
            "content": "## Quality readiness questions\n\n1. What should I build?",
        },
    ])
    msg = AccumulatedMessage(content="## Quality readiness questions\n\n1. What should I build?")

    outputs, _ = await _collect(
        accumulated_msg=msg,
        state=state,
        tools_param=[{"type": "function", "function": {"name": "ask_plan_questions"}}],
        handle_no_tool_calls_path_fn=_fail_no_tool,
    )

    assert outputs == [LoopRecoveryDone(has_tool_calls=True)]
    assert msg.content == ""
    assert msg.tool_calls
    call = msg.tool_calls[0]
    assert call["function"]["name"] == "ask_plan_questions"
    assert "Quality readiness questions" in call["function"]["arguments"]
    assert state.messages[-1]["content"] == ""
    assert state.messages[-1]["tool_calls"] == msg.tool_calls


@pytest.mark.asyncio
async def test_plan_mode_structured_question_card_appends_to_existing_tool_call():
    async def _fail_no_tool(**kwargs):
        raise AssertionError("plan-mode question-card recovery should continue to tool iteration")
        yield {}

    existing_tool_call = {
        "id": "tc_skill",
        "type": "function",
        "function": {"name": "get_skill", "arguments": "{\"skill_id\":\"grill_me\"}"},
    }
    state = LoopRunState(messages=[
        {
            "role": "system",
            "content": "Plan mode is active. If the user explicitly asks for a structured question card, you must use ask_plan_questions.",
        },
        {
            "role": "user",
            "content": (
                "The user asks for a plan but gives no target subsystem, success signal, "
                "mutation scope, or verification expectation. Use a structured question "
                "card titled 'Quality readiness questions'."
            ),
        },
        {
            "role": "assistant",
            "content": "### Quality readiness questions\n\n1. What subsystem or surface is this plan for?",
            "tool_calls": [existing_tool_call],
        },
    ])
    msg = AccumulatedMessage(
        content="### Quality readiness questions\n\n1. What subsystem or surface is this plan for?",
        tool_calls=[existing_tool_call],
    )

    outputs, _ = await _collect(
        accumulated_msg=msg,
        state=state,
        tools_param=[
            {"type": "function", "function": {"name": "get_skill"}},
            {"type": "function", "function": {"name": "ask_plan_questions"}},
        ],
        handle_no_tool_calls_path_fn=_fail_no_tool,
    )

    assert outputs == [LoopRecoveryDone(has_tool_calls=True)]
    assert msg.content == ""
    assert [call["function"]["name"] for call in msg.tool_calls or []] == [
        "get_skill",
        "ask_plan_questions",
    ]
    assert msg.tool_calls[0] is existing_tool_call
    assert "Quality readiness questions" in msg.tool_calls[1]["function"]["arguments"]
    assert state.messages[-1]["content"] == ""
    assert state.messages[-1]["tool_calls"] == msg.tool_calls


@pytest.mark.asyncio
async def test_plan_mode_publish_validation_error_retries_repaired_tool_call():
    async def _fail_no_tool(**kwargs):
        raise AssertionError("publish_plan validation recovery should continue to tool iteration")
        yield {}

    prior_args = {
        "title": "Native Spindrel Plan Parity",
        "summary": "Verify native Spindrel plan mode can publish and render a plan artifact.",
        "scope": "Live E2E diagnostics only; do not modify repository files.",
        "key_changes": ["Exercise native plan publication mechanics."],
        "interfaces": ["No public API or UI interface changes."],
        "assumptions_and_defaults": ["Live diagnostics can use the dedicated E2E channel."],
        "acceptance_criteria": ["Plan state has revision 1."],
        "test_plan": ["Inspect the rendered plan artifact."],
        "steps": [
            {"id": "step-1", "label": "Start native plan mode"},
            {"id": "step-2", "label": "Publish the inline plan artifact"},
            {"id": "step-3", "label": "Capture docs screenshots"},
            {"id": "step-4", "label": "Verify"},
        ],
    }
    state = LoopRunState(
        messages=[
            {"role": "system", "content": "Plan mode is active. Use publish_plan for structured drafts."},
            {"role": "user", "content": "Publish a professional native plan."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "tc_publish",
                    "type": "function",
                    "function": {
                        "name": "publish_plan",
                        "arguments": json.dumps(prior_args),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_publish",
                "content": "Step 'step-4' needs a concrete, outcome-oriented action label.",
            },
            {
                "role": "assistant",
                "content": "I hit a plan validation issue. If you want, I can republish it.",
            },
        ],
        tool_calls_made=["publish_plan"],
    )
    msg = AccumulatedMessage(content="I hit a plan validation issue. If you want, I can republish it.")

    outputs, _ = await _collect(
        accumulated_msg=msg,
        state=state,
        tools_param=[{"type": "function", "function": {"name": "publish_plan"}}],
        handle_no_tool_calls_path_fn=_fail_no_tool,
    )

    assert outputs == [LoopRecoveryDone(has_tool_calls=True)]
    assert msg.content == ""
    assert msg.tool_calls
    call = msg.tool_calls[0]
    assert call["function"]["name"] == "publish_plan"
    repaired_args = json.loads(call["function"]["arguments"])
    repaired_step = repaired_args["steps"][3]
    assert repaired_step["id"] == "step-4"
    assert repaired_step["label"] == "Verify Native Spindrel Plan Parity against acceptance criteria"
    assert state.messages[-1]["content"] == ""
    assert state.messages[-1]["tool_calls"] == msg.tool_calls


@pytest.mark.asyncio
async def test_plan_mode_publish_validation_retry_runs_once():
    state = LoopRunState(
        messages=[
            {"role": "system", "content": "Plan mode is active. Use publish_plan for structured drafts."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "tc_publish",
                    "type": "function",
                    "function": {
                        "name": "publish_plan",
                        "arguments": json.dumps({
                            "title": "Plan Retry",
                            "summary": "Retry a failed plan.",
                            "scope": "Recovery only.",
                            "steps": [{"id": "step-1", "label": "Verify"}],
                        }),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_publish",
                "content": "Step 'step-1' needs a concrete, outcome-oriented action label.",
            },
            {"role": "assistant", "content": "I still cannot publish this."},
        ],
        tool_calls_made=["publish_plan", "publish_plan"],
    )

    outputs, _ = await _collect(
        accumulated_msg=AccumulatedMessage(content="I still cannot publish this."),
        state=state,
        tools_param=[{"type": "function", "function": {"name": "publish_plan"}}],
    )

    assert outputs == [
        {"type": "response", "text": "I still cannot publish this."},
        LoopRecoveryDone(has_tool_calls=False, return_loop=True),
    ]
