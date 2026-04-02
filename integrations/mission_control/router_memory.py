"""Mission Control — Memory + reference file endpoints."""
from __future__ import annotations

import asyncio
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user
from integrations.mission_control.helpers import get_bot, get_mc_prefs, get_user, tracked_channels
from integrations.mission_control.schemas import MemoryResponse

router = APIRouter()


@router.get("/memory", response_model=MemoryResponse)
async def memory(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """MEMORY.md + reference files from tracked bots."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    bot_ids = list({ch.bot_id for ch in channels})
    if prefs.get("tracked_bot_ids"):
        tracked = set(prefs["tracked_bot_ids"])
        bot_ids = [bid for bid in bot_ids if bid in tracked]

    sections: list[dict] = []

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

        def _read_memory(mem_root=mem_root, bot=bot):
            memory_content = None
            mem_md = os.path.join(mem_root, "MEMORY.md")
            if os.path.isfile(mem_md):
                try:
                    with open(mem_md) as f:
                        memory_content = f.read()
                except Exception:
                    pass

            ref_dir = os.path.join(mem_root, "reference")
            ref_files: list[str] = []
            if os.path.isdir(ref_dir):
                ref_files = sorted(
                    e.name for e in os.scandir(ref_dir) if e.is_file()
                )

            return {
                "bot_id": bot.id,
                "bot_name": bot.name,
                "memory_content": memory_content,
                "reference_files": ref_files,
            }

        sections.append(await asyncio.to_thread(_read_memory))

    return {"sections": sections}


@router.get("/memory/{bot_id}/reference/{filename}")
async def read_reference_file(
    bot_id: str,
    filename: str,
    auth=Depends(verify_auth_or_user),
):
    """Read a specific reference file from a bot's memory/reference/ directory."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")

    try:
        bot = get_bot(bot_id)
    except Exception:
        raise HTTPException(404, f"Bot '{bot_id}' not found")

    if bot.memory_scheme != "workspace-files":
        raise HTTPException(400, f"Bot '{bot_id}' does not use workspace-files memory scheme")

    from app.services.memory_scheme import get_memory_root

    try:
        mem_root = get_memory_root(bot)
    except Exception:
        raise HTTPException(500, "Could not resolve memory root")

    ref_path = os.path.join(mem_root, "reference", filename)

    real_ref_dir = os.path.realpath(os.path.join(mem_root, "reference"))
    real_path = os.path.realpath(ref_path)
    if not real_path.startswith(real_ref_dir + os.sep) and real_path != real_ref_dir:
        raise HTTPException(400, "Invalid filename")

    if not os.path.isfile(ref_path):
        raise HTTPException(404, "Reference file not found")

    def _read():
        with open(ref_path) as f:
            return f.read()

    try:
        content = await asyncio.to_thread(_read)
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not a text file")
    return {"content": content}
