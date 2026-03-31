"""Gmail IMAP poller — background process entry point.

Creates an IngestionPipeline + GmailFeed, polls on interval,
delivers items to bound channels via agent_client HTTP calls.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("gmail.poller")

_shutdown_event = asyncio.Event()


async def _run() -> None:
    from integrations.gmail import agent_client
    from integrations.gmail.config import settings
    from integrations.gmail.factory import create_feed

    feed, store = create_feed()
    email_addr = settings.GMAIL_EMAIL
    binding_prefix = f"gmail:{email_addr}"

    poll_interval = settings.GMAIL_POLL_INTERVAL
    backoff = poll_interval
    max_backoff = max(poll_interval * 8, 300)

    # Initial delay for server startup
    logger.info("Gmail poller starting for %s (waiting 5s for server)...", email_addr)
    await asyncio.sleep(5)

    try:
        while not _shutdown_event.is_set():
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

                # Deliver items to bound channels matching THIS email account
                if result.items:
                    channels = await agent_client.resolve_channels_for_binding(binding_prefix)
                    if not channels:
                        logger.warning(
                            "No channels bound to %s; %d items not delivered",
                            binding_prefix, len(result.items),
                        )
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
                                else:
                                    logger.warning(
                                        "Failed to deliver %s to channel %s at %s",
                                        item.source_id, channel_id, path,
                                    )

                # Reset backoff on success
                backoff = poll_interval

            except Exception:
                logger.exception("Poll cycle failed")
                backoff = min(backoff * 2, max_backoff)

            # Sleep but wake on shutdown
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=backoff)
                break  # shutdown requested
            except asyncio.TimeoutError:
                pass  # normal timeout, continue polling
    finally:
        logger.info("Cleaning up...")
        feed._disconnect()
        store.close()
        await agent_client._http.aclose()


def main() -> None:
    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        logger.info("Shutting down (signal %s)...", sig)
        _shutdown_event.set()

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
