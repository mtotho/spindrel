import uuid

import pytest

from app.db.models import Channel, Session
from app.services.agent_harnesses.settings import load_session_settings
from app.services.channels import create_detached_channel_session, reset_channel_session


@pytest.mark.asyncio
async def test_create_detached_channel_session_inherits_harness_model_effort_from_source(db_session):
    channel_id = uuid.uuid4()
    source_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        name="Harness",
        bot_id="harness-bot",
        client_id=f"harness-{uuid.uuid4().hex[:8]}",
        active_session_id=source_id,
    )
    source = Session(
        id=source_id,
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="harness-bot",
        channel_id=channel_id,
        metadata_={
            "harness_settings": {
                "model": "codex-fast",
                "mode_models": {
                    "default": "codex-fast",
                    "plan": "codex-deep",
                },
                "effort": "high",
                "runtime_settings": {"permission_mode": "workspace-write"},
            },
            "harness_resume_reset_at": "do-not-copy",
        },
    )
    db_session.add_all([channel, source])
    await db_session.commit()

    new_session_id = await create_detached_channel_session(
        db_session,
        channel,
        source_session_id=source_id,
    )

    new_session = await db_session.get(Session, new_session_id)
    assert new_session is not None
    assert new_session.metadata_ == {
        "harness_settings": {
            "model": "codex-fast",
            "mode_models": {
                "default": "codex-fast",
                "plan": "codex-deep",
            },
            "effort": "high",
            "runtime_settings": {"permission_mode": "workspace-write"},
        }
    }
    settings = await load_session_settings(db_session, new_session_id)
    assert settings.model == "codex-fast"
    assert settings.effort == "high"
    assert settings.mode_models == {"default": "codex-fast", "plan": "codex-deep"}


@pytest.mark.asyncio
async def test_reset_channel_session_inherits_harness_settings_from_active_session(db_session):
    channel_id = uuid.uuid4()
    source_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        name="Harness",
        bot_id="harness-bot",
        client_id=f"harness-{uuid.uuid4().hex[:8]}",
        active_session_id=source_id,
    )
    source = Session(
        id=source_id,
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="harness-bot",
        channel_id=channel_id,
        metadata_={"harness_settings": {"model": "claude-haiku-4-5", "effort": "low"}},
    )
    db_session.add_all([channel, source])
    await db_session.commit()

    new_session_id = await reset_channel_session(db_session, channel)

    new_session = await db_session.get(Session, new_session_id)
    assert new_session is not None
    assert channel.active_session_id == new_session_id
    assert new_session.metadata_ == {
        "harness_settings": {"model": "claude-haiku-4-5", "effort": "low"}
    }


@pytest.mark.asyncio
async def test_create_detached_channel_session_does_not_copy_cross_channel_source(db_session):
    channel_id = uuid.uuid4()
    other_channel_id = uuid.uuid4()
    source_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        name="Harness",
        bot_id="harness-bot",
        client_id=f"harness-{uuid.uuid4().hex[:8]}",
    )
    source = Session(
        id=source_id,
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="harness-bot",
        channel_id=other_channel_id,
        metadata_={"harness_settings": {"model": "wrong-channel", "effort": "high"}},
    )
    db_session.add_all([channel, source])
    await db_session.commit()

    new_session_id = await create_detached_channel_session(
        db_session,
        channel,
        source_session_id=source_id,
    )

    new_session = await db_session.get(Session, new_session_id)
    assert new_session is not None
    assert new_session.metadata_ == {}
