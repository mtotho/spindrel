from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Attachment, Channel, Message, Session, Task
from app.services.chat_late_input import claim_pending_chat_burst
from app.services.sessions import _filter_messages_to_persist


pytestmark = pytest.mark.asyncio


async def _seed_session_channel(db_session, *, bot_id: str = "bot-a"):
    session_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    db_session.add(Session(
        id=session_id,
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        bot_id=bot_id,
        channel_id=channel_id,
    ))
    db_session.add(Channel(
        id=channel_id,
        name="Test Channel",
        bot_id=bot_id,
        client_id=f"channel-{uuid.uuid4().hex[:8]}",
        active_session_id=session_id,
    ))
    await db_session.commit()
    return session_id, channel_id


async def test_claim_pending_chat_burst_marks_task_complete_and_preserves_order(db_session):
    session_id, channel_id = await _seed_session_channel(db_session)
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    task_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    db_session.add_all([
        Message(id=second_id, session_id=session_id, role="user", content="second"),
        Message(id=first_id, session_id=session_id, role="user", content="first"),
        Task(
            id=task_id,
            bot_id="bot-a",
            client_id="client-a",
            session_id=session_id,
            channel_id=channel_id,
            prompt="queued",
            status="pending",
            task_type="api",
            created_at=created_at,
            execution_config={
                "chat_burst": True,
                "burst_user_msg_ids": [str(first_id), str(second_id)],
                "pre_user_msg_id": str(first_id),
            },
        ),
    ])
    await db_session.commit()

    absorbed = await claim_pending_chat_burst(
        db_session,
        session_id=session_id,
        channel_id=channel_id,
        bot_id="bot-a",
        correlation_id=uuid.uuid4(),
    )
    await db_session.commit()

    assert absorbed is not None
    assert absorbed.task_id == task_id
    assert absorbed.message_ids == [first_id, second_id]
    assert [msg.content for msg in absorbed.messages] == ["first", "second"]
    assert absorbed.task_scheduled_age_seconds >= 4

    task = await db_session.get(Task, task_id)
    assert task.status == "complete"
    assert task.completed_at is not None
    assert task.result == "[absorbed into active turn]"
    assert task.execution_config["absorbed_message_ids"] == [str(first_id), str(second_id)]
    assert task.execution_config["absorbed_by_correlation_id"]
    assert task.execution_config["absorbed_at"]


async def test_claim_pending_chat_burst_does_not_claim_running_or_nonmatching_tasks(db_session):
    session_id, channel_id = await _seed_session_channel(db_session)
    message_id = uuid.uuid4()
    db_session.add(Message(id=message_id, session_id=session_id, role="user", content="late"))
    running = Task(
        id=uuid.uuid4(),
        bot_id="bot-a",
        client_id="client-a",
        session_id=session_id,
        channel_id=channel_id,
        prompt="running",
        status="running",
        task_type="api",
        execution_config={"chat_burst": True, "burst_user_msg_ids": [str(message_id)]},
    )
    other_bot = Task(
        id=uuid.uuid4(),
        bot_id="bot-b",
        client_id="client-a",
        session_id=session_id,
        channel_id=channel_id,
        prompt="other bot",
        status="pending",
        task_type="api",
        execution_config={"chat_burst": True, "burst_user_msg_ids": [str(message_id)]},
    )
    db_session.add_all([running, other_bot])
    await db_session.commit()

    absorbed = await claim_pending_chat_burst(
        db_session,
        session_id=session_id,
        channel_id=channel_id,
        bot_id="bot-a",
        correlation_id=uuid.uuid4(),
    )

    assert absorbed is None
    assert (await db_session.get(Task, running.id)).status == "running"
    assert (await db_session.get(Task, other_bot.id)).status == "pending"


async def test_claim_pending_chat_burst_returns_image_payloads_by_message(db_session):
    session_id, channel_id = await _seed_session_channel(db_session)
    message_id = uuid.uuid4()
    attachment_id = uuid.uuid4()
    db_session.add(Message(id=message_id, session_id=session_id, role="user", content="see image"))
    db_session.add(Attachment(
        id=attachment_id,
        message_id=message_id,
        channel_id=channel_id,
        type="image",
        filename="graph.png",
        mime_type="image/png",
        size_bytes=3,
        file_data=b"abc",
    ))
    db_session.add(Task(
        id=uuid.uuid4(),
        bot_id="bot-a",
        client_id="client-a",
        session_id=session_id,
        channel_id=channel_id,
        prompt="queued",
        status="pending",
        task_type="api",
        execution_config={"chat_burst": True, "burst_user_msg_ids": [str(message_id)]},
    ))
    await db_session.commit()

    absorbed = await claim_pending_chat_burst(
        db_session,
        session_id=session_id,
        channel_id=channel_id,
        bot_id="bot-a",
        correlation_id=uuid.uuid4(),
    )

    assert absorbed is not None
    assert absorbed.attachment_payloads == [{
        "type": "image",
        "content": "YWJj",
        "mime_type": "image/png",
        "name": "graph.png",
        "attachment_id": str(attachment_id),
        "source": "late_chat_burst",
    }]
    assert absorbed.attachments_by_message_id[message_id] == absorbed.attachment_payloads


async def test_skip_persist_messages_are_filtered():
    kept = {"role": "assistant", "content": "done"}
    skipped_user = {
        "role": "user",
        "content": "already persisted",
        "_skip_persist": True,
    }

    assert _filter_messages_to_persist(
        [{"role": "system", "content": "policy"}, skipped_user, kept],
        0,
        pre_user_msg_id=None,
    ) == [kept]

    assert _filter_messages_to_persist(
        [{"role": "user", "content": "pre"}, skipped_user, kept],
        0,
        pre_user_msg_id=uuid.uuid4(),
    ) == [kept]
