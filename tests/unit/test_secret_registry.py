"""Tests for app.services.secret_registry — secret redaction engine."""
from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from app.services import secret_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset module state before each test."""
    secret_registry._pattern = None
    secret_registry._known_secrets = set()
    secret_registry._built = False
    yield
    secret_registry._pattern = None
    secret_registry._known_secrets = set()
    secret_registry._built = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_settings(**overrides):
    defaults = {
        "SECRET_REDACTION_ENABLED": True,
        "API_KEY": "test-api-key-12345",
        "ADMIN_API_KEY": "admin-key-67890",
        "LLM_API_KEY": "litellm-key-abc",
        "ENCRYPTION_KEY": "enc-key-def",
        "JWT_SECRET": "jwt-secret-ghi",
        "GOOGLE_CLIENT_SECRET": "google-secret-jkl",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
    }
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# rebuild — collects from settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_collects_from_settings():
    fake = _fake_settings()
    with patch("app.services.secret_registry.settings", fake), \
         patch("app.services.secret_registry._collect_secrets", new_callable=AsyncMock) as mock_collect:
        mock_collect.return_value = {"test-api-key-12345", "admin-key-67890"}
        await secret_registry.rebuild()
        assert secret_registry._built
        assert len(secret_registry._known_secrets) == 2


@pytest.mark.asyncio
async def test_rebuild_collects_settings_values():
    """Verify _collect_secrets actually reads settings fields."""
    fake = _fake_settings()
    with patch("app.services.secret_registry.settings", fake):
        # Mock DB-dependent sources to prevent actual DB calls
        with patch("app.services.secret_registry._collect_secrets", wraps=secret_registry._collect_secrets) as wrapped:
            # Patch the DB call inside _collect_secrets to be a no-op
            async def patched_collect():
                secrets = set()
                def _add(val):
                    if val and len(val) >= secret_registry.MIN_SECRET_LENGTH:
                        secrets.add(val)
                _add(fake.API_KEY)
                _add(fake.ADMIN_API_KEY)
                _add(fake.LLM_API_KEY)
                _add(fake.ENCRYPTION_KEY)
                _add(fake.JWT_SECRET)
                _add(fake.GOOGLE_CLIENT_SECRET)
                _add(fake.DATABASE_URL)
                return secrets

            with patch("app.services.secret_registry._collect_secrets", patched_collect):
                await secret_registry.rebuild()
                assert "test-api-key-12345" in secret_registry._known_secrets
                assert "admin-key-67890" in secret_registry._known_secrets
                assert "litellm-key-abc" in secret_registry._known_secrets
                assert "jwt-secret-ghi" in secret_registry._known_secrets


# ---------------------------------------------------------------------------
# rebuild — skips short values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_skips_short_values():
    fake = _fake_settings(API_KEY="short", ADMIN_API_KEY="ab")
    async def patched_collect():
        secrets = set()
        def _add(val):
            if val and len(val) >= secret_registry.MIN_SECRET_LENGTH:
                secrets.add(val)
        _add(fake.API_KEY)
        _add(fake.ADMIN_API_KEY)
        return secrets

    with patch("app.services.secret_registry.settings", fake), \
         patch("app.services.secret_registry._collect_secrets", patched_collect):
        await secret_registry.rebuild()
        assert "short" not in secret_registry._known_secrets
        assert "ab" not in secret_registry._known_secrets


# ---------------------------------------------------------------------------
# rebuild — collects from providers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_collects_from_providers():
    fake = _fake_settings()
    provider_row = MagicMock()
    provider_row.api_key = "provider-api-key-xyz"
    provider_row.config = {"management_key": "mgmt-key-123456"}

    async def patched_collect():
        secrets = set()
        def _add(val):
            if val and len(val) >= secret_registry.MIN_SECRET_LENGTH:
                secrets.add(val)
        _add(provider_row.api_key)
        _add(provider_row.config.get("management_key"))
        return secrets

    with patch("app.services.secret_registry.settings", fake), \
         patch("app.services.secret_registry._collect_secrets", patched_collect):
        await secret_registry.rebuild()
        assert "provider-api-key-xyz" in secret_registry._known_secrets
        assert "mgmt-key-123456" in secret_registry._known_secrets


# ---------------------------------------------------------------------------
# rebuild — collects from integration settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_collects_from_integration_settings():
    fake = _fake_settings()

    async def patched_collect():
        secrets = set()
        def _add(val):
            if val and len(val) >= secret_registry.MIN_SECRET_LENGTH:
                secrets.add(val)
        # Simulate integration secret
        _add("slack-bot-token-very-secret")
        return secrets

    with patch("app.services.secret_registry.settings", fake), \
         patch("app.services.secret_registry._collect_secrets", patched_collect):
        await secret_registry.rebuild()
        assert "slack-bot-token-very-secret" in secret_registry._known_secrets


# ---------------------------------------------------------------------------
# rebuild — collects from MCP servers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_collects_from_mcp():
    fake = _fake_settings()

    async def patched_collect():
        secrets = set()
        def _add(val):
            if val and len(val) >= secret_registry.MIN_SECRET_LENGTH:
                secrets.add(val)
        _add("mcp-api-key-long-value")
        return secrets

    with patch("app.services.secret_registry.settings", fake), \
         patch("app.services.secret_registry._collect_secrets", patched_collect):
        await secret_registry.rebuild()
        assert "mcp-api-key-long-value" in secret_registry._known_secrets


# ---------------------------------------------------------------------------
# redact — basic behavior
# ---------------------------------------------------------------------------

def test_redact_replaces_known_secret():
    secret_registry._known_secrets = {"my-secret-key-12345"}
    secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)

    with patch("app.services.secret_registry.settings", _fake_settings()):
        result = secret_registry.redact("The key is my-secret-key-12345 and that's it")
        assert result == "The key is [REDACTED] and that's it"


def test_redact_handles_multiple_secrets():
    secret_registry._known_secrets = {"secret-aaa-111", "secret-bbb-222"}
    secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)

    with patch("app.services.secret_registry.settings", _fake_settings()):
        result = secret_registry.redact("first=secret-aaa-111 second=secret-bbb-222")
        assert result == "first=[REDACTED] second=[REDACTED]"


def test_redact_longest_first():
    """Longest secrets should be matched first so substrings don't partially match."""
    secret_registry._known_secrets = {"secret", "my-secret-key"}
    secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)

    with patch("app.services.secret_registry.settings", _fake_settings()):
        result = secret_registry.redact("The value is my-secret-key here")
        # Should redact the longer match, not just "secret"
        assert "my-[REDACTED]-key" not in result
        assert result == "The value is [REDACTED] here"


