from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.agent_harnesses.base import TurnResult
from app.services.turn_worker import (
    _codex_plan_evidence,
    _mirror_harness_native_plan_state,
    _metadata_has_codex_plan_signal,
    _run_harness_turn,
    _tool_calls_include_exit_plan_mode,
)


pytestmark = pytest.mark.asyncio


class _FakeSessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, *args, **kwargs):
        return None


class _FakePlanSessionFactory:
    def __init__(self, session) -> None:
        self.session = session
        self.commits = 0

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, *args, **kwargs):
        return self.session

    async def commit(self):
        self.commits += 1

    async def refresh(self, session):
        return None


class _FakeChannelPromptSessionFactory(_FakeSessionFactory):
    def __init__(self, channel_prompt: str) -> None:
        self.channel_prompt = channel_prompt

    async def get(self, model, ident, *args, **kwargs):
        if getattr(model, "__name__", "") == "Channel":
            return SimpleNamespace(
                channel_prompt=self.channel_prompt,
                channel_prompt_workspace_file_path=None,
                channel_prompt_workspace_id=None,
            )
        return None


class _RuntimeCapturingContext:
    name = "codex"

    def __init__(self) -> None:
        self.ctx = None

    async def start_turn(self, *, ctx, prompt, emit):
        self.ctx = ctx
        return TurnResult(
            session_id="native-after-turn",
            final_text="done",
            metadata={"codex_dynamic_tools_signature": "next-signature"},
        )


class _RuntimeNeverCompletes:
    name = "claude-code"

    def __init__(self) -> None:
        self.cancelled = False

    async def start_turn(self, *, ctx, prompt, emit):
        emit.tool_start(tool_name="Bash", arguments={"cmd": "ls"})
        try:
            await _sleep_forever()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_codex_plan_metadata_detection_and_evidence():
    metadata = {
        "codex_native_plan": [
            {"status": "pending", "step": "Inspect bridge state"},
            {"status": "inProgress", "step": "Patch dynamic tools"},
        ]
    }

    assert _metadata_has_codex_plan_signal(metadata) is True
    assert _codex_plan_evidence(metadata) == [
        "Codex native plan steps: pending: Inspect bridge state; inProgress: Patch dynamic tools"
    ]


async def test_claude_exit_plan_mode_tool_detection():
    assert _tool_calls_include_exit_plan_mode([
        {"function": {"name": "Read", "arguments": {}}},
        {"function": {"name": "ExitPlanMode", "arguments": {"plan": "Ship it"}}},
    ]) is True
    assert _tool_calls_include_exit_plan_mode([
        {"function": {"name": "Read", "arguments": {}}},
    ]) is False


async def test_claude_exit_plan_mode_tool_does_not_leave_spindrel_plan_mode(monkeypatch):
    session = SimpleNamespace(metadata_={"plan_mode": "planning"})
    factory = _FakePlanSessionFactory(session)
    monkeypatch.setattr("app.services.turn_worker.async_session", factory)

    await _mirror_harness_native_plan_state(
        session_id=uuid.uuid4(),
        runtime_name="claude-code",
        result_metadata={},
        persisted_tool_calls=[
            {"function": {"name": "ExitPlanMode", "arguments": {"plan": "Ship it"}}},
        ],
    )

    assert session.metadata_["plan_mode"] == "planning"
    assert factory.commits == 0


