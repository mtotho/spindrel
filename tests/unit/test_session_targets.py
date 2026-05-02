import uuid

import pytest

from app.db.models import Session
from app.services.session_targets import (
    normalize_session_target,
    resolve_task_session_target,
    validate_session_target_for_channel,
)
from tests.factories import build_channel, build_task


@pytest.mark.asyncio
async def test_validate_existing_session_target_accepts_visible_channel_session(db_session):
    channel = build_channel(client_id="channel:test")
    session = Session(
        id=uuid.uuid4(),
        client_id="channel:test",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        session_type="channel",
    )
    db_session.add_all([channel, session])
    await db_session.commit()

    target = await validate_session_target_for_channel(
        db_session,
        channel.id,
        {"mode": "existing", "session_id": str(session.id)},
    )

    assert target == {"mode": "existing", "session_id": str(session.id)}


@pytest.mark.asyncio
async def test_validate_existing_session_target_rejects_other_channel(db_session):
    channel = build_channel(client_id="channel:one")
    other = build_channel(client_id="channel:two")
    session = Session(
        id=uuid.uuid4(),
        client_id="channel:two",
        bot_id=other.bot_id,
        channel_id=other.id,
        session_type="channel",
    )
    db_session.add_all([channel, other, session])
    await db_session.commit()

    with pytest.raises(ValueError, match="does not belong"):
        await validate_session_target_for_channel(
            db_session,
            channel.id,
            {"mode": "existing", "session_id": str(session.id)},
        )


@pytest.mark.asyncio
async def test_resolve_new_each_run_creates_visible_channel_session(db_session):
    channel = build_channel(client_id="channel:new-each")
    task = build_task(
        bot_id=channel.bot_id,
        channel_id=channel.id,
        client_id=channel.client_id,
        execution_config={"session_target": {"mode": "new_each_run"}},
    )
    db_session.add_all([channel, task])
    await db_session.commit()

    session_id, resolved_channel = await resolve_task_session_target(db_session, task)
    await db_session.commit()

    session = await db_session.get(Session, session_id)
    assert resolved_channel.id == channel.id
    assert task.session_id == session_id
    assert session is not None
    assert session.channel_id == channel.id
    assert session.session_type == "channel"
    assert session.source_task_id is None
    assert session.metadata_["created_by"] == "task_session_target"


@pytest.mark.asyncio
async def test_resolve_api_task_keeps_explicit_session_by_default(db_session):
    channel = build_channel(client_id="channel:api-existing")
    active_session = Session(
        id=uuid.uuid4(),
        client_id=channel.client_id,
        bot_id=channel.bot_id,
        channel_id=channel.id,
        session_type="channel",
    )
    detached_session = Session(
        id=uuid.uuid4(),
        client_id=channel.client_id,
        bot_id=channel.bot_id,
        channel_id=channel.id,
        session_type="channel",
    )
    channel.active_session_id = active_session.id
    task = build_task(
        bot_id=channel.bot_id,
        channel_id=channel.id,
        client_id=channel.client_id,
        session_id=detached_session.id,
        task_type="api",
        execution_config={"pre_user_msg_id": str(uuid.uuid4())},
    )
    db_session.add_all([channel, active_session, detached_session, task])
    await db_session.commit()

    session_id, resolved_channel = await resolve_task_session_target(db_session, task)
    await db_session.commit()

    assert resolved_channel.id == channel.id
    assert session_id == detached_session.id
    assert task.session_id == detached_session.id


@pytest.mark.asyncio
async def test_resolve_non_api_channel_task_defaults_to_primary(db_session):
    channel = build_channel(client_id="channel:primary-default")
    active_session = Session(
        id=uuid.uuid4(),
        client_id=channel.client_id,
        bot_id=channel.bot_id,
        channel_id=channel.id,
        session_type="channel",
    )
    older_session = Session(
        id=uuid.uuid4(),
        client_id=channel.client_id,
        bot_id=channel.bot_id,
        channel_id=channel.id,
        session_type="channel",
    )
    channel.active_session_id = active_session.id
    task = build_task(
        bot_id=channel.bot_id,
        channel_id=channel.id,
        client_id=channel.client_id,
        session_id=older_session.id,
        task_type="agent",
        execution_config={},
    )
    db_session.add_all([channel, active_session, older_session, task])
    await db_session.commit()

    session_id, _ = await resolve_task_session_target(db_session, task)
    await db_session.commit()

    assert session_id == active_session.id
    assert task.session_id == active_session.id


def test_normalize_session_target_defaults_to_primary():
    assert normalize_session_target(None) == {"mode": "primary"}


def test_normalize_session_target_rejects_missing_existing_session_id():
    with pytest.raises(ValueError, match="session_id is required"):
        normalize_session_target({"mode": "existing"})
