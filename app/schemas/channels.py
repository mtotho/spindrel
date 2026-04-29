"""Shared channel response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChannelBotMemberOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    bot_id: str
    bot_name: Optional[str] = None
    config: dict = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrationBindingOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    integration_type: str
    client_id: str
    dispatch_config: Optional[dict] = None
    display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummaryOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    root_path: str
    slug: str

    model_config = {"from_attributes": True}


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str]
    integration: Optional[str]
    active_session_id: Optional[uuid.UUID]
    require_mention: bool
    passive_memory: bool
    private: bool = False
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    member_bots: list[ChannelBotMemberOut] = []
    workspace_id: Optional[uuid.UUID] = None
    resolved_workspace_id: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    project: Optional[ProjectSummaryOut] = None
    config: dict = {}
    category: Optional[str] = None
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelListItemOut(ChannelOut):
    """Extended public channel item with optional heartbeat status."""

    heartbeat_enabled: Optional[bool] = None
    heartbeat_next_run_at: Optional[datetime] = None


class AdminChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    display_name: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    integrations: list[IntegrationBindingOut] = []
    member_bots: list[dict] = []
    heartbeat_enabled: bool = False
    heartbeat_in_quiet_hours: bool = False
    workspace_id: Optional[uuid.UUID] = None
    resolved_workspace_id: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    project: Optional[ProjectSummaryOut] = None
    category: Optional[str] = None
    tags: list[str] = []
    last_message_at: Optional[datetime] = None
    recent_message_count_24h: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelListOut(BaseModel):
    channels: list[AdminChannelOut]
    total: int
    page: int
    page_size: int


class ChannelEntitySummary(BaseModel):
    session_count: int = 0
    message_count: int = 0
    memory_count: int = 0
    task_count: int = 0
    active_session_message_count: int = 0


class ChannelDetailOut(BaseModel):
    channel: AdminChannelOut
    entities: ChannelEntitySummary

    model_config = {"from_attributes": True}


class ChannelSettingsOut(BaseModel):
    """All channel settings - superset of channel output fields."""

    id: uuid.UUID
    name: str
    bot_id: str
    client_id: Optional[str] = None
    integration: Optional[str] = None
    active_session_id: Optional[uuid.UUID] = None
    require_mention: bool = True
    passive_memory: bool = True
    private: bool = False
    protected: bool = False
    user_id: Optional[uuid.UUID] = None
    allow_bot_messages: bool = False
    workspace_rag: bool = True
    thinking_display: str = "append"
    tool_output_display: str = "compact"
    max_iterations: Optional[int] = None
    task_max_run_seconds: Optional[int] = None
    channel_prompt: Optional[str] = None
    channel_prompt_workspace_file_path: Optional[str] = None
    channel_prompt_workspace_id: Optional[uuid.UUID] = None
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_workspace_file_path: Optional[str] = None
    compaction_workspace_id: Optional[uuid.UUID] = None
    history_mode: Optional[str] = None
    compaction_model: Optional[str] = None
    compaction_model_provider_id: Optional[str] = None
    trigger_heartbeat_before_compaction: Optional[bool] = None
    memory_flush_enabled: Optional[bool] = None
    memory_flush_model: Optional[str] = None
    memory_flush_model_provider_id: Optional[str] = None
    memory_flush_prompt: Optional[str] = None
    memory_flush_prompt_template_id: Optional[uuid.UUID] = None
    memory_flush_workspace_file_path: Optional[str] = None
    memory_flush_workspace_id: Optional[uuid.UUID] = None
    section_index_count: Optional[int] = None
    section_index_verbosity: Optional[str] = None
    model_override: Optional[str] = None
    model_provider_id_override: Optional[str] = None
    local_tools_disabled: Optional[list[str]] = None
    mcp_servers_disabled: Optional[list[str]] = None
    client_tools_disabled: Optional[list[str]] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    workspace_schema_template_id: Optional[uuid.UUID] = None
    workspace_schema_content: Optional[str] = None
    index_segments: list[dict] = []
    model_tier_overrides: dict = {}
    index_segment_defaults: Optional[dict] = None
    workspace_id: Optional[uuid.UUID] = None
    resolved_workspace_id: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    project: Optional[ProjectSummaryOut] = None
    project_workspace_id: Optional[str] = None
    project_path: Optional[str] = None
    resolved_project_workspace_id: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = []
    pipeline_mode: str = "auto"
    layout_mode: str = "full"
    chat_mode: str = "default"
    header_backdrop_mode: str = "glass"
    plan_mode_control: str = "auto"
    widget_theme_ref: Optional[str] = None
    widget_agency_mode: str = "propose"
    pinned_widget_context_enabled: bool = True

    model_config = {"from_attributes": True}
