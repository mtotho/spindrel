"""FastAPI router for Gmail integration — health, status, manual trigger."""

from __future__ import annotations

import asyncio
import imaplib
import logging

from fastapi import APIRouter, Depends

from app.dependencies import verify_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping():
    return {"status": "ok", "service": "gmail"}


@router.get("/status")
async def gmail_status(_auth=Depends(verify_auth)):
    """Test IMAP connectivity and return account info."""
    from integrations.gmail.config import settings

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return {"connected": False, "error": "GMAIL_EMAIL not configured"}

    def _check():
        try:
            conn = imaplib.IMAP4_SSL(settings.GMAIL_IMAP_HOST, settings.GMAIL_IMAP_PORT)
            conn.login(email_addr, settings.GMAIL_APP_PASSWORD)
            ok, folders = conn.list()
            folder_count = len(folders) if ok == "OK" and folders else 0
            conn.logout()
            return {"connected": True, "email": email_addr, "folder_count": folder_count}
        except Exception as exc:
            return {"connected": False, "email": email_addr, "error": str(exc)}

    return await asyncio.to_thread(_check)


@router.post("/trigger")
async def gmail_trigger(_auth=Depends(verify_auth)):
    """Manually trigger a poll cycle and return results."""
    from integrations.gmail.config import settings
    from integrations.gmail.factory import create_feed

    if not settings.GMAIL_EMAIL:
        return {"error": "GMAIL_EMAIL not configured", "fetched": 0}

    feed, store = create_feed()
    try:
        result = await feed.run_cycle()
    finally:
        feed._disconnect()
        store.close()

    return {
        "fetched": result.fetched,
        "passed": result.passed,
        "quarantined": result.quarantined,
        "skipped": result.skipped,
        "errors": result.errors,
        "items": [
            {"title": item.title, "source_id": item.source_id, "path": item.suggested_path}
            for item in result.items
        ],
    }
