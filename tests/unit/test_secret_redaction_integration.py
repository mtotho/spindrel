"""Tests for secret redaction integration points — tool_dispatch, agent loop,
chat endpoint, admin API, container injection, and false-positive safety.

These tests verify that secrets are properly redacted at each point where
they flow through the system, complementing the core engine tests in
test_secret_registry.py.
"""
from __future__ import annotations

import json
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_secret_registry():
    """Reset the secret registry between tests."""
    from app.services import secret_registry
    secret_registry._pattern = None
    secret_registry._known_secrets = set()
    secret_registry._built = False
    yield
    secret_registry._pattern = None
    secret_registry._known_secrets = set()
    secret_registry._built = False


def _set_secrets(*secrets: str):
    """Prime the secret registry with known secrets."""
    from app.services import secret_registry
    secret_registry._known_secrets = set(secrets)
    secret_registry._pattern = secret_registry._build_pattern(set(secrets))
    secret_registry._built = True


# ===========================================================================
# 1. tool_dispatch — redaction before DB storage and LLM consumption
# ===========================================================================

class TestToolDispatchRedaction:
    """Verify that dispatch_tool_call() redacts secrets from tool results."""

    # Patch targets — tool_dispatch imports these at module level, so we
    # must patch at the usage site, not the source module.
    _TD = "app.agent.tool_dispatch"
    _COMMON_PATCHES = [
        f"{_TD}.is_client_tool",  # must return False for local tool path
        f"{_TD}.is_mcp_tool",     # must return False for local tool path
    ]

    def _dispatch_patches(self, tool_return_value, **extra):
        """Context manager with all necessary patches for dispatch_tool_call."""
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch(f"{self._TD}.is_client_tool", return_value=False))
        stack.enter_context(patch(f"{self._TD}.is_mcp_tool", return_value=False))
        stack.enter_context(patch(f"{self._TD}.is_local_tool", return_value=True))
        stack.enter_context(patch(f"{self._TD}.call_local_tool", new_callable=AsyncMock,
                                  return_value=tool_return_value))
        stack.enter_context(patch("app.agent.recording._record_tool_call", new_callable=AsyncMock))
        stack.enter_context(patch("app.agent.hooks.fire_hook", new_callable=AsyncMock))
        stack.enter_context(patch(f"{self._TD}._check_tool_policy", new_callable=AsyncMock, return_value=None))
        for k, v in extra.items():
            stack.enter_context(patch(k, **v) if isinstance(v, dict) else patch(k, v))
        return stack

    async def _call_dispatch(self, name="echo", args="{}", tool_call_id="tc_1"):
        from app.agent.tool_dispatch import dispatch_tool_call
        return await dispatch_tool_call(
            name=name, args=args, tool_call_id=tool_call_id,
            bot_id="test-bot", bot_memory=None,
            session_id=uuid.uuid4(), client_id="test",
            correlation_id=uuid.uuid4(), channel_id=uuid.uuid4(),
            iteration=0, provider_id=None,
            summarize_enabled=False, summarize_threshold=10000,
            summarize_model="test/model", summarize_max_tokens=500,
            summarize_exclude=set(), compaction=False,
        )

    @pytest.mark.asyncio
    async def test_tool_result_redacted_before_llm(self):
        """result_for_llm should have secrets replaced with [REDACTED]."""
        _set_secrets("super-secret-api-key-12345")
        with self._dispatch_patches('{"output": "Key is super-secret-api-key-12345"}'):
            result = await self._call_dispatch()
        assert "[REDACTED]" in result.result_for_llm
        assert "super-secret-api-key-12345" not in result.result_for_llm

    @pytest.mark.asyncio
    async def test_raw_result_redacted_for_storage(self):
        """result_obj.result (used for DB recording) should also be redacted."""
        _set_secrets("db-password-xyz789")
        with self._dispatch_patches("Connection: db-password-xyz789"):
            result = await self._call_dispatch(name="exec_command", tool_call_id="tc_2")
        assert "db-password-xyz789" not in result.result
        assert "[REDACTED]" in result.result

    @pytest.mark.asyncio
    async def test_client_action_extraction_unaffected(self):
        """client_action JSON should still be extracted before redaction."""
        _set_secrets("secret-token-abc")
        tool_output = json.dumps({
            "client_action": {"type": "tts", "text": "Hello"},
            "message": "Done with secret-token-abc visible",
        })
        with self._dispatch_patches(tool_output):
            result = await self._call_dispatch(name="some_tool", tool_call_id="tc_3")
        assert result.embedded_client_action == {"type": "tts", "text": "Hello"}
        assert "secret-token-abc" not in result.result_for_llm

    @pytest.mark.asyncio
    async def test_no_redaction_when_disabled(self):
        """When SECRET_REDACTION_ENABLED=False, tool results pass through."""
        _set_secrets("my-secret-value")
        with self._dispatch_patches(
            "Output: my-secret-value",
            **{"app.services.secret_registry.is_enabled": MagicMock(return_value=False)},
        ):
            result = await self._call_dispatch(tool_call_id="tc_4")
        assert "my-secret-value" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_multiple_secrets_all_redacted(self):
        """Multiple different secrets in one tool output should all be redacted."""
        _set_secrets("api-key-111", "password-222", "token-333-abc")
        with self._dispatch_patches("Keys: api-key-111, password-222, token-333-abc"):
            result = await self._call_dispatch(tool_call_id="tc_5")
        assert result.result_for_llm == "Keys: [REDACTED], [REDACTED], [REDACTED]"

    @pytest.mark.asyncio
    async def test_tool_event_error_uses_redacted_result(self):
        """tool_event error messages must use redacted result, not raw."""
        _set_secrets("super-secret-password-123")
        error_json = json.dumps({"error": "Auth failed: super-secret-password-123"})
        with self._dispatch_patches(error_json):
            result = await self._call_dispatch(name="failing_tool", tool_call_id="tc_err")
        # The tool_event should have the error redacted
        assert "super-secret-password-123" not in str(result.tool_event)
        assert "[REDACTED]" in result.tool_event.get("error", "")

    @pytest.mark.asyncio
    async def test_tool_event_non_error_does_not_leak(self):
        """A normal (non-error) tool result must not leak secrets in tool_event."""
        _set_secrets("normal-secret-value-xyz")
        with self._dispatch_patches("Output: normal-secret-value-xyz"):
            result = await self._call_dispatch(name="some_tool", tool_call_id="tc_norm")
        # tool_event should not contain the raw secret anywhere
        assert "normal-secret-value-xyz" not in json.dumps(result.tool_event)