async def test_harness_turn_context_carries_latest_harness_metadata(monkeypatch):
    runtime = _RuntimeCapturingContext()
    latest_meta = {
        "runtime": "codex",
        "session_id": "native-before-turn",
        "codex_dynamic_tools_signature": "prior-signature",
    }

    async def _load_latest_harness_metadata(db, session_id):
        return latest_meta, datetime.now(timezone.utc)

    async def _persist_turn(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.turn_worker.async_session",
        _FakeSessionFactory(),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.get_runtime",
        lambda runtime_name: runtime,
    )
    monkeypatch.setattr(
        "app.services.turn_worker._load_prior_harness_session_id",
        lambda session_id: _async_value("native-before-turn"),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.persist_turn",
        _persist_turn,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.load_session_mode",
        lambda db, session_id: _async_value("default"),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.revoke_turn_bypass",
        lambda turn_id: None,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.settings.load_session_settings",
        lambda db, session_id: _async_value(
            SimpleNamespace(model=None, effort=None, runtime_settings={})
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_context_hints",
        lambda db, session_id: _async_value(()),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.clear_consumed_context_hints",
        lambda db, session_id: _async_value(None),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_latest_harness_metadata",
        _load_latest_harness_metadata,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        lambda db, channel_id, bot: _async_value(
            SimpleNamespace(
                workdir="/tmp",
                source="bot",
                bot_workspace_dir="/tmp/bot",
                project_dir=None,
            )
        ),
    )

    text, error = await _run_harness_turn(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        bot=SimpleNamespace(
            id="codex-bot",
            harness_runtime="codex",
            harness_workdir="/tmp",
            memory_scheme=None,
        ),
        user_message="hello",
        correlation_id=uuid.uuid4(),
        msg_metadata=None,
        pre_user_msg_id=None,
        suppress_outbox=True,
    )

    assert error is None
    assert text == "done"
    assert runtime.ctx is not None
    assert runtime.ctx.harness_metadata == latest_meta


async def test_harness_turn_context_includes_channel_prompt_instruction(monkeypatch):
    runtime = _RuntimeCapturingContext()

    async def _persist_turn(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.turn_worker.async_session",
        _FakeChannelPromptSessionFactory("Channel prompt marker: PLAN-123"),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.get_runtime",
        lambda runtime_name: runtime,
    )
    monkeypatch.setattr(
        "app.services.turn_worker._load_prior_harness_session_id",
        lambda session_id: _async_value(None),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.persist_turn",
        _persist_turn,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.load_session_mode",
        lambda db, session_id: _async_value("default"),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.revoke_turn_bypass",
        lambda turn_id: None,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.settings.load_session_settings",
        lambda db, session_id: _async_value(
            SimpleNamespace(model=None, effort=None, runtime_settings={})
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_context_hints",
        lambda db, session_id: _async_value(()),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.clear_consumed_context_hints",
        lambda db, session_id: _async_value(None),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_latest_harness_metadata",
        lambda db, session_id: _async_value(({}, None)),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        lambda db, channel_id, bot: _async_value(
            SimpleNamespace(
                workdir="/tmp",
                source="bot",
                bot_workspace_dir="/tmp/bot",
                project_dir=None,
            )
        ),
    )

    text, error = await _run_harness_turn(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        bot=SimpleNamespace(
            id="codex-bot",
            harness_runtime="codex",
            harness_workdir="/tmp",
            memory_scheme=None,
        ),
        user_message="hello",
        correlation_id=uuid.uuid4(),
        msg_metadata=None,
        pre_user_msg_id=None,
        suppress_outbox=True,
    )

    assert error is None
    assert text == "done"
    assert runtime.ctx is not None
    [hint] = runtime.ctx.context_hints
    assert hint.kind == "channel_prompt"
    assert hint.priority == "instruction"
    assert hint.consume_after_next_turn is False
    assert "PLAN-123" in hint.text


async def test_harness_heartbeat_turn_marks_persisted_rows(monkeypatch):
    runtime = _RuntimeCapturingContext()
    persisted_kwargs: list[dict] = []

    async def _persist_turn(*args, **kwargs):
        persisted_kwargs.append(kwargs)
        return None

    monkeypatch.setattr(
        "app.services.turn_worker.async_session",
        _FakeSessionFactory(),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.get_runtime",
        lambda runtime_name: runtime,
    )
    monkeypatch.setattr(
        "app.services.turn_worker._load_prior_harness_session_id",
        lambda session_id: _async_value(None),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.persist_turn",
        _persist_turn,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.load_session_mode",
        lambda db, session_id: _async_value("default"),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.revoke_turn_bypass",
        lambda turn_id: None,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.settings.load_session_settings",
        lambda db, session_id: _async_value(
            SimpleNamespace(model=None, effort=None, runtime_settings={})
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_context_hints",
        lambda db, session_id: _async_value(()),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.clear_consumed_context_hints",
        lambda db, session_id: _async_value(None),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_latest_harness_metadata",
        lambda db, session_id: _async_value(({}, None)),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        lambda db, channel_id, bot: _async_value(
            SimpleNamespace(
                workdir="/tmp",
                source="bot",
                bot_workspace_dir="/tmp/bot",
                project_dir=None,
            )
        ),
    )

    text, error = await _run_harness_turn(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        bot=SimpleNamespace(
            id="codex-bot",
            harness_runtime="codex",
            harness_workdir="/tmp",
            memory_scheme=None,
        ),
        user_message="heartbeat",
        correlation_id=uuid.uuid4(),
        msg_metadata={"source": "heartbeat", "is_heartbeat": True},
        pre_user_msg_id=None,
        suppress_outbox=True,
        is_heartbeat=True,
    )

    assert error is None
    assert text == "done"
    assert persisted_kwargs
    assert persisted_kwargs[-1]["is_heartbeat"] is True


async def test_harness_turn_cancel_persists_interrupted_tool_transcript(monkeypatch):
    runtime = _RuntimeNeverCompletes()
    persisted: list[list[dict]] = []

    async def _persist_turn(db, session_id, bot, messages, *args, **kwargs):
        persisted.append(messages)
        return None

    monkeypatch.setattr(
        "app.services.turn_worker.async_session",
        _FakeSessionFactory(),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.get_runtime",
        lambda runtime_name: runtime,
    )
    monkeypatch.setattr(
        "app.services.turn_worker._load_prior_harness_session_id",
        lambda session_id: _async_value("native-before-turn"),
    )
    monkeypatch.setattr(
        "app.services.turn_worker.persist_turn",
        _persist_turn,
    )
    monkeypatch.setattr(
        "app.services.turn_worker.session_locks.is_cancel_requested",
        lambda session_id: True,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.load_session_mode",
        lambda db, session_id: _async_value("default"),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.revoke_turn_bypass",
        lambda turn_id: None,
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.settings.load_session_settings",
        lambda db, session_id: _async_value(
            SimpleNamespace(model=None, effort=None, runtime_settings={})
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_context_hints",
        lambda db, session_id: _async_value(()),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.session_state.load_latest_harness_metadata",
        lambda db, session_id: _async_value(({}, None)),
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        lambda db, channel_id, bot: _async_value(
            SimpleNamespace(
                workdir="/tmp",
                source="bot",
                bot_workspace_dir="/tmp/bot",
                project_dir=None,
            )
        ),
    )

    text, error = await _run_harness_turn(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        bot=SimpleNamespace(
            id="claude-bot",
            harness_runtime="claude-code",
            harness_workdir="/tmp",
            memory_scheme=None,
        ),
        user_message="stop this",
        correlation_id=uuid.uuid4(),
        msg_metadata=None,
        pre_user_msg_id=None,
        suppress_outbox=True,
    )

    assert text == ""
    assert error == "cancelled"
    assert runtime.cancelled is True
    assert len(persisted) == 1
    assistant = persisted[0][1]
    assert assistant["_turn_cancelled"] is True
    assert assistant["_harness"]["interrupted"] is True
    assert assistant["tool_calls"][0]["function"]["name"] == "Bash"


async def _async_value(value):
    return value


async def _sleep_forever():
    await asyncio.Event().wait()
