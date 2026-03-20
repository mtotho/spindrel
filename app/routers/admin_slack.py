"""Admin Slack channel config routes + /api/slack/config endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy import func
from app.config import settings
from app.db.engine import async_session
from app.db.models import Bot as BotRow, Session, SlackChannelConfig

router = APIRouter()
api_router = APIRouter()  # Registered at root level for /api/slack/config

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/slack", response_class=HTMLResponse)
async def admin_slack(request: Request):
    async with async_session() as db:
        channel_configs = (await db.execute(
            select(SlackChannelConfig).order_by(SlackChannelConfig.channel_id)
        )).scalars().all()
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

        # Distinct channel IDs seen in sessions (client_id = "slack:{channel_id}")
        raw_client_ids = (await db.execute(
            select(Session.client_id)
            .where(Session.client_id.like("slack:%"))
            .distinct()
            .order_by(Session.client_id)
        )).scalars().all()

    # Extract channel_id from "slack:{channel_id}"
    seen_channels = [cid[len("slack:"):] for cid in raw_client_ids if cid]

    # Build a lookup: channel_id -> SlackChannelConfig row (if configured)
    config_map = {c.channel_id: c for c in channel_configs}

    default_bot = settings.SLACK_DEFAULT_BOT

    return templates.TemplateResponse("admin/slack.html", {
        "request": request,
        "channel_configs": channel_configs,
        "all_bots": all_bots,
        "default_bot": default_bot,
        "seen_channels": seen_channels,
        "config_map": config_map,
    })


@router.post("/slack/channels", response_class=HTMLResponse)
async def admin_slack_channel_upsert(
    request: Request,
    channel_id: str = Form(...),
    bot_id: str = Form(...),
    description: str = Form(""),
):
    channel_id = channel_id.strip()
    bot_id = bot_id.strip()
    if not channel_id or not bot_id:
        return HTMLResponse("<div class='text-red-400 p-4'>channel_id and bot_id are required.</div>", status_code=422)

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(SlackChannelConfig)
        .values(
            channel_id=channel_id,
            bot_id=bot_id,
            description=description.strip() or None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["channel_id"],
            set_={"bot_id": bot_id, "description": description.strip() or None, "updated_at": now},
        )
    )
    async with async_session() as db:
        await db.execute(stmt)
        await db.commit()
    return RedirectResponse("/admin/slack", status_code=303)


@router.delete("/slack/channels/{config_id}", response_class=HTMLResponse)
async def admin_slack_channel_delete(config_id: int):
    async with async_session() as db:
        row = await db.get(SlackChannelConfig, config_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        await db.delete(row)
        await db.commit()
    return HTMLResponse("", status_code=200)


# ---------------------------------------------------------------------------
# API endpoint for Slack integration (registered at /api/slack/config)
# ---------------------------------------------------------------------------

@api_router.get("/slack/config")
async def api_slack_config(request: Request):
    """Returns Slack channel→bot mapping for the Slack integration service."""
    # Simple API key check
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    expected = getattr(settings, "API_KEY", None)
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        channel_rows = (await db.execute(select(SlackChannelConfig))).scalars().all()
        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {row.channel_id: row.bot_id for row in channel_rows}
    default_bot = settings.SLACK_DEFAULT_BOT

    bots = {
        row.id: {
            "display_name": row.slack_display_name or row.name,
            "icon_emoji": row.slack_icon_emoji or None,
            "icon_url": row.slack_icon_url or None,
        }
        for row in bot_rows
    }

    return JSONResponse({"default_bot": default_bot, "channels": channels, "bots": bots})
