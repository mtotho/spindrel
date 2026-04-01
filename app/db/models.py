import uuid
from datetime import datetime, time, timezone
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, Time, UniqueConstraint, text

from app.config import settings
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    integration: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    require_mention: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    passive_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    context_compaction: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    compaction_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compaction_keep_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compaction_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_knowledge_compaction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    compaction_workspace_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    elevation_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elevation_threshold: Mapped[float | None] = mapped_column(nullable=True)
    elevated_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider_id_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    allow_bot_messages: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    workspace_rag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    thinking_display: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'append'"))
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_max_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_max_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_types_allowed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    # Tool / skill overrides (null = inherit from bot)
    local_tools_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    local_tools_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mcp_servers_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mcp_servers_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    client_tools_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    client_tools_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pinned_tools_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skills_override: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skills_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skills_extra: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    carapaces_extra: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    carapaces_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model_tier_overrides: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    workspace_skills_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    workspace_base_prompt_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    channel_workspace_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    index_segments: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    history_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_heartbeat_before_compaction: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Dedicated memory flush before compaction (replaces heartbeat trigger)
    memory_flush_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    memory_flush_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_flush_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_flush_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_flush_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    memory_flush_workspace_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_flush_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_prompt_workspace_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_prompt_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shared_workspaces.id", ondelete="SET NULL"), nullable=True,
    )
    section_index_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_index_verbosity: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_pruning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    context_pruning_keep_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workspace_schema_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    workspace_schema_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="channel",
        foreign_keys="Session.channel_id",
    )
    integrations: Mapped[list["ChannelIntegration"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    heartbeat: Mapped[Optional["ChannelHeartbeat"]] = relationship(
        "ChannelHeartbeat", uselist=False, viewonly=True,
    )
    members: Mapped[list["ChannelMember"]] = relationship(
        cascade="all, delete-orphan",
    )


class ChannelMember(Base):
    __tablename__ = "channel_members"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_channel_members_user_id", "user_id"),
    )


class ConversationSection(Base):
    __tablename__ = "conversation_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    embedding: Mapped[list | None] = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_viewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_conversation_sections_channel_seq", "channel_id", "sequence"),
        Index("ix_conversation_sections_session_id", "session_id"),
    )


class CompactionLog(Base):
    __tablename__ = "compaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True,
    )
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    history_mode: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    forced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    memory_flush: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    messages_archived: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation_sections.id", ondelete="SET NULL"), nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    flush_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_compaction_logs_channel_created", "channel_id", created_at.desc()),
    )


class ChannelIntegration(Base):
    __tablename__ = "channel_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False,
    )
    integration_type: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    activation_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    channel: Mapped["Channel"] = relationship(back_populates="integrations")

    __table_args__ = (
        UniqueConstraint("channel_id", "client_id", name="uq_channel_integrations_channel_client"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )
    last_active: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    root_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    channel: Mapped["Channel | None"] = relationship(
        back_populates="sessions",
        foreign_keys=[channel_id],
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )

    session: Mapped["Session"] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # image, file, text, audio, video
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    posted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_integration: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'web'"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    described_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )

    message: Mapped["Message"] = relationship(back_populates="attachments")

    __table_args__ = (
        Index("ix_attachments_message_type", "message_id", "type"),
        Index("ix_attachments_channel_type", "channel_id", "type"),
        Index(
            "ix_attachments_unsummarized",
            "type", "described_at",
            postgresql_where=text("described_at IS NULL AND type IN ('image', 'text', 'file')"),
        ),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_documents_source", "source"),
    )


class IntegrationDocument(Base):
    __tablename__ = "integration_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    integration_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    message_range_start: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    message_range_end: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    message_count: Mapped[int | None] = mapped_column(nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class BotPersona(Base):
    __tablename__ = "bot_personas"

    bot_id: Mapped[str] = mapped_column(primary_key=True)
    persona_layer: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class ToolEmbedding(Base):
    __tablename__ = "tool_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tool_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    server_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_integration: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_: Mapped[dict] = mapped_column("schema", JSONB, nullable=False)
    embed_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    indexed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_tool_embeddings_server_name", "server_name"),
    )


