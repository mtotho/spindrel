"""Shared Pydantic schemas used across multiple admin sub-modules."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import uuid
from pydantic import BaseModel


class MemoryConfigOut(BaseModel):
    enabled: bool = False
    cross_channel: bool = False
    cross_client: bool = False
    cross_bot: bool = False
    prompt: Optional[str] = None
    similarity_threshold: float = 0.45

    model_config = {"from_attributes": True}


class KnowledgeConfigOut(BaseModel):
    enabled: bool = False

    model_config = {"from_attributes": True}


class SkillConfigOut(BaseModel):
    id: str
    mode: str = "on_demand"

    model_config = {"from_attributes": True}


class BotOut(BaseModel):
    id: str
    name: str
    model: str
    system_prompt: str = ""
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    local_tools: list[str] = []
    mcp_servers: list[str] = []
    client_tools: list[str] = []
    pinned_tools: list[str] = []
    skills: list[SkillConfigOut] = []
    tool_retrieval: bool = True
    tool_discovery: bool = True
    tool_similarity_threshold: Optional[float] = None
    tool_result_config: dict = {}
    persona: bool = False
    persona_content: Optional[str] = None
    persona_from_workspace: bool = False
    workspace_persona_content: Optional[str] = None
    context_compaction: bool = True
    compaction_interval: Optional[int] = None
    compaction_keep_turns: Optional[int] = None
    compaction_model: Optional[str] = None
    audio_input: str = "transcribe"
    memory: MemoryConfigOut = MemoryConfigOut()
    memory_max_inject_chars: Optional[int] = None
    knowledge: KnowledgeConfigOut = KnowledgeConfigOut()
    knowledge_max_inject_chars: Optional[int] = None
    delegate_bots: list[str] = []
    model_provider_id: Optional[str] = None
    fallback_models: list[dict] = []
    integration_config: dict = {}
    workspace: dict = {}
    docker_sandbox_profiles: list[str] = []
    attachment_summarization_enabled: Optional[bool] = None
    attachment_summary_model: Optional[str] = None
    attachment_text_max_chars: Optional[int] = None
    attachment_vision_concurrency: Optional[int] = None
    context_pruning: Optional[bool] = None
    context_pruning_keep_turns: Optional[int] = None
    history_mode: Optional[str] = "summary"
    model_params: dict = {}
    delegation_config: dict = {}
    user_id: Optional[str] = None
    shared_workspace_id: Optional[str] = None
    shared_workspace_role: Optional[str] = None
    api_permissions: Optional[list[str]] = None
    api_docs_mode: Optional[str] = None
    memory_scheme: Optional[str] = None
    memory_hygiene_enabled: Optional[bool] = None
    memory_hygiene_interval_hours: Optional[int] = None
    memory_hygiene_prompt: Optional[str] = None
    memory_hygiene_only_if_active: Optional[bool] = None
    workspace_only: bool = False
    system_prompt_workspace_file: bool = False
    system_prompt_write_protected: bool = False
    source_type: str = "manual"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class BotListOut(BaseModel):
    bots: list[BotOut]
    total: int


class MemoryOut(BaseModel):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    client_id: str
    bot_id: str
    content: str
    message_count: Optional[int] = None
    correlation_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryListOut(BaseModel):
    memories: list[MemoryOut]
