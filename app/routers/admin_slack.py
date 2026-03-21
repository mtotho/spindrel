"""Admin Slack channel config routes + /api/slack/config endpoint."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.engine import async_session
from app.db.models import Bot as BotRow, IntegrationChannelConfig, Session
from app.routers.admin_template_filters import install_admin_template_filters
from app.services.sessions import derive_integration_session_id

logger = logging.getLogger(__name__)

router = APIRouter()
api_router = APIRouter()  # Registered at root level for /api/slack/config

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


async def _fetch_channel_names(channel_ids: list[str]) -> dict[str, str]:
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
                else:
                    logger.warning(
                        "Slack conversations.info failed for %s: %s (add channels:read or groups:read scope)",
                        cid, data.get("error"),
                    )
            except Exception as exc:
                logger.warning("Failed to fetch Slack channel name for %s: %s", cid, exc)
    return names


@router.get("/slack", response_class=HTMLResponse)
async def admin_slack(request: Request):
    async with async_session() as db:
        channel_configs = (await db.execute(
            select(IntegrationChannelConfig)
            .where(IntegrationChannelConfig.integration == "slack")
            .order_by(IntegrationChannelConfig.client_id)
        )).scalars().all()
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()

        # Distinct channel IDs seen in sessions (client_id = "slack:{channel_id}")
        raw_client_ids = (await db.execute(
            select(Session.client_id)
            .where(Session.client_id.like("slack:%"))
            .distinct()
            .order_by(Session.client_id)
        )).scalars().all()

    seen_channels = [cid[len("slack:"):] for cid in raw_client_ids if cid]

    # Merge seen + configured channels (configured may include ones not yet in sessions)
    configured_ids = {c.client_id[len("slack:"):] for c in channel_configs}
    all_channel_ids = list(dict.fromkeys(seen_channels + list(configured_ids)))

    channel_names = await _fetch_channel_names(all_channel_ids)
    config_map = {c.client_id[len("slack:"):]: c for c in channel_configs}

    # Compute derived session_id per channel
    session_ids = {
        cid: str(derive_integration_session_id(f"slack:{cid}"))
        for cid in all_channel_ids
    }

    return templates.TemplateResponse("admin/slack.html", {
        "request": request,
        "channel_configs": channel_configs,
        "all_bots": all_bots,
        "default_bot": settings.SLACK_DEFAULT_BOT,
        "seen_channels": seen_channels,
        "all_channel_ids": all_channel_ids,
        "config_map": config_map,
        "channel_names": channel_names,
        "session_ids": session_ids,
        "has_token": bool(settings.SLACK_BOT_TOKEN),
    })


@router.get("/slack/channels/{channel_id}/edit-form", response_class=HTMLResponse)
async def admin_slack_edit_form(request: Request, channel_id: str):
    async with async_session() as db:
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()
        client_id = f"slack:{channel_id}"
        cfg = (await db.execute(
            select(IntegrationChannelConfig)
            .where(IntegrationChannelConfig.client_id == client_id)
        )).scalar_one_or_none()

    channel_names = await _fetch_channel_names([channel_id])
    channel_name = channel_names.get(channel_id)

    return templates.TemplateResponse("admin/slack_channel_edit.html", {
        "request": request,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "cfg": cfg,
        "all_bots": all_bots,
    })


@router.post("/slack/channels/{channel_id}", response_class=HTMLResponse)
async def admin_slack_channel_save(
    request: Request,
    channel_id: str,
    bot_id: str = Form(...),
    description: str = Form(""),
    require_mention: str | None = Form(None),
    passive_memory: str | None = Form(None),
    rag_on_all: str | None = Form(None),
):
    channel_id = channel_id.strip()
    bot_id = bot_id.strip()
    if not channel_id or not bot_id:
        return HTMLResponse(
            "<div class='text-red-400 p-3 text-sm'>channel_id and bot_id are required.</div>",
            status_code=422,
        )

    client_id = f"slack:{channel_id}"
    require_mention_bool = require_mention == "true"
    passive_memory_bool = passive_memory == "true"
    rag_on_all_bool = rag_on_all == "true"
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(IntegrationChannelConfig)
        .values(
            client_id=client_id,
            integration="slack",
            bot_id=bot_id,
            require_mention=require_mention_bool,
            passive_memory=passive_memory_bool,
            rag_on_all=rag_on_all_bool,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["client_id"],
            set_={
                "bot_id": bot_id,
                "require_mention": require_mention_bool,
                "passive_memory": passive_memory_bool,
                "rag_on_all": rag_on_all_bool,
                "updated_at": now,
            },
        )
    )
    async with async_session() as db:
        await db.execute(stmt)
        await db.commit()
        all_bots = (await db.execute(select(BotRow).order_by(BotRow.name))).scalars().all()
        cfg = (await db.execute(
            select(IntegrationChannelConfig)
            .where(IntegrationChannelConfig.client_id == client_id)
        )).scalar_one_or_none()

    channel_names = await _fetch_channel_names([channel_id])
    session_id = str(derive_integration_session_id(client_id))

    # Return updated channel row + clear edit slot (OOB)
    tmpl = templates.env.get_template("admin/slack_channel_row.html")
    row_html = tmpl.render(
        request=request,
        channel_id=channel_id,
        cfg=cfg,
        channel_name=channel_names.get(channel_id),
        default_bot=settings.SLACK_DEFAULT_BOT,
        session_id=session_id,
        all_bots=all_bots,
    )
    oob_row = row_html.replace(
        f'id="slack-row-{channel_id}"',
        f'id="slack-row-{channel_id}" hx-swap-oob="outerHTML:#slack-row-{channel_id}"',
        1,
    )
    return HTMLResponse(oob_row)


@router.delete("/slack/channels/{channel_id}", response_class=HTMLResponse)
async def admin_slack_channel_delete(channel_id: str):
    client_id = f"slack:{channel_id}"
    async with async_session() as db:
        row = await db.get(IntegrationChannelConfig, client_id)
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
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    expected = getattr(settings, "API_KEY", None)
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        channel_rows = (await db.execute(
            select(IntegrationChannelConfig)
            .where(IntegrationChannelConfig.integration == "slack")
        )).scalars().all()
        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {
        row.client_id[len("slack:"):]: {
            "bot_id": row.bot_id,
            "require_mention": row.require_mention,
            "passive_memory": row.passive_memory,
            "rag_on_all": row.rag_on_all,
        }
        for row in channel_rows
    }
    bots = {
        row.id: {
            "display_name": row.slack_display_name or row.name,
            "icon_emoji": row.slack_icon_emoji or None,
            "icon_url": row.slack_icon_url or None,
        }
        for row in bot_rows
    }

    return JSONResponse({"default_bot": settings.SLACK_DEFAULT_BOT, "channels": channels, "bots": bots})
