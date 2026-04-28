"""Live harness smoke tests for deployed Claude Code and Codex channels.

These tests intentionally target existing harness channels and create a fresh
detached Spindrel session per case. They are skipped unless the live channel
ids are supplied via env vars.
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


@dataclass(frozen=True)
class HarnessCase:
    name: str
    channel_env: str
    bot_env: str
    default_bot_id: str
    native_commands: tuple[str, ...]
    bridge_tool_visible_name: str
    light_model: str
    light_effort: str


HARNESSES = (
    HarnessCase(
        name="codex",
        channel_env="HARNESS_SMOKE_CODEX_CHANNEL_ID",
        bot_env="HARNESS_SMOKE_CODEX_BOT_ID",
        default_bot_id="codex-bot",
        native_commands=("config", "mcp-status", "skills"),
        bridge_tool_visible_name="bennie_loggins_health_summary",
        light_model=os.environ.get("HARNESS_SMOKE_CODEX_LIGHT_MODEL", "gpt-5.4-mini"),
        light_effort=os.environ.get("HARNESS_SMOKE_CODEX_LIGHT_EFFORT", "low"),
    ),
    HarnessCase(
        name="claude",
        channel_env="HARNESS_SMOKE_CLAUDE_CHANNEL_ID",
        bot_env="HARNESS_SMOKE_CLAUDE_BOT_ID",
        default_bot_id="claude-code-bot",
        native_commands=("version", "auth"),
        bridge_tool_visible_name="mcp__spindrel__bennie_loggins_health_summary",
        light_model=os.environ.get("HARNESS_SMOKE_CLAUDE_LIGHT_MODEL", "claude-haiku-4-5"),
        light_effort=os.environ.get("HARNESS_SMOKE_CLAUDE_LIGHT_EFFORT", "low"),
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
def _configured_case(case: HarnessCase) -> tuple[str, str]:
    channel_id = os.environ.get(case.channel_env, "").strip()
    if not channel_id:
        pytest.skip(f"{case.channel_env} is not set")
    return channel_id, os.environ.get(case.bot_env, case.default_bot_id).strip()


def _timeout() -> float:
    return float(os.environ.get("HARNESS_SMOKE_TIMEOUT", "300"))


async def _fresh_session(client: E2EClient, case: HarnessCase) -> tuple[str, str, str]:
    channel_id, bot_id = _configured_case(case)
    session_id = await client.create_channel_session(channel_id)
    return channel_id, session_id, bot_id


def _assert_clean_turn(result: StreamResult) -> None:
    assert result.response_text.strip(), "turn ended without assistant text"
    assert not result.error_events, [
        event.data for event in result.error_events
    ]


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


def _message_mentions_tool(message: dict, tool_name: str) -> bool:
    return any(str(value) == tool_name for value in _all_nested_values(message))


def _turn_id(result: StreamResult) -> str | None:
    for event in reversed(result.events):
        if event.type == "response":
            value = event.data.get("turn_id")
            return str(value) if value else None
    return None


async def _assert_trace_has_turn_context(client: E2EClient, result: StreamResult) -> None:
    turn_id = _turn_id(result)
    assert turn_id, "turn stream did not expose a turn/correlation id"
    trace = await client.get_trace_detail(turn_id)
    assert trace["correlation_id"] == turn_id
    kinds = {event["kind"] for event in trace["events"]}
    assert "message" in kinds or "trace_event" in kinds


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_session_controls_and_trace_diagnostics(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    original_config = await client.get_channel_config(channel_id)

    try:
        style_result = await client.execute_slash_command(
            "style",
            session_id=session_id,
            args=["terminal"],
        )
        assert style_result["result_type"] == "side_effect"
        assert style_result["payload"]["effect"] == "style"
        assert style_result["payload"]["scope_kind"] == "channel"
        assert style_result["payload"]["scope_id"] == channel_id

        model_result = await client.execute_slash_command(
            "model",
            session_id=session_id,
            args=[case.light_model],
        )
        assert model_result["payload"]["effect"] == "model"

        effort_result = await client.execute_slash_command(
            "effort",
            session_id=session_id,
            args=[case.light_effort],
        )
        assert effort_result["payload"]["effect"] == "effort"

        settings = await client.get_session_harness_settings(session_id)
        assert settings["model"] == case.light_model
        assert settings["effort"] == case.light_effort

        approval_mode = await client.set_session_approval_mode(session_id, "acceptEdits")
        assert approval_mode["mode"] == "acceptEdits"

        result = await client.chat_session_stream(
            "Diagnostics turn. Reply with exactly: harness diagnostics ok",
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert "harness diagnostics ok" in result.response_text.lower()
        await _assert_trace_has_turn_context(client, result)

        budget = await client.get_context_budget(channel_id, session_id=session_id)
        assert {"utilization", "consumed_tokens", "total_tokens"} <= set(budget.keys())
    finally:
        await client.patch_channel_config(
            channel_id,
            {"chat_mode": original_config.get("chat_mode") or "default"},
        )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_native_runtime_commands(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _, session_id, _ = await _fresh_session(client, case)

    for command in case.native_commands:
        result = await client.execute_slash_command(
            "runtime",
            session_id=session_id,
            args=[command],
        )
        assert result["result_type"] == "harness_runtime_command"
        payload = result["payload"]
        assert payload["command"] == command
        assert payload["status"] in {"ok", "error"}
        assert payload.get("detail") or result.get("fallback_text")


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_basic_turn_persists_assistant_message(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)

    result = await client.chat_session_stream(
        "Live harness smoke. Reply with exactly: harness smoke ok",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )

    _assert_clean_turn(result)
    assert "harness smoke ok" in result.response_text.lower()

    messages = await client.get_session_messages(session_id)
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    assert assistant_messages, f"no assistant message persisted for {session_id}"


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_plan_mode_round_trip(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)

    command_result = await client.execute_slash_command(
        "plan",
        session_id=session_id,
    )
    assert command_result["result_type"] == "side_effect"
    assert command_result["payload"]["effect"] == "plan"

    result = await client.chat_session_stream(
        "In plan mode, give a two-step plan for checking harness diagnostics. Do not modify files.",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )

    _assert_clean_turn(result)
    assert "plan" in result.response_text.lower() or "step" in result.response_text.lower()


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_safe_workspace_write_and_cleanup(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    if os.environ.get("HARNESS_SMOKE_INCLUDE_SAFE_WRITES", "1") != "1":
        pytest.skip("safe workspace writes disabled")

    channel_id, session_id, bot_id = await _fresh_session(client, case)
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-harness-smoke/{case.name}-{marker}.txt"
    exact_content = f"spindrel harness smoke {marker}"

    try:
        result = await client.chat_session_stream(
            (
                f"Create or overwrite the relative file {rel_path!r} with exactly "
                f"{exact_content!r}. Then read it back and report only the exact "
                "file content. Do not edit anything else."
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
        await client.chat_session_stream(
            (
                f"Delete only the relative file {rel_path!r} if it exists. "
                "If the containing .spindrel-harness-smoke directory is empty, "
                "you may remove that directory too. Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_spindrel_tool_bridge_invocation_is_visible(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    tool_name = "bennie_loggins_health_summary"

    discovery = await client.chat_session_stream(
        (
            f"Bridge diagnostic. If get_tool_info is available, call it for tool name {tool_name!r}. "
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
            f"If {tool_name} is now available, call it with recent_count 2. "
            "Do not modify files. Summarize whether the tool call succeeded."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(invocation)

    messages = await client.get_session_messages(session_id, limit=20)
    assert any(_message_mentions_tool(m, case.bridge_tool_visible_name) for m in messages), (
        f"{case.bridge_tool_visible_name} was not visible in persisted session messages for {session_id}"
    )
