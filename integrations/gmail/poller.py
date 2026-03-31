"""Gmail IMAP poller — background process entry point.

Creates an IngestionPipeline + GmailFeed, polls on interval,
delivers items to bound channels via agent_client HTTP calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("gmail.poller")


async def _run() -> None:
    from integrations.ingestion.config import IngestionConfig
    from integrations.ingestion.pipeline import IngestionPipeline
    from integrations.ingestion.store import IngestionStore

    from integrations.gmail import agent_client
    from integrations.gmail.config import settings
    from integrations.gmail.feed import GmailFeed

    # Store lives alongside workspaces
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

    poll_interval = settings.GMAIL_POLL_INTERVAL
    backoff = poll_interval

    # Initial delay for server startup
    logger.info("Gmail poller starting (waiting 5s for server)...")
    await asyncio.sleep(5)

    while True:
        try:
            result = await feed.run_cycle()
            logger.info(
                "Cycle: fetched=%d passed=%d quarantined=%d skipped=%d errors=%d",
                result.fetched, result.passed, result.quarantined,
                result.skipped, len(result.errors),
            )

            if result.errors:
                for err in result.errors:
                    logger.warning("Cycle error: %s", err)

            # Deliver items to bound channels
            if result.items:
                channels = await agent_client.resolve_channels_for_binding("gmail:")
                if not channels:
                    logger.warning("No gmail-bound channels found; %d items not delivered", len(result.items))
                else:
                    for item in result.items:
                        for ch in channels:
                            channel_id = str(ch.get("id", ""))
                            if not channel_id:
                                continue
                            path = item.suggested_path or f"data/gmail/{item.source_id}.md"
                            ok = await agent_client.write_workspace_file(
                                channel_id, path, item.body,
                            )
                            if ok:
                                logger.info(
                                    "Delivered %s to channel %s at %s",
                                    item.source_id, channel_id, path,
                                )

            # Reset backoff on success
            backoff = poll_interval

        except Exception:
            logger.exception("Poll cycle failed")
            backoff = min(backoff * 2, 60)

        await asyncio.sleep(backoff)


def main() -> None:
    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        logger.info("Shutting down (signal %s)...", sig)
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
