"""Admin Channels page — replaces admin_slack.py.

Shows ALL channels (integration + web/CLI), channel settings inline edit,
session reset, and /api/slack/config backward-compat endpoint.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel, Session
from app.routers.admin_template_filters import install_admin_template_filters
from app.services.channels import reset_channel_session

logger = logging.getLogger(__name__)

router = APIRouter()
api_router = APIRouter()  # Registered at root level for /api/slack/config

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


async def _fetch_slack_channel_names(channel_ids: list[str]) -> dict[str, str]:
    """Call Slack conversations.info for each channel. Returns {channel_id: name}."""
    token = settings.SLACK_BOT_TOKEN
    if not token or not channel_ids:
        return {}
    names: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for cid in channel_ids:
            try:
                r = await client.get(
                    "https://slack.com/api/conversations.info",
                    params={"channel": cid},
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = r.json()
                if data.get("ok"):
                    ch = data.get("channel") or {}
                    name = ch.get("name_normalized") or ch.get("name")
                    if name:
                        names[cid] = name
            except Exception as exc:
                logger.warning("Failed to fetch Slack channel name for %s: %s", cid, exc)
    return names


@router.get("/channels", response_class=HTMLResponse)
async def admin_channels(request: Request):
    async with async_session() as db:
        channels = (await db.execute(
            select(Channel).order_by(Channel.integration.desc().nullsfirst(), Channel.name)
        )).scalars().all()
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

    # Resolve Slack channel names for display
    slack_ids = []
    for ch in channels:
        if ch.integration == "slack" and ch.client_id:
            slack_id = ch.client_id.removeprefix("slack:")
            slack_ids.append(slack_id)
    slack_names = await _fetch_slack_channel_names(slack_ids)

    return templates.TemplateResponse("admin/channels.html", {
        "request": request,
        "channels": channels,
        "all_bots": all_bots,
        "slack_names": slack_names,
        "has_token": bool(settings.SLACK_BOT_TOKEN),
    })


@router.get("/channels/{channel_id}/edit-form", response_class=HTMLResponse)
async def admin_channel_edit_form(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

    return templates.TemplateResponse("admin/channel_edit.html", {
        "request": request,
        "channel": channel,
        "all_bots": all_bots,
    })


@router.post("/channels/{channel_id}", response_class=HTMLResponse)
async def admin_channel_save(
    request: Request,
    channel_id: uuid.UUID,
    bot_id: str = Form(...),
    name: str = Form(""),
    require_mention: str | None = Form(None),
    passive_memory: str | None = Form(None),
    rag_on_all: str | None = Form(None),
):
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        channel.bot_id = bot_id.strip()
        if name.strip():
            channel.name = name.strip()
        channel.require_mention = require_mention == "true"
        channel.passive_memory = passive_memory == "true"
        channel.rag_on_all = rag_on_all == "true"
        channel.updated_at = now
        await db.commit()
        await db.refresh(channel)
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

    # Resolve Slack name if integration
    slack_names: dict[str, str] = {}
    if channel.integration == "slack" and channel.client_id:
        slack_id = channel.client_id.removeprefix("slack:")
        slack_names = await _fetch_slack_channel_names([slack_id])

    tmpl = templates.env.get_template("admin/channel_row.html")
    row_html = tmpl.render(
        request=request,
        channel=channel,
        slack_names=slack_names,
        all_bots=all_bots,
    )
    oob_row = row_html.replace(
        f'id="channel-row-{channel_id}"',
        f'id="channel-row-{channel_id}" hx-swap-oob="outerHTML:#channel-row-{channel_id}"',
        1,
    )
    return HTMLResponse(oob_row)


@router.post("/channels/{channel_id}/reset", response_class=HTMLResponse)
async def admin_channel_reset(request: Request, channel_id: uuid.UUID):
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        new_session_id = await reset_channel_session(db, channel)

    return HTMLResponse(
        f'<span class="text-xs text-green-400">Reset! New session: {str(new_session_id)[:8]}...</span>'
    )


# ---------------------------------------------------------------------------
# API endpoint for Slack integration (registered at /api/slack/config)
# Backward compat — reads from Channel table now.
# ---------------------------------------------------------------------------

@api_router.get("/slack/config")
async def api_slack_config(request: Request):
    """Returns Slack channel->bot mapping for the Slack integration service."""
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    expected = getattr(settings, "API_KEY", None)
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "slack")
        )).scalars().all()
        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {}
    for row in channel_rows:
        if not row.client_id:
            continue
        slack_id = row.client_id.removeprefix("slack:")
        channels[slack_id] = {
            "bot_id": row.bot_id,
            "require_mention": row.require_mention,
            "passive_memory": row.passive_memory,
            "rag_on_all": row.rag_on_all,
        }

    bots = {
        row.id: {
            "display_name": row.display_name or row.name,
            "icon_emoji": (row.integration_config or {}).get("slack", {}).get("icon_emoji") or None,
            "icon_url": row.avatar_url or None,
        }
        for row in bot_rows
    }

    return JSONResponse({"default_bot": settings.SLACK_DEFAULT_BOT, "channels": channels, "bots": bots})
