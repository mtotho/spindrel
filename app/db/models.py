import uuid
from datetime import datetime, time, timezone
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, Time, UniqueConstraint, text

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
    compaction_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    model_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider_id_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    allow_bot_messages: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    workspace_rag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    thinking_display: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'append'"))
    tool_output_display: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'compact'"))
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_max_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_max_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_types_allowed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    # Tool / skill channel restrictions (null = inherit from bot)
    local_tools_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mcp_servers_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    client_tools_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    carapaces_extra: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    carapaces_disabled: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model_tier_overrides: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    workspace_base_prompt_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    channel_workspace_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
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
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

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
    bot_members: Mapped[list["ChannelBotMember"]] = relationship(
        back_populates="channel",
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


class ChannelBotMember(Base):
    __tablename__ = "channel_bot_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False,
    )
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    channel: Mapped["Channel"] = relationship(back_populates="bot_members")

    __table_args__ = (
        UniqueConstraint("channel_id", "bot_id", name="uq_channel_bot_members_channel_bot"),
        Index("ix_channel_bot_members_channel_id", "channel_id"),
        Index("ix_channel_bot_members_bot_id", "bot_id"),
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
    session_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'channel'"),
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Per-integration thread linkage — keyed by integration_id, value is
    # an integration-specific ref dict (e.g. Slack:
    # ``{"channel": "C123", "thread_ts": "1700000000.1"}``). NULL for the
    # common case (channel sessions, ephemerals, pre-Phase-7 thread rows).
    # Written once at thread spawn or on first inbound Slack reply; never
    # mutated afterward. The dispatch-resolution layer merges this into
    # the typed DispatchTarget so outbound posts land in the right thread.
    integration_thread_refs: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    # Scratch-session pointer (migration 232). parent_channel_id links an
    # ephemeral session back to the channel whose "Scratch chat" header
    # button opened it; owner_user_id records which user owns it so two
    # users sharing a channel each get their own scratch thread.
    # is_current flags the active scratch for that (channel, user) pair —
    # reset flips old rows to false and marks a fresh one true while
    # keeping history queryable.
    parent_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    channel: Mapped["Channel | None"] = relationship(
        back_populates="sessions",
        foreign_keys=[channel_id],
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        foreign_keys="Message.session_id",
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

    session: Mapped["Session"] = relationship(
        back_populates="messages",
        foreign_keys="Message.session_id",
    )
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
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
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
    tsv = mapped_column("tsv", TSVECTOR().with_variant(Text(), "sqlite"), nullable=True)
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
    # Lifecycle: 'running' on dispatch entry, 'awaiting_approval' if gated,
    # then 'done' / 'error' / 'denied' / 'expired' on resolution.
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_tool_calls_correlation_id", "correlation_id"),
        Index("ix_tool_calls_bot_id_created_at", "bot_id", "created_at"),
        Index("ix_tool_calls_bot_id_status", "bot_id", "status"),
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

    __table_args__ = (
        Index("ix_trace_events_correlation_id", "correlation_id"),
        Index("ix_trace_events_bot_created", "bot_id", "created_at"),
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

    __table_args__ = (
        Index("ix_filesystem_chunks_bot_root", "bot_id", "root"),
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
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    prompt_style: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'markdown'"))
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
    docker_stacks_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tool_retrieval: Mapped[bool] = mapped_column(nullable=False, default=True)
    tool_discovery: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), default=True)
    tool_similarity_threshold: Mapped[float | None] = mapped_column(nullable=True)
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_script_tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persona: Mapped[bool] = mapped_column(nullable=False, default=False)
    base_prompt: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"), default=True)
    context_compaction: Mapped[bool] = mapped_column(nullable=False, default=True)
    compaction_interval: Mapped[int | None] = mapped_column(nullable=True)
    compaction_keep_turns: Mapped[int | None] = mapped_column(nullable=True)
    compaction_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_knowledge_compaction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    audio_input: Mapped[str] = mapped_column(Text, nullable=False, default="transcribe")
    memory_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    filesystem_indexes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    host_exec_config: Mapped[dict] = mapped_column(JSONB, server_default=text('\'{"enabled": false}\'::jsonb'))
    filesystem_access: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    integration_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tool_result_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    memory_max_inject_chars: Mapped[int | None] = mapped_column(nullable=True)
    delegation_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    model_params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    bot_sandbox: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    workspace: Mapped[dict] = mapped_column(JSONB, server_default=text("'{\"enabled\": false}'::jsonb"))
    attachment_summarization_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attachment_summary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_summary_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    memory_scheme: Mapped[str | None] = mapped_column(Text, nullable=True)  # "workspace-files"|null
    # Memory hygiene (periodic curation)
    memory_hygiene_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    memory_hygiene_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_hygiene_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_hygiene_only_if_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    memory_hygiene_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_hygiene_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_hygiene_target_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_hygiene_extra_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_hygiene_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    next_hygiene_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # Skill review (periodic skill curation — separate from memory maintenance)
    skill_review_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    skill_review_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_review_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_review_only_if_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    skill_review_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_review_model_provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_review_target_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_review_extra_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_skill_review_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    next_skill_review_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    system_prompt_workspace_file: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    system_prompt_write_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    history_mode: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'file'"))
    context_pruning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    carapaces: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))  # "system"|"file"|"manual"
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class BotGrant(Base):
    """User-level access grant for a bot (mirrors `ChannelMember` shape).

    Admin bypasses; bot owner (`bots.user_id == user.id`) bypasses; otherwise a
    row here is what authorizes a user to use a bot via widgets and the
    channel bot picker. Role is kept as a column for forward-compat (today the
    only accepted value is `'view'`).
    """

    __tablename__ = "bot_grants"

    bot_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("bots.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'view'"), default="view")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_bot_grants_user_id", "user_id"),
        Index("ix_bot_grants_bot_id", "bot_id"),
    )


