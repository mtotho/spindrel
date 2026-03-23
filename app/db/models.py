import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Integer, Text, text

from app.config import settings
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
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
    elevation_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elevation_threshold: Mapped[float | None] = mapped_column(nullable=True)
    elevated_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="channel",
        foreign_keys="Session.channel_id",
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
    metadata_: Mapped[dict] = mapped_column(
        "metadata_", JSONB, server_default=text("'{}'::jsonb")
    )
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
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


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
    context_compaction: Mapped[bool] = mapped_column(nullable=False, default=True)
    compaction_interval: Mapped[int | None] = mapped_column(nullable=True)
    compaction_keep_turns: Mapped[int | None] = mapped_column(nullable=True)
    compaction_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_knowledge_compaction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    bot_sandbox: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    elevation_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elevation_threshold: Mapped[float | None] = mapped_column(nullable=True)
    elevated_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


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
    prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    dispatch_results: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    trigger_response: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    channel: Mapped["Channel"] = relationship("Channel")


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
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dispatch_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    dispatch_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    callback_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recurrence: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. "+1h", "+1d"
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


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
