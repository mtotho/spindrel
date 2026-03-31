"""FastAPI router for Gmail integration — health, status, manual trigger."""

from __future__ import annotations

import asyncio
import imaplib
import logging
import os

from fastapi import APIRouter, Depends

from app.dependencies import verify_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping():
    return {"status": "ok", "service": "gmail"}


@router.get("/status")
async def status(_auth=Depends(verify_auth)):
    """Test IMAP connectivity and return account info."""
    from integrations.gmail.config import settings

    email_addr = settings.GMAIL_EMAIL
    if not email_addr:
        return {"connected": False, "error": "GMAIL_EMAIL not configured"}

    def _check():
        try:
            conn = imaplib.IMAP4_SSL(settings.GMAIL_IMAP_HOST, settings.GMAIL_IMAP_PORT)
            conn.login(email_addr, settings.GMAIL_APP_PASSWORD)
            status, folders = conn.list()
            folder_count = len(folders) if status == "OK" and folders else 0
            conn.logout()
            return {"connected": True, "email": email_addr, "folder_count": folder_count}
        except Exception as exc:
            return {"connected": False, "email": email_addr, "error": str(exc)}

    return await asyncio.to_thread(_check)


@router.post("/trigger")
async def trigger(_auth=Depends(verify_auth)):
    """Manually trigger a poll cycle and return results."""
    from integrations.ingestion.config import IngestionConfig
    from integrations.ingestion.pipeline import IngestionPipeline
    from integrations.ingestion.store import IngestionStore

    from integrations.gmail.config import settings
    from integrations.gmail.feed import GmailFeed

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
