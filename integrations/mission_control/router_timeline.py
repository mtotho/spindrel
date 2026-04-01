"""Mission Control — Timeline endpoint."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user
from integrations.mission_control.helpers import (
    get_mc_prefs,
    get_user,
    humanize_event,
    read_timeline_for_channel,
    tracked_channels,
)
from integrations.mission_control.schemas import TimelineEvent, TimelineResponse

router = APIRouter()


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    days: int = Query(7, ge=1, le=90),
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated timeline: reads timeline.md from all tracked channels, merges events."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    all_events: list[TimelineEvent] = []

    all_raw = await asyncio.gather(
        *(read_timeline_for_channel(ch) for ch in channels)
    )
    for ch, raw_events in zip(channels, all_raw):
        for ev in raw_events:
            if ev["date"] < cutoff:
                break
            all_events.append(TimelineEvent(
                date=ev["date"],
                time=ev["time"],
                event=humanize_event(ev["event"]),
                channel_id=str(ch.id),
                channel_name=ch.name,
            ))

    all_events.sort(key=lambda e: (e.date, e.time), reverse=True)
    return {"events": all_events}