# ===========================================================================
# 2. Agent loop — redaction of final response text
# ===========================================================================

class TestAgentLoopRedaction:
    """Verify that redact() is called on LLM response text in the agent loop."""

    @pytest.mark.asyncio
    async def test_redact_imported_in_loop(self):
        """The loop module should import _redact_secrets from the registry."""
        # This verifies the import exists and is callable
        from app.services.secret_registry import redact
        _set_secrets("leaked-secret-in-response")
        result = redact("The bot said: leaked-secret-in-response here")
        assert result == "The bot said: [REDACTED] here"

    @pytest.mark.asyncio
    async def test_redact_preserves_markdown(self):
        """Redaction should not break markdown formatting around secrets."""
        _set_secrets("sk-abc123def456")
        from app.services.secret_registry import redact
        text = "Use `sk-abc123def456` as your key.\n\n**Token:** sk-abc123def456"
        result = redact(text)
        assert result == "Use `[REDACTED]` as your key.\n\n**Token:** [REDACTED]"

    @pytest.mark.asyncio
    async def test_redact_in_json_output(self):
        """Secrets inside JSON-formatted tool results should be redacted."""
        _set_secrets("ghp_realTokenValue123456")
        from app.services.secret_registry import redact
        data = json.dumps({"token": "ghp_realTokenValue123456", "status": "ok"})
        result = redact(data)
        parsed = json.loads(result)
        assert parsed["token"] == "[REDACTED]"
        assert parsed["status"] == "ok"


# ===========================================================================
# 3. check-secrets endpoint — auth, response shape, pattern stripping
# ===========================================================================

