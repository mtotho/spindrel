"""Tests for GitHub webhook HMAC-SHA256 signature validation."""

import hashlib
import hmac
from unittest.mock import patch

from integrations.github.validator import validate_signature


def _sign(payload: bytes, secret: str) -> str:
    """Create a valid X-Hub-Signature-256 header value."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class TestValidateSignature:
    def test_valid_signature(self):
        secret = "test-secret"
        payload = b'{"action": "completed"}'
        header = _sign(payload, secret)

        with patch("integrations.github.validator.github_config") as mock_cfg:
            mock_cfg.GITHUB_WEBHOOK_SECRET = secret
            assert validate_signature(payload, header) is True

    def test_invalid_signature(self):
        secret = "test-secret"
        payload = b'{"action": "completed"}'
        header = "sha256=deadbeef"

        with patch("integrations.github.validator.github_config") as mock_cfg:
            mock_cfg.GITHUB_WEBHOOK_SECRET = secret
            assert validate_signature(payload, header) is False

    def test_missing_header(self):
        with patch("integrations.github.validator.github_config") as mock_cfg:
            mock_cfg.GITHUB_WEBHOOK_SECRET = "test-secret"
            assert validate_signature(b"payload", None) is False

    def test_no_secret_configured_allows_all(self):
        with patch("integrations.github.validator.github_config") as mock_cfg:
            mock_cfg.GITHUB_WEBHOOK_SECRET = ""
            assert validate_signature(b"anything", None) is True

    def test_wrong_prefix(self):
        with patch("integrations.github.validator.github_config") as mock_cfg:
            mock_cfg.GITHUB_WEBHOOK_SECRET = "secret"
            assert validate_signature(b"payload", "md5=abc123") is False