class BotKnowledge(Base):
    __tablename__ = "bot_knowledge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)        # "project_xyz", "home_network"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)    # NULL = cross-bot
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True) # NULL = cross-client
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_bot: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_threshold: Mapped[float | None] = mapped_column(nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'tool'"))
    editable_from_tool: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class KnowledgePin(Base):
    __tablename__ = "knowledge_pins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    knowledge_name: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)    # NULL = any bot
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True) # NULL = any client
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_type: Mapped[str] = mapped_column(Text, nullable=False)  # "local" | "mcp" | "client"
    server_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    iteration: Mapped[int | None] = mapped_column(nullable=True)
    arguments: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    count: Mapped[int | None] = mapped_column(nullable=True)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class UsageLimit(Base):
    __tablename__ = "usage_limits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)  # "model" or "bot"
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)  # model name or bot_id
    period: Mapped[str] = mapped_column(Text, nullable=False)  # "daily" or "monthly"
    limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class KnowledgeAccess(Base):
    __tablename__ = "knowledge_access"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bot_knowledge.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'channel' | 'bot' | 'global'
    scope_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # channel UUID or bot_id or NULL
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'rag'"))  # 'rag' | 'pinned' | 'tag_only'
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    knowledge: Mapped["BotKnowledge"] = relationship("BotKnowledge", backref="access_entries")


class KnowledgeWrite(Base):
    __tablename__ = "knowledge_writes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bot_knowledge.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_name: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class FilesystemChunk(Base):
    __tablename__ = "filesystem_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)    # NULL = cross-bot
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True) # NULL = cross-client
    root: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)  # relative to root
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int | None] = mapped_column(nullable=True)
    end_line: Mapped[int | None] = mapped_column(nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata_", JSONB, server_default=text("'{}'::jsonb")
    )
    tsv = mapped_column("tsv", TSVECTOR().with_variant(Text(), "sqlite"), nullable=True)  # populated via raw SQL in indexer
    indexed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class SandboxProfile(Base):
    __tablename__ = "sandbox_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str] = mapped_column(Text, nullable=False)
    scope_mode: Mapped[str] = mapped_column(Text, nullable=False, default="session")
    network_mode: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    read_only_root: Mapped[bool] = mapped_column(nullable=False, default=False)
    create_options: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    mount_specs: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    env: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    labels: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    port_mappings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    idle_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    instances: Mapped[list["SandboxInstance"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    bot_access: Mapped[list["SandboxBotAccess"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class SandboxBotAccess(Base):
    __tablename__ = "sandbox_bot_access"

    bot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_profiles.id", ondelete="CASCADE"), primary_key=True
    )

    profile: Mapped["SandboxProfile"] = relationship(back_populates="bot_access")


class SandboxInstance(Base):
    __tablename__ = "sandbox_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_profiles.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    container_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    container_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    created_by_bot: Mapped[str] = mapped_column(Text, nullable=False)
    locked_operations: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    port_mappings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    last_inspected_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    profile: Mapped["SandboxProfile"] = relationship(back_populates="instances")


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    billing_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'usage'"))
    plan_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    models: Mapped[list["ProviderModel"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class ProviderModel(Base):
    __tablename__ = "provider_models"
    __table_args__ = (
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        Text, ForeignKey("provider_configs.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_cost_per_1m: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_cost_per_1m: Mapped[str | None] = mapped_column(Text, nullable=True)
    no_system_messages: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    provider: Mapped["ProviderConfig"] = relationship(back_populates="models")


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mcp_servers: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    client_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    pinned_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    skills: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    docker_sandbox_profiles: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tool_retrieval: Mapped[bool] = mapped_column(nullable=False, default=True)
    tool_similarity_threshold: Mapped[float | None] = mapped_column(nullable=True)
    persona: Mapped[bool] = mapped_column(nullable=False, default=False)
    base_prompt: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), default=True)
    context_compaction: Mapped[bool] = mapped_column(nullable=False, default=True)
    compaction_interval: Mapped[int | None] = mapped_column(nullable=True)
    compaction_keep_turns: Mapped[int | None] = mapped_column(nullable=True)
    compaction_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_knowledge_compaction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    audio_input: Mapped[str] = mapped_column(Text, nullable=False, default="transcribe")
    memory_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    knowledge_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    filesystem_indexes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    host_exec_config: Mapped[dict] = mapped_column(JSONB, server_default=text('\'{"enabled": false}\'::jsonb'))
    filesystem_access: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    integration_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tool_result_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    knowledge_max_inject_chars: Mapped[int | None] = mapped_column(nullable=True)
    memory_max_inject_chars: Mapped[int | None] = mapped_column(nullable=True)
    delegation_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    model_params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    bot_sandbox: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    workspace: Mapped[dict] = mapped_column(JSONB, server_default=text("'{\"enabled\": false}'::jsonb"))
    elevation_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elevation_threshold: Mapped[float | None] = mapped_column(nullable=True)
    elevated_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_summarization_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attachment_summary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_text_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_vision_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_provider_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    fallback_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    api_docs_mode: Mapped[str | None] = mapped_column(Text, nullable=True)  # "pinned"|"rag"|"on_demand"|null
    memory_scheme: Mapped[str | None] = mapped_column(Text, nullable=True)  # "workspace-files"|null
    system_prompt_workspace_file: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    system_prompt_write_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    history_mode: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'file'"))
    context_pruning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    context_pruning_keep_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carapaces: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    workspace_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Carapace(Base):
    __tablename__ = "carapaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    local_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mcp_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    pinned_tools: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    system_prompt_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    includes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    delegates: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tags: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    requires: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class SharedWorkspace(Base):
    __tablename__ = "shared_workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'python:3.12-slim'"))
    network: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    env: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    ports: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mounts: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    cpus: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_limit: Mapped[str | None] = mapped_column(Text, nullable=True)
    docker_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_only_root: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    container_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    container_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'stopped'"))
    image_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    startup_script: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'/workspace/startup.sh'"))
    workspace_skills_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    workspace_base_prompt_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    indexing_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    editor_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    write_protected_paths: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    skills: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    bots: Mapped[list["SharedWorkspaceBot"]] = relationship("SharedWorkspaceBot", back_populates="workspace", cascade="all, delete-orphan")


class SharedWorkspaceBot(Base):
    __tablename__ = "shared_workspace_bots"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bot_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("bots.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'member'"))
    cwd_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    write_access: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    workspace: Mapped["SharedWorkspace"] = relationship("SharedWorkspace", back_populates="bots")


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))



