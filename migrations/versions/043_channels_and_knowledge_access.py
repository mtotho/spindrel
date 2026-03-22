"""Introduce channels table, knowledge_access table, and channel_id on related tables.

Channels become the persistent top-level container. Sessions are resettable conversations
within a channel. Knowledge, tasks, and plans scope to channels (persistent) rather than
sessions (ephemeral).

Revision ID: 043
Revises: 042
"""
import uuid
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID, TIMESTAMP

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels = None
depends_on = None


def _derive_channel_id(client_id: str) -> str:
    """Mirror app.services.channels.derive_channel_id in pure Python."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}"))


def _derive_legacy_session_id(client_id: str) -> str:
    """Mirror the old derive_integration_session_id (bare client_id, no prefix)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, client_id))


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Step 1: Create channels table
    # -----------------------------------------------------------------------
    op.create_table(
        "channels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), unique=True, nullable=True),
        sa.Column("integration", sa.Text(), nullable=True),
        sa.Column("active_session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("dispatch_config", JSONB, nullable=True),
        sa.Column("require_mention", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("passive_memory", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rag_on_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # -----------------------------------------------------------------------
    # Step 2: Add channel_id FK to sessions
    # -----------------------------------------------------------------------
    op.add_column("sessions", sa.Column("channel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_sessions_channel_id",
        "sessions", "channels",
        ["channel_id"], ["id"],
        ondelete="SET NULL",
    )

    # -----------------------------------------------------------------------
    # Step 3: Populate channels from IntegrationChannelConfig + sessions
    # (Done in Python to avoid uuid-ossp extension dependency)
    # -----------------------------------------------------------------------
    conn = op.get_bind()

    # 3a: From IntegrationChannelConfig rows
    icc_rows = conn.execute(sa.text(
        "SELECT client_id, integration, bot_id, require_mention, passive_memory, "
        "rag_on_all, created_at, updated_at FROM integration_channel_configs"
    )).fetchall()

    for row in icc_rows:
        channel_id = _derive_channel_id(row.client_id)
        conn.execute(sa.text("""
            INSERT INTO channels (id, name, bot_id, client_id, integration,
                                  require_mention, passive_memory, rag_on_all,
                                  created_at, updated_at)
            VALUES (:id, :name, :bot_id, :client_id, :integration,
                    :require_mention, :passive_memory, :rag_on_all,
                    :created_at, :updated_at)
            ON CONFLICT (client_id) DO NOTHING
        """), {
            "id": channel_id,
            "name": row.client_id,
            "bot_id": row.bot_id or "default",
            "client_id": row.client_id,
            "integration": row.integration,
            "require_mention": row.require_mention,
            "passive_memory": row.passive_memory,
            "rag_on_all": row.rag_on_all,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        })

    # 3b: Pull dispatch_config from legacy derived sessions into channels
    for row in icc_rows:
        legacy_session_id = _derive_legacy_session_id(row.client_id)
        conn.execute(sa.text("""
            UPDATE channels c
            SET dispatch_config = s.dispatch_config
            FROM sessions s
            WHERE s.id = :session_id
              AND c.client_id = :client_id
              AND s.dispatch_config IS NOT NULL
              AND c.dispatch_config IS NULL
        """), {"session_id": legacy_session_id, "client_id": row.client_id})

    # 3c: Integration sessions without an IntegrationChannelConfig row
    integration_sessions = conn.execute(sa.text("""
        SELECT DISTINCT ON (s.client_id)
            s.client_id, s.bot_id, s.created_at,
            split_part(s.client_id, ':', 1) AS integration
        FROM sessions s
        WHERE (s.client_id LIKE 'slack:%%' OR s.client_id LIKE 'discord:%%' OR s.client_id LIKE 'teams:%%')
        ORDER BY s.client_id, s.last_active DESC NULLS LAST
    """)).fetchall()

    for row in integration_sessions:
        channel_id = _derive_channel_id(row.client_id)
        conn.execute(sa.text("""
            INSERT INTO channels (id, name, bot_id, client_id, integration, created_at, updated_at)
            VALUES (:id, :name, :bot_id, :client_id, :integration, :created_at, :created_at)
            ON CONFLICT (client_id) DO NOTHING
        """), {
            "id": channel_id,
            "name": row.client_id,
            "bot_id": row.bot_id,
            "client_id": row.client_id,
            "integration": row.integration,
            "created_at": row.created_at,
        })

    # -----------------------------------------------------------------------
    # Step 5: Backfill channel_id on sessions (integration sessions)
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        UPDATE sessions s
        SET channel_id = c.id
        FROM channels c
        WHERE c.client_id = s.client_id
          AND c.client_id IS NOT NULL
    """))

    # -----------------------------------------------------------------------
    # Step 6: Set active_session_id on channels (most recently active session)
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        UPDATE channels c
        SET active_session_id = sub.session_id
        FROM (
            SELECT DISTINCT ON (s.channel_id) s.channel_id, s.id AS session_id
            FROM sessions s
            WHERE s.channel_id IS NOT NULL
            ORDER BY s.channel_id, s.last_active DESC NULLS LAST
        ) sub
        WHERE c.id = sub.channel_id
    """))

    # Add FK for active_session_id after backfill to avoid circular dependency
    op.create_foreign_key(
        "fk_channels_active_session_id",
        "channels", "sessions",
        ["active_session_id"], ["id"],
        ondelete="SET NULL",
    )

    # -----------------------------------------------------------------------
    # Step 7: Create knowledge_access table
    # -----------------------------------------------------------------------
    op.create_table(
        "knowledge_access",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("knowledge_id", UUID(as_uuid=True), sa.ForeignKey("bot_knowledge.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_key", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False, server_default=sa.text("'rag'")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("knowledge_id", "scope_type", "scope_key", name="uq_knowledge_access_scope"),
    )

    # -----------------------------------------------------------------------
    # Step 8: Migrate knowledge scoping → knowledge_access
    # -----------------------------------------------------------------------

    # bot_id scoped knowledge → scope_type='bot'
    op.execute(sa.text("""
        INSERT INTO knowledge_access (id, knowledge_id, scope_type, scope_key, mode)
        SELECT gen_random_uuid(), bk.id, 'bot', bk.bot_id, 'rag'
        FROM bot_knowledge bk
        WHERE bk.bot_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_knowledge_access_scope DO NOTHING
    """))

    # session_id scoped knowledge → scope_type='channel' (find channel via session)
    op.execute(sa.text("""
        INSERT INTO knowledge_access (id, knowledge_id, scope_type, scope_key, mode)
        SELECT gen_random_uuid(), bk.id, 'channel', s.channel_id::text, 'rag'
        FROM bot_knowledge bk
        JOIN sessions s ON s.id = bk.session_id
        WHERE bk.session_id IS NOT NULL AND s.channel_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_knowledge_access_scope DO NOTHING
    """))

    # Global knowledge (all scoping columns NULL) → scope_type='global'
    op.execute(sa.text("""
        INSERT INTO knowledge_access (id, knowledge_id, scope_type, scope_key, mode)
        SELECT gen_random_uuid(), bk.id, 'global', NULL, 'rag'
        FROM bot_knowledge bk
        WHERE bk.bot_id IS NULL AND bk.session_id IS NULL AND bk.client_id IS NULL
        ON CONFLICT ON CONSTRAINT uq_knowledge_access_scope DO NOTHING
    """))

    # Migrate knowledge_pins → knowledge_access with mode='pinned'
    op.execute(sa.text("""
        INSERT INTO knowledge_access (id, knowledge_id, scope_type, scope_key, mode)
        SELECT gen_random_uuid(), bk.id,
            CASE WHEN kp.bot_id IS NOT NULL THEN 'bot' ELSE 'global' END,
            kp.bot_id,
            'pinned'
        FROM knowledge_pins kp
        JOIN bot_knowledge bk ON bk.name = kp.knowledge_name
            AND (bk.bot_id = kp.bot_id OR (bk.bot_id IS NULL AND kp.bot_id IS NULL))
        ON CONFLICT ON CONSTRAINT uq_knowledge_access_scope DO NOTHING
    """))

    # -----------------------------------------------------------------------
    # Step 9: Add channel_id to tasks, plans, memories, knowledge_writes
    # -----------------------------------------------------------------------
    op.add_column("tasks", sa.Column("channel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_tasks_channel_id", "tasks", "channels", ["channel_id"], ["id"], ondelete="SET NULL")

    op.add_column("plans", sa.Column("channel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_plans_channel_id", "plans", "channels", ["channel_id"], ["id"], ondelete="SET NULL")

    op.add_column("memories", sa.Column("channel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_memories_channel_id", "memories", "channels", ["channel_id"], ["id"], ondelete="SET NULL")

    op.add_column("knowledge_writes", sa.Column("channel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_knowledge_writes_channel_id", "knowledge_writes", "channels", ["channel_id"], ["id"], ondelete="SET NULL")

    # -----------------------------------------------------------------------
    # Step 10: Backfill channel_id on tasks/plans/memories from their session
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        UPDATE tasks t SET channel_id = s.channel_id
        FROM sessions s WHERE s.id = t.session_id AND s.channel_id IS NOT NULL
    """))
    op.execute(sa.text("""
        UPDATE plans p SET channel_id = s.channel_id
        FROM sessions s WHERE s.id = p.session_id AND s.channel_id IS NOT NULL
    """))
    op.execute(sa.text("""
        UPDATE memories m SET channel_id = s.channel_id
        FROM sessions s WHERE s.id = m.session_id AND s.channel_id IS NOT NULL
    """))


def downgrade() -> None:
    # Drop FKs and columns added in step 9
    op.drop_constraint("fk_knowledge_writes_channel_id", "knowledge_writes", type_="foreignkey")
    op.drop_column("knowledge_writes", "channel_id")
    op.drop_constraint("fk_memories_channel_id", "memories", type_="foreignkey")
    op.drop_column("memories", "channel_id")
    op.drop_constraint("fk_plans_channel_id", "plans", type_="foreignkey")
    op.drop_column("plans", "channel_id")
    op.drop_constraint("fk_tasks_channel_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "channel_id")

    # Drop knowledge_access
    op.drop_table("knowledge_access")

    # Drop FK and column from sessions
    op.drop_constraint("fk_channels_active_session_id", "channels", type_="foreignkey")
    op.drop_constraint("fk_sessions_channel_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "channel_id")

    # Drop channels table
    op.drop_table("channels")
