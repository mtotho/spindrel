"""Unit coverage for app.services.agent_harnesses.settings.

PATCH semantics (missing key = no change, null = clear, value = set), the
256-char model guard, and round-trip via load_session_settings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Session as SessionRow
from app.services.agent_harnesses.settings import (
    HARNESS_SETTINGS_KEY,
    MODEL_ID_MAX_LEN,
    HarnessSettings,
    load_session_settings,
    patch_session_settings,
)
from app.services import session_plan_mode as spm
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def session_row(db_session):
    bot = build_bot(id="harness-settings-bot", name="HS Bot", model="x")
    bot.harness_runtime = "claude-code"
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return session


async def test_load_returns_defaults_when_unset(session_row, db_session):
    settings = await load_session_settings(db_session, session_row.id)
    assert settings == HarnessSettings()


async def test_load_returns_defaults_for_missing_session(db_session):
    settings = await load_session_settings(db_session, uuid.uuid4())
    assert settings == HarnessSettings()


async def test_patch_sets_model(session_row, db_session):
    out = await patch_session_settings(
        db_session, session_row.id, patch={"model": "claude-sonnet-4-6"}
    )
    assert out.model == "claude-sonnet-4-6"
    assert out.effort is None
    assert out.mode_models == {"default": "claude-sonnet-4-6"}
    # Re-read via load to make sure the metadata persisted.
    fresh = await load_session_settings(db_session, session_row.id)
    assert fresh.model == "claude-sonnet-4-6"


async def test_patch_trims_model_whitespace(session_row, db_session):
    out = await patch_session_settings(
        db_session, session_row.id, patch={"model": "  claude-sonnet  "}
    )
    assert out.model == "claude-sonnet"


async def test_patch_rejects_oversized_model(session_row, db_session):
    too_long = "x" * (MODEL_ID_MAX_LEN + 1)
    with pytest.raises(ValueError, match="exceeds .* limit"):
        await patch_session_settings(
            db_session, session_row.id, patch={"model": too_long}
        )


async def test_patch_rejects_empty_model(session_row, db_session):
    with pytest.raises(ValueError, match="non-empty"):
        await patch_session_settings(
            db_session, session_row.id, patch={"model": "   "}
        )


async def test_null_clears_field(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "claude-sonnet"}
    )
    cleared = await patch_session_settings(
        db_session, session_row.id, patch={"model": None}
    )
    assert cleared.model is None
    assert cleared.mode_models == {}


async def test_missing_key_leaves_field_unchanged(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "claude-sonnet", "effort": "high"}
    )
    # Patch only effort — model must persist.
    out = await patch_session_settings(
        db_session, session_row.id, patch={"effort": "medium"}
    )
    assert out.model == "claude-sonnet"
    assert out.effort == "medium"


async def test_plan_mode_model_is_stored_separately_from_default(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "gpt-5.3-codex"}
    )
    await db_session.refresh(session_row)
    spm.write_session_plan_metadata(session_row, mode=spm.PLAN_MODE_PLANNING)
    await db_session.commit()

    planning = await patch_session_settings(
        db_session, session_row.id, patch={"model": "gpt-5.5"}
    )

    assert planning.model == "gpt-5.5"
    assert planning.mode_models == {
        "default": "gpt-5.3-codex",
        "plan": "gpt-5.5",
    }
    await db_session.refresh(session_row)
    meta = session_row.metadata_[HARNESS_SETTINGS_KEY]
    assert meta["model"] == "gpt-5.3-codex"
    assert meta["mode_models"]["plan"] == "gpt-5.5"

    spm.write_session_plan_metadata(session_row, mode=spm.PLAN_MODE_CHAT)
    await db_session.commit()
    default_settings = await load_session_settings(db_session, session_row.id)
    assert default_settings.model == "gpt-5.3-codex"

    spm.write_session_plan_metadata(session_row, mode=spm.PLAN_MODE_PLANNING)
    await db_session.commit()
    plan_settings = await load_session_settings(db_session, session_row.id)
    assert plan_settings.model == "gpt-5.5"


async def test_clearing_plan_model_preserves_default_model(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "gpt-5.3-codex"}
    )
    await db_session.refresh(session_row)
    spm.write_session_plan_metadata(session_row, mode=spm.PLAN_MODE_PLANNING)
    await db_session.commit()
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "gpt-5.5"}
    )

    cleared = await patch_session_settings(
        db_session, session_row.id, patch={"model": None}
    )

    assert cleared.model is None
    assert cleared.mode_models == {"default": "gpt-5.3-codex"}
    await db_session.refresh(session_row)
    assert session_row.metadata_[HARNESS_SETTINGS_KEY]["model"] == "gpt-5.3-codex"


async def test_clearing_all_fields_removes_metadata_key(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"model": "claude-sonnet", "effort": "high"}
    )
    await patch_session_settings(
        db_session, session_row.id, patch={"model": None, "effort": None}
    )
    # Metadata key should be gone — nothing leftover.
    await db_session.refresh(session_row)
    assert HARNESS_SETTINGS_KEY not in (session_row.metadata_ or {})


async def test_runtime_settings_round_trip(session_row, db_session):
    payload = {"foo": "bar", "nested": {"k": 1}}
    out = await patch_session_settings(
        db_session, session_row.id, patch={"runtime_settings": payload}
    )
    assert out.runtime_settings == payload


async def test_runtime_settings_null_clears(session_row, db_session):
    await patch_session_settings(
        db_session, session_row.id, patch={"runtime_settings": {"k": "v"}}
    )
    cleared = await patch_session_settings(
        db_session, session_row.id, patch={"runtime_settings": None}
    )
    assert cleared.runtime_settings == {}


async def test_invalid_runtime_settings_type_rejected(session_row, db_session):
    with pytest.raises(ValueError, match="object or null"):
        await patch_session_settings(
            db_session, session_row.id, patch={"runtime_settings": "not a dict"}
        )


async def test_missing_session_raises(db_session):
    with pytest.raises(ValueError, match="session not found"):
        await patch_session_settings(
            db_session, uuid.uuid4(), patch={"model": "claude-sonnet"}
        )
