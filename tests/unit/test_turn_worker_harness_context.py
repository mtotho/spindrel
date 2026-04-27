from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.agent_harnesses.base import TurnResult
from app.services.turn_worker import _run_harness_turn


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


async def _async_value(value):
    return value
