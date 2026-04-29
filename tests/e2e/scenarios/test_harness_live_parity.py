"""Live parity diagnostics for Codex and Claude Code harness channels.

These tests target real deployed harness channels and create a fresh detached
Spindrel session per scenario. They are skipped unless channel ids are supplied.

Tiers are controlled by ``HARNESS_PARITY_TIER``:

- ``core`` (default): runtime controls, trace, status, basic context telemetry.
- ``bridge``: core plus Spindrel bridge discovery/invocation persistence.
- ``plan``: bridge plus native plan-mode round-trip checks.
- ``writes``: plan plus safe temporary workspace write/read/delete.
- ``context``: writes plus context-pressure and native compaction checks.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.streaming import StreamResult


pytestmark = pytest.mark.e2e


TIER_ORDER = {
    "core": 0,
    "bridge": 1,
    "plan": 2,
    "writes": 3,
    "context": 4,
}


CORE_BRIDGE_BASELINE_TOOLS = (
    "get_tool_info",
    "list_channels",
    "read_conversation_history",
    "list_sub_sessions",
    "read_sub_session",
)


@dataclass(frozen=True)
class HarnessCase:
    name: str
    runtime: str
    channel_env: str
    bot_env: str
    default_bot_id: str
    native_commands: tuple[str, ...]
    model_candidates: tuple[str, ...]
    effort_env: str
    model_env: str


HARNESSES = (
    HarnessCase(
        name="codex",
        runtime="codex",
        channel_env="HARNESS_PARITY_CODEX_CHANNEL_ID",
        bot_env="HARNESS_PARITY_CODEX_BOT_ID",
        default_bot_id="codex-bot",
        native_commands=("config", "mcp-status", "plugins", "skills", "features"),
        model_candidates=(
            "gpt-5.4-mini",
            "gpt-5.3-codex-spark",
        ),
        effort_env="HARNESS_PARITY_CODEX_EFFORT",
        model_env="HARNESS_PARITY_CODEX_MODEL",
    ),
    HarnessCase(
        name="claude",
        runtime="claude-code",
        channel_env="HARNESS_PARITY_CLAUDE_CHANNEL_ID",
        bot_env="HARNESS_PARITY_CLAUDE_BOT_ID",
        default_bot_id="claude-code-bot",
        native_commands=("version", "auth"),
        model_candidates=("claude-haiku-4-5",),
        effort_env="HARNESS_PARITY_CLAUDE_EFFORT",
        model_env="HARNESS_PARITY_CLAUDE_MODEL",
    ),
)


HARNESS_PARAMS = tuple(
    pytest.param(
        case,
        id=case.name,
        marks=pytest.mark.skipif(
            not os.environ.get(case.channel_env, "").strip(),
            reason=f"{case.channel_env} is not set",
        ),
    )
    for case in HARNESSES
)


def _tier() -> str:
    value = os.environ.get("HARNESS_PARITY_TIER", "core").strip().lower() or "core"
    return value if value in TIER_ORDER else "core"


def _requires_tier(required: str) -> None:
    if TIER_ORDER[_tier()] < TIER_ORDER[required]:
        pytest.skip(f"HARNESS_PARITY_TIER={required!r} or higher is required")


def _timeout() -> float:
    return float(os.environ.get("HARNESS_PARITY_TIMEOUT", "300"))


def _bridge_tool_name() -> str:
    return os.environ.get("HARNESS_PARITY_BRIDGE_TOOL", "list_channels").strip() or "list_channels"


def _bridge_tool_args() -> dict[str, Any]:
    raw = os.environ.get("HARNESS_PARITY_BRIDGE_TOOL_ARGS", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"HARNESS_PARITY_BRIDGE_TOOL_ARGS is not JSON: {exc}") from exc
    assert isinstance(parsed, dict), "HARNESS_PARITY_BRIDGE_TOOL_ARGS must be a JSON object"
    return parsed


def _bridge_visible_names(tool_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((
        tool_name,
        f"mcp__spindrel__{tool_name}",
    )))


def _configured_case(case: HarnessCase) -> tuple[str, str]:
    channel_id = os.environ.get(case.channel_env, "").strip()
    if not channel_id:
        pytest.skip(f"{case.channel_env} is not set")
    return channel_id, os.environ.get(case.bot_env, case.default_bot_id).strip()


async def _fresh_session(client: E2EClient, case: HarnessCase) -> tuple[str, str, str]:
    channel_id, bot_id = _configured_case(case)
    session_id = await client.create_channel_session(channel_id)
    return channel_id, session_id, bot_id


def _assert_clean_turn(result: StreamResult) -> None:
    assert result.response_text.strip(), "turn ended without assistant text"
    assert not result.error_events, [event.data for event in result.error_events]


def _turn_id(result: StreamResult) -> str | None:
    for event in reversed(result.events):
        if event.type == "response":
            value = event.data.get("turn_id")
            return str(value) if value else None
    return None


def _all_nested_values(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_nested_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_nested_values(nested)
    else:
        yield value


def _message_mentions_any_tool(message: dict, names: tuple[str, ...]) -> bool:
    values = {str(value) for value in _all_nested_values(message)}
    return any(name in values for name in names)


def _assistant_messages(messages: list[dict]) -> list[dict]:
    return [message for message in messages if message.get("role") == "assistant"]


def _has_persisted_tool_transcript(message: dict) -> bool:
    tool_calls = message.get("tool_calls")
    meta = message.get("metadata") or {}
    body = meta.get("assistant_turn_body") if isinstance(meta, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    return bool(tool_calls) and any(
        isinstance(item, dict) and item.get("kind") == "tool_call"
        for item in (items or [])
    )


def _has_persisted_tool_result_envelope(message: dict) -> bool:
    tool_call_ids = {
        call.get("id")
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and isinstance(call.get("id"), str)
    }
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    return any(
        isinstance(result, dict) and isinstance(result.get("content_type"), str)
        and (
            not tool_call_ids
            or not result.get("tool_call_id")
            or result.get("tool_call_id") in tool_call_ids
        )
        for result in (tool_results or [])
    )


def _has_persisted_tool_result_containing(message: dict, expected: str) -> bool:
    tool_call_ids = {
        call.get("id")
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and isinstance(call.get("id"), str)
    }
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    return any(
        isinstance(result, dict)
        and result.get("content_type") in {"text/plain", "text/markdown"}
        and (
            not tool_call_ids
            or not result.get("tool_call_id")
            or result.get("tool_call_id") in tool_call_ids
        )
        and expected in str(result.get("body") or result.get("plain_body") or "")
        for result in (tool_results or [])
    )


def _has_get_tool_info_schema_envelope(message: dict, tool_name: str) -> bool:
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        if result.get("tool_name") != "get_tool_info":
            continue
        body = result.get("body")
        if not isinstance(body, str):
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        schema = parsed.get("schema") if isinstance(parsed, dict) else None
        fn = schema.get("function") if isinstance(schema, dict) else None
        if isinstance(fn, dict) and fn.get("name") == tool_name:
            return True
    return False


def _assert_bridge_baseline(
    status: dict,
    *,
    required: tuple[str, ...] = CORE_BRIDGE_BASELINE_TOOLS,
) -> None:
    bridge = status.get("bridge_status") or {}
    exported = set(str(name) for name in bridge.get("exported_tools") or [])
    required_seen = set(str(name) for name in bridge.get("required_baseline_tools") or [])
    missing = set(str(name) for name in bridge.get("missing_baseline_tools") or [])
    assert not missing, f"missing harness bridge baseline tools: {sorted(missing)}"
    for tool_name in required:
        assert tool_name in exported or tool_name in required_seen, (
            f"{tool_name!r} was not visible in harness bridge status: {bridge}"
        )


def _model_option_map(caps: dict) -> dict[str, dict]:
    options = caps.get("model_options") or []
    return {
        str(option.get("id")): option
        for option in options
        if isinstance(option, dict) and option.get("id")
    }


def _choose_model_and_effort(case: HarnessCase, caps: dict) -> tuple[str | None, str | None]:
    options = _model_option_map(caps)
    available = set(str(model) for model in (caps.get("available_models") or []))
    available.update(options)
    available.update(str(model) for model in (caps.get("supported_models") or []))

    requested_model = os.environ.get(case.model_env, "").strip()
    candidates = (requested_model,) if requested_model else case.model_candidates
    model = next((candidate for candidate in candidates if candidate in available), None)
    if model is None and options:
        model = next(iter(options))
    if model is None and available:
        model = sorted(available)[0]

    option = options.get(model or "")
    effort_values = []
    if isinstance(option, dict):
        effort_values = [str(value) for value in option.get("effort_values") or []]
    if not effort_values:
        effort_values = [str(value) for value in caps.get("effort_values") or []]

    requested_effort = os.environ.get(case.effort_env, "").strip()
    if requested_effort and requested_effort in effort_values:
        return model, requested_effort
    for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
        if effort in effort_values:
            return model, effort
    return model, None


async def _configure_low_cost_session(
    client: E2EClient,
    case: HarnessCase,
    session_id: str,
) -> tuple[str | None, str | None, dict]:
    caps = await client.get_runtime_capabilities(case.runtime)
    model, effort = _choose_model_and_effort(case, caps)
    if model:
        result = await client.execute_slash_command("model", session_id=session_id, args=[model])
        assert result["payload"]["effect"] == "model"
    if effort:
        result = await client.execute_slash_command("effort", session_id=session_id, args=[effort])
        assert result["payload"]["effect"] == "effort"
    settings = await client.get_session_harness_settings(session_id)
    if model:
        assert settings["model"] == model
    if effort:
        assert settings["effort"] == effort
    return model, effort, caps


async def _assert_trace_has_turn_context(client: E2EClient, result: StreamResult) -> dict:
    turn_id = _turn_id(result)
    assert turn_id, "turn stream did not expose a turn/correlation id"
    trace = await client.get_trace_detail(turn_id)
    assert trace["correlation_id"] == turn_id
    kinds = {event["kind"] for event in trace["events"]}
    assert "message" in kinds or "trace_event" in kinds
    return trace


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_parity_controls_trace_and_context(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    original_config = await client.get_channel_config(channel_id)

    try:
        model, effort, caps = await _configure_low_cost_session(client, case, session_id)
        approval_mode = await client.set_session_approval_mode(session_id, "acceptEdits")
        assert approval_mode["mode"] == "acceptEdits"

        style = await client.execute_slash_command("style", session_id=session_id, args=["terminal"])
        assert style["payload"]["effect"] == "style"
        assert style["payload"]["scope_id"] == channel_id
        terminal_config = await client.get_channel_config(channel_id)
        assert terminal_config.get("chat_mode") == "terminal"

        for command in case.native_commands:
            result = await client.execute_slash_command("runtime", session_id=session_id, args=[command])
            assert result["result_type"] == "harness_runtime_command"
            assert result["payload"]["command"] == command
            assert result["payload"]["status"] in {"ok", "error"}
            assert result["payload"].get("detail") or result.get("fallback_text")

        context = await client.execute_slash_command("context", session_id=session_id)
        assert context["result_type"] == "harness_context_summary"
        assert context["payload"]["runtime"] == case.runtime

        marker = uuid.uuid4().hex[:12]
        result = await client.chat_session_stream(
            (
                f"Harness parity core check. Store this test marker for the next turn: {marker}. "
                "For this turn only, reply exactly: parity core ready"
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert "parity core ready" in result.response_text.lower()
        await _assert_trace_has_turn_context(client, result)

        resumed = await client.chat_session_stream(
            "Reply with only the stored test marker from the previous turn. Do not repeat any other prior phrase.",
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(resumed)
        assert marker in resumed.response_text
        await _assert_trace_has_turn_context(client, resumed)

        status = await client.get_session_harness_status(session_id)
        assert status["runtime"] == case.runtime
        assert status["harness_session_id"], "native harness session id was not persisted"
        assert status["usage"], "harness status did not expose latest runtime usage"
        _assert_bridge_baseline(status)
        if model:
            assert status["model"] == model
        if effort:
            assert status["effort"] == effort
        diagnostics = status.get("context_diagnostics") or {}
        assert diagnostics.get("confidence") in {"medium", "high", "low"}
        assert status.get("context_window_tokens") or caps.get("context_window_tokens")

        budget = await client.get_context_budget(channel_id, session_id=session_id)
        assert {"utilization", "consumed_tokens", "total_tokens"} <= set(budget.keys())

        messages = await client.get_session_messages(session_id)
        assert _assistant_messages(messages), "assistant message did not persist"
    finally:
        await client.patch_channel_config(
            channel_id,
            {"chat_mode": original_config.get("chat_mode") or "default"},
        )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_bridge_tools_persist_and_renderable(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("bridge")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    tool_name = _bridge_tool_name()
    tool_args = _bridge_tool_args()
    visible_names = _bridge_visible_names(tool_name)
    discovery_args = json.dumps({"tool_name": tool_name}, sort_keys=True)

    discovery = await client.chat_session_stream(
        (
            f"Bridge parity diagnostic. You must call exactly the host-provided "
            f"get_tool_info tool now with JSON arguments "
            f"{discovery_args}. Do not call {tool_name} in this turn. "
            "Do not use shell commands. Do not modify files. Briefly say whether "
            "get_tool_info returned a callable schema."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(discovery)

    invocation = await client.chat_session_stream(
        (
            f"Now call the host-provided {tool_name} tool with this exact JSON object as "
            f"arguments: {json.dumps(tool_args, sort_keys=True)}. Do not use shell commands. "
            "Do not modify files. Summarize whether the call succeeded."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(invocation)
    await _assert_trace_has_turn_context(client, invocation)

    messages = await client.get_session_messages(session_id, limit=30)
    assistants = _assistant_messages(messages)
    assert any(_has_get_tool_info_schema_envelope(message, tool_name) for message in assistants), (
        f"get_tool_info did not persist a callable schema envelope for {tool_name!r}"
    )
    assert any(_message_mentions_any_tool(message, visible_names) for message in assistants), (
        f"{visible_names} was not visible in persisted assistant messages for {session_id}"
    )
    assert any(_has_persisted_tool_transcript(message) for message in assistants), (
        "bridge tool calls did not persist canonical tool_calls + assistant_turn_body"
    )
    bridge_messages = [
        message for message in assistants if _message_mentions_any_tool(message, visible_names)
    ]
    assert any(_has_persisted_tool_result_envelope(message) for message in bridge_messages), (
        "bridge tool calls did not persist ToolResultEnvelope metadata for UI rendering"
    )
    status = await client.get_session_harness_status(session_id)
    _assert_bridge_baseline(status)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_plan_mode_round_trip(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("plan")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    command_result = await client.execute_slash_command("plan", session_id=session_id)
    assert command_result["result_type"] == "side_effect"
    assert command_result["payload"]["effect"] == "plan"

    plan_status = await client.get_session_harness_status(session_id)
    assert plan_status["session_plan_mode"] == "planning"

    result = await client.chat_session_stream(
        (
            "In native plan mode, give a two-step plan for checking harness diagnostics. "
            "Do not modify files."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
        harness_question_answer={
            "answer": "General diagnostic scan. Please provide the concise two-step diagnostic plan without modifying files.",
            "selected_options": ["General diagnostic scan"],
            "notes": "E2E plan-mode parity answer.",
        },
    )
    _assert_clean_turn(result)
    response_text = result.response_text.strip()
    assert response_text, "plan-mode turn returned no assistant text"
    lower_response = response_text.lower()
    assert (
        "plan" in lower_response
        or "step" in lower_response
        or bool(re.search(r"(^|\n)\s*1[.)]\s+", response_text))
    ), f"plan-mode turn did not look like a plan: {response_text!r}"
    await _assert_trace_has_turn_context(client, result)

    after_status = await client.get_session_harness_status(session_id)
    assert after_status["session_plan_mode"] == "planning"
    assert after_status["runtime"] == case.runtime
    _assert_bridge_baseline(after_status)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_safe_workspace_write_read_delete(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("writes")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-harness-parity/{case.name}-{marker}.txt"
    exact_content = f"spindrel harness parity {marker}"

    try:
        result = await client.chat_session_stream(
            (
                f"Create or overwrite the relative file {rel_path!r} with exactly "
                f"{exact_content!r}. Then read it back and report only the exact file content. "
                "Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert marker in result.response_text
        assert result.tool_events, "no live tool events were emitted for the write turn"
        messages = await client.get_session_messages(session_id, limit=20)
        assistants = _assistant_messages(messages)
        assert any(
            _has_persisted_tool_result_containing(message, exact_content)
            for message in assistants
        ), "write/read turn did not persist a readable tool-result envelope with file content"
    finally:
        cleanup = await client.chat_session_stream(
            (
                f"Delete only the relative file {rel_path!r} if it exists. "
                "If the containing .spindrel-harness-parity directory is empty, "
                "you may remove that directory too. Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(cleanup)


@pytest.mark.asyncio
async def test_live_claude_harness_default_mode_write_approval_resume(
    client: E2EClient,
) -> None:
    _requires_tier("writes")
    case = HARNESSES[1]
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-harness-parity/claude-approval-{marker}.txt"
    exact_content = f"spindrel harness approval {marker}"

    try:
        approval_mode = await client.set_session_approval_mode(session_id, "default")
        assert approval_mode["mode"] == "default"

        result = await client.chat_session_stream(
            (
                f"Create or overwrite the relative file {rel_path!r} with exactly "
                f"{exact_content!r}. Then read it back and report only the exact file content. "
                "Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
            approval_decision={
                "approved": True,
                "decided_by": "e2e_harness_parity",
                "bypass_rest_of_turn": True,
            },
        )
        _assert_clean_turn(result)
        assert marker in result.response_text
        assert any(event.type == "approval_request" for event in result.events), (
            "Claude default mode write did not request harness approval"
        )
        assert any(
            event.type == "approval_resolved" and event.data.get("decision") == "approved"
            for event in result.events
        ), "Claude harness approval did not resolve as approved"

        messages = await client.get_session_messages(session_id, limit=20)
        assistants = _assistant_messages(messages)
        assert any(
            _has_persisted_tool_result_containing(message, exact_content)
            for message in assistants
        ), "approved Claude write/read did not persist readable result content"
    finally:
        await client.set_session_approval_mode(session_id, "bypassPermissions")
        cleanup = await client.chat_session_stream(
            (
                f"Delete only the relative file {rel_path!r} if it exists. "
                "Do not delete any other files or directories."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(cleanup)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_context_pressure_and_native_compact(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("context")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    caps = await client.get_runtime_capabilities(case.runtime)
    if not caps.get("native_compaction"):
        pytest.skip(f"{case.runtime} does not advertise native compaction")

    filler = "context-pressure-token " * int(os.environ.get("HARNESS_PARITY_CONTEXT_FILL_WORDS", "80"))
    first = await client.chat_session_stream(
        (
            "Context pressure sample one. The payload below is context only; do not repeat it. "
            "Reply with exactly: pressure one ok\n\n"
            f"Payload:\n{filler[:1000]}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(first)
    first_status = await client.get_session_harness_status(session_id)

    second = await client.chat_session_stream(
        (
            "Context pressure sample two. The payload below is context only; do not repeat it. "
            "Reply with exactly: pressure two ok\n\n"
            f"Payload:\n{filler}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(second)
    second_status = await client.get_session_harness_status(session_id)

    first_diag = first_status.get("context_diagnostics") or {}
    second_diag = second_status.get("context_diagnostics") or {}
    first_tokens = first_diag.get("context_tokens")
    second_tokens = second_diag.get("context_tokens")
    if not isinstance(first_tokens, int) or not isinstance(second_tokens, int):
        pytest.skip("runtime did not report comparable context token estimates")
    assert first_tokens >= 0
    assert second_tokens >= 0

    compact = await client.execute_slash_command("compact", session_id=session_id)
    assert compact["result_type"] == "harness_native_compaction"
    assert compact["payload"]["status"] == "completed"

    compact_status = await client.get_session_harness_status(session_id)
    native = compact_status.get("native_compaction") or {}
    assert native.get("status") == "completed"
    remaining = compact_status.get("context_remaining_pct")
    assert remaining is None or remaining >= 50.0
