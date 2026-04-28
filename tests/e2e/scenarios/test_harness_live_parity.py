"""Live parity diagnostics for Codex and Claude Code harness channels.

These tests target real deployed harness channels and create a fresh detached
Spindrel session per scenario. They are skipped unless channel ids are supplied.

Tiers are controlled by ``HARNESS_PARITY_TIER``:

- ``core`` (default): runtime controls, trace, status, basic context telemetry.
- ``bridge``: core plus Spindrel bridge discovery/invocation persistence.
- ``writes``: bridge plus safe temporary workspace write/read/delete.
- ``context``: writes plus context-pressure and native compaction checks.
"""

from __future__ import annotations

import os
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
    "writes": 2,
    "context": 3,
}


@dataclass(frozen=True)
class HarnessCase:
    name: str
    runtime: str
    channel_env: str
    bot_env: str
    default_bot_id: str
    native_commands: tuple[str, ...]
    bridge_visible_names: tuple[str, ...]
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
        native_commands=("config", "mcp-status", "skills"),
        bridge_visible_names=("bennie_loggins_health_summary",),
        model_candidates=(
            "gpt-5.3-codex-spark",
            "gpt-5.4-mini",
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
        bridge_visible_names=(
            "mcp__spindrel__bennie_loggins_health_summary",
            "bennie_loggins_health_summary",
        ),
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

        for command in case.native_commands:
            result = await client.execute_slash_command("runtime", session_id=session_id, args=[command])
            assert result["result_type"] == "harness_runtime_command"
            assert result["payload"]["command"] == command
            assert result["payload"]["status"] in {"ok", "error"}
            assert result["payload"].get("detail") or result.get("fallback_text")

        context = await client.execute_slash_command("context", session_id=session_id)
        assert context["result_type"] == "harness_context_summary"
        assert context["payload"]["runtime"] == case.runtime

        result = await client.chat_session_stream(
            "Harness parity core check. Include the exact phrase: parity core ok",
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert "parity core ok" in result.response_text.lower()
        await _assert_trace_has_turn_context(client, result)

        status = await client.get_session_harness_status(session_id)
        assert status["runtime"] == case.runtime
        assert status["usage"], "harness status did not expose latest runtime usage"
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
    tool_name = "bennie_loggins_health_summary"

    discovery = await client.chat_session_stream(
        (
            f"Bridge parity diagnostic. If get_tool_info is available, call it for {tool_name!r}. "
            "Do not modify files. Briefly say whether the schema loaded."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(discovery)

    invocation = await client.chat_session_stream(
        (
            f"Now call {tool_name} with recent_count 2 if it is available. "
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
    assert any(_message_mentions_any_tool(message, case.bridge_visible_names) for message in assistants), (
        f"{case.bridge_visible_names} was not visible in persisted assistant messages for {session_id}"
    )
    assert any(_has_persisted_tool_transcript(message) for message in assistants), (
        "bridge tool calls did not persist canonical tool_calls + assistant_turn_body"
    )


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
    assert second_tokens >= first_tokens, (
        f"context estimate did not grow across turns: {first_tokens} -> {second_tokens}"
    )

    compact = await client.execute_slash_command("compact", session_id=session_id)
    assert compact["result_type"] == "harness_native_compaction"
    assert compact["payload"]["status"] == "completed"

    compact_status = await client.get_session_harness_status(session_id)
    native = compact_status.get("native_compaction") or {}
    assert native.get("status") == "completed"
    remaining = compact_status.get("context_remaining_pct")
    assert remaining is None or remaining >= 50.0