def test_redact_no_match():
    secret_registry._known_secrets = {"some-secret-value"}
    secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)

    with patch("app.services.secret_registry.settings", _fake_settings()):
        result = secret_registry.redact("nothing secret here")
        assert result == "nothing secret here"


def test_redact_disabled():
    secret_registry._known_secrets = {"my-secret-value"}
    secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)

    with patch("app.services.secret_registry.settings", _fake_settings(SECRET_REDACTION_ENABLED=False)):
        result = secret_registry.redact("The key is my-secret-value")
        assert result == "The key is my-secret-value"


def test_redact_no_secrets():
    secret_registry._known_secrets = set()
    secret_registry._pattern = None

    with patch("app.services.secret_registry.settings", _fake_settings()):
        result = secret_registry.redact("some text")
        assert result == "some text"


# ---------------------------------------------------------------------------
# detect_patterns — heuristic matching
# ---------------------------------------------------------------------------

def test_detect_patterns_openai_key():
    text = "My key is sk-abc123def456ghi789jkl012mno"
    results = secret_registry.detect_patterns(text)
    assert len(results) >= 1
    assert results[0]["type"] == "OpenAI API key"


def test_detect_patterns_github_token():
    text = "Token: ghp_ABCDEFghijklmnopqrstuvwxyz123456"
    results = secret_registry.detect_patterns(text)
    assert len(results) >= 1
    types = [r["type"] for r in results]
    assert "GitHub token" in types