class Carapace(Base):
    __tablename__ = "carapaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class CapabilityEmbedding(Base):
    __tablename__ = "capability_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    carapace_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    embed_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    indexed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )


class SharedWorkspace(Base):
    __tablename__ = "shared_workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    env: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    workspace_base_prompt_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    indexing_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    write_protected_paths: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
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
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggers: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    scripts: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    last_surfaced_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    surface_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    archived_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)



class BotSkillEnrollment(Base):
    """Per-bot persistent skill working set.

    Each row is a (bot, skill) enrollment. Replaces per-turn ephemeral auto-enrollment.
    See Phase 3 Working Set Design.
    """
    __tablename__ = "bot_skill_enrollment"

    bot_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("bots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # source: 'starter' | 'fetched' | 'manual' | 'migration' | 'authored'
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    enrolled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    fetch_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    auto_inject_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_auto_injected_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class BotToolEnrollment(Base):
    """Per-bot persistent tool working set.

    Mirrors BotSkillEnrollment for tools. Each row is a (bot, tool_name)
    enrollment that persists across turns and sessions.
    """
    __tablename__ = "bot_tool_enrollment"

    bot_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("bots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_name: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    # source: 'starter' | 'fetched' | 'manual'
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    enrolled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


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
    group: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_heartbeat: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    workflow_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_session_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_tool_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

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
    workflow_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_session_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    step_states: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"))
    run_isolation: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'inline'"),
    )
    run_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_tasks_status_run_at", "status", "run_at"),
        Index("ix_tasks_correlation_id", "correlation_id"),
    )


class ChannelPipelineSubscription(Base):
    """Per-channel subscription to a pipeline (Task) definition.

    Decouples "what the pipeline is" (Task, source=system|user) from
    "where it runs" (channel) and "on what cadence" (cron). Replaces the
    implicit global visibility of source=system tasks in channel launchpads.
    """

    __tablename__ = "channel_pipeline_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"), default=uuid.uuid4,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    featured_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    schedule: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "task_id", name="uq_channel_pipeline_subscription"),
        Index("ix_channel_pipeline_subscriptions_channel", "channel_id"),
    )


class Outbox(Base):
    """Durable channel-event outbox.

    Phase D of the Integration Delivery refactor. One row per
    ``(channel, event seq, target integration)`` tuple. Inserted in the
    same DB transaction as the originating message rows by
    ``app/services/outbox.py:enqueue`` so a crash between commit and
    renderer-ack cannot lose deliveries. The drainer
    (``app/services/outbox_drainer.py``) pulls rows via
    ``SELECT ... FOR UPDATE SKIP LOCKED``, routes them through
    ``renderer_registry``, and updates the row state.

    Mirrors ``migrations/versions/188_add_outbox.py``.
    """

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    target_integration_id: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    delivery_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    defer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_letter_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_outbox_channel_state", "channel_id", "delivery_state"),
        # NB: the partial index ix_outbox_pending is in the migration only;
        # SQLAlchemy doesn't carry the `postgresql_where` predicate cleanly
        # across dialects so the migration owns it.
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


