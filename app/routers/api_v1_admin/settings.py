"""Server settings CRUD: /settings."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user

log = logging.getLogger(__name__)

router = APIRouter()


class SettingsUpdateIn(BaseModel):
    settings: dict[str, Any]


class GlobalFallbackModelsIn(BaseModel):
    models: list[dict]


class GlobalModelTiersIn(BaseModel):
    tiers: dict[str, dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def system_status(_auth=Depends(verify_auth_or_user)):
    """Lightweight status endpoint for UI polling (pause banner)."""
    from app.config import settings
    return {
        "paused": settings.SYSTEM_PAUSED,
        "pause_behavior": settings.SYSTEM_PAUSE_BEHAVIOR,
    }


@router.get("/settings")
async def admin_get_settings(
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import get_all_settings
    groups = await get_all_settings()
    return {"groups": groups}


@router.put("/settings")
async def admin_update_settings(
    body: SettingsUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import update_settings
    try:
        applied = await update_settings(body.settings, db)
    except ValueError as exc:
        # ValueError from settings validation is safe to expose (e.g. "Unknown key: ...")
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        log.exception("Settings update failed")
        raise HTTPException(status_code=400, detail="Settings update failed. Check server logs for details.")
    return {"ok": True, "applied": applied}


@router.delete("/settings/{key}")
async def admin_reset_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import reset_setting
    try:
        default_value = await reset_setting(key, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        log.exception("Setting reset failed for key=%s", key)
        raise HTTPException(status_code=400, detail="Setting reset failed. Check server logs for details.")
    return {"ok": True, "default": default_value}


@router.get("/settings/chat-history-deviations")
async def chat_history_deviations(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Return channels whose chat-history settings deviate from global defaults."""
    from sqlalchemy import select
    from app.config import settings
    from app.db.models import Channel

    channels = (await db.execute(select(Channel))).scalars().all()

    _fields = [
        ("history_mode", settings.DEFAULT_HISTORY_MODE),
        ("compaction_interval", settings.COMPACTION_INTERVAL),
        ("compaction_keep_turns", settings.COMPACTION_KEEP_TURNS),
        ("compaction_model", settings.COMPACTION_MODEL),
        ("trigger_heartbeat_before_compaction", settings.TRIGGER_HEARTBEAT_BEFORE_COMPACTION),
        ("section_index_count", settings.SECTION_INDEX_COUNT),
        ("section_index_verbosity", settings.SECTION_INDEX_VERBOSITY),
    ]

    result = []
    for ch in channels:
        deviations = []
        for field_name, global_val in _fields:
            ch_val = getattr(ch, field_name, None)
            if ch_val is not None and ch_val != global_val:
                deviations.append({
                    "field": field_name,
                    "global_value": global_val,
                    "channel_value": ch_val,
                })
        if deviations:
            result.append({
                "channel_id": str(ch.id),
                "channel_name": ch.name,
                "deviations": deviations,
            })

    return {"channels": result}


@router.get("/settings/memory-scheme-defaults")
async def memory_scheme_defaults(_auth: str = Depends(verify_auth_or_user)):
    """Return built-in default prompts for the workspace-files memory scheme."""
    from app.config import DEFAULT_MEMORY_SCHEME_PROMPT, DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT
    return {
        "prompt": DEFAULT_MEMORY_SCHEME_PROMPT,
        "flush_prompt": DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT,
    }


@router.get("/version/check-update")
async def check_update(_auth=Depends(verify_auth_or_user)):
    """Check GitHub for the latest release and compare to current version."""
    from app.config import VERSION, settings

    # Get git hash
    git_hash: str | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "-1", "--format=%h",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            git_hash = stdout.decode().strip() or None
    except Exception:
        pass

    result: dict[str, Any] = {
        "current": VERSION,
        "git_hash": git_hash,
        "latest": None,
        "latest_url": None,
        "published_at": None,
        "update_available": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try releases/latest first
            resp = await client.get(
                f"https://api.github.com/repos/{settings.GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                latest = data.get("tag_name", "").lstrip("v")
                result["latest"] = latest
                result["latest_url"] = data.get("html_url")
                result["published_at"] = data.get("published_at")
                result["update_available"] = latest != VERSION
            else:
                # Fallback to tags
                resp = await client.get(
                    f"https://api.github.com/repos/{settings.GITHUB_REPO}/tags?per_page=1",
                    headers={"Accept": "application/vnd.github+json"},
                )
                if resp.status_code == 200:
                    tags = resp.json()
                    if tags:
                        latest = tags[0]["name"].lstrip("v")
                        result["latest"] = latest
                        result["latest_url"] = f"https://github.com/{settings.GITHUB_REPO}/releases/tag/{tags[0]['name']}"
                        result["update_available"] = latest != VERSION
    except Exception as exc:
        log.warning("Failed to check for updates: %s", exc)
        result["error"] = str(exc)

    return result


@router.get("/global-fallback-models")
async def get_global_fallback_models(_auth: str = Depends(verify_auth_or_user)):
    from app.services.server_config import get_global_fallback_models
    return {"models": get_global_fallback_models()}


@router.put("/global-fallback-models")
async def update_global_fallback_models(
    body: GlobalFallbackModelsIn,
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_config import update_global_fallback_models
    await update_global_fallback_models(body.models)
    return {"ok": True, "models": body.models}


@router.get("/global-model-tiers")
async def get_global_model_tiers(_auth: str = Depends(verify_auth_or_user)):
    from app.services.server_config import get_model_tiers
    return {"tiers": get_model_tiers()}


@router.put("/global-model-tiers")
async def update_global_model_tiers(
    body: GlobalModelTiersIn,
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_config import VALID_TIER_NAMES, update_model_tiers
    invalid = set(body.tiers.keys()) - VALID_TIER_NAMES
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid tier names: {sorted(invalid)}. Valid: {sorted(VALID_TIER_NAMES)}")
    await update_model_tiers(body.tiers)
    return {"ok": True, "tiers": body.tiers}
