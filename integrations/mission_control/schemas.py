"""Pydantic schemas for Mission Control API responses."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class KanbanCard(BaseModel):
    title: str
    meta: dict
    description: str
    channel_id: str
    channel_name: str


class KanbanColumn(BaseModel):
    name: str
    cards: list[KanbanCard]


class KanbanMoveRequest(BaseModel):
    card_id: str
    from_column: str
    to_column: str
    channel_id: str  # UUID as string for JSON input


class KanbanCreateRequest(BaseModel):
    channel_id: str
    title: str
    column: str = "Backlog"
    priority: str = "medium"
    assigned: str = ""
    tags: str = ""
    due: str = ""
    description: str = ""


class KanbanUpdateRequest(BaseModel):
    card_id: str
    channel_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assigned: Optional[str] = None
    due: Optional[str] = None
    tags: Optional[str] = None


class MCPrefsUpdate(BaseModel):
    tracked_channel_ids: Optional[list[str]] = None
    tracked_bot_ids: Optional[list[str]] = None
    kanban_filters: Optional[dict] = None
    layout_prefs: Optional[dict] = None


class ChannelOverview(BaseModel):
    id: str
    name: str
    bot_id: str
    bot_name: str | None = None
    model: str | None = None
    workspace_enabled: bool
    task_count: int = 0
    template_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_member: bool = False


class BotOverview(BaseModel):
    id: str
    name: str
    model: str
    channel_count: int = 0
    memory_scheme: str | None = None


class JournalEntry(BaseModel):
    date: str
    bot_id: str
    bot_name: str
    content: str


class JournalResponse(BaseModel):
    entries: list[JournalEntry]


class MemoryBotSection(BaseModel):
    bot_id: str
    bot_name: str
    memory_content: str | None = None
    reference_files: list[str] = []


class MemoryResponse(BaseModel):
    sections: list[MemoryBotSection]


class TimelineEvent(BaseModel):
    date: str
    time: str
    event: str
    channel_id: str
    channel_name: str


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


class MCPlanStep(BaseModel):
    position: int
    status: str
    content: str


class MCPlan(BaseModel):
    id: str
    title: str
    status: str
    meta: dict[str, str]
    steps: list[MCPlanStep]
    notes: str
    channel_id: str
    channel_name: str


class MCPlansResponse(BaseModel):
    plans: list[MCPlan]


class FeatureReadiness(BaseModel):
    ready: bool
    detail: str
    count: int = 0
    total: int = 0
    issues: list[str] = []


class ReadinessResponse(BaseModel):
    dashboard: FeatureReadiness
    kanban: FeatureReadiness
    journal: FeatureReadiness
    memory: FeatureReadiness
    timeline: FeatureReadiness
    plans: FeatureReadiness