class ServerSetting(Base):
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class WidgetTheme(Base):
    __tablename__ = "widget_themes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    forked_from_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    light_tokens: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    dark_tokens: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    custom_css: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
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
    # Display payload captured at approval-create (e.g. `_capability` for the
    # capability-approval card). Distinct from `dispatch_metadata`, which is
    # routing config for the dispatcher.
    approval_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Links to the tool_calls row that's currently 'awaiting_approval' so the
    # decide endpoint can flip its status without a fragile lookup.
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="SET NULL"), nullable=True
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("300"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class IntegrationManifest(Base):
    """Declarative integration manifest — seeded from integration.yaml, edited via UI."""

    __tablename__ = "integration_manifests"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Plug'"))
    manifest: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    yaml_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'yaml'"))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


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
    session_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'isolated'"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        Index("ix_workflow_runs_created_at", "created_at"),
    )


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)  # encrypted with Fernet
    events: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    deliveries: Mapped[list["WebhookDelivery"]] = relationship("WebhookDelivery", back_populates="endpoint", cascade="all, delete-orphan")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    endpoint: Mapped["WebhookEndpoint"] = relationship("WebhookEndpoint", back_populates="deliveries")

    __table_args__ = (
        Index("ix_webhook_deliveries_endpoint_id", "endpoint_id"),
        Index("ix_webhook_deliveries_created_at", "created_at"),
        Index("ix_webhook_deliveries_endpoint_event", "endpoint_id", "event"),
    )


class UsageSpikeConfig(Base):
    """Singleton config for usage spike detection + alerting."""
    __tablename__ = "usage_spike_config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    baseline_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("24"))
    relative_threshold: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("2.0"))
    absolute_threshold_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    targets: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    last_alert_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class UsageSpikeAlert(Base):
    """History of fired spike alerts."""
    __tablename__ = "usage_spike_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    window_rate_usd_per_hour: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_rate_usd_per_hour: Mapped[float] = mapped_column(Float, nullable=False)
    spike_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)  # "relative" | "absolute"
    top_models: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    top_bots: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    recent_traces: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    targets_attempted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    targets_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    delivery_details: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_usage_spike_alerts_created_at", "created_at"),
    )


class DockerStack(Base):
    __tablename__ = "docker_stacks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_bot: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    compose_definition: Mapped[str] = mapped_column(Text, nullable=False)
    project_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="stopped")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    container_ids: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    exposed_ports: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'bot'"))
    integration_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_stopped_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_docker_stacks_bot_channel", "created_by_bot", "channel_id"),
        Index(
            "ix_docker_stacks_integration_id_unique",
            "integration_id",
            unique=True,
            postgresql_where=text("integration_id IS NOT NULL"),
        ),
    )


class BotHook(Base):
    """Bot-configurable hooks that run shell commands in response to lifecycle events."""
    __tablename__ = "bot_hooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    bot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False, default=dict,
    )
    command: Mapped[str] = mapped_column(Text, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60"),
    )
    on_failure: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'warn'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_bot_hooks_bot_id", "bot_id"),
    )


class WidgetTemplatePackage(Base):
    """User-editable widget template package. YAML template + optional Python code.

    Seed packages are re-hydrated from YAML on every boot (is_readonly=true).
    User packages override seeds when is_active=true for a given tool_name.
    """
    __tablename__ = "widget_template_packages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    yaml_template: Mapped[str] = mapped_column(Text, nullable=False)
    python_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    is_readonly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    is_orphaned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    is_invalid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_integration: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"),
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_widget_template_packages_tool_name", "tool_name"),
        Index(
            "uq_widget_template_packages_active",
            "tool_name",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
        Index(
            "uq_widget_template_packages_seed_source",
            "tool_name", "source_file", "source_integration",
            unique=True,
            postgresql_where=text("source = 'seed'"),
            sqlite_where=text("source = 'seed'"),
        ),
    )


class WidgetDashboard(Base):
    """A named dashboard that pins can live on.

    Slug is the primary key — the user chooses it at create time and it
    appears in the URL (``/widgets/<slug>``). The ``default`` row is
    bootstrapped by migration; every other dashboard is user-created.
    Sidebar-rail membership lives on the ``dashboard_rail_pins`` junction
    table so the same dashboard can be rail-pinned for everyone (``user_id
    IS NULL``) and individual users independently.
    """
    __tablename__ = "widget_dashboards"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Layout preset + type. NULL = `standard` preset (legacy + default).
    # Shape: {"layout_type": "grid", "preset": "standard" | "fine"}
    grid_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )


