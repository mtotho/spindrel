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
            status, folders = conn.list()
            folder_count = len(folders) if status == "OK" and folders else 0
            conn.logout()
            return f"Connected to {email_addr} — {folder_count} folders available. Polling folders: {', '.join(settings.GMAIL_FOLDERS)}"
        except Exception as exc:
            return f"Gmail connection failed for {email_addr}: {exc}"

    return await asyncio.to_thread(_check)


@reg.register({"type": "function", "function": {
    "name": "trigger_gmail_poll",
    "description": (
        "Manually trigger a Gmail poll cycle to fetch new emails immediately. "
        "Returns a summary of fetched, passed, quarantined, and skipped emails."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}})
async def trigger_gmail_poll() -> str:
    """Trigger a manual Gmail poll cycle."""
    import os
    from integrations.ingestion.config import IngestionConfig
    from integrations.ingestion.pipeline import IngestionPipeline
    from integrations.ingestion.store import IngestionStore
    from integrations.gmail.config import settings
    from integrations.gmail.feed import GmailFeed

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return "Gmail not configured — GMAIL_EMAIL is not set."

    db_dir = os.path.expanduser("~/.agent-workspaces/.ingestion")
    os.makedirs(db_dir, exist_ok=True)
    store = IngestionStore(os.path.join(db_dir, "gmail.db"))

    config = IngestionConfig(
        agent_base_url=settings.AGENT_BASE_URL,
        agent_api_key=settings.AGENT_API_KEY,
    )
    pipeline = IngestionPipeline(config=config, store=store)

    feed = GmailFeed(
        pipeline=pipeline,
        store=store,
        host=settings.GMAIL_IMAP_HOST,
        port=settings.GMAIL_IMAP_PORT,
        email_addr=settings.GMAIL_EMAIL,
        password=settings.GMAIL_APP_PASSWORD,
        folders=settings.GMAIL_FOLDERS,
        max_per_poll=settings.GMAIL_MAX_PER_POLL,
    )

    result = await feed.run_cycle()

    parts = [
        f"Gmail poll complete: {result.fetched} fetched, {result.passed} passed, "
        f"{result.quarantined} quarantined, {result.skipped} skipped."
    ]
    if result.items:
        parts.append("New emails:")
        for item in result.items:
            parts.append(f"  - {item.title} → {item.suggested_path}")
    if result.errors:
        parts.append(f"Errors: {'; '.join(result.errors)}")

    return "\n".join(parts)
