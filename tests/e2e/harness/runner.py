"""Scenario runner — executes YAML scenarios against the E2E harness."""

from __future__ import annotations

import logging
from typing import Any

from .assertions import (
    assert_contains_all,
    assert_contains_any,
    assert_does_not_contain,
    assert_no_error_events,
    assert_no_tools_called,
    assert_response_length,
    assert_response_matches,
    assert_response_not_empty,
    assert_stream_event_sequence,
    assert_tool_called,
    assert_tool_called_all,
    assert_tool_called_with_args,
    assert_tool_count,
    assert_tool_not_called,
)
from .client import E2EClient
from .scenario import (
    InlineBotConfig,
    Scenario,
    ScenarioResult,
    ScenarioStep,
    StepAssertion,
    StepResult,
)
from .streaming import StreamResult

logger = logging.getLogger(__name__)


# -- Assertion dispatcher --
# Maps YAML assertion keys to handler functions.
# Each handler returns None on success or an error string on failure.


def _dispatch_assertion(
    assertion: StepAssertion,
    response_text: str,
    stream_result: StreamResult | None,
) -> str | None:
    """Run a single assertion, return None on pass or error message on fail."""
    key = assertion.key
    value = assertion.value
    tools_used = stream_result.tools_used if stream_result else []
    events = stream_result.events if stream_result else []
    tool_events = stream_result.tool_events if stream_result else []

    try:
        if key == "response_not_empty":
            assert_response_not_empty(response_text)

        elif key == "response_contains_any":
            assert_contains_any(response_text, value)

        elif key == "response_contains_all":
            assert_contains_all(response_text, value)

        elif key == "response_not_contains":
            assert_does_not_contain(response_text, value)

        elif key == "response_matches":
            assert_response_matches(response_text, value)

        elif key == "response_length":
            assert_response_length(
                response_text,
                min_chars=value.get("min", 0),
                max_chars=value.get("max", 10000),
            )

        elif key == "no_errors":
            if not stream_result:
                return "no_errors requires streaming (stream: true)"
            assert_no_error_events(events)

        elif key == "event_sequence":
            if not stream_result:
                return "event_sequence requires streaming (stream: true)"
            assert_stream_event_sequence(events, value)

        elif key == "tool_called":
            if not stream_result:
                logger.warning(
                    "tool_called assertion on non-streaming step — "
                    "tool events not available, skipping"
                )
                return None
            assert_tool_called(tools_used, value)

        elif key == "tool_called_all":
            if not stream_result:
                return "tool_called_all requires streaming (stream: true)"
            assert_tool_called_all(tools_used, value)

        elif key == "tool_not_called":
            if not stream_result:
                logger.warning(
                    "tool_not_called assertion on non-streaming step — skipping"
                )
                return None
            assert_tool_not_called(tools_used, value)

        elif key == "no_tools_called":
            if not stream_result:
                logger.warning(
                    "no_tools_called assertion on non-streaming step — skipping"
                )
                return None
            assert_no_tools_called(tools_used)

        elif key == "tool_count":
            if not stream_result:
                return "tool_count requires streaming (stream: true)"
            assert_tool_count(
                tools_used,
                min_count=value.get("min"),
                max_count=value.get("max"),
            )

        elif key == "tool_called_with_args":
            if not stream_result:
                return "tool_called_with_args requires streaming (stream: true)"
            assert_tool_called_with_args(
                tool_events,
                tool_name=value["tool"],
                args_contain=value.get("args", {}),
            )

        else:
            return f"Unknown assertion key: {key!r}"

    except AssertionError as e:
        return str(e)

    return None


# -- Inline bot lifecycle --