def test_detect_patterns_jwt():
    text = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "JWT" in types


def test_detect_patterns_connection_string():
    text = "DATABASE_URL=postgresql://user:pass@host:5432/mydb"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Connection string" in types


def test_detect_patterns_private_key():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Private key header" in types


def test_detect_patterns_aws_key():
    text = "AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "AWS access key" in types


def test_detect_patterns_slack_token():
    text = "SLACK_TOKEN=xoxb-123456789012-abcdefghij"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Slack token" in types


def test_detect_patterns_no_false_positives_normal_prose():
    text = (
        "The server is running normally. Disk usage is at 45%. "
        "Temperature: 72°F. CPU load: 2.3. Memory: 8GB/16GB used."
    )
    results = secret_registry.detect_patterns(text)
    assert results == []


def test_detect_patterns_no_false_positives_code():
    text = """
    def hello():
        name = "world"
        count = 42
        return f"Hello {name}, count={count}"
    """
    results = secret_registry.detect_patterns(text)
    assert results == []


# ---------------------------------------------------------------------------
# check_user_input — combined exact + pattern
# ---------------------------------------------------------------------------

def test_check_user_input_exact_match():
    secret_registry._known_secrets = {"my-super-secret-key-123"}

    result = secret_registry.check_user_input("here is my-super-secret-key-123 in my message")
    assert result is not None
    assert result["exact_matches"] == 1


def test_check_user_input_pattern_match():
    secret_registry._known_secrets = set()

    result = secret_registry.check_user_input("Use this key: sk-abc123def456ghi789jkl012mno")
    assert result is not None
    assert result["exact_matches"] == 0
    assert len(result["pattern_matches"]) >= 1


def test_check_user_input_clean():
    secret_registry._known_secrets = {"some-known-secret"}

    result = secret_registry.check_user_input("Hello, how are you?")
    assert result is None


def test_check_user_input_both_exact_and_pattern():
    secret_registry._known_secrets = {"my-known-secret-key"}

    result = secret_registry.check_user_input(
        "my-known-secret-key and also sk-abc123def456ghi789jkl012mno"
    )
    assert result is not None
    assert result["exact_matches"] == 1
    assert len(result["pattern_matches"]) >= 1


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------

def test_is_enabled_true():
    with patch("app.services.secret_registry.settings", _fake_settings(SECRET_REDACTION_ENABLED=True)):
        assert secret_registry.is_enabled() is True


def test_is_enabled_false():
    with patch("app.services.secret_registry.settings", _fake_settings(SECRET_REDACTION_ENABLED=False)):
        assert secret_registry.is_enabled() is False


# ---------------------------------------------------------------------------
# _build_pattern
# ---------------------------------------------------------------------------

def test_build_pattern_empty():
    assert secret_registry._build_pattern(set()) is None


def test_build_pattern_single():
    pat = secret_registry._build_pattern({"my-secret"})
    assert pat is not None
    assert pat.search("contains my-secret here")


def test_build_pattern_escapes_regex_chars():
    """Secrets with regex-special chars should be escaped."""
    pat = secret_registry._build_pattern({"pass.word+test"})
    assert pat is not None
    assert pat.search("pass.word+test")
    assert not pat.search("password_test")  # dot shouldn't match arbitrary char


@pytest.mark.asyncio
async def test_rebuild_disabled():
    with patch("app.services.secret_registry.settings", _fake_settings(SECRET_REDACTION_ENABLED=False)):
        await secret_registry.rebuild()
        assert secret_registry._built
        assert secret_registry._pattern is None
        assert len(secret_registry._known_secrets) == 0


# ---------------------------------------------------------------------------
# detect_patterns — Stripe keys
# ---------------------------------------------------------------------------

def test_detect_patterns_stripe_live_key():
    text = "sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Stripe live key" in types


def test_detect_patterns_stripe_test_key():
    text = "sk_test_4eC39HqLyjWDarjtT1zdp7dc"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Stripe test key" in types


