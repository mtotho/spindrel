from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.routers.chat._routes import _queue_channel_task
from app.schemas.chat import ChatRequest


pytestmark = pytest.mark.asyncio


class _FakeDb:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)


async def test_queued_channel_task_carries_pre_persisted_user_message_id():
    db = _FakeDb()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    pre_user_msg_id = uuid.uuid4()
    run = SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
        session_id=session_id,
        session_scoped_delivery=False,
    )

    task = await _queue_channel_task(
        db=db,
        req=ChatRequest(message="queued", bot_id="bot-a"),
        run=run,
        message="queued",
        pre_user_msg_id=pre_user_msg_id,
    )

    assert db.added == [task]
    assert task.session_id == session_id
    assert task.channel_id == channel_id
    assert task.prompt == "queued"
    assert task.execution_config == {"pre_user_msg_id": str(pre_user_msg_id)}


async def test_session_scoped_queued_channel_task_keeps_delivery_policy_and_pre_user_id():
    db = _FakeDb()
    pre_user_msg_id = uuid.uuid4()
    run = SimpleNamespace(
        channel=SimpleNamespace(id=uuid.uuid4()),
        session_id=uuid.uuid4(),
        session_scoped_delivery=True,
    )

    task = await _queue_channel_task(
        db=db,
        req=ChatRequest(message="queued", bot_id="bot-a", external_delivery="none"),
        run=run,
        message="queued",
        pre_user_msg_id=pre_user_msg_id,
    )

    assert task.execution_config == {
        "session_scoped": True,
        "external_delivery": "none",
        "pre_user_msg_id": str(pre_user_msg_id),
    }


async def test_busy_queued_channel_task_can_be_initially_deferred():
    db = _FakeDb()
    run = SimpleNamespace(
        channel=SimpleNamespace(id=uuid.uuid4()),
        session_id=uuid.uuid4(),
        session_scoped_delivery=True,
    )

    task = await _queue_channel_task(
        db=db,
        req=ChatRequest(message="queued", bot_id="bot-a", external_delivery="none"),
        run=run,
        message="queued",
        pre_user_msg_id=uuid.uuid4(),
        delay_seconds=10,
    )

    assert task.scheduled_at is not None
    assert task.scheduled_at > task.created_at
