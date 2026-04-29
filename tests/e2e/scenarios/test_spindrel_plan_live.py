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


def _plan_runtime(state: dict) -> dict:
    runtime = state.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


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


async def _create_approved_execution_plan(client: E2EClient, session_id: str, *, title: str) -> dict:
    await client.start_session_plan_mode(session_id)
    created = await client.create_session_plan(
        session_id,
        {
            "title": title,
            "summary": "Verify native Spindrel plan execution parity.",
            "scope": "Live E2E diagnostics only; do not modify repository files.",
            "acceptance_criteria": ["Plan progress can be recorded"],
            "steps": [
                {"id": "step-1", "label": "Begin approved execution"},
                {"id": "step-2", "label": "Record execution outcome"},
            ],
        },
    )
    assert created["revision"] == 1
    approved = await client.approve_session_plan(session_id, revision=1)
    assert approved["mode"] == "executing"
    assert approved["accepted_revision"] == 1
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
            "outcome 'step_done', step_id 'step-1', summary 'Completed step one in the live "
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
    assert latest.get("outcome") == "step_done"
    assert latest.get("step_id") == "step-1"

    plan = await client.get_session_plan(session_id)
    steps = {step["id"]: step for step in plan.get("steps") or []}
    assert steps["step-1"]["status"] == "done"
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
    await client.delete_workspace_path(workspace_id, rel_path)
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

    assert not await _workspace_file_exists(client, workspace_id, rel_path), (
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
                "question_id": "risk",
                "label": "Risk focus",
                "answer": "Prioritize stale-plan handling and missing-outcome blocking.",
            },
            {
                "question_id": "done",
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
    await client.delete_workspace_path(workspace_id, rel_path)
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
    assert not await _workspace_file_exists(client, workspace_id, rel_path)
    state = await client.get_session_plan_state(session_id)
    assert state["mode"] == "planning"
    assert state["has_plan"] is False


@pytest.mark.asyncio
async def test_live_spindrel_behavior_missing_outcome_blocks_next_mutation(client: E2EClient) -> None:
    _requires_tier("behavior")
    channel_id, session_id, bot_id = await _fresh_session(client, "behavior_pending")
    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    rel_path = f".spindrel-plan-parity/pending-outcome-{uuid.uuid4().hex}.txt"
    await client.delete_workspace_path(workspace_id, rel_path)
    title = f"Native Spindrel Pending Outcome Parity {int(time.time())}"
    await _create_approved_execution_plan(client, session_id, title=title)

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
    assert not await _workspace_file_exists(client, workspace_id, rel_path)
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