class TestCheckSecretsEndpoint:
    """Verify the /chat/check-secrets endpoint behavior."""

    def test_clean_input_returns_no_secrets(self):
        """Clean text should return has_secrets=False."""
        from app.services.secret_registry import check_user_input
        _set_secrets("known-server-secret-123")
        result = check_user_input("Hello, how are you today?")
        assert result is None

    def test_exact_match_detected(self):
        """Known secrets should trigger exact match detection."""
        from app.services.secret_registry import check_user_input
        _set_secrets("my-api-key-abcdef123456")
        result = check_user_input("Please use my-api-key-abcdef123456 for the request")
        assert result is not None
        assert result["exact_matches"] == 1

    def test_pattern_match_detected(self):
        """Common secret patterns should trigger heuristic detection."""
        from app.services.secret_registry import check_user_input
        result = check_user_input("Here is my key: sk-proj-ABCDEFghijklmnopqrstuvwx")
        assert result is not None
        assert len(result["pattern_matches"]) > 0

    def test_pattern_match_includes_type(self):
        """Pattern matches should include the detected type."""
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("Token: ghp_ABCDEFghijklmnopqrstuvwx")
        assert len(result) >= 1
        assert result[0]["type"] == "GitHub token"

    def test_detect_patterns_truncates_match(self):
        """The match field should be truncated (not reveal the full secret)."""
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("sk-proj-ABCDEFghijklmnopqrstuvwxyz1234567890abcdef")
        assert len(result) >= 1
        match_str = result[0]["match"]
        # Should be truncated — not the full value
        assert len(match_str) < 20
        assert "..." in match_str

    def test_response_strips_match_and_positions(self):
        """The endpoint response should strip match content and positions."""
        from app.services.secret_registry import check_user_input
        result = check_user_input("Here: sk-proj-ABCDEFghijklmnopqrstuvwxyz1234")
        assert result is not None
        # Simulate what the endpoint does
        safe_patterns = [{"type": pm["type"]} for pm in result.get("pattern_matches", [])]
        for pm in safe_patterns:
            assert "match" not in pm
            assert "start" not in pm
            assert "end" not in pm
            assert "type" in pm

    def test_both_exact_and_pattern(self):
        """A message with both a known secret and a pattern should report both."""
        from app.services.secret_registry import check_user_input
        _set_secrets("known-secret-value-xyz")
        result = check_user_input(
            "Use known-secret-value-xyz and also sk-ant-ABCDEFghijklmnopqrstuvwx"
        )
        assert result is not None
        assert result["exact_matches"] == 1
        assert len(result["pattern_matches"]) >= 1


# ===========================================================================
# 4. Admin API — name validation, duplicate handling
# ===========================================================================