def test_detect_patterns_stripe_restricted_key():
    text = "rk_live_abc123def456ghi789jkl012mno"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Stripe restricted key" in types


def test_detect_patterns_sendgrid_key():
    text = "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"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "SendGrid API key" in types


def test_detect_patterns_google_api_key():
    text = "AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe"
    results = secret_registry.detect_patterns(text)
    types = [r["type"] for r in results]
    assert "Google API key" in types


# ---------------------------------------------------------------------------
# extract_pattern_values — full match extraction
# ---------------------------------------------------------------------------

def test_extract_pattern_values_returns_full_values():
    text = "My key is sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR and token ghp_ABCDEFghijklmnopqrstuvwxyz123456"
    values = secret_registry.extract_pattern_values(text)
    assert "sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR" in values
    assert "ghp_ABCDEFghijklmnopqrstuvwxyz123456" in values


def test_extract_pattern_values_no_duplicates():
    text = "sk_live_abc123def456ghi789jkl sk_live_abc123def456ghi789jkl"
    values = secret_registry.extract_pattern_values(text)
    assert len(values) == 1


def test_extract_pattern_values_empty_for_clean_text():
    values = secret_registry.extract_pattern_values("Hello, how are you?")
    assert values == []


# ---------------------------------------------------------------------------
# register_runtime_secrets — dynamic registration
# ---------------------------------------------------------------------------

def test_register_runtime_secrets_adds_to_known():
    with patch("app.services.secret_registry.settings", _fake_settings()):
        secret_registry._known_secrets = set()
        secret_registry._pattern = None
        count = secret_registry.register_runtime_secrets(["sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR"])
        assert count == 1
        assert "sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR" in secret_registry._known_secrets
        assert secret_registry._pattern is not None


def test_register_runtime_secrets_rebuilds_pattern():
    with patch("app.services.secret_registry.settings", _fake_settings()):
        secret_registry._known_secrets = {"existing-secret-abc"}
        secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)
        secret_registry.register_runtime_secrets(["new-runtime-secret-xyz"])
        # Both old and new should be redactable
        result = secret_registry.redact("existing-secret-abc and new-runtime-secret-xyz")
        assert result == "[REDACTED] and [REDACTED]"


def test_register_runtime_secrets_skips_duplicates():
    with patch("app.services.secret_registry.settings", _fake_settings()):
        secret_registry._known_secrets = {"already-known-secret"}
        secret_registry._pattern = secret_registry._build_pattern(secret_registry._known_secrets)
        count = secret_registry.register_runtime_secrets(["already-known-secret"])
        assert count == 0


def test_register_runtime_secrets_skips_short():
    with patch("app.services.secret_registry.settings", _fake_settings()):
        secret_registry._known_secrets = set()
        secret_registry._pattern = None
        count = secret_registry.register_runtime_secrets(["ab"])
        assert count == 0


def test_register_runtime_secrets_disabled():
    with patch("app.services.secret_registry.settings", _fake_settings(SECRET_REDACTION_ENABLED=False)):
        secret_registry._known_secrets = set()
        count = secret_registry.register_runtime_secrets(["some-secret-value"])
        assert count == 0


def test_register_then_redact_end_to_end():
    """Full flow: detect patterns, extract values, register, then redact."""
    with patch("app.services.secret_registry.settings", _fake_settings()):
        secret_registry._known_secrets = set()
        secret_registry._pattern = None
        message = "Use this Stripe key: sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR"
        # Detect
        hits = secret_registry.detect_patterns(message)
        assert len(hits) >= 1
        # Extract full values
        values = secret_registry.extract_pattern_values(message)
        assert len(values) >= 1
        # Register
        secret_registry.register_runtime_secrets(values)
        # Now redact should work
        response = "Your Stripe key sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR has been noted."
        redacted = secret_registry.redact(response)
        assert "sk_live_dhjcEWcbfwybVYD8Ga0IjmTzMwpacvXR" not in redacted
        assert "[REDACTED]" in redacted
