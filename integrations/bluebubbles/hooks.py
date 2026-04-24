"""BlueBubbles integration hooks — metadata registration.

Registers the bb: client_id prefix so channels auto-detect integration="bluebubbles".
Also provides resolve_dispatch_config so web UI responses can be mirrored to iMessage.
"""
from __future__ import annotations

import logging
import os

from integrations.sdk import IntegrationMeta, register_integration

logger = logging.getLogger(__name__)


def _resolve_dispatch_config(client_id: str) -> dict | None:
    """Build BB dispatch_config from a bb: client_id.

    Extracts the chat GUID from the client_id and looks up server_url/password
    from IntegrationSetting DB cache (admin UI) or environment variables.
    """
    if not client_id.startswith("bb:"):
        return None
    chat_guid = client_id.removeprefix("bb:")
    if not chat_guid:
        return None

    # Try DB-cached settings first (admin UI), then env vars
    server_url = None
    password = None
    try:
        from app.services.integration_settings import get_value
        server_url = get_value("bluebubbles", "BLUEBUBBLES_SERVER_URL")
        password = get_value("bluebubbles", "BLUEBUBBLES_PASSWORD")
    except Exception:
        pass
    if not server_url:
        server_url = os.environ.get("BLUEBUBBLES_SERVER_URL")
    if not password:
        password = os.environ.get("BLUEBUBBLES_PASSWORD")

    if not server_url or not password:
        logger.debug("Cannot resolve BB dispatch_config: missing server_url or password")
        return None

    return {
        "type": "bluebubbles",
        "chat_guid": chat_guid,
        "server_url": server_url,
        "password": password,
    }


def _claims_user_id(recipient_user_id: str) -> bool:
    """BlueBubbles recipient ids are phone numbers (``+…``) or emails (``@``)."""
    return "@" in recipient_user_id or recipient_user_id.startswith("+")


register_integration(IntegrationMeta(
    integration_type="bluebubbles",
    client_id_prefix="bb:",
    resolve_dispatch_config=_resolve_dispatch_config,
    claims_user_id=_claims_user_id,
))
