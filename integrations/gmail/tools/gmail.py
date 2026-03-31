"""Gmail bot tools — status check and manual poll trigger."""

from __future__ import annotations

import logging

from integrations import _register as reg

logger = logging.getLogger(__name__)


@reg.register({"type": "function", "function": {
    "name": "check_gmail_status",
    "description": (
        "Check Gmail IMAP connectivity and account status. "
        "Returns connection status, email address, and folder count."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}})
async def check_gmail_status() -> str:
    """Check Gmail IMAP connectivity."""
    import asyncio
    import imaplib
    from integrations.gmail.config import settings

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return "Gmail not configured — GMAIL_EMAIL is not set."

    def _check():
        try:
            conn = imaplib.IMAP4_SSL(settings.GMAIL_IMAP_HOST, settings.GMAIL_IMAP_PORT)
            conn.login(email_addr, settings.GMAIL_APP_PASSWORD)
            ok, folders = conn.list()
            folder_count = len(folders) if ok == "OK" and folders else 0
            conn.logout()
            return (
                f"Connected to {email_addr} — {folder_count} folders available. "
                f"Polling folders: {', '.join(settings.GMAIL_FOLDERS)}"
            )
        except Exception as exc:
            return f"Gmail connection failed for {email_addr}: {exc}"

    return await asyncio.to_thread(_check)


@reg.register({"type": "function", "function": {
    "name": "trigger_gmail_poll",
    "description": (
        "Manually trigger a Gmail poll cycle to fetch new emails immediately. "
        "Runs emails through the security pipeline and returns a summary. "
        "Note: this processes emails but does NOT deliver them to channel workspaces — "
        "the background poller handles delivery. Use this to check what new emails are available."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}})
async def trigger_gmail_poll() -> str:
    """Trigger a manual Gmail poll cycle."""
    from integrations.gmail.config import settings
    from integrations.gmail.factory import create_feed

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return "Gmail not configured — GMAIL_EMAIL is not set."

    feed, store = create_feed()
    try:
        result = await feed.run_cycle()
    finally:
        feed._disconnect()
        store.close()

    parts = [
        f"Gmail poll complete: {result.fetched} fetched, {result.passed} passed, "
        f"{result.quarantined} quarantined, {result.skipped} skipped."
    ]
    if result.items:
        parts.append("New emails processed:")
        for item in result.items:
            parts.append(f"  - {item.title} → {item.suggested_path}")
    if result.errors:
        parts.append(f"Errors: {'; '.join(result.errors)}")
    if not result.items and not result.errors:
        parts.append("No new emails.")

    return "\n".join(parts)
