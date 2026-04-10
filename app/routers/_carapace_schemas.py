"""Shared Pydantic schemas for carapace endpoints (admin + bot-facing)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CarapaceOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    local_tools: list[str] = []
    mcp_tools: list[str] = []
    pinned_tools: list[str] = []
    system_prompt_fragment: Optional[str] = None
    includes: list[str] = []
    delegates: list = []
    tags: list[str] = []
    source_type: str = "manual"
    source_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CarapaceCreateIn(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    local_tools: list[str] = []
    mcp_tools: list[str] = []
    pinned_tools: list[str] = []
    system_prompt_fragment: Optional[str] = None
    includes: list[str] = []
    delegates: list = []
    tags: list[str] = []


class CarapaceUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    local_tools: Optional[list[str]] = None
    mcp_tools: Optional[list[str]] = None
    pinned_tools: Optional[list[str]] = None
    system_prompt_fragment: Optional[str] = None
    includes: Optional[list[str]] = None
    delegates: Optional[list] = None
    tags: Optional[list[str]] = None


async def try_reload() -> None:
    """Best-effort reload of the in-memory carapace registry."""
    try:
        from app.agent.carapaces import reload_carapaces
        await reload_carapaces()
    except Exception:
        pass
