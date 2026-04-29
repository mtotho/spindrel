"""Live diagnostics for native Spindrel session plan mode.

These tests target a real deployed Spindrel channel and create fresh detached
sessions so the channel's active conversation is left alone. They intentionally
exercise native Spindrel plan mode, not Codex/Claude harness plan bridging.

Tiers are controlled by ``SPINDREL_PLAN_TIER``:

- ``core``: channel/bot sanity plus plan-mode start/exit.
- ``questions``: core plus native ``ask_plan_questions`` widget publishing.
- ``publish``: questions plus ``publish_plan`` artifact publishing.
- ``approve``: publish plus native plan approval state transition.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.streaming import StreamResult


pytestmark = pytest.mark.e2e


DEFAULT_CHANNEL_ID = "67a06926-87e6-40fb-b85b-7eac36c74b98"
DEFAULT_BOT_ID = "e2e-bot"
PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"
NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"

TIER_ORDER = {
    "core": 0,
    "questions": 1,
    "publish": 2,
    "approve": 3,
}


def _tier() -> str:
    value = os.environ.get("SPINDREL_PLAN_TIER", "core").strip().lower() or "core"
    return value if value in TIER_ORDER else "core"


def _requires_tier(required: str) -> None:
    if TIER_ORDER[_tier()] < TIER_ORDER[required]:
        pytest.skip(f"SPINDREL_PLAN_TIER={required!r} or higher is required")


def _configured_channel() -> str:
    channel_id = os.environ.get("SPINDREL_PLAN_CHANNEL_ID", "").strip()
    if not channel_id:
        pytest.skip("SPINDREL_PLAN_CHANNEL_ID is not set")
    return channel_id


def _configured_bot() -> str:
    return os.environ.get("SPINDREL_PLAN_BOT_ID", DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID


def _timeout() -> float:
    return float(os.environ.get("SPINDREL_PLAN_TIMEOUT", "450"))


def _artifact_root() -> Path:
    return Path(os.environ.get("SPINDREL_PLAN_ARTIFACT_DIR", "/tmp/spindrel-plan-parity"))


def _sessions_artifact() -> Path:
    return _artifact_root() / "spindrel-plan-sessions.json"


def _record_session(kind: str, *, channel_id: str, session_id: str, bot_id: str) -> None:
    path = _sessions_artifact()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            data = {}
    data.update({
        "channel_id": channel_id,
        "bot_id": bot_id,
        "updated_at": int(time.time()),
        f"{kind}_session_id": session_id,
    })
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


async def _fresh_session(client: E2EClient, kind: str) -> tuple[str, str, str]:
    channel_id = _configured_channel()
    bot_id = _configured_bot()
    session_id = await client.create_channel_session(channel_id)
    _record_session(kind, channel_id=channel_id, session_id=session_id, bot_id=bot_id)
    return channel_id, session_id, bot_id


def _assert_clean_turn(result: StreamResult) -> None:
    assert not result.error_events, [event.data for event in result.error_events]
    assert result.response_text.strip() or result.tools_used, "turn ended without assistant text or tool use"


def _assistant_messages(messages: list[dict]) -> list[dict]:
    return [message for message in messages if message.get("role") == "assistant"]


def _tool_result_envelopes(messages: list[dict]) -> list[dict]:
    envelopes: list[dict] = []
    for message in messages:
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        for result in meta.get("tool_results") or []:
            if isinstance(result, dict):
                envelopes.append(result)
    return envelopes


def _envelope_body(envelope: dict) -> dict:
    body = envelope.get("body")
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _has_plan_questions_envelope(messages: list[dict], *, title: str) -> bool:
    for envelope in _tool_result_envelopes(messages):
        if envelope.get("content_type") != NATIVE_APP_CONTENT_TYPE:
            continue
        body = _envelope_body(envelope)
        state = body.get("state") if isinstance(body.get("state"), dict) else {}
        if (
            body.get("widget_ref") == "core/plan_questions"
            and state.get("title") == title
            and state.get("questions")
        ):
            return True
    return False


def _has_plan_envelope(messages: list[dict], title: str) -> bool:
    for envelope in _tool_result_envelopes(messages):
        if envelope.get("content_type") != PLAN_CONTENT_TYPE:
            continue
        body = _envelope_body(envelope)
        if body.get("title") == title:
            return True
    return False


@pytest.mark.asyncio
async def test_live_spindrel_plan_mode_start_exit(client: E2EClient) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, "core")
    bot = await client.get_bot(bot_id)
    assert bot.get("harness_runtime") in (None, "")
    assert bot.get("model") == os.environ.get("SPINDREL_PLAN_MODEL", "gpt-5.4-mini")

    before = await client.get_session_plan_state(session_id)
    assert before["mode"] == "chat"
    assert before["has_plan"] is False

    started = await client.start_session_plan_mode(session_id)
    assert started["mode"] == "planning"
    assert started["has_plan"] is False

    await client.exit_session_plan_mode(session_id)
    exited = await client.get_session_plan_state(session_id)
    assert exited["mode"] == "chat"
    assert exited["has_plan"] is False
    _record_session("core", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_plan_questions_widget(client: E2EClient) -> None:
    _requires_tier("questions")
    channel_id, session_id, bot_id = await _fresh_session(client, "question")
    await client.start_session_plan_mode(session_id)

    result = await client.chat_session_stream(
        (
            "Native plan-mode diagnostic. Use @tool:ask_plan_questions now. "
            "Ask exactly two focused questions in a structured card titled "
            "'Native plan parity questions'. The two question labels must be exactly "
            "'Plan behavior focus' and 'Success signal'. Do not publish a plan yet."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "ask_plan_questions" in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False
    planning_state = state.get("planning_state") or {}
    assert planning_state.get("open_questions"), planning_state

    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_questions_envelope(
        messages,
        title="Native plan parity questions",
    ), "ask_plan_questions did not persist the native question widget"


@pytest.mark.asyncio
async def test_live_spindrel_publish_plan_artifact(client: E2EClient) -> None:
    _requires_tier("publish")
    channel_id, session_id, bot_id = await _fresh_session(client, "plan")
    await client.start_session_plan_mode(session_id)
    title = f"Native Spindrel Plan Parity {int(time.time())}"

    result = await client.chat_session_stream(
        (
            "Native plan-mode diagnostic. Use @tool:publish_plan now and do not ask follow-up questions. "
            f"Publish a plan with title {title!r}. "
            "Use summary 'Verify native Spindrel plan mode can publish and render a plan artifact.' "
            "Use scope 'Live E2E diagnostics only; do not modify repository files.' "
            "Use exactly three pending steps: "
            "'Start native plan mode', 'Publish the inline plan artifact', "
            "and 'Capture docs screenshots'. "
            "Use acceptance criteria 'Plan state has revision 1' and "
            "'Persisted transcript contains a Spindrel plan envelope'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is True
    assert state["revision"] == 1
    assert state.get("validation") is not None

    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_envelope(messages, title), "publish_plan did not persist the inline plan envelope"
    _record_session("plan", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_approve_plan_state_transition(client: E2EClient) -> None:
    _requires_tier("approve")
    channel_id, session_id, bot_id = await _fresh_session(client, "approve")
    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": "Native Spindrel Plan Approval Diagnostic",
            "summary": "Verify native plan approval transitions the session to execution.",
            "scope": "State transition only; no agent turn or repository mutation.",
            "acceptance_criteria": ["Plan state moves to executing"],
            "steps": [
                {"id": "start", "label": "Start native plan mode"},
                {"id": "approve", "label": "Approve the active revision"},
            ],
        },
    )
    assert created["revision"] == 1
    approved = await client.approve_session_plan(session_id, revision=1)
    assert approved["mode"] == "executing"
    assert approved["accepted_revision"] == 1

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "executing"
    assert state["accepted_revision"] == 1
    _record_session("approve", channel_id=channel_id, session_id=session_id, bot_id=bot_id)
