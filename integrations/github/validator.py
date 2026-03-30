"""HMAC-SHA256 signature validation for GitHub webhooks."""
from __future__ import annotations

import hashlib
import hmac

from integrations.github.config import settings


def validate_signature(payload: bytes, signature_header: str | None) -> bool:
    """Validate X-Hub-Signature-256 header against the payload.

    Returns True if valid. When no secret is configured, skips validation (dev mode).
    """
    if not settings.GITHUB_WEBHOOK_SECRET:
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