async def _create_inline_bot(client: E2EClient, bot_cfg: InlineBotConfig) -> None:
    """Create an inline bot via admin API. Pre-cleans if already exists."""
    # Try to delete first in case a previous run left it behind
    try:
        resp = await client.delete(
            f"/api/v1/admin/bots/{bot_cfg.id}", params={"force": "true"}
        )
        if resp.status_code == 204:
            logger.info("Pre-cleaned stale inline bot %s", bot_cfg.id)
    except Exception:
        pass

    # Resolve model: explicit > server's DEFAULT_MODEL (from E2E config)
    model = bot_cfg.model or client.config.default_model
    payload: dict[str, Any] = {
        "id": bot_cfg.id,
        "name": bot_cfg.name,
        "model": model,
        "system_prompt": bot_cfg.system_prompt,
        "local_tools": bot_cfg.local_tools,
        "tool_retrieval": bot_cfg.tool_retrieval,
        "context_compaction": False,
        "persona": False,
    }
    if bot_cfg.tool_similarity_threshold is not None:
        payload["tool_similarity_threshold"] = bot_cfg.tool_similarity_threshold

    resp = await client.post("/api/v1/admin/bots", json=payload)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create inline bot {bot_cfg.id}: "
            f"{resp.status_code} {resp.text}"
        )
    logger.info("Created inline bot %s", bot_cfg.id)


async def _delete_inline_bot(client: E2EClient, bot_id: str) -> None:
    """Delete an inline bot via admin API."""
    try:
        resp = await client.delete(
            f"/api/v1/admin/bots/{bot_id}", params={"force": "true"}
        )
        if resp.status_code == 204:
            logger.info("Deleted inline bot %s", bot_id)
        else:
            logger.warning(
                "Failed to delete inline bot %s: %s %s",
                bot_id, resp.status_code, resp.text,
            )
    except Exception as e:
        logger.warning("Error deleting inline bot %s: %s", bot_id, e)


# -- Step execution --


async def _run_step(
    client: E2EClient,
    step: ScenarioStep,
    step_index: int,
    bot_id: str,
    channel_id: str,
    timeout: int,
) -> StepResult:
    """Execute a single scenario step and run all its assertions."""
    response_text = ""
    stream_result: StreamResult | None = None
    failures: list[str] = []
    tools_used: list[str] = []

    try:
        if step.stream:
            stream_result = await client.chat_stream(
                message=step.message,
                bot_id=bot_id,
                channel_id=channel_id,
            )
            response_text = stream_result.response_text
            tools_used = stream_result.tools_used
        else:
            chat_resp = await client.chat(
                message=step.message,
                bot_id=bot_id,
                channel_id=channel_id,
            )
            response_text = chat_resp.response
    except Exception as e:
        failures.append(f"Step {step_index} request failed: {e}")
        return StepResult(
            step_index=step_index,
            passed=False,
            failures=failures,
            tools_used=tools_used,
            response_text=response_text,
        )

    # Run all assertions (soft — collect all failures)
    for assertion in step.assertions:
        error = _dispatch_assertion(assertion, response_text, stream_result)
        if error:
            failures.append(f"[{assertion.key}] {error}")

    return StepResult(
        step_index=step_index,
        passed=len(failures) == 0,
        failures=failures,
        tools_used=tools_used,
        response_text=response_text,
    )


# -- Scenario execution --


async def run_scenario(client: E2EClient, scenario: Scenario) -> ScenarioResult:
    """Execute a complete YAML scenario and return the result."""
    step_results: list[StepResult] = []
    inline_bot_id: str | None = None
    is_external = client.config.is_external

    try:
        # Create inline bot if needed (skip in external mode — use default bot)
        if scenario.bot and not is_external:
            inline_bot_id = scenario.bot.id
            try:
                await _create_inline_bot(client, scenario.bot)
            except Exception as e:
                return ScenarioResult(
                    scenario=scenario,
                    passed=False,
                    error=f"Failed to create inline bot: {e}",
                )

        # In external mode, use the scenario's bot_id if it references a pre-existing
        # server bot; only fall back to default for inline bots (which can't be created).
        if is_external:
            bot_id = scenario.bot_id or client.default_bot_id
        else:
            bot_id = scenario.effective_bot_id(client.default_bot_id)
        channel_id = client.new_channel_id()

        for i, step in enumerate(scenario.steps):
            # Per-step channel isolation if configured
            if scenario.channel == "per_step":
                channel_id = client.new_channel_id()

            result = await _run_step(
                client=client,
                step=step,
                step_index=i,
                bot_id=bot_id,
                channel_id=channel_id,
                timeout=scenario.timeout,
            )
            step_results.append(result)

        all_passed = all(r.passed for r in step_results)
        return ScenarioResult(
            scenario=scenario,
            passed=all_passed,
            step_results=step_results,
        )

    finally:
        # Always clean up inline bot
        if inline_bot_id:
            await _delete_inline_bot(client, inline_bot_id)
