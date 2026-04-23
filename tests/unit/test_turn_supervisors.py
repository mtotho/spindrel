from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import Session
from app.services import session_plan_mode as spm
from app.services import turn_supervisors as supervisors


def _make_session() -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id=f"client-{uuid.uuid4().hex[:6]}",
        bot_id="test-bot",
        channel_id=uuid.uuid4(),
        metadata_={},
    )


def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(spm, "get_bot", lambda _bot_id: SimpleNamespace(id="test-bot"))
    monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))


async def test_turn_supervisor_errors_are_swallowed(monkeypatch):
    called = False

    async def bad(_ctx):
        raise RuntimeError("boom")

    async def good(_ctx):
        nonlocal called
        called = True

    monkeypatch.setattr(supervisors, "_turn_supervisors", [bad, good])

    await supervisors.run_turn_supervisors(
        supervisors.TurnEndContext(
            session_id=uuid.uuid4(),
            bot_id="test-bot",
            turn_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
        )
    )

    assert called is True


async def test_plan_supervisor_marks_missing_outcome_pending(
    monkeypatch,
    tmp_path,
):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Supervised Plan",
        summary="Require a turn-end outcome.",
        scope="Internal supervisor enforcement.",
        acceptance_criteria=["Missing outcomes are recorded."],
        steps=[{"id": "audit", "label": "Audit supervisor state"}],
    )
    spm.approve_session_plan(session)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, _model, session_id):
            assert session_id == session.id
            return session

        async def commit(self):
            return None

    monkeypatch.setattr(supervisors, "async_session", lambda: _FakeSession())
    monkeypatch.setattr(spm, "publish_session_plan_event", lambda *_args, **_kwargs: None)

    turn_id = uuid.uuid4()
    await supervisors.run_turn_supervisors(
        supervisors.TurnEndContext(
            session_id=session.id,
            channel_id=session.channel_id,
            bot_id="test-bot",
            turn_id=turn_id,
            correlation_id=turn_id,
            result="I changed something but did not record a plan outcome.",
        )
    )

    pending = session.metadata_["plan_runtime"]["pending_turn_outcome"]
    assert pending["turn_id"] == str(turn_id)
    assert pending["step_id"] == "audit"
