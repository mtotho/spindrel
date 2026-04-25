"""Seed FilesystemChunk rows so a bot's knowledge-base/ index renders non-empty.

Usage:
    python - <bot_id>

Inserts a small set of canned ``knowledge-base/<file>`` chunks for the named
bot, with NULL embeddings and a stable ``content_hash`` per (file, chunk).
The Memory & Knowledge inventory page (``/admin/learning#Knowledge``) only
reads ``COUNT(file_path)``, ``COUNT(*)``, and ``MAX(indexed_at)`` so a fake
embedding is fine for the screenshot.

Idempotent: existing rows for the same (bot_id, file_path, chunk_index)
are left in place — the helper inserts only the missing ones.

Path prefix matches ``WorkspaceService.get_bot_knowledge_base_index_prefix``:
standalone bots → ``knowledge-base``; shared-workspace bots → ``bots/<id>/
knowledge-base``. The screenshot bots are standalone.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from datetime import datetime, timedelta, timezone


SEED_FILES: list[tuple[str, list[str]]] = [
    (
        "home-network.md",
        [
            "## Home network\n\nGateway: 10.10.30.1 (UniFi UDM Pro). VLAN 30 carries the agent server, NAS, and home automation hub.",
            "Reserved leases live in `/config/dhcp.yaml`. Anything outside VLAN 30 cannot reach the agent server's REST API.",
        ],
    ),
    (
        "automations.md",
        [
            "## Standing automations\n\n- Nightly backup at 03:00 (rsync /opt/thoth-data → NAS, then a Postgres dump).",
            "- Camera 4 alarm triggers a push notification when motion is detected between 22:00 and 06:00.",
            "- Amazon delivery watcher pings here when an order moves to Out for delivery.",
        ],
    ),
    (
        "houseplant-roster.md",
        [
            "## Houseplant roster\n\nMonstera (kitchen, every 7d), fiddle leaf (living room, every 10d), pothos (bedroom, every 14d), snake plant (bath, every 21d).",
        ],
    ),
    (
        "preferred-providers.md",
        [
            "## Preferred providers\n\nDefault chat: Anthropic Sonnet 4.6. Cheap classification: Haiku 4.5. Local fallback: Ollama llama3.1-8b.",
            "Image generation falls back from gpt-image to Gemini Flash Image when OpenAI is rate-limited.",
        ],
    ),
]


async def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python - <bot_id>")

    bot_id = sys.argv[1]

    from app.agent.bots import get_bot, load_bots  # type: ignore
    from app.domain.errors import NotFoundError  # type: ignore
    from app.db.engine import async_session  # type: ignore
    from app.db.models import FilesystemChunk  # type: ignore
    from app.services.workspace import workspace_service  # type: ignore
    from sqlalchemy import select  # type: ignore

    # The bot registry is populated at server startup; this script runs in a
    # fresh subprocess so we must hydrate it ourselves before get_bot works.
    await load_bots()
    try:
        bot = get_bot(bot_id)
    except NotFoundError as e:
        raise SystemExit(str(e))

    # Match whatever prefix /admin/learning's library inventory queries on.
    # Standalone bots → "knowledge-base"; shared-workspace bots →
    # "bots/<id>/knowledge-base". Computing the prefix here keeps the seed
    # in lockstep with the inventory route (no manual coupling on the bot's
    # workspace shape).
    prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot).rstrip("/")

    inserted = 0
    skipped = 0

    async with async_session() as db:
        # Indexed_at is staggered so the "last indexed" column shows a
        # plausibly-recent timestamp without all rows being identical.
        base_ts = datetime.now(timezone.utc) - timedelta(minutes=12)
        for file_idx, (file_name, chunks) in enumerate(SEED_FILES):
            file_path = f"{prefix}/{file_name}"
            for chunk_idx, content in enumerate(chunks):
                existing = (
                    await db.execute(
                        select(FilesystemChunk.id).where(
                            FilesystemChunk.bot_id == bot_id,
                            FilesystemChunk.file_path == file_path,
                            FilesystemChunk.chunk_index == chunk_idx,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    skipped += 1
                    continue

                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                row = FilesystemChunk(
                    id=uuid.uuid4(),
                    bot_id=bot_id,
                    client_id=None,
                    root="",
                    file_path=file_path,
                    content_hash=content_hash,
                    chunk_index=chunk_idx,
                    content=content,
                    embedding=None,
                    language="markdown",
                    symbol=None,
                    start_line=None,
                    end_line=None,
                    embedding_model=None,
                    indexed_at=base_ts + timedelta(seconds=file_idx * 30 + chunk_idx),
                )
                db.add(row)
                inserted += 1

        await db.commit()

    print(f"ok bot={bot_id} prefix={prefix!r} inserted={inserted} skipped={skipped} files={len(SEED_FILES)}")


if __name__ == "__main__":
    asyncio.run(main())
