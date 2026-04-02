"""Shared factory for creating GmailFeed + pipeline instances.

Avoids duplicating the setup code across poller, router, and tools.
"""

from __future__ import annotations

import os

from integrations.ingestion.config import IngestionConfig
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore

from integrations.gmail.config import settings
from integrations.gmail.feed import GmailFeed

_DB_DIR = os.path.expanduser("~/.agent-workspaces/.ingestion")


def create_feed() -> tuple[GmailFeed, IngestionStore]:
    """Create a GmailFeed with its pipeline and store.

    Returns (feed, store) — caller should call store.close() when done.
    """
    os.makedirs(_DB_DIR, exist_ok=True)
    store = IngestionStore(os.path.join(_DB_DIR, "gmail.db"))

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

    return feed, store