class WidgetDashboardPin(Base):
    """A widget pinned to a named dashboard.

    Row shape mirrors ``channel.config.pinned_widgets[]`` entries so the
    scope-aware ``PinnedToolWidget`` renderer handles both surfaces through
    one code path. ``dashboard_key`` is a FK to ``widget_dashboards.slug``;
    deleting a dashboard cascades its pins.
    """
    __tablename__ = "widget_dashboard_pins"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    dashboard_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("widget_dashboards.slug", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False, server_default=text("'default'"),
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_args: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    widget_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    display_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    grid_layout: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict,
    )
    is_main_panel: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE"), default=False,
    )
    # Chat-surface zone the pin lives on when its dashboard is a channel
    # dashboard. ``rail`` = OmniPanel sidebar; ``header`` = ChannelHeader chip
    # row; ``dock`` = right-side WidgetDock; ``grid`` = dashboard-only (not
    # on the chat screen). User dashboards always carry ``grid``.
    zone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'grid'"), default="grid",
    )
    pinned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )

    __table_args__ = (
        Index(
            "ix_widget_dashboard_pins_key_pos",
            "dashboard_key", "position",
        ),
        # Partial unique index — at most one panel pin per dashboard. Both
        # backends support partial indexes (SQLite ≥3.8.0); the predicate is
        # rendered for whichever dialect the engine is on.
        Index(
            "uq_widget_dashboard_pins_main_panel",
            "dashboard_key",
            unique=True,
            postgresql_where=text("is_main_panel = TRUE"),
            sqlite_where=text("is_main_panel = 1"),
        ),
    )


class WidgetCronSubscription(Base):
    """One scheduled ``@on_cron`` handler declared by a pinned widget bundle.

    Rows are reconciled against a pin's ``widget.yaml`` on pin create and
    envelope change (``app/services/widget_cron.py::register_pin_crons``).
    The task scheduler tick (``app/agent/tasks.py::task_worker`` →
    ``spawn_due_widget_crons``) advances ``next_fire_at`` and invokes
    ``widget_py.invoke_cron(pin, cron_name)`` under the pin's
    ``source_bot_id``. Pin deletion cascades to these rows.
    """

    __tablename__ = "widget_cron_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    pin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("widget_dashboard_pins.id", ondelete="CASCADE"),
        nullable=False,
    )
    cron_name: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[str] = mapped_column(Text, nullable=False)
    handler: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True,
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "pin_id", "cron_name",
            name="uq_widget_cron_subscriptions_pin_name",
        ),
        Index("ix_widget_cron_subscriptions_pin", "pin_id"),
        Index(
            "ix_widget_cron_subscriptions_due",
            "next_fire_at",
            postgresql_where=text("enabled = TRUE AND next_fire_at IS NOT NULL"),
            sqlite_where=text("enabled = 1 AND next_fire_at IS NOT NULL"),
        ),
    )


class WidgetEventSubscription(Base):
    """One ``@on_event`` handler declared by a pinned widget bundle.

    Rows are reconciled against a pin's ``widget.yaml`` on pin create and
    envelope change (``app/services/widget_events.py::register_pin_events``).
    Unlike cron (which polls this table every 5s), event subscribers are
    push-based: a live ``asyncio.Task`` per row reads
    ``channel_events.subscribe(pin.source_channel_id)`` and fires
    ``widget_py.invoke_event(pin, event_kind, payload)`` under the pin's
    ``source_bot_id``. Pin deletion cascades these rows (and must also
    cancel the live task — see ``unregister_pin_events``).
    """

    __tablename__ = "widget_event_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    pin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("widget_dashboard_pins.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(Text, nullable=False)
    handler: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "pin_id", "event_kind", "handler",
            name="uq_widget_event_subscriptions_pin_kind_handler",
        ),
        Index("ix_widget_event_subscriptions_pin", "pin_id"),
    )


class DashboardRailPin(Base):
    """Per-user or "everyone" rail pinning for widget dashboards.

    ``user_id IS NULL`` means the dashboard appears in the sidebar rail for
    every user who can see it (admin-only to set). A non-null ``user_id``
    means "pinned just for this user" — visible in their rail, invisible
    to everyone else.

    Real uniqueness lives in the partial unique indexes declared via
    ``postgresql_where`` below. SQLite in-memory tests skip partial-index
    enforcement; the service layer (``app/services/dashboard_rail.py``)
    does an idempotent upsert so tests still pass without DB-level locking.
    """
    __tablename__ = "dashboard_rail_pins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dashboard_slug: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "widget_dashboards.slug",
            ondelete="CASCADE", onupdate="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    rail_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )

    __table_args__ = (
        Index(
            "ix_drp_everyone", "dashboard_slug",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
            sqlite_where=text("user_id IS NULL"),
        ),
        Index(
            "ix_drp_user", "dashboard_slug", "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_drp_user_id", "user_id"),
    )


class PushSubscription(Base):
    """Web Push subscription — one row per registered (user, device) pair.

    `endpoint` + keys come straight from the browser's PushManager subscription
    JSON; the backend uses pywebpush to POST encrypted payloads to that
    endpoint. A 410 Gone from the push service on delivery means the user
    dropped the subscription (cleared site data, declined notifications) —
    the send service prunes the row when that happens. """
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_push_subscriptions_user_id", "user_id"),
    )
