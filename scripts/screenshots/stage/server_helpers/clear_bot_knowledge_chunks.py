"""Delete every FilesystemChunk row for a bot's knowledge-base/ prefix.

Usage:
    python - <bot_id>

Mirror of ``seed_bot_knowledge_chunks.py`` for teardown. Targets only
``knowledge-base/%`` paths so unrelated index rows for the same bot are
not touched.
"""
from __future__ import annotations

import asyncio
import sys


async def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python - <bot_id>")

    bot_id = sys.argv[1]

    from app.agent.bots import get_bot, load_bots  # type: ignore
    from app.domain.errors import NotFoundError  # type: ignore
    from app.db.engine import async_session  # type: ignore
    from app.db.models import FilesystemChunk  # type: ignore
    from app.services.workspace import workspace_service  # type: ignore
    from sqlalchemy import delete  # type: ignore

    await load_bots()
    try:
        bot = get_bot(bot_id)
    except NotFoundError:
        print(f"skip bot={bot_id} not found")
        return

    prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot).rstrip("/")

    async with async_session() as db:
        result = await db.execute(
            delete(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot_id,
                FilesystemChunk.file_path.like(f"{prefix}/%"),
            )
        )
        await db.commit()
        print(f"ok bot={bot_id} prefix={prefix!r} deleted={result.rowcount or 0}")


if __name__ == "__main__":
    asyncio.run(main())