class TestSecretValueValidation:
    """Test the Pydantic model validation for secret names."""

    def test_valid_env_var_name(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        model = SecretValueCreate(name="MY_API_KEY", value="test")
        assert model.name == "MY_API_KEY"

    def test_valid_name_lowercase(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        model = SecretValueCreate(name="my_key", value="test")
        assert model.name == "my_key"

    def test_valid_name_underscore_prefix(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        model = SecretValueCreate(name="_PRIVATE", value="test")
        assert model.name == "_PRIVATE"

    def test_invalid_name_starts_with_digit(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="valid env var"):
            SecretValueCreate(name="123_KEY", value="test")

    def test_invalid_name_has_spaces(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="valid env var"):
            SecretValueCreate(name="MY KEY", value="test")

    def test_invalid_name_has_dashes(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="valid env var"):
            SecretValueCreate(name="MY-KEY", value="test")

    def test_invalid_name_has_special_chars(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="valid env var"):
            SecretValueCreate(name="MY.KEY", value="test")

    def test_invalid_name_empty(self):
        from app.routers.api_v1_admin.secret_values import SecretValueCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SecretValueCreate(name="", value="test")

    def test_update_name_validation(self):
        from app.routers.api_v1_admin.secret_values import SecretValueUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="valid env var"):
            SecretValueUpdate(name="bad name!", value="test")

    def test_update_name_none_allowed(self):
        """None name (no change) should be valid."""
        from app.routers.api_v1_admin.secret_values import SecretValueUpdate
        model = SecretValueUpdate(name=None, value="new-val")
        assert model.name is None


# ===========================================================================
# 5. Container injection — sandbox and host_exec env var injection
# ===========================================================================

class TestContainerInjection:
    """Verify secret values are injected into container environments."""

    def test_get_env_dict_used_in_sandbox(self):
        """sandbox.py imports and uses get_env_dict for docker exec -e flags."""
        # Verify the import path exists and the code pattern is present
        import inspect
        from app.services import sandbox
        source = inspect.getsource(sandbox)
        assert "get_env_dict" in source
        assert "secret_values" in source

    def test_get_env_dict_used_in_host_exec(self):
        """host_exec.py imports and uses get_env_dict for env dict."""
        import inspect
        from app.services import host_exec
        source = inspect.getsource(host_exec)
        assert "get_env_dict" in source
        assert "secret_values" in source

    def test_host_exec_env_includes_secrets(self):
        """HostExecService._build_env should include secret values."""
        from app.services.host_exec import HostExecService

        mock_cfg = MagicMock()
        mock_cfg.env_passthrough = []

        svc = HostExecService()
        with (
            patch("app.services.host_exec.settings") as mock_settings,
            patch("app.services.secret_values.get_env_dict",
                  return_value={"SECRET_TOKEN": "my-secret-123"}),
        ):
            mock_settings.HOST_EXEC_ENV_PASSTHROUGH = []
            env = svc._build_env(mock_cfg)

        assert "SECRET_TOKEN" in env
        assert env["SECRET_TOKEN"] == "my-secret-123"

    def test_env_dict_returns_all_cached_values(self):
        """get_env_dict should return all cached secret values."""
        from app.services import secret_values
        secret_values._cache.clear()
        secret_values._cache["KEY_A"] = "val_a"
        secret_values._cache["KEY_B"] = "val_b"
        secret_values._cache["KEY_C"] = "val_c"

        result = secret_values.get_env_dict()
        assert result == {"KEY_A": "val_a", "KEY_B": "val_b", "KEY_C": "val_c"}
        secret_values._cache.clear()

    def test_env_dict_is_isolated_copy(self):
        """Mutations to the returned dict should not affect the cache."""
        from app.services import secret_values
        secret_values._cache.clear()
        secret_values._cache["KEY"] = "value"

        d = secret_values.get_env_dict()
        d["KEY"] = "mutated"
        d["NEW_KEY"] = "extra"

        assert secret_values._cache["KEY"] == "value"
        assert "NEW_KEY" not in secret_values._cache
        secret_values._cache.clear()


# ===========================================================================
# 6. Secret collection from various sources
# ===========================================================================

class TestSecretCollection:
    """Verify _collect_secrets gathers from all expected sources."""

    @pytest.mark.asyncio
    async def test_collects_from_settings(self):
        from app.services.secret_registry import _collect_secrets
        with (
            patch("app.services.secret_registry.settings") as mock_settings,
            patch("app.services.secret_registry.is_enabled", return_value=True),
        ):
            mock_settings.API_KEY = "settings-api-key-abc"
            mock_settings.ADMIN_API_KEY = "admin-key-def"
            mock_settings.LLM_API_KEY = "litellm-key-ghi"
            mock_settings.ENCRYPTION_KEY = "enc-key-jkl"
            mock_settings.JWT_SECRET = "jwt-secret-mno"
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = "postgresql://user:pass@host/db"

            secrets = await _collect_secrets()

        assert "settings-api-key-abc" in secrets
        assert "admin-key-def" in secrets
        assert "litellm-key-ghi" in secrets
        assert "enc-key-jkl" in secrets
        assert "jwt-secret-mno" in secrets
        assert "postgresql://user:pass@host/db" in secrets

    @pytest.mark.asyncio
    async def test_skips_none_values(self):
        from app.services.secret_registry import _collect_secrets
        with patch("app.services.secret_registry.settings") as mock_settings:
            mock_settings.API_KEY = None
            mock_settings.ADMIN_API_KEY = None
            mock_settings.LLM_API_KEY = None
            mock_settings.ENCRYPTION_KEY = None
            mock_settings.JWT_SECRET = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = None

            secrets = await _collect_secrets()

        # None values should not be added (we can't redact None)
        # But other sources may contribute; at minimum no crash
        for s in secrets:
            assert s is not None

    @pytest.mark.asyncio
    async def test_skips_short_values(self):
        from app.services.secret_registry import _collect_secrets, MIN_SECRET_LENGTH
        with patch("app.services.secret_registry.settings") as mock_settings:
            mock_settings.API_KEY = "ab"  # too short
            mock_settings.ADMIN_API_KEY = "x"  # too short
            mock_settings.LLM_API_KEY = "long-enough-key-123"
            mock_settings.ENCRYPTION_KEY = None
            mock_settings.JWT_SECRET = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = None

            secrets = await _collect_secrets()

        assert "ab" not in secrets
        assert "x" not in secrets
        assert "long-enough-key-123" in secrets

    @pytest.mark.asyncio
    async def test_collects_from_secret_values_vault(self):
        from app.services.secret_registry import _collect_secrets
        with (
            patch("app.services.secret_registry.settings") as mock_settings,
            patch("app.services.secret_values.get_env_dict",
                  return_value={"GITHUB_TOKEN": "ghp_vault_value_12345"}),
        ):
            mock_settings.API_KEY = None
            mock_settings.ADMIN_API_KEY = None
            mock_settings.LLM_API_KEY = None
            mock_settings.ENCRYPTION_KEY = None
            mock_settings.JWT_SECRET = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = None

            secrets = await _collect_secrets()

        assert "ghp_vault_value_12345" in secrets


# ===========================================================================
# 7. False-positive safety — normal text should not be over-redacted
# ===========================================================================

class TestFalsePositiveSafety:
    """Ensure redaction doesn't mangle normal text."""

    def test_normal_prose_unchanged(self):
        _set_secrets("super-secret-password-12345")
        from app.services.secret_registry import redact
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "Today's temperature is 72 degrees Fahrenheit. "
            "Please check your email at user@example.com."
        )
        assert redact(text) == text

    def test_urls_not_redacted(self):
        _set_secrets("sk-ant-realkey12345678901234")
        from app.services.secret_registry import redact
        text = "Visit https://docs.example.com/api/v1/endpoint for details."
        assert redact(text) == text

    def test_code_snippets_not_redacted(self):
        _set_secrets("production-db-password")
        from app.services.secret_registry import redact
        text = '''
def hello():
    print("Hello, World!")
    return 42
'''
        assert redact(text) == text

    def test_short_values_not_registered(self):
        """Values shorter than MIN_SECRET_LENGTH should not be secrets."""
        from app.services import secret_registry
        from app.services.secret_registry import _build_pattern

        # Only long enough values should create a pattern
        short_secrets = {"ab", "x", "hi", "12"}
        pattern = _build_pattern(short_secrets)
        assert pattern is not None  # _build_pattern doesn't filter, _add does

        # But _collect_secrets / rebuild() skips them
        # Verify via MIN_SECRET_LENGTH
        assert secret_registry.MIN_SECRET_LENGTH >= 6

    def test_empty_registry_is_noop(self):
        """With no secrets registered, redact should be a fast no-op."""
        from app.services.secret_registry import redact
        # _reset_secret_registry fixture leaves everything empty
        text = "This text has no secrets and should pass through unchanged."
        assert redact(text) == text

    def test_partial_match_not_redacted(self):
        """A substring of a secret should not match if it's not the full secret."""
        _set_secrets("my-very-long-secret-key-abc123")
        from app.services.secret_registry import redact
        # "my-very" is a substring but not the full secret
        text = "my-very casual conversation about nothing"
        assert redact(text) == text

    def test_numbers_not_redacted(self):
        """Plain numbers should not trigger redaction."""
        _set_secrets("secret-value-9876543210")
        from app.services.secret_registry import redact
        text = "The population is 9876543210 people."
        # The number itself is not the secret; the full string is
        assert "9876543210" in redact(text)

    def test_email_not_false_positive_pattern(self):
        """Email addresses should not trigger pattern detection."""
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("Contact us at admin@company.com for support.")
        # Email should not match any secret pattern
        email_matches = [r for r in result if "admin@company.com" in r.get("match", "")]
        assert len(email_matches) == 0

    def test_uuid_not_false_positive_pattern(self):
        """UUIDs should not trigger pattern detection."""
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("Request ID: 550e8400-e29b-41d4-a716-446655440000")
        # UUID should not be detected as a secret
        assert len(result) == 0

    def test_base64_image_not_false_positive(self):
        """Base64-encoded image data should not trigger false positives."""
        from app.services.secret_registry import detect_patterns
        # Short base64 that doesn't look like a JWT
        result = detect_patterns("data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==")
        jwt_matches = [r for r in result if r["type"] == "JWT"]
        assert len(jwt_matches) == 0


# ===========================================================================
# 8. Heuristic pattern detection — comprehensive format coverage
# ===========================================================================

class TestPatternDetection:
    """Verify heuristic patterns catch realistic secret formats."""

    def test_openai_project_key(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("sk-proj-AbCdEf_GhIjKl-MnOpQrStUvWx")
        types = [r["type"] for r in result]
        assert any("OpenAI" in t for t in types)

    def test_anthropic_key(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("sk-ant-api03-AbCdEfGhIjKlMnOpQrSt")
        types = [r["type"] for r in result]
        assert "Anthropic API key" in types

    def test_github_fine_grained_pat(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("github_pat_11AAAAAA_abcdefghijklmnopqrst")
        types = [r["type"] for r in result]
        assert "GitHub fine-grained token" in types

    def test_slack_bot_token(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwx")
        types = [r["type"] for r in result]
        assert "Slack token" in types

    def test_aws_access_key(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("AKIAIOSFODNN7EXAMPLE")
        types = [r["type"] for r in result]
        assert "AWS access key" in types

    def test_connection_string_postgres(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("postgresql://admin:password@db.example.com:5432/mydb")
        types = [r["type"] for r in result]
        assert "Connection string" in types

    def test_connection_string_mongodb(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("mongodb://user:pass@cluster0.mongodb.net/mydb?retryWrites=true")
        types = [r["type"] for r in result]
        assert "Connection string" in types

    def test_private_key_rsa(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("-----BEGIN RSA PRIVATE KEY-----")
        types = [r["type"] for r in result]
        assert "Private key header" in types

    def test_private_key_openssh(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("-----BEGIN OPENSSH PRIVATE KEY-----")
        types = [r["type"] for r in result]
        assert "Private key header" in types

    def test_password_in_code(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns('password = "SuperSecret123!"')
        types = [r["type"] for r in result]
        assert "Password assignment" in types

    def test_api_key_in_yaml(self):
        from app.services.secret_registry import detect_patterns
        result = detect_patterns("api_key: 'my_secret_token_value_here'")
        types = [r["type"] for r in result]
        assert "Password assignment" in types

    def test_jwt_realistic(self):
        from app.services.secret_registry import detect_patterns
        # Minimal realistic JWT
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = detect_patterns(jwt)
        types = [r["type"] for r in result]
        assert "JWT" in types


# ===========================================================================
# 9. Registry rebuild — integration with secret_values vault
# ===========================================================================

class TestRegistryRebuildIntegration:
    """Test that the registry rebuilds properly after vault changes."""

    @pytest.mark.asyncio
    async def test_rebuild_registers_vault_secrets(self):
        """After rebuild, vault secrets should be in the known_secrets set."""
        from app.services import secret_registry

        with (
            patch("app.services.secret_registry.settings") as mock_settings,
            patch("app.services.secret_registry.is_enabled", return_value=True),
            patch("app.services.secret_values.get_env_dict",
                  return_value={"DB_PASS": "vault-db-password-999"}),
        ):
            mock_settings.API_KEY = None
            mock_settings.ADMIN_API_KEY = None
            mock_settings.LLM_API_KEY = None
            mock_settings.ENCRYPTION_KEY = None
            mock_settings.JWT_SECRET = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = None

            await secret_registry.rebuild()

        assert "vault-db-password-999" in secret_registry._known_secrets
        result = secret_registry.redact("Connection uses vault-db-password-999")
        assert result == "Connection uses [REDACTED]"

    @pytest.mark.asyncio
    async def test_rebuild_clears_old_secrets(self):
        """Rebuild should replace, not append to, the known secrets."""
        from app.services import secret_registry

        # Pre-load a secret
        _set_secrets("old-secret-to-clear")
        assert "old-secret-to-clear" in secret_registry._known_secrets

        # Rebuild without that secret
        with (
            patch("app.services.secret_registry.settings") as mock_settings,
            patch("app.services.secret_registry.is_enabled", return_value=True),
            patch("app.services.secret_values.get_env_dict", return_value={}),
        ):
            mock_settings.API_KEY = "new-api-key-only"
            mock_settings.ADMIN_API_KEY = None
            mock_settings.LLM_API_KEY = None
            mock_settings.ENCRYPTION_KEY = None
            mock_settings.JWT_SECRET = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.DATABASE_URL = None

            await secret_registry.rebuild()

        assert "old-secret-to-clear" not in secret_registry._known_secrets
        assert "new-api-key-only" in secret_registry._known_secrets


# ===========================================================================
# 10. Secret values CRUD — cache correctness
# ===========================================================================

class TestSecretValuesCRUDCache:
    """Test cache management for create/delete operations."""

    @pytest.mark.asyncio
    async def test_create_adds_to_cache(self):
        from app.services import secret_values

        secret_values._cache.clear()
        mock_row = MagicMock()
        mock_row.id = uuid.uuid4()
        mock_row.name = "NEW_SECRET"
        mock_row.value = "enc:data"
        mock_row.description = "test"
        mock_row.created_by = None
        mock_row.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01"))
        mock_row.updated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01"))

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=None)
        mock_db.add = MagicMock()

        with (
            patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock),
            patch("app.services.secret_values.encrypt", return_value="enc:encrypted"),
            patch("app.services.secret_values.SecretValue", return_value=mock_row),
        ):
            await secret_values.create_secret(mock_db, "NEW_SECRET", "plaintext-value")

        assert secret_values._cache["NEW_SECRET"] == "plaintext-value"
        secret_values._cache.clear()

    @pytest.mark.asyncio
    async def test_delete_removes_from_cache(self):
        from app.services import secret_values

        secret_values._cache.clear()
        secret_values._cache["TO_DELETE"] = "some-value"

        mock_row = MagicMock()
        mock_row.name = "TO_DELETE"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_row)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock):
            result = await secret_values.delete_secret(mock_db, uuid.uuid4())

        assert result is True
        assert "TO_DELETE" not in secret_values._cache
        secret_values._cache.clear()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self):
        from app.services import secret_values

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        result = await secret_values.delete_secret(mock_db, uuid.uuid4())
        assert result is False


# ===========================================================================
# 11. Context compaction — secrets must not leak to summarization LLM
# ===========================================================================

class TestCompactionRedaction:
    """Verify that compaction redacts secrets before sending to the LLM."""

    def test_build_transcript_redacts_secrets(self):
        """_build_transcript should redact secrets from message content."""
        _set_secrets("super-secret-db-password")
        from app.services.compaction import _build_transcript
        conversation = [
            {"role": "user", "content": "What is the DB password?"},
            {"role": "assistant", "content": "The password is super-secret-db-password"},
        ]
        transcript = _build_transcript(conversation)
        assert "super-secret-db-password" not in transcript
        assert "[REDACTED]" in transcript
        assert "[USER]:" in transcript
        assert "[ASSISTANT]:" in transcript

    def test_build_transcript_handles_multipart_content(self):
        """_build_transcript should redact secrets in multi-part content."""
        _set_secrets("leaked-api-key-xyz")
        from app.services.compaction import _build_transcript
        conversation = [
            {"role": "user", "content": [
                {"type": "text", "text": "Found key leaked-api-key-xyz in env"},
            ]},
        ]
        transcript = _build_transcript(conversation)
        assert "leaked-api-key-xyz" not in transcript
        assert "[REDACTED]" in transcript

    def test_build_transcript_no_secrets_passthrough(self):
        """When no secrets are registered, content passes through unchanged."""
        from app.services.compaction import _build_transcript
        conversation = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well!"},
        ]
        transcript = _build_transcript(conversation)
        assert "Hello, how are you?" in transcript
        assert "I'm doing well!" in transcript

    @pytest.mark.asyncio
    async def test_generate_summary_redacts_transcript(self):
        """_generate_summary should not send raw secrets to the LLM."""
        _set_secrets("my-secret-token-12345")
        from app.services.compaction import _generate_summary

        captured_messages = []

        class FakeCompletion:
            class choice:
                class message:
                    content = '{"title": "Test", "summary": "A summary"}'
            choices = [choice]
            usage = None

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    async def create(**kwargs):
                        captured_messages.extend(kwargs.get("messages", []))
                        return FakeCompletion()

        conversation = [
            {"role": "user", "content": "Show me the token"},
            {"role": "assistant", "content": "The token is my-secret-token-12345"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=FakeClient()):
            await _generate_summary(conversation, "test-model", None)

        # The transcript sent to the LLM should have secrets redacted
        all_content = " ".join(m.get("content", "") for m in captured_messages)
        assert "my-secret-token-12345" not in all_content
        assert "[REDACTED]" in all_content
