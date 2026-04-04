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
        "Runs emails through the 4-layer security pipeline and delivers "
        "passed emails to all bound channel workspaces. Returns a summary "
        "of fetched, passed, quarantined, and delivered counts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deliver": {
                "type": "boolean",
                "description": (
                    "Whether to deliver passed emails to bound channel workspaces. "
                    "Default true. Set false to only check what's available without writing files."
                ),
            },
            "since_days": {
                "type": "integer",
                "description": (
                    "Override: only fetch emails from the last N days. "
                    "Ignores the cursor and uses IMAP SINCE criteria."
                ),
            },
            "max_items": {
                "type": "integer",
                "description": "Override: max emails to fetch this call (default: GMAIL_MAX_PER_POLL).",
            },
            "folders": {
                "type": "string",
                "description": "Override: comma-separated IMAP folders to poll (default: GMAIL_FOLDERS).",
            },
        },
    },
}})
async def trigger_gmail_poll(
    deliver: bool = True,
    since_days: int | None = None,
    max_items: int | None = None,
    folders: str | None = None,
) -> str:
    """Trigger a manual Gmail poll cycle with optional delivery and overrides."""
    from integrations.gmail import agent_client
    from integrations.gmail.config import settings
    from integrations.gmail.factory import create_feed

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return "Gmail not configured — GMAIL_EMAIL is not set."

    folders_list = (
        [f.strip() for f in folders.split(",") if f.strip()]
        if folders
        else None
    )

    has_overrides = since_days is not None or max_items is not None or folders_list is not None

    feed, store = create_feed()
    try:
        if has_overrides:
            # Use overrides path — fetch with custom params, then run pipeline
            raw_items = await feed.fetch_items_with_overrides(
                since_days=since_days,
                max_items=max_items,
                folders=folders_list,
            )
            result = await feed._run_pipeline(raw_items)
        else:
            result = await feed.run_cycle()
    finally:
        feed._disconnect()
        store.close()

    parts = [
        f"Gmail poll complete: {result.fetched} fetched, {result.passed} passed, "
        f"{result.quarantined} quarantined, {result.skipped} skipped."
    ]

    # Deliver passed items to bound channel workspaces
    delivered = 0
    if deliver and result.items:
        binding_prefix = f"gmail:{email_addr}"
        channels = await agent_client.resolve_channels_for_binding(binding_prefix)
        if not channels:
            parts.append(
                f"Warning: No channels bound to {binding_prefix}. "
                f"{len(result.items)} emails processed but not delivered."
            )
        else:
            for item in result.items:
                for ch in channels:
                    channel_id = str(ch.get("id", ""))
                    if not channel_id:
                        continue
                    path = item.suggested_path or f"data/gmail/{item.source_id}.md"
                    ok = await agent_client.write_workspace_file(channel_id, path, item.body)
                    if ok:
                        delivered += 1

    if result.items:
        parts.append("New emails processed:")
        for item in result.items:
            parts.append(f"  - {item.title} → {item.suggested_path}")
        if deliver and delivered > 0:
            parts.append(f"Delivered {delivered} file(s) to workspace.")
    if result.errors:
        parts.append(f"Errors: {'; '.join(result.errors)}")
    if not result.items and not result.errors:
        parts.append("No new emails.")

    return "\n".join(parts)
