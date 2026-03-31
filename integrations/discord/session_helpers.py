"""Discord<->agent session identity helpers."""
import uuid


def discord_client_id(channel_id: str) -> str:
    return f"discord:{channel_id}"


def derive_session_id(client_id: str) -> str:
    """Derive a stable session_id from client_id alone (channel-scoped, bot-independent)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, client_id))
