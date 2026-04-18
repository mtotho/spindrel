"""Unit tests for app.services.server_settings."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import Settings, settings
from app.db.models import ServerSetting
from app.services.server_settings import (
    SETTINGS_SCHEMA,
    _coerce,
    _get_env_default,
    _serialize,
    load_settings_from_db,
    reset_setting,
    update_settings,
)


_SETTINGS_SNAPSHOT_KEYS = (
    "AGENT_MAX_ITERATIONS",
    "AGENT_TRACE",
    "LOG_LEVEL",
    "TOOL_RETRIEVAL_THRESHOLD",
    "MEMORY_HYGIENE_TARGET_HOUR",
    "MEMORY_HYGIENE_INTERVAL_HOURS",
    "CORS_ORIGINS",
    "SYSTEM_PAUSED",
)


@pytest.fixture
def settings_snapshot():
    """Snapshot + restore the in-memory Settings singleton for the keys we mutate.

    update_settings / reset_setting patch the process-wide `settings` object;
    without snapshot+restore, a test that flips ``AGENT_TRACE`` leaks into every
    subsequent test in the session (B.28).
    """
    snapshot = {k: getattr(settings, k) for k in _SETTINGS_SNAPSHOT_KEYS}
    yield
    for k, v in snapshot.items():
        object.__setattr__(settings, k, v)


# ---------------------------------------------------------------------------
# Pure functions — no DB
# ---------------------------------------------------------------------------

class TestSchemaValidity:
    def test_when_schema_built_then_every_key_exists_on_settings(self):
        for key in SETTINGS_SCHEMA:
            assert key in Settings.model_fields, (
                f"SETTINGS_SCHEMA key {key!r} not found in Settings class"
            )

    def test_when_schema_built_then_every_key_has_required_fields(self):
        for key, schema in SETTINGS_SCHEMA.items():
            assert "group" in schema, f"{key}: missing group"
            assert "label" in schema, f"{key}: missing label"
            assert "description" in schema, f"{key}: missing description"
            assert schema["type"] in ("string", "int", "float", "bool"), (
                f"{key}: invalid type {schema['type']}"
            )

    def test_when_key_is_heartbeat_default_prompt_then_schema_is_textarea_string(self):
        schema = SETTINGS_SCHEMA["HEARTBEAT_DEFAULT_PROMPT"]

        assert schema["group"] == "Heartbeat"
        assert schema["type"] == "string"
        assert schema["widget"] == "textarea"


class TestCoercion:
    def test_when_bool_given_truthy_strings_then_returns_true(self):
        schema = {"type": "bool"}
        assert _coerce("true", schema) is True
        assert _coerce("1", schema) is True
        assert _coerce("yes", schema) is True

    def test_when_bool_given_falsey_strings_then_returns_false(self):
        schema = {"type": "bool"}
        assert _coerce("false", schema) is False
        assert _coerce("0", schema) is False
        assert _coerce("", schema) is False

    def test_when_int_nullable_and_empty_then_returns_none(self):
        schema = {"type": "int", "nullable": True}
        assert _coerce("", schema) is None
        assert _coerce("None", schema) is None
        assert _coerce("null", schema) is None

    def test_when_float_given_decimal_then_parses(self):
        assert _coerce("0.35", {"type": "float"}) == pytest.approx(0.35)

    def test_when_type_is_string_then_returns_verbatim(self):
        assert _coerce("hello", {"type": "string"}) == "hello"


class TestSerialization:
    def test_when_bool_then_serialized_as_lowercase_word(self):
        assert _serialize(True) == "true"
        assert _serialize(False) == "false"

    def test_when_none_then_serialized_as_empty_string(self):
        assert _serialize(None) == ""

    def test_when_int_then_serialized_as_str(self):
        assert _serialize(42) == "42"


class TestGetEnvDefault:
    def test_when_key_is_known_then_returns_class_default(self):
        assert _get_env_default("AGENT_MAX_ITERATIONS") == 15

    def test_when_key_unknown_then_returns_none(self):
        assert _get_env_default("NONEXISTENT_KEY_XYZ") is None

    def test_when_key_is_bool_then_returns_bool_default(self):
        assert _get_env_default("AGENT_TRACE") is False


# ---------------------------------------------------------------------------
# update_settings — real DB
# ---------------------------------------------------------------------------

class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_when_single_int_key_set_then_persisted_and_in_memory_patched(
        self, db_session, settings_snapshot
    ):
        applied = await update_settings({"AGENT_MAX_ITERATIONS": 42}, db_session)

        row = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "AGENT_MAX_ITERATIONS")
            )
        ).scalar_one()
        assert row.value == "42"
        assert applied == {"AGENT_MAX_ITERATIONS": 42}
        assert settings.AGENT_MAX_ITERATIONS == 42

    @pytest.mark.asyncio
    async def test_when_bool_key_set_true_then_db_stores_true_string(
        self, db_session, settings_snapshot
    ):
        await update_settings({"AGENT_TRACE": True}, db_session)

        row = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "AGENT_TRACE")
            )
        ).scalar_one()
        assert row.value == "true"
        assert settings.AGENT_TRACE is True

    @pytest.mark.asyncio
    async def test_when_key_upserted_twice_then_row_updated_not_duplicated(
        self, db_session, settings_snapshot
    ):
        await update_settings({"LOG_LEVEL": "DEBUG"}, db_session)
        await update_settings({"LOG_LEVEL": "WARNING"}, db_session)

        rows = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "LOG_LEVEL")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].value == "WARNING"
        assert settings.LOG_LEVEL == "WARNING"

    @pytest.mark.asyncio
    async def test_when_multiple_keys_set_then_all_persisted_and_returned(
        self, db_session, settings_snapshot
    ):
        applied = await update_settings(
            {"LOG_LEVEL": "ERROR", "TOOL_RETRIEVAL_THRESHOLD": 0.42, "SYSTEM_PAUSED": True},
            db_session,
        )

        assert applied == {"LOG_LEVEL": "ERROR", "TOOL_RETRIEVAL_THRESHOLD": 0.42, "SYSTEM_PAUSED": True}
        keys = {
            r.key
            for r in (await db_session.execute(select(ServerSetting))).scalars().all()
        }
        assert keys == {"LOG_LEVEL", "TOOL_RETRIEVAL_THRESHOLD", "SYSTEM_PAUSED"}

    @pytest.mark.asyncio
    async def test_when_unknown_key_then_raises_value_error(self, db_session):
        with pytest.raises(ValueError, match="Unknown setting"):
            await update_settings({"DOES_NOT_EXIST": "foo"}, db_session)

    @pytest.mark.asyncio
    async def test_when_read_only_key_then_raises_value_error(self, db_session):
        with pytest.raises(ValueError, match="read-only"):
            await update_settings({"API_KEY": "new_key"}, db_session)

    @pytest.mark.asyncio
    async def test_when_sibling_row_exists_then_not_touched(
        self, db_session, settings_snapshot
    ):
        await update_settings({"CORS_ORIGINS": "https://example.com"}, db_session)

        await update_settings({"LOG_LEVEL": "DEBUG"}, db_session)

        sibling = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "CORS_ORIGINS")
            )
        ).scalar_one()
        assert sibling.value == "https://example.com"


# ---------------------------------------------------------------------------
# reset_setting — real DB
# ---------------------------------------------------------------------------

class TestResetSetting:
    @pytest.mark.asyncio
    async def test_when_override_exists_then_row_deleted_and_in_memory_reverts(
        self, db_session, settings_snapshot
    ):
        await update_settings({"AGENT_MAX_ITERATIONS": 99}, db_session)
        assert settings.AGENT_MAX_ITERATIONS == 99
        env_default = _get_env_default("AGENT_MAX_ITERATIONS")

        result = await reset_setting("AGENT_MAX_ITERATIONS", db_session)

        row = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "AGENT_MAX_ITERATIONS")
            )
        ).scalar_one_or_none()
        assert row is None
        assert result == env_default
        assert settings.AGENT_MAX_ITERATIONS == env_default

    @pytest.mark.asyncio
    async def test_when_no_override_exists_then_reset_is_noop_and_returns_default(
        self, db_session, settings_snapshot
    ):
        env_default = _get_env_default("LOG_LEVEL")

        result = await reset_setting("LOG_LEVEL", db_session)

        assert result == env_default
        assert settings.LOG_LEVEL == env_default

    @pytest.mark.asyncio
    async def test_when_sibling_row_exists_then_reset_leaves_it_untouched(
        self, db_session, settings_snapshot
    ):
        await update_settings({"LOG_LEVEL": "DEBUG", "AGENT_TRACE": True}, db_session)

        await reset_setting("LOG_LEVEL", db_session)

        sibling = (
            await db_session.execute(
                select(ServerSetting).where(ServerSetting.key == "AGENT_TRACE")
            )
        ).scalar_one()
        assert sibling.value == "true"
        assert settings.AGENT_TRACE is True

    @pytest.mark.asyncio
    async def test_when_unknown_key_then_raises_value_error(self, db_session):
        with pytest.raises(ValueError, match="Unknown setting"):
            await reset_setting("DOES_NOT_EXIST", db_session)

    @pytest.mark.asyncio
    async def test_when_read_only_key_then_raises_value_error(self, db_session):
        with pytest.raises(ValueError, match="read-only"):
            await reset_setting("API_KEY", db_session)


# ---------------------------------------------------------------------------
# load_settings_from_db — real DB, patched async_session
# ---------------------------------------------------------------------------

class TestLoadSettingsFromDb:
    @pytest.mark.asyncio
    async def test_when_override_rows_present_then_in_memory_settings_patched(
        self, db_session, patched_async_sessions, settings_snapshot
    ):
        db_session.add(ServerSetting(key="LOG_LEVEL", value="ERROR"))
        db_session.add(ServerSetting(key="AGENT_MAX_ITERATIONS", value="99"))
        await db_session.commit()

        await load_settings_from_db()

        assert settings.LOG_LEVEL == "ERROR"
        assert settings.AGENT_MAX_ITERATIONS == 99

    @pytest.mark.asyncio
    async def test_when_unknown_key_row_then_skipped_silently(
        self, db_session, patched_async_sessions, settings_snapshot
    ):
        db_session.add(ServerSetting(key="UNKNOWN_LEGACY_KEY", value="x"))
        db_session.add(ServerSetting(key="LOG_LEVEL", value="WARNING"))
        await db_session.commit()

        await load_settings_from_db()

        assert settings.LOG_LEVEL == "WARNING"

    @pytest.mark.asyncio
    async def test_when_read_only_key_row_then_not_patched(
        self, db_session, patched_async_sessions, settings_snapshot
    ):
        original_api_key = settings.API_KEY
        db_session.add(ServerSetting(key="API_KEY", value="tampered-key"))
        await db_session.commit()

        await load_settings_from_db()

        assert settings.API_KEY == original_api_key
