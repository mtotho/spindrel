"""Unit tests for app.services.server_settings."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.server_settings import (
    SETTINGS_SCHEMA,
    _coerce,
    _serialize,
    _get_env_default,
)
from app.config import Settings


class TestSchemaValidity:
    """Every key in SETTINGS_SCHEMA must be a real field on Settings."""

    def test_all_keys_exist_on_settings(self):
        for key in SETTINGS_SCHEMA:
            assert key in Settings.model_fields, (
                f"SETTINGS_SCHEMA key '{key}' not found in Settings class"
            )

    def test_all_keys_have_required_fields(self):
        for key, schema in SETTINGS_SCHEMA.items():
            assert "group" in schema, f"{key}: missing group"
            assert "label" in schema, f"{key}: missing label"
            assert "description" in schema, f"{key}: missing description"
            assert "type" in schema, f"{key}: missing type"
            assert schema["type"] in ("string", "int", "float", "bool"), (
                f"{key}: invalid type {schema['type']}"
            )


    def test_heartbeat_default_prompt_in_schema(self):
        assert "HEARTBEAT_DEFAULT_PROMPT" in SETTINGS_SCHEMA
        schema = SETTINGS_SCHEMA["HEARTBEAT_DEFAULT_PROMPT"]
        assert schema["group"] == "Heartbeat"
        assert schema["type"] == "string"
        assert schema["widget"] == "textarea"


class TestCoercion:
    def test_bool_true_values(self):
        schema = {"type": "bool"}
        assert _coerce("true", schema) is True
        assert _coerce("1", schema) is True
        assert _coerce("yes", schema) is True
        assert _coerce("True", schema) is True

    def test_bool_false_values(self):
        schema = {"type": "bool"}
        assert _coerce("false", schema) is False
        assert _coerce("0", schema) is False
        assert _coerce("no", schema) is False
        assert _coerce("", schema) is False

    def test_int_coercion(self):
        schema = {"type": "int"}
        assert _coerce("42", schema) == 42
        assert _coerce("0", schema) == 0

    def test_int_nullable(self):
        schema = {"type": "int", "nullable": True}
        assert _coerce("", schema) is None
        assert _coerce("None", schema) is None
        assert _coerce("null", schema) is None

    def test_float_coercion(self):
        schema = {"type": "float"}
        assert _coerce("0.35", schema) == pytest.approx(0.35)
        assert _coerce("2.0", schema) == pytest.approx(2.0)

    def test_string_coercion(self):
        schema = {"type": "string"}
        assert _coerce("hello", schema) == "hello"


class TestSerialization:
    def test_bool(self):
        assert _serialize(True) == "true"
        assert _serialize(False) == "false"

    def test_none(self):
        assert _serialize(None) == ""

    def test_int(self):
        assert _serialize(42) == "42"

    def test_string(self):
        assert _serialize("hello") == "hello"


class TestGetEnvDefault:
    def test_known_key(self):
        default = _get_env_default("AGENT_MAX_ITERATIONS")
        assert default == 15

    def test_unknown_key(self):
        assert _get_env_default("NONEXISTENT_KEY_XYZ") is None

    def test_bool_default(self):
        assert _get_env_default("AGENT_TRACE") is False


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_rejects_unknown_key(self):
        from app.services.server_settings import update_settings
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="Unknown setting"):
            await update_settings({"DOES_NOT_EXIST": "foo"}, mock_db)

    @pytest.mark.asyncio
    async def test_rejects_read_only(self):
        from app.services.server_settings import update_settings
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="read-only"):
            await update_settings({"API_KEY": "new_key"}, mock_db)


class TestResetSetting:
    @pytest.mark.asyncio
    async def test_rejects_unknown_key(self):
        from app.services.server_settings import reset_setting
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="Unknown setting"):
            await reset_setting("DOES_NOT_EXIST", mock_db)

    @pytest.mark.asyncio
    async def test_rejects_read_only(self):
        from app.services.server_settings import reset_setting
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="read-only"):
            await reset_setting("API_KEY", mock_db)
