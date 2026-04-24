"""Run inside the e2e agent-server container.

Usage:
    python - <bot_id> [bot_id ...]

Usage/cost pills on ``/admin/bots`` are computed from ``trace_events`` rows
with ``event_type="token_usage"`` (see ``app/routers/api_v1_admin/usage.py``).
This seeder inserts a handful of such rows per bot so the admin list shows
realistic cost badges without spending real LLM tokens.

Idempotent: if the bot already has any ``token_usage`` event, this script
no-ops for that bot.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone


SEED_MARK = "screenshot"


async def main() -> None:
    bot_ids = sys.argv[1:]
    if not bot_ids:
        raise SystemExit("usage: python - <bot_id> [bot_id ...]")

    from app.db.engine import async_session  # type: ignore
    from app.db.models import TraceEvent  # type: ignore
    from sqlalchemy import select  # type: ignore

    async with async_session() as db:
        for bot_id in bot_ids:
            existing = (
                await db.execute(
                    select(TraceEvent)
                    .where(TraceEvent.bot_id == bot_id)
                    .where(TraceEvent.event_type == "token_usage")
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"skip bot_id={bot_id} (already has token_usage events)")
                continue

            now = datetime.now(timezone.utc)
            model = "claude-haiku-4-5"
            provider_id = "anthropic"
            # 8 events spread across the last few days so the /admin/bots
            # 30-day cost summary has plausible totals.
            for i in range(8):
                prompt = 1200 + i * 150
                completion = 280 + i * 45
                ev = TraceEvent(
                    bot_id=bot_id,
                    event_type="token_usage",
                    event_name="chat_completion",
                    data={
                        "model": model,
                        "provider_id": provider_id,
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "cached_tokens": 0,
                        "response_cost": round(0.004 + i * 0.0008, 6),
                        "seeded_for": SEED_MARK,
                    },
                    created_at=now - timedelta(days=i // 3, hours=4 + i),
                )
                db.add(ev)
            await db.commit()
            print(f"ok bot_id={bot_id} seeded=8 token_usage events")


if __name__ == "__main__":
    asyncio.run(main())