class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ChannelHeartbeat(Base):
    __tablename__ = "channel_heartbeats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    model: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    dispatch_results: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    trigger_response: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    quiet_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    workspace_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatch_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'always'"))
    previous_result_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repetition_detection: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    channel: Mapped["Channel"] = relationship("Channel")


class HeartbeatRun(Base):
    __tablename__ = "heartbeat_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    heartbeat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_heartbeats.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    repetition_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class IntegrationChannelConfig(Base):
    __tablename__ = "integration_channel_configs"

    client_id: Mapped[str] = mapped_column(Text, primary_key=True)
    integration: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'slack'"))
    require_mention: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    passive_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dispatch_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    callback_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    execution_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recurrence: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. "+1h", "+1d"
    task_type: Mapped[str] = mapped_column(Text, nullable=False, default="agent", server_default=text("'agent'"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    workspace_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    max_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_tasks_status_run_at", "status", "run_at"),
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")

    items: Mapped[list["PlanItem"]] = relationship(
        "PlanItem", back_populates="plan", cascade="all, delete-orphan", order_by="PlanItem.position"
    )


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


class ModelElevationLog(Base):
    __tablename__ = "model_elevation_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    base_model: Mapped[str] = mapped_column(Text, nullable=False)
    model_chosen: Mapped[str] = mapped_column(Text, nullable=False)
    was_elevated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    classifier_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    elevation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_fired: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    signal_scores: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    integration_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    auth_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'local'"))
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    user: Mapped["User"] = relationship("User")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class SecretValue(Base):
    __tablename__ = "secret_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # encrypted with Fernet
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    plan: Mapped["Plan"] = relationship("Plan", back_populates="items")


class ServerSetting(Base):
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class IntegrationSetting(Base):
    __tablename__ = "integration_settings"

    integration_id: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ServerConfig(Base):
    __tablename__ = "server_config"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("'default'"))
    global_fallback_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    model_tiers: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ModelFallbackEvent(Base):
    __tablename__ = "model_fallback_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_model: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True,
    )
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_model_fallback_events_model_created", "model", "created_at"),
        Index("ix_model_fallback_events_created", "created_at"),
    )


class ToolPolicyRule(Base):
    __tablename__ = "tool_policy_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # "allow" | "deny" | "require_approval"
    conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    approval_timeout: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("300"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ToolApproval(Base):
    __tablename__ = "tool_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_type: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    policy_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_policy_rules.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    dispatch_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatch_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("300"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    secrets: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    defaults: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    steps: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    triggers: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tags: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    session_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'isolated'"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str] = mapped_column(Text, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_states: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    dispatch_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
    )
