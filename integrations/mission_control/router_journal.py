"""Mission Control — Journal endpoint."""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user
from integrations.mission_control.helpers import get_bot, get_mc_prefs, get_user, tracked_channels
from integrations.mission_control.schemas import JournalResponse

router = APIRouter()


@router.get("/journal", response_model=JournalResponse)
async def journal(
    days: int = Query(7, ge=1, le=90),
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated daily logs from tracked bots."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    bot_ids = list({ch.bot_id for ch in channels})
    if prefs.get("tracked_bot_ids"):
        tracked = set(prefs["tracked_bot_ids"])
        bot_ids = [bid for bid in bot_ids if bid in tracked]

    entries: list[dict] = []
    today = date.today()

    for bot_id in bot_ids:
        try:
            bot = get_bot(bot_id)
        except Exception:
            continue

        if bot.memory_scheme != "workspace-files":
            continue

        from app.services.memory_scheme import get_memory_root
        try:
            mem_root = get_memory_root(bot)
        except Exception:
            continue

        logs_dir = os.path.join(mem_root, "logs")
        if not os.path.isdir(logs_dir):
            continue

        def _read_logs(logs_dir=logs_dir, bot=bot):
            results = []
            for day_offset in range(days):
                d = today - timedelta(days=day_offset)
                log_path = os.path.join(logs_dir, f"{d.isoformat()}.md")
                if os.path.isfile(log_path):
                    try:
                        with open(log_path) as f:
                            content = f.read()
                        if content.strip():
                            results.append({
                                "date": d.isoformat(),
                                "bot_id": bot.id,
                                "bot_name": bot.name,
                                "content": content,
                            })
                    except Exception:
                        pass
            return results

        entries.extend(await asyncio.to_thread(_read_logs))

    entries.sort(key=lambda e: e["date"], reverse=True)
    return {"entries": entries}
