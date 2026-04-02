"""HMAC-SHA256 signature validation for GitHub webhooks."""

import hashlib
import hmac

from integrations.github.config import github_config


def validate_signature(payload: bytes, signature_header: str | None) -> bool:
    """Validate X-Hub-Signature-256 header against the payload.

    Returns True if the signature is valid, False otherwise.
    """
    if not github_config.GITHUB_WEBHOOK_SECRET:
        # No secret configured — fail-secure (reject webhook)
        import logging
        logging.getLogger(__name__).warning(
            "GITHUB_WEBHOOK_SECRET not configured — rejecting webhook. "
            "Set the secret to enable webhook processing."
        )
        return False

    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        github_config.GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
