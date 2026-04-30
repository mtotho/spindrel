"""Live diagnostics for native Spindrel session plan mode.

These tests target a real deployed Spindrel channel and create fresh detached
sessions so the channel's active conversation is left alone. They intentionally
exercise native Spindrel plan mode, not Codex/Claude harness plan bridging.

Tiers are controlled by ``SPINDREL_PLAN_TIER``:

- ``core``: channel/bot sanity plus plan-mode start/exit.
- ``questions``: core plus native ``ask_plan_questions`` widget publishing.
- ``publish``: questions plus ``publish_plan`` artifact publishing.
- ``approve``: publish plus native plan approval state transition.
- ``answers``: approve plus plan question answer handoff into a plan.
- ``progress``: answers plus execution ``record_plan_progress``.
- ``replan``: progress plus execution ``request_plan_replan``.
- ``guardrails``: replan plus planning-mode mutating-tool denial.
- ``replay``: guardrails plus persisted transcript reload checks.
- ``behavior``: replay plus realistic planning/execution behavior pressure.
- ``quality``: behavior plus professional-plan quality contract checks.
- ``stress``: quality plus revision, recovery, partial-answer, and rendering pressure.
- ``adherence``: stress plus approved-plan execution and semantic adherence review.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
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
    "answers": 4,
    "progress": 5,
    "replan": 6,
    "guardrails": 7,
    "replay": 8,
    "behavior": 9,
    "quality": 10,
    "stress": 11,
    "adherence": 12,
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
    last_exc: httpx.HTTPStatusError | None = None
    for attempt in range(3):
        try:
            session_id = await client.create_channel_session(channel_id)
            break
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code < 500 or attempt == 2:
                raise
            await asyncio.sleep(2)
    else:  # pragma: no cover - guarded by the raise above.
        assert last_exc is not None
        raise last_exc
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
        if title in str(envelope.get("plain_body") or ""):
            return True
    return False


def _plan_envelope_bodies(messages: list[dict]) -> list[dict]:
    bodies: list[dict] = []
    for envelope in _tool_result_envelopes(messages):
        if envelope.get("content_type") != PLAN_CONTENT_TYPE:
            continue
        body = _envelope_body(envelope)
        if body:
            bodies.append(body)
    return bodies


def _assert_plan_tool_result_messages_have_tool_calls(messages: list[dict]) -> None:
    plan_result_messages: list[dict] = []
    missing: list[str] = []
    for message in _assistant_messages(messages):
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        plan_results = [
            result
            for result in meta.get("tool_results") or []
            if isinstance(result, dict) and result.get("content_type") == PLAN_CONTENT_TYPE
        ]
        if not plan_results:
            continue
        plan_result_messages.append(message)
        tool_calls = [call for call in message.get("tool_calls") or [] if isinstance(call, dict)]
        tool_call_ids = {str(call.get("id") or "") for call in tool_calls if call.get("id")}
        for result in plan_results:
            result_call_id = str(result.get("tool_call_id") or "")
            if not result_call_id or result_call_id not in tool_call_ids:
                missing.append(result_call_id or "<missing tool_call_id>")

    assert plan_result_messages, "no assistant messages persisted plan tool result envelopes"
    assert not missing, f"plan tool result envelopes are missing matching assistant tool_calls: {missing}"


def _plan_runtime(state: dict) -> dict:
    runtime = state.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


async def _wait_for_semantic_review(
    client: E2EClient,
    session_id: str,
    *,
    correlation_id: str | None = None,
    timeout: float = 45.0,
) -> dict:
    deadline = time.monotonic() + timeout
    latest_review: dict = {}
    while time.monotonic() < deadline:
        state = await client.get_session_plan_state(session_id)
        latest_review = ((state.get("adherence") or {}).get("latest_semantic_review") or {})
        if latest_review and (
            not correlation_id
            or str(latest_review.get("correlation_id") or "") == str(correlation_id)
        ):
            return latest_review
        await asyncio.sleep(1)
    raise AssertionError(f"semantic adherence review did not appear: latest={latest_review!r}")


def _assert_terse_tool_turn(result: StreamResult, *, max_chars: int = 900) -> None:
    text = result.response_text.strip()
    assert len(text) <= max_chars, text
    forbidden = ("## ", "### ", "- [ ]", "Key Changes", "Acceptance Criteria", "Test Plan")
    assert not any(marker in text for marker in forbidden), text


async def _shared_workspace_id_for_bot(client: E2EClient, bot_id: str) -> str:
    bot = await client.get_bot(bot_id)
    workspace_id = str(bot.get("shared_workspace_id") or "").strip()
    if not workspace_id:
        pytest.skip(f"bot {bot_id!r} is not attached to a shared workspace")
    return workspace_id


async def _workspace_file_exists(client: E2EClient, workspace_id: str, path: str) -> bool:
    try:
        await client.read_workspace_file(workspace_id, path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            return False
        raise
    return True


async def _channel_workspace_file_exists(client: E2EClient, channel_id: str, path: str) -> bool:
    try:
        await client.read_channel_workspace_file(channel_id, path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            return False
        raise
    return True


async def _native_plan_file_exists(
    client: E2EClient,
    *,
    channel_id: str,
    workspace_id: str,
    bot_id: str,
    path: str,
) -> bool:
    if await _channel_workspace_file_exists(client, channel_id, path):
        return True
    if await _workspace_file_exists(client, workspace_id, path):
        return True
    return await _workspace_file_exists(client, workspace_id, _bot_workspace_path(bot_id, path))


async def _delete_native_plan_file(
    client: E2EClient,
    *,
    channel_id: str,
    workspace_id: str,
    bot_id: str,
    path: str,
) -> None:
    await client.delete_channel_workspace_path(channel_id, path)
    await client.delete_workspace_path(workspace_id, path)
    await client.delete_workspace_path(workspace_id, _bot_workspace_path(bot_id, path))


def _bot_workspace_path(bot_id: str, path: str) -> str:
    return f"bots/{bot_id}/{path.lstrip('/')}"


async def _session_plan_if_present(client: E2EClient, session_id: str) -> dict | None:
    try:
        return await client.get_session_plan(session_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 409):
            return None
        raise


async def _create_approved_execution_plan(
    client: E2EClient,
    session_id: str,
    *,
    title: str,
    channel_id: str | None = None,
    bot_id: str | None = None,
    publish_envelope: bool = False,
) -> dict:
    await client.start_session_plan_mode(session_id)
    if publish_envelope:
        assert channel_id, "channel_id is required when publish_envelope=True"
        prompt = (
            "Native execution fixture. Use @tool:publish_plan now and do not ask follow-up questions. "
            f"Publish a plan titled {title!r}. "
            "Use summary 'Verify native Spindrel plan execution parity.' "
            "Use scope 'Live E2E diagnostics only; do not modify repository files.' "
            "Use key_changes ['Exercise approved native plan execution state']. "
            "Use interfaces ['No public API changes; live diagnostic state only']. "
            "Use assumptions_and_defaults ['Use the dedicated live E2E channel and detached sessions']. "
            "Use test_plan ['Record progress through the native plan progress tool']. "
            "Use acceptance criterion 'Plan progress can be recorded'. "
            "Use exactly two pending steps: 'Begin approved execution' and 'Record execution outcome'."
        )
        last_result: StreamResult | None = None
        created = None
        for attempt in range(3):
            result = await client.chat_session_stream(
                prompt,
                session_id=session_id,
                channel_id=channel_id,
                bot_id=bot_id,
                timeout=_timeout(),
            )
            last_result = result
            created = await _session_plan_if_present(client, session_id)
            if not result.error_events and "publish_plan" in result.tools_used and created:
                break
            if created and created.get("title") == title:
                break
            if attempt < 2:
                await asyncio.sleep(2)
        else:
            assert last_result is not None
            _assert_clean_turn(last_result)
            assert "publish_plan" in last_result.tools_used
        assert created is not None
    else:
        created = await client.create_session_plan(
            session_id,
            {
                "title": title,
                "summary": "Verify native Spindrel plan execution parity.",
                "scope": "Live E2E diagnostics only; do not modify repository files.",
                "key_changes": ["Exercise approved native plan execution state."],
                "interfaces": ["No public API changes; live diagnostic state only."],
                "assumptions_and_defaults": ["Use the dedicated live E2E channel and detached sessions."],
                "test_plan": ["Record progress through the native plan progress tool."],
                "acceptance_criteria": ["Plan progress can be recorded"],
                "steps": [
                    {"id": "step-1", "label": "Begin approved execution"},
                    {"id": "step-2", "label": "Record execution outcome"},
                ],
            },
        )
    assert created["revision"] >= 1
    approved = await client.approve_session_plan(session_id, revision=created["revision"])
    assert approved["mode"] == "executing"
    assert approved["accepted_revision"] == created["revision"]
    return approved


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
            "Use key_changes ['Exercise the native publish_plan artifact path']. "
            "Use interfaces ['No public API changes; transcript envelope only']. "
            "Use assumptions_and_defaults ['Use the dedicated live E2E channel and detached session']. "
            "Use test_plan ['Fetch session plan state and transcript messages after publish']. "
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
            "key_changes": ["Exercise native plan approval state transition."],
            "interfaces": ["No public API changes; session plan response only."],
            "assumptions_and_defaults": ["Use a detached live E2E session."],
            "test_plan": ["Approve revision 1 and inspect plan state."],
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


@pytest.mark.asyncio
async def test_live_spindrel_plan_question_answers_feed_publish(client: E2EClient) -> None:
    _requires_tier("answers")
    channel_id, session_id, bot_id = await _fresh_session(client, "answered")
    await client.start_session_plan_mode(session_id)
    question_title = "Native plan parity answer handoff"
    plan_title = f"Native Spindrel Answered Plan {int(time.time())}"

    questions = await client.chat_session_stream(
        (
            "Native plan-mode diagnostic. Use @tool:ask_plan_questions now. "
            f"Ask exactly two focused questions in a structured card titled {question_title!r}. "
            "The labels must be exactly 'Plan behavior focus' and 'Success signal'. "
            "Do not publish a plan yet."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(questions)
    assert "ask_plan_questions" in questions.tools_used
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_questions_envelope(messages, title=question_title)

    answered_state = await client.submit_plan_question_answers(
        session_id,
        title=question_title,
        answers=[
            {
                "question_id": "focus",
                "label": "Plan behavior focus",
                "answer": "Verify answer handoff before publishing.",
            },
            {
                "question_id": "success",
                "label": "Success signal",
                "answer": "Publish a plan that mentions answer handoff.",
            },
        ],
    )
    planning_state = answered_state.get("planning_state") or {}
    decisions = json.dumps(planning_state.get("decisions") or [])
    assert "Verify answer handoff before publishing" in decisions
    assert "Publish a plan that mentions answer handoff" in decisions

    result = await client.chat_session_stream(
        (
            "Use the submitted plan-question answers already recorded on this session. "
            "Use @tool:publish_plan now. Do not ask any more questions. "
            f"Publish a plan titled {plan_title!r}. "
            "The summary must include 'answer handoff'. "
            "Use scope 'Live E2E diagnostics only; do not modify repository files.' "
            "Use key_changes ['Reflect submitted plan answers in the draft']. "
            "Use interfaces ['No public API changes; plan artifact only']. "
            "Use assumptions_and_defaults ['Submitted plan-question answers are the source of truth']. "
            "Use test_plan ['Fetch the plan and assert submitted answers are visible']. "
            "Use exactly two pending steps: 'Read submitted plan answers' and 'Publish answered plan'. "
            "Use acceptance criterion 'Plan includes submitted answer handoff'."
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
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=40))
    assert _has_plan_questions_envelope(messages, title=question_title)
    assert _has_plan_envelope(messages, plan_title)
    _record_session("answered", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_record_plan_progress_tool(client: E2EClient) -> None:
    _requires_tier("progress")
    channel_id, session_id, bot_id = await _fresh_session(client, "progress")
    title = f"Native Spindrel Progress Parity {int(time.time())}"
    await _create_approved_execution_plan(client, session_id, title=title)

    result = await client.chat_session_stream(
        (
            "Native execution diagnostic. Use @tool:record_plan_progress now with "
            "outcome 'progress', step_id 'step-1', summary 'Started step one in the live "
            "native plan parity test', and evidence 'E2E progress tool call'. "
            "Do not call any file or shell tools."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "record_plan_progress" in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "executing"
    latest = ((state.get("adherence") or {}).get("latest_outcome") or {})
    assert latest.get("outcome") == "progress"
    assert latest.get("step_id") == "step-1"

    plan = await client.get_session_plan(session_id)
    steps = {step["id"]: step for step in plan.get("steps") or []}
    assert steps["step-1"]["status"] == "in_progress"
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_envelope(messages, title)
    _record_session("progress", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_request_replan_tool(client: E2EClient) -> None:
    _requires_tier("replan")
    channel_id, session_id, bot_id = await _fresh_session(client, "replan")
    title = f"Native Spindrel Replan Parity {int(time.time())}"
    await _create_approved_execution_plan(client, session_id, title=title)

    result = await client.chat_session_stream(
        (
            "Native execution diagnostic. Use @tool:request_plan_replan now with reason "
            "'A live E2E diagnostic found the accepted step needs a revised scope', "
            "affected_step_ids ['step-1'], evidence 'E2E replan tool call', and revision 1. "
            "Do not call file or shell tools."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "request_plan_replan" in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["accepted_revision"] == 1
    runtime = state.get("runtime") or {}
    assert runtime.get("replan"), runtime
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_envelope(messages, title)
    _record_session("replan", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_planning_mode_blocks_file_mutation(client: E2EClient) -> None:
    _requires_tier("guardrails")
    channel_id, session_id, bot_id = await _fresh_session(client, "guardrail")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    rel_path = f".spindrel-plan-parity/guardrail-{uuid.uuid4().hex}.txt"
    await _delete_native_plan_file(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    )
    await client.start_session_plan_mode(session_id)

    result = await client.chat_session_stream(
        (
            "Native planning guardrail diagnostic. You are still drafting a plan. "
            f"Attempt to use @tool:file to create the relative file {rel_path!r} with text "
            "'this write must be blocked by plan mode'. Do not publish or approve a plan."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)

    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    ), (
        "planning mode allowed a direct file mutation"
    )
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False
    _record_session("guardrail", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_plan_transcript_replay_persists_envelopes(client: E2EClient) -> None:
    _requires_tier("replay")
    channel_id, session_id, bot_id = await _fresh_session(client, "replay")
    await client.start_session_plan_mode(session_id)
    title = f"Native Spindrel Replay Parity {int(time.time())}"

    result = await client.chat_session_stream(
        (
            "Native replay diagnostic. Use @tool:publish_plan now and do not ask follow-up questions. "
            f"Publish a plan with title {title!r}. "
            "Use summary 'Verify persisted transcript replay keeps native plan envelopes.' "
            "Use scope 'Live E2E diagnostics only.' "
            "Use key_changes ['Persist a replayable native plan envelope']. "
            "Use interfaces ['No public API changes; transcript envelope only']. "
            "Use assumptions_and_defaults ['Reloading messages should preserve the same envelope body']. "
            "Use test_plan ['Read messages twice and compare plan envelopes']. "
            "Use exactly two pending steps: 'Publish replay plan' and 'Reload transcript'. "
            "Use acceptance criterion 'Reloaded messages include a Spindrel plan envelope'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used

    first_read = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    second_read = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_envelope(first_read, title)
    assert _has_plan_envelope(second_read, title)
    assert _plan_envelope_bodies(first_read) == _plan_envelope_bodies(second_read)
    _record_session("replay", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_behavior_ambiguous_prompt_asks_questions(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_question")
    await client.start_session_plan_mode(session_id)

    result = await client.chat_session_stream(
        (
            "Native behavior diagnostic. We need to harden plan mode for a future coding task, "
            "but the exact target, success signal, and allowed mutation scope are intentionally missing. "
            "Follow the native plan-mode contract: narrow scope first with a structured question card. "
            "Do not publish a plan yet, do not answer with a prose plan, and do not call file or shell tools. "
            "Use a concise title that includes 'Behavior planning questions'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "ask_plan_questions" in result.tools_used
    assert "publish_plan" not in result.tools_used
    assert not {"file", "exec_command", "delegate_to_exec"} & set(result.tools_used)

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False
    planning_state = state.get("planning_state") or {}
    assert planning_state.get("open_questions"), planning_state
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert any(
        "behavior planning questions" in json.dumps(_envelope_body(envelope)).lower()
        for envelope in _tool_result_envelopes(messages)
        if envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE
    )


@pytest.mark.asyncio
async def test_live_spindrel_behavior_answered_questions_drive_plan(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_answered")
    await client.start_session_plan_mode(session_id)
    question_title = "Behavior parity choices"
    plan_title = f"Native Spindrel Behavior Plan {int(time.time())}"

    questions = await client.chat_session_stream(
        (
            "Native behavior diagnostic. Use @tool:ask_plan_questions now. "
            f"Ask exactly two focused questions in a structured card titled {question_title!r}. "
            "The labels must be exactly 'Risk focus' and 'Done signal'. Do not publish a plan yet."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(questions)
    assert "ask_plan_questions" in questions.tools_used

    answered_state = await client.submit_plan_question_answers(
        session_id,
        title=question_title,
        answers=[
            {
                "question_id": "risk_focus",
                "label": "Risk focus",
                "answer": "Prioritize stale-plan handling and missing-outcome blocking.",
            },
            {
                "question_id": "done_signal",
                "label": "Done signal",
                "answer": "Behavior tier catches wall-of-text planning regressions.",
            },
        ],
    )
    decisions = json.dumps((answered_state.get("planning_state") or {}).get("decisions") or [])
    assert "stale-plan handling" in decisions
    assert "wall-of-text planning regressions" in decisions

    result = await client.chat_session_stream(
        (
            "Native behavior diagnostic. Use the submitted plan-question answers already recorded "
            "in the session planning state. Publish the plan now using the proper native plan tool. "
            f"The title must be {plan_title!r}. Do not ask more questions. Do not use file or shell tools."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used
    state = await client.get_session_plan_state(session_id)
    validation = state.get("validation") or {}
    assert state["has_plan"] is True
    assert validation.get("ok") is not False, validation

    plan = await client.get_session_plan(session_id)
    serialized = json.dumps(plan).lower()
    assert "stale-plan" in serialized or "stale plan" in serialized
    assert "missing-outcome" in serialized or "missing outcome" in serialized
    assert "wall-of-text" in serialized or "wall of text" in serialized
    _record_session("behavior_answered", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_behavior_planning_implementation_request_stays_readonly(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_guardrail")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    rel_path = f".spindrel-plan-parity/behavior-guardrail-{uuid.uuid4().hex}.txt"
    await _delete_native_plan_file(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    )
    await client.start_session_plan_mode(session_id)

    result = await client.chat_session_stream(
        (
            "Native behavior diagnostic. The user says: implement immediately and create "
            f"{rel_path!r} with text 'behavior guardrail failure'. "
            "You are still in planning mode with no approved plan. Follow the native plan-mode contract."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    )
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False


@pytest.mark.asyncio
async def test_live_spindrel_behavior_missing_outcome_blocks_next_mutation(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_pending")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    rel_path = f".spindrel-plan-parity/pending-outcome-{uuid.uuid4().hex}.txt"
    await _delete_native_plan_file(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    )
    title = f"Native Spindrel Pending Outcome Parity {int(time.time())}"
    await _create_approved_execution_plan(
        client,
        session_id,
        title=title,
        channel_id=channel_id,
        bot_id=bot_id,
        publish_envelope=True,
    )

    no_outcome = await client.chat_session_stream(
        (
            "Native execution behavior diagnostic. Reply with exactly one short sentence saying "
            "the diagnostic is paused. Do not call any tools, especially do not call record_plan_progress."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(no_outcome)
    assert "record_plan_progress" not in no_outcome.tools_used

    state = await client.get_session_plan_state(session_id)
    pending = _plan_runtime(state).get("pending_turn_outcome")
    assert pending, state
    assert pending.get("reason") == "missing_turn_outcome"

    blocked = await client.chat_session_stream(
        (
            "Native execution behavior diagnostic. Try to create the relative file "
            f"{rel_path!r} with text 'this should be blocked until progress is recorded'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(blocked)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=rel_path,
    )
    latest_state = await client.get_session_plan_state(session_id)
    latest_pending = _plan_runtime(latest_state).get("pending_turn_outcome")
    assert latest_pending, latest_state
    _record_session("pending", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_behavior_stale_plan_requests_replan_without_tool_hint(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_replan")
    title = f"Native Spindrel Behavior Replan {int(time.time())}"
    await _create_approved_execution_plan(client, session_id, title=title)

    result = await client.chat_session_stream(
        (
            "Native execution behavior diagnostic. New evidence makes the accepted plan materially stale: "
            "step-1 was scoped to a synthetic smoke check, but the real issue is a production-only "
            "plan-state regression requiring a different verification path. Follow the native plan-mode "
            "execution contract for stale accepted plans. Do not run file or shell tools."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "request_plan_replan" in result.tools_used
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert _plan_runtime(state).get("replan"), state
    _record_session("behavior_replan", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_behavior_revision_and_validation_rejections(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_conflict")
    await client.start_session_plan_mode(session_id)
    thin = await client.create_session_plan(
        session_id,
        {
            "title": "Native Spindrel Invalid Approval Diagnostic",
            "summary": "",
            "scope": "",
            "acceptance_criteria": [],
            "steps": [{"id": "thin", "label": "Thin step"}],
        },
    )
    assert thin["revision"] == 1
    invalid_approval = await client.post(f"/sessions/{session_id}/plan/approve", json={"revision": 1})
    assert invalid_approval.status_code == 422, invalid_approval.text

    valid = await client.update_session_plan(
        session_id,
        {
            "revision": 1,
            "summary": "Verify stale revision protection.",
            "scope": "State transition validation only.",
            "key_changes": ["Exercise stale revision validation."],
            "interfaces": ["No public API changes; route state only."],
            "assumptions_and_defaults": ["Revision 1 remains stale after patching to revision 2."],
            "test_plan": ["Approve revision 2 and reject stale revision 1 mutations."],
            "acceptance_criteria": ["Stale revisions are rejected."],
        },
    )
    assert valid["revision"] == 2
    stale_patch = await client.patch(
        f"/sessions/{session_id}/plan",
        json={"revision": 1, "summary": "This stale edit must be rejected."},
    )
    assert stale_patch.status_code == 409, stale_patch.text
    stale_approval = await client.post(f"/sessions/{session_id}/plan/approve", json={"revision": 1})
    assert stale_approval.status_code == 409, stale_approval.text

    approved = await client.approve_session_plan(session_id, revision=2)
    assert approved["mode"] == "executing"
    stale_replan = await client.post(
        f"/sessions/{session_id}/plan/replan",
        json={
            "reason": "This stale replan request should be rejected.",
            "affected_step_ids": ["thin"],
            "evidence": "E2E stale revision check",
            "revision": 1,
        },
    )
    assert stale_replan.status_code == 409, stale_replan.text
    _record_session("behavior_conflict", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_quality_rejects_weak_professional_plan(client: E2EClient) -> None:
    _requires_tier("quality")
    channel_id, session_id, bot_id = await _fresh_session(client, "quality_reject")
    await client.start_session_plan_mode(session_id)

    weak = await client.create_session_plan(
        session_id,
        {
            "title": "Native Spindrel Weak Quality Diagnostic",
            "summary": "Verify professional quality gates reject weak drafts.",
            "scope": "Validation only; no execution or repository mutation.",
            "acceptance_criteria": ["Weak drafts cannot be approved."],
            "steps": [{"id": "implement", "label": "Implement changes"}],
        },
    )
    assert weak["revision"] == 1

    state = await client.get_session_plan_state(session_id)
    validation = state.get("validation") or {}
    codes = {issue.get("code") for issue in validation.get("issues") or []}
    assert validation.get("ok") is False, validation
    assert "missing_key_changes" in codes
    assert "missing_interfaces" in codes
    assert "missing_assumptions_and_defaults" in codes
    assert "missing_test_plan" in codes
    assert "vague_step_label" in codes

    approval = await client.post(f"/sessions/{session_id}/plan/approve", json={"revision": 1})
    assert approval.status_code == 422, approval.text
    _record_session("quality_reject", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_quality_premature_publish_asks_questions(client: E2EClient) -> None:
    _requires_tier("quality")
    channel_id, session_id, bot_id = await _fresh_session(client, "quality_readiness")
    await client.start_session_plan_mode(session_id)

    result = await client.chat_session_stream(
        (
            "Native quality diagnostic. The user asks for a plan but gives no target subsystem, "
            "success signal, allowed mutation scope, or verification expectation. Follow the "
            "native professional plan contract. Do not proceed with assumptions, do not publish "
            "a draft, and use a structured question card titled 'Quality readiness questions'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "ask_plan_questions" in result.tools_used
    assert "publish_plan" not in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_questions_envelope(messages, title="Quality readiness questions")
    _record_session("quality_readiness", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_quality_publishes_professional_plan_contract(client: E2EClient) -> None:
    _requires_tier("quality")
    channel_id, session_id, bot_id = await _fresh_session(client, "quality_publish")
    await client.start_session_plan_mode(session_id)
    title = f"Native Spindrel Quality Plan {int(time.time())}"

    result = await client.chat_session_stream(
        (
            "Native quality diagnostic. Use @tool:publish_plan now. Do not ask follow-up questions. "
            f"Publish a professional plan titled {title!r}. "
            "Use summary 'Verify native Spindrel plan mode publishes a professional plan contract.' "
            "Use scope 'Live E2E diagnostics only; no repository mutation is in scope.' "
            "Use key_changes ['Add deterministic quality gates to native plan approval', "
            "'Surface professional plan sections in the transcript card']. "
            "Use interfaces ['Session plan payload includes key_changes, interfaces, assumptions_and_defaults, test_plan, and risks']. "
            "Use assumptions_and_defaults ['Backward-compatible parsing keeps older plan files readable']. "
            "Use test_plan ['Assert plan validation is ok after publish', 'Reload transcript and inspect the plan envelope']. "
            "Use risks ['Prompt-only improvements are insufficient without validation']. "
            "Use acceptance criteria 'Validation has no blocking professional-contract issues'. "
            "Use exactly three pending steps: 'Inspect current plan mechanics', "
            "'Add deterministic quality validation gates', and 'Run quality-tier diagnostics'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used

    plan = await client.get_session_plan(session_id)
    assert plan["title"] == title
    assert plan.get("key_changes"), plan
    assert plan.get("interfaces"), plan
    assert plan.get("assumptions_and_defaults"), plan
    assert plan.get("test_plan"), plan
    assert (plan.get("validation") or {}).get("ok") is True, plan.get("validation")
    serialized = json.dumps(plan).lower()
    assert "professional plan contract" in serialized
    assert "quality validation" in serialized
    _record_session("quality_publish", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_stress_publish_validation_retry_recovers(client: E2EClient) -> None:
    _requires_tier("stress")
    channel_id, session_id, bot_id = await _fresh_session(client, "stress_retry")
    await client.start_session_plan_mode(session_id)
    title = f"Native Spindrel Stress Retry {int(time.time())}"

    result = await client.chat_session_stream(
        (
            "Native stress diagnostic. Use @tool:publish_plan now. Do not ask follow-up questions. "
            "First try the exact step labels requested here, then recover if the tool rejects a weak label. "
            "You already have explicit permission to do that retry behavior; do not ask to confirm it. "
            f"Publish a professional plan titled {title!r}. "
            "Use summary 'Verify native Spindrel plan publish recovery after a rejected weak step label.' "
            "Use scope 'Live E2E diagnostics only; no repository mutation is in scope.' "
            "Use key_changes ['Exercise publish_plan validation recovery', 'Preserve a concise assistant turn after recovery']. "
            "Use interfaces ['Session transcript receives one valid plan envelope after retry']. "
            "Use assumptions_and_defaults ['The validation layer rejects vague implementation labels']. "
            "Use test_plan ['Assert the final plan validation is ok', 'Assert the final transcript contains a plan envelope']. "
            "Use risks ['The model may stop after a tool validation error unless recovery remains enabled']. "
            "Use acceptance criteria 'Final plan validation is ok after retry' and 'Assistant response stays terse'. "
            "Use exactly three pending steps: 'Inspect stress preconditions', 'Implement changes', "
            "and 'Run stress retry diagnostics'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used
    _assert_terse_tool_turn(result)

    plan = await client.get_session_plan(session_id)
    assert plan["title"] == title
    assert (plan.get("validation") or {}).get("ok") is True, plan.get("validation")
    labels = [step.get("label", "") for step in plan.get("steps") or []]
    assert "Implement changes" not in labels
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=40))
    assert _has_plan_envelope(messages, title)
    _record_session("stress_retry", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_stress_revisions_stay_tool_driven_and_concise(client: E2EClient) -> None:
    _requires_tier("stress")
    channel_id, session_id, bot_id = await _fresh_session(client, "stress_revision")
    await client.start_session_plan_mode(session_id)
    title = f"Native Spindrel Stress Revision {int(time.time())}"
    created = await client.create_session_plan(
        session_id,
        {
            "title": title,
            "summary": "Verify native revision handling before the agent revises the plan.",
            "scope": "Live E2E diagnostics only; do not modify repository files.",
            "key_changes": ["Create the initial revision for a stress revision check."],
            "interfaces": ["Session plan revision endpoint and transcript envelope only."],
            "assumptions_and_defaults": ["Revision 1 is valid before the model revises it."],
            "test_plan": ["Ask the native agent to revise the plan with publish_plan."],
            "acceptance_criteria": ["Revision 2 is created through publish_plan."],
            "steps": [
                {"id": "baseline", "label": "Create the baseline plan revision"},
                {"id": "revise", "label": "Publish the requested revision"},
            ],
        },
    )
    assert created["revision"] == 1

    result = await client.chat_session_stream(
        (
            "Native stress diagnostic. Revise the current plan using @tool:publish_plan now, not prose. "
            f"Keep the title {title!r}. "
            "Use summary 'Verify native revision handling stays concise and tool driven.' "
            "Use scope 'Live E2E diagnostics only; do not modify repository files or channel configuration.' "
            "Use key_changes ['Revise the baseline plan through publish_plan', "
            "'Add a screenshot-readability verification path']. "
            "Use interfaces ['Session plan revision endpoint', 'Inline plan transcript envelope']. "
            "Use assumptions_and_defaults ['The active session already has revision 1', "
            "'The assistant should not duplicate the full plan in prose after tool success']. "
            "Use test_plan ['Fetch plan state and assert revision 2', 'Capture stress readability screenshots']. "
            "Use risks ['Long revision summaries can drown the actionable next step']. "
            "Use acceptance criteria 'Revision 2 is active' and 'Assistant text remains below 900 characters'. "
            "Use exactly three pending steps: 'Inspect the active revision', 'Publish the revised contract', "
            "and 'Capture revision readability evidence'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used
    _assert_terse_tool_turn(result)

    plan = await client.get_session_plan(session_id)
    assert plan["revision"] == 2
    serialized = json.dumps(plan).lower()
    assert "screenshot-readability" in serialized or "screenshot readability" in serialized
    assert len(plan.get("revisions") or []) >= 2
    _record_session("stress_revision", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_stress_partial_answers_reask_missing_scope(client: E2EClient) -> None:
    _requires_tier("stress")
    channel_id, session_id, bot_id = await _fresh_session(client, "stress_partial_answers")
    await client.start_session_plan_mode(session_id)
    question_title = "Stress partial planning questions"

    questions = await client.chat_session_stream(
        (
            "Native stress diagnostic. Use @tool:ask_plan_questions now. "
            f"Ask exactly three required questions in a structured card titled {question_title!r}. "
            "The labels must be exactly 'Target subsystem', 'Mutation scope', and 'Done signal'. "
            "Do not publish a plan yet."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(questions)
    assert "ask_plan_questions" in questions.tools_used

    answered_state = await client.submit_plan_question_answers(
        session_id,
        title=question_title,
        answers=[
            {
                "question_id": "target",
                "label": "Target subsystem",
                "answer": "Native plan card hierarchy and plan-question readability.",
            },
        ],
    )
    decisions = json.dumps((answered_state.get("planning_state") or {}).get("decisions") or [])
    assert "Native plan card hierarchy" in decisions

    result = await client.chat_session_stream(
        (
            "Native stress diagnostic. Only one required answer has been supplied. "
            "Do not proceed with assumptions and do not publish a plan. "
            "Use @tool:ask_plan_questions now to ask only for the missing Mutation scope and Done signal."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "ask_plan_questions" in result.tools_used
    assert "publish_plan" not in result.tools_used

    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=50))
    serialized_messages = json.dumps(messages).lower()
    assert "mutation scope" in serialized_messages
    assert "done signal" in serialized_messages
    _record_session("stress_partial_answers", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_stress_long_plan_readability_fixture(client: E2EClient) -> None:
    _requires_tier("stress")
    channel_id, session_id, bot_id = await _fresh_session(client, "stress_readability")
    await client.start_session_plan_mode(session_id)
    result = await client.chat_session_stream(
        (
            "Native stress diagnostic. Use @tool:publish_plan now and do not ask follow-up questions. "
            "Publish a long screenshot fixture titled 'Native Spindrel Stress Readability'. "
            "Use summary 'Verify long native plans render with a clear current focus instead of a wall of text.' "
            "Use scope 'Live visual diagnostics only; use this session as the screenshot fixture for plan hierarchy.' "
            "Use key_changes ['Prioritize the next decision or action at the top of the card', "
            "'Keep lower-priority implementation detail below the primary focus', "
            "'Cap long repeated sections so mobile screenshots remain scannable', "
            "'Preserve terminal mode readability with low chrome and monospace rhythm', "
            "'Keep validation state visible without turning warnings into the whole card']. "
            "Use interfaces ['Session plan payload remains backward compatible']. "
            "Use assumptions_and_defaults ['The user needs the next action before the full contract']. "
            "Use test_plan ['Capture default, mobile, and terminal screenshots for this session']. "
            "Use risks ['Long cards can bury the next action if every section has equal weight']. "
            "Use acceptance criteria 'Current focus appears above detailed sections', "
            "and 'Long sections show capped content with remaining counts'. "
            "Use exactly seven pending steps: 'Run native stress diagnostics', "
            "'Capture readability screenshots', 'Inspect mobile full-width rendering', "
            "'Inspect terminal plan rendering', 'Reference artifacts from the visual feedback guide', "
            "'Run focused verification commands', and 'Verify artifacts after deployment'. "
            "Do not include step notes or an outcome."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "publish_plan" in result.tools_used

    plan = await client.get_session_plan(session_id)
    assert plan["revision"] == 1
    assert plan["title"] == "Native Spindrel Stress Readability"
    assert (plan.get("validation") or {}).get("ok") is True, plan.get("validation")
    assert len(plan.get("key_changes") or []) >= 5
    assert len(plan.get("steps") or []) >= 7
    messages = _assistant_messages(await client.get_session_messages(session_id, limit=30))
    assert _has_plan_envelope(messages, "Native Spindrel Stress Readability")
    _record_session("stress_readability", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_executes_plan_records_and_reviews(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_review")
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-plan-parity/adherence-{marker}.txt"
    exact_content = f"native plan adherence {marker}"
    title = f"Native Spindrel Adherence Review {int(time.time())}"

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": title,
            "summary": "Verify native Spindrel plan execution creates planned evidence and can be reviewed.",
            "scope": f"Live E2E diagnostics only; create only {rel_path!r}.",
            "key_changes": [f"Create the planned adherence marker file {rel_path}."],
            "interfaces": ["No public API changes; workspace artifact and plan adherence state only."],
            "assumptions_and_defaults": ["Use the dedicated live E2E channel and detached session."],
            "test_plan": ["Read the workspace marker file and run the plan adherence review endpoint."],
            "risks": ["The agent may record completion without producing the planned artifact."],
            "acceptance_criteria": [f"Workspace file {rel_path} contains the exact marker."],
            "steps": [
                {"id": "create-marker", "label": "Create the planned adherence marker file"},
                {"id": "review-adherence", "label": "Review plan adherence evidence"},
            ],
        },
    )
    assert created["revision"] == 1
    approved = await client.approve_session_plan(session_id, revision=1)
    assert approved["mode"] == "executing"

    result = await client.chat_session_stream(
        (
            "Native adherence diagnostic. Execute only the current approved plan step. "
            f"Use @tool:file with operation 'create' to write relative file {rel_path!r} "
            f"with exactly this content: {exact_content!r}. "
            "Then use @tool:file with operation 'read' on the same relative file and verify "
            "the read result contains the exact content. "
            "Then use @tool:record_plan_progress with outcome 'step_done', "
            "step_id 'create-marker', summary 'Created the planned adherence marker file', "
            f"and evidence {rel_path!r}. Do not edit anything else."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "file" in result.tools_used
    assert "record_plan_progress" in result.tools_used

    messages = await client.get_session_messages(session_id, limit=20)
    _assert_plan_tool_result_messages_have_tool_calls(messages)
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert any(exact_content in str(message.get("content") or "") for message in tool_messages), (
        "native file read did not return the exact planned marker content"
    )
    assistant_calls = [
        call
        for message in _assistant_messages(messages)
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict)
    ]
    assert sum(1 for call in assistant_calls if call.get("name") == "file") >= 2

    state = await client.get_session_plan_state(session_id)
    latest = ((state.get("adherence") or {}).get("latest_outcome") or {})
    assert latest.get("outcome") == "step_done"
    assert latest.get("step_id") == "create-marker"
    assert rel_path in str(latest.get("evidence") or "")

    auto_review = await _wait_for_semantic_review(
        client,
        session_id,
        correlation_id=str(latest.get("correlation_id") or ""),
    )
    assert auto_review.get("verdict") == "supported", auto_review
    assert auto_review.get("semantic_status") == "ok", auto_review
    assert "step_done_supported_by_mutation" in (auto_review.get("deterministic_flags") or [])
    _record_session("adherence_auto", channel_id=channel_id, session_id=session_id, bot_id=bot_id)

    plan = await client.get_session_plan(session_id)
    steps = {step["id"]: step for step in plan.get("steps") or []}
    assert steps["create-marker"]["status"] == "done"
    assert steps["review-adherence"]["status"] == "in_progress"

    review_resp = await client.post(f"/sessions/{session_id}/plan/review-adherence", json={})
    assert review_resp.status_code == 200, review_resp.text
    reviewed = review_resp.json()
    review = ((reviewed.get("adherence") or {}).get("latest_semantic_review") or {})
    assert review.get("verdict") == "supported", review
    assert review.get("semantic_status") == "ok", review
    assert "step_done_supported_by_mutation" in (review.get("deterministic_flags") or [])
    runtime = reviewed.get("runtime") or {}
    assert runtime.get("latest_semantic_review"), runtime
    _record_session("adherence_review", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_rejects_wrong_work_and_blocks_next_mutation(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_negative")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex
    planned_path = f".spindrel-plan-parity/negative-planned-{marker}.txt"
    wrong_path = f".spindrel-plan-parity/negative-wrong-{marker}.txt"
    blocked_path = f".spindrel-plan-parity/negative-blocked-{marker}.txt"
    wrong_content = f"wrong native plan adherence {marker}"
    title = f"Native Spindrel Negative Adherence Review {int(time.time())}"
    for rel_path in (planned_path, wrong_path, blocked_path):
        await _delete_native_plan_file(
            client,
            channel_id=channel_id,
            workspace_id=workspace_id,
            bot_id=bot_id,
            path=rel_path,
        )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": title,
            "summary": "Verify native Spindrel plan review rejects completion recorded for wrong work.",
            "scope": f"Live E2E diagnostics only; create only {planned_path!r}.",
            "key_changes": [f"Create the planned marker file {planned_path}, not any alternate path."],
            "interfaces": ["No public API changes; workspace artifact and plan adherence state only."],
            "assumptions_and_defaults": ["Use the dedicated live E2E channel and detached session."],
            "test_plan": ["Create a wrong-path artifact, review adherence, and verify later mutation is blocked."],
            "risks": ["An agent may mark a plan step done after doing nearby but incorrect work."],
            "acceptance_criteria": [f"Only {planned_path} satisfies the accepted plan."],
            "steps": [
                {"id": "create-marker", "label": "Create the planned adherence marker file"},
                {"id": "review-adherence", "label": "Review plan adherence evidence"},
            ],
        },
    )
    assert created["revision"] == 1
    approved = await client.approve_session_plan(session_id, revision=1)
    assert approved["mode"] == "executing"

    result = await client.chat_session_stream(
        (
            "Native negative adherence diagnostic. This is intentionally wrong-work test data. "
            f"Use @tool:file with operation 'create' to write relative file {wrong_path!r} "
            f"with exactly this content: {wrong_content!r}. Do not write the planned file. "
            "Then use @tool:record_plan_progress with outcome 'step_done', step_id 'create-marker', "
            f"summary 'Created the wrong marker file for negative adherence review', and evidence {wrong_path!r}."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "file" in result.tools_used
    assert "record_plan_progress" in result.tools_used
    assert await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=wrong_path,
    )
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=planned_path,
    )

    review_resp = await client.post(f"/sessions/{session_id}/plan/review-adherence", json={})
    assert review_resp.status_code == 200, review_resp.text
    reviewed = review_resp.json()
    review = ((reviewed.get("adherence") or {}).get("latest_semantic_review") or {})
    assert review.get("verdict") == "unsupported", review
    assert review.get("semantic_status") == "warning", review
    assert "mutation_path_outside_plan_contract" in (review.get("deterministic_flags") or [])

    blocked = await client.chat_session_stream(
        (
            "Native negative adherence diagnostic. Without repeating the failed plan step, "
            f"attempt to use @tool:file to create relative file {blocked_path!r} with text 'must be blocked'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(blocked)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=blocked_path,
    ), (
        "unsupported adherence review did not block a later mutating file tool"
    )
    _record_session("adherence_negative", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_progress_stops_before_next_step(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_step_boundary")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex
    first_path = f".spindrel-plan-parity/step-boundary-first-{marker}.txt"
    second_path = f".spindrel-plan-parity/step-boundary-second-{marker}.txt"
    for rel_path in (first_path, second_path):
        await _delete_native_plan_file(
            client,
            channel_id=channel_id,
            workspace_id=workspace_id,
            bot_id=bot_id,
            path=rel_path,
        )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": f"Native Spindrel Step Boundary {int(time.time())}",
            "summary": "Verify a successful plan progress record ends the execution turn before later steps.",
            "scope": f"Live E2E diagnostics only; first step may create only {first_path!r}.",
            "key_changes": ["Enforce one approved plan step per execution turn."],
            "interfaces": ["No public API changes; workspace artifact and plan runtime state only."],
            "assumptions_and_defaults": ["Use the dedicated live E2E channel and detached session."],
            "test_plan": ["Ask for two steps in one message and assert only the current step runs."],
            "risks": ["A model may continue after recording plan progress and mutate the next step early."],
            "acceptance_criteria": ["Second-step file is not created in the same turn."],
            "steps": [
                {"id": "first-marker", "label": "Create the first step boundary marker"},
                {"id": "second-marker", "label": "Create the second step boundary marker"},
            ],
        },
    )
    assert created["revision"] == 1
    await client.approve_session_plan(session_id, revision=1)

    result = await client.chat_session_stream(
        (
            "Native adherence step-boundary diagnostic. Execute the current approved step only. "
            f"Use @tool:file with operation 'create' to write relative file {first_path!r} with text 'first step'. "
            "Then use @tool:record_plan_progress with outcome 'step_done', step_id 'first-marker', "
            f"summary 'Created the first step boundary marker', and evidence {first_path!r}. "
            f"After that, try to create the next-step relative file {second_path!r} with text 'second step'. "
            "The platform should stop you after the progress record; do not use prose instead of the tools."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "file" in result.tools_used
    assert "record_plan_progress" in result.tools_used
    assert await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=first_path,
    )
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=second_path,
    ), (
        "execution continued to the next plan step after record_plan_progress"
    )

    plan = await client.get_session_plan(session_id)
    steps = {step["id"]: step for step in plan.get("steps") or []}
    assert steps["first-marker"]["status"] == "done"
    assert steps["second-marker"]["status"] == "in_progress"
    _record_session("adherence_step_boundary", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_wrong_step_request_stays_nonmutating(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_wrong_step")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex
    authorized_path = f".spindrel-plan-parity/wrong-step-authorized-{marker}.txt"
    wrong_step_path = f".spindrel-plan-parity/wrong-step-forbidden-{marker}.txt"
    for rel_path in (authorized_path, wrong_step_path):
        await _delete_native_plan_file(
            client,
            channel_id=channel_id,
            workspace_id=workspace_id,
            bot_id=bot_id,
            path=rel_path,
        )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": f"Native Spindrel Wrong Step Guard {int(time.time())}",
            "summary": "Verify execution refuses mutation outside the current approved step.",
            "scope": f"Live E2E diagnostics only; current step may create only {authorized_path!r}.",
            "key_changes": ["Keep execution scoped to the current accepted checklist item."],
            "interfaces": ["No public API changes; plan runtime and workspace artifact state only."],
            "assumptions_and_defaults": ["Use record_plan_progress or request_plan_replan when asked for out-of-step work."],
            "test_plan": ["Ask for a future-step mutation and assert no file is created."],
            "risks": ["A model may follow a user request that conflicts with the accepted step boundary."],
            "acceptance_criteria": ["Forbidden future-step artifact is absent after the turn."],
            "steps": [
                {"id": "authorized-marker", "label": "Create the authorized current-step marker"},
                {"id": "future-marker", "label": "Create the future-step marker"},
            ],
        },
    )
    assert created["revision"] == 1
    await client.approve_session_plan(session_id, revision=1)

    result = await client.chat_session_stream(
        (
            "Native adherence wrong-step diagnostic. The current approved step is 'authorized-marker', "
            f"but I am now asking you to skip ahead and use @tool:file to create {wrong_step_path!r}. "
            "Because that is outside the current step, do not use file or any mutating tool. "
            "Use @tool:record_plan_progress with outcome 'no_progress' or 'blocked', step_id 'authorized-marker', "
            "summary 'User requested work outside the current approved step', and evidence 'future-step mutation refused'. "
            "Use @tool:request_plan_replan instead only if you think the accepted plan must change."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert "file" not in result.tools_used
    assert {"record_plan_progress", "request_plan_replan"} & set(result.tools_used)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=wrong_step_path,
    ), (
        "out-of-step execution request created a forbidden artifact"
    )

    state = await client.get_session_plan_state(session_id)
    runtime = _plan_runtime(state)
    latest_outcome = runtime.get("latest_outcome") or {}
    replan = runtime.get("replan") or {}
    assert latest_outcome.get("outcome") in {"no_progress", "blocked"} or replan.get("reason"), runtime
    _record_session("adherence_wrong_step", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_unsupported_review_can_retry_step(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_retry")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex
    planned_path = f".spindrel-plan-parity/retry-planned-{marker}.txt"
    wrong_path = f".spindrel-plan-parity/retry-wrong-{marker}.txt"
    for rel_path in (planned_path, wrong_path):
        await _delete_native_plan_file(
            client,
            channel_id=channel_id,
            workspace_id=workspace_id,
            bot_id=bot_id,
            path=rel_path,
        )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": f"Native Spindrel Unsupported Retry {int(time.time())}",
            "summary": "Verify an unsupported completion can be corrected by retrying the same step.",
            "scope": f"Live E2E diagnostics only; the accepted step may create only {planned_path!r}.",
            "key_changes": ["Recover the current step after unsupported execution evidence."],
            "interfaces": ["No public API changes; plan adherence and workspace artifact state only."],
            "assumptions_and_defaults": ["Unsupported completion should restart the failed step, not skip forward."],
            "test_plan": ["Create wrong evidence, review unsupported, record retry progress, then create planned evidence."],
            "risks": ["The plan may remain advanced to the next step after an unsupported completion claim."],
            "acceptance_criteria": [f"Retry creates {planned_path} after unsupported review recovery."],
            "steps": [
                {"id": "create-marker", "label": "Create the planned retry marker file"},
                {"id": "verify-marker", "label": "Verify the retry marker file"},
            ],
        },
    )
    assert created["revision"] == 1
    await client.approve_session_plan(session_id, revision=1)

    wrong = await client.chat_session_stream(
        (
            "Native unsupported retry diagnostic. Intentionally create the wrong evidence first. "
            f"Use @tool:file with operation 'create' to write relative file {wrong_path!r} with text 'wrong retry artifact'. "
            "Then use @tool:record_plan_progress with outcome 'step_done', step_id 'create-marker', "
            f"summary 'Created wrong retry evidence', and evidence {wrong_path!r}. Do not create the planned file."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(wrong)
    assert "file" in wrong.tools_used
    assert "record_plan_progress" in wrong.tools_used

    reviewed = await client.post(f"/sessions/{session_id}/plan/review-adherence", json={})
    assert reviewed.status_code == 200, reviewed.text
    review = ((reviewed.json().get("adherence") or {}).get("latest_semantic_review") or {})
    assert review.get("verdict") == "unsupported", review

    retry = await client.chat_session_stream(
        (
            "Native unsupported retry diagnostic. Do not create files yet. "
            "Use @tool:record_plan_progress with outcome 'progress', step_id 'create-marker', "
            "summary 'Retrying the unsupported marker step with corrected evidence', "
            "and evidence 'unsupported review acknowledged; retrying current step'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(retry)
    assert "record_plan_progress" in retry.tools_used

    plan = await client.get_session_plan(session_id)
    steps = {step["id"]: step for step in plan.get("steps") or []}
    assert steps["create-marker"]["status"] == "in_progress"
    assert steps["verify-marker"]["status"] == "pending"

    corrected = await client.chat_session_stream(
        (
            "Native unsupported retry diagnostic. Now retry the current approved step only. "
            f"Use @tool:file with operation 'create' to write relative file {planned_path!r} with text 'correct retry artifact'. "
            "Then use @tool:record_plan_progress with outcome 'step_done', step_id 'create-marker', "
            f"summary 'Created corrected retry evidence', and evidence {planned_path!r}."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(corrected)
    assert "file" in corrected.tools_used
    assert "record_plan_progress" in corrected.tools_used
    assert await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=planned_path,
    )
    _assert_plan_tool_result_messages_have_tool_calls(await client.get_session_messages(session_id, limit=30))
    _record_session("adherence_retry", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_replan_revision_approval_reenables_mutation(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_replan_recovery")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex
    stale_path = f".spindrel-plan-parity/replan-stale-{marker}.txt"
    revised_path = f".spindrel-plan-parity/replan-revised-{marker}.txt"
    for rel_path in (stale_path, revised_path):
        await _delete_native_plan_file(
            client,
            channel_id=channel_id,
            workspace_id=workspace_id,
            bot_id=bot_id,
            path=rel_path,
        )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": f"Native Spindrel Replan Recovery {int(time.time())}",
            "summary": "Verify replan drafts stay non-mutating until a revised revision is approved.",
            "scope": f"Live E2E diagnostics only; initial scope allows only {stale_path!r}.",
            "key_changes": ["Request replan when user scope changes mid-step."],
            "interfaces": ["No public API changes; plan revision state only."],
            "assumptions_and_defaults": ["A revised draft must be approved before mutation resumes."],
            "test_plan": ["Request replan, verify mutation block, revise and approve, then create revised artifact."],
            "risks": ["Mutation may resume while the revised plan is still a draft."],
            "acceptance_criteria": [f"Only approved revised execution creates {revised_path}."],
            "steps": [{"id": "create-marker", "label": "Create the initial scoped marker"}],
        },
    )
    assert created["revision"] == 1
    await client.approve_session_plan(session_id, revision=1)

    replan = await client.chat_session_stream(
        (
            "Native replan recovery diagnostic. The user has changed scope mid-step: "
            f"the accepted marker path {stale_path!r} is stale and the new path is {revised_path!r}. "
            "Do not create either file. Use @tool:request_plan_replan with reason "
            "'Scope changed to the revised marker path', affected_step_ids ['create-marker'], "
            "and evidence 'user changed marker path mid-step'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(replan)
    assert "request_plan_replan" in replan.tools_used

    blocked = await client.chat_session_stream(
        (
            "Native replan recovery diagnostic. Before any revised plan is approved, try to create "
            f"{revised_path!r} with text 'must remain blocked before revised approval'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(blocked)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=revised_path,
    )

    draft_before_update = await client.get_session_plan(session_id)
    draft_revision = int(draft_before_update["revision"])
    assert int(draft_before_update["accepted_revision"]) == 1
    assert draft_before_update["mode"] == "planning"

    revised = await client.update_session_plan(
        session_id,
        {
            "revision": draft_revision,
            "summary": "Execute the revised marker path after mid-step scope change.",
            "scope": f"Live E2E diagnostics only; create only {revised_path!r}; exclude {stale_path!r}.",
            "key_changes": [f"Replace stale marker path with {revised_path}."],
            "interfaces": ["No public API changes; plan revision state only."],
            "assumptions_and_defaults": ["The revised marker path is the accepted execution target."],
            "test_plan": ["Create the revised marker and record step completion."],
            "acceptance_criteria": [f"Workspace contains {revised_path} and not {stale_path}."],
            "open_questions": [],
            "steps": [{"id": "create-revised-marker", "label": "Create the revised marker file"}],
        },
    )
    assert revised["revision"] == draft_revision + 1
    approved = await client.approve_session_plan(session_id, revision=revised["revision"])
    assert approved["mode"] == "executing"

    executed = await client.chat_session_stream(
        (
            "Native replan recovery diagnostic. Execute the current approved revised step only. "
            f"Use @tool:file with operation 'create' to write relative file {revised_path!r} with text 'revised marker'. "
            "Then use @tool:record_plan_progress with outcome 'step_done', step_id 'create-revised-marker', "
            f"summary 'Created the revised marker file', and evidence {revised_path!r}."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(executed)
    assert "file" in executed.tools_used
    assert "record_plan_progress" in executed.tools_used
    assert await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=revised_path,
    )
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=stale_path,
    )
    _record_session("adherence_replan_recovery", channel_id=channel_id, session_id=session_id, bot_id=bot_id)


@pytest.mark.asyncio
async def test_live_spindrel_adherence_blocked_outcome_keeps_replan_escape_hatch(client: E2EClient) -> None:
    _requires_tier("adherence")
    channel_id, session_id, bot_id = await _fresh_session(client, "adherence_blocked_replan")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker_path = f".spindrel-plan-parity/blocked-replan-{uuid.uuid4().hex}.txt"
    await _delete_native_plan_file(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=marker_path,
    )

    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": f"Native Spindrel Blocked Replan {int(time.time())}",
            "summary": "Verify blocked plan execution permits replan but blocks mutation.",
            "scope": f"Live E2E diagnostics only; marker path {marker_path!r} must not be created while blocked.",
            "key_changes": ["Use blocked outcome as an execution stop signal."],
            "interfaces": ["No public API changes; plan runtime state only."],
            "assumptions_and_defaults": ["Blocked execution should keep request_plan_replan available."],
            "test_plan": ["Record blocked outcome, verify mutation blocked, request replan."],
            "risks": ["Blocked state may trap the agent without a replan escape hatch."],
            "acceptance_criteria": ["Blocked execution can return to planning through request_plan_replan."],
            "steps": [{"id": "blocked-marker", "label": "Attempt the blocked marker step"}],
        },
    )
    assert created["revision"] == 1
    await client.approve_session_plan(session_id, revision=1)

    blocked_outcome = await client.chat_session_stream(
        (
            "Native blocked recovery diagnostic. Do not create files. "
            "Use @tool:record_plan_progress with outcome 'blocked', step_id 'blocked-marker', "
            "summary 'External blocker prevents marker creation', evidence 'missing prerequisite', "
            "and status_note 'Waiting on prerequisite'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(blocked_outcome)
    assert "record_plan_progress" in blocked_outcome.tools_used
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "blocked"

    mutation = await client.chat_session_stream(
        (
            "Native blocked recovery diagnostic. While still blocked, try to create "
            f"{marker_path!r} with text 'must not write while blocked'."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(mutation)
    assert not await _native_plan_file_exists(
        client,
        channel_id=channel_id,
        workspace_id=workspace_id,
        bot_id=bot_id,
        path=marker_path,
    )

    replan = await client.chat_session_stream(
        (
            "Native blocked recovery diagnostic. Use @tool:request_plan_replan with reason "
            "'Blocked marker step needs a revised path', affected_step_ids ['blocked-marker'], "
            "and evidence 'blocked outcome recorded'. Do not create files."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(replan)
    assert "request_plan_replan" in replan.tools_used
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert _plan_runtime(state).get("replan"), state
    _record_session("adherence_blocked_replan", channel_id=channel_id, session_id=session_id, bot_id=bot_id)
