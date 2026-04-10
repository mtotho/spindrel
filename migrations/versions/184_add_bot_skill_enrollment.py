"""Add bot_skill_enrollment table for per-bot working-set skill discovery.

Phase 3.1 of the Skill Simplification working-set design. Replaces per-turn
ephemeral auto-enrollment (core + integration + bot-authored merge) with a
persistent, self-curating per-bot working set.

The table records which skills each bot has enrolled, with a `source` field
distinguishing starter pack, fetched-on-success, manual UI add, etc.

Revision ID: 184
Revises: 183
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "184"
down_revision = "183"
branch_labels = None
depends_on = None


# NOTE: hardcoded copy of app.config.STARTER_SKILL_IDS — migrations stay
# self-contained (no imports from app/) so they keep working when the app
# code changes. If you change the runtime list in app/config.py, you do NOT
# need to update this — the migration only runs once on the version-184
# upgrade and represents the starter pack as it stood at that moment.
STARTER_SKILL_IDS = (
    "attachments",
    "workspace_files",
    "delegation",
    "context_mastery",
    "prompt_injection_and_security",
)


def upgrade() -> None:
    op.create_table(
        "bot_skill_enrollment",
        sa.Column(
            "bot_id",
            sa.Text(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            sa.Text(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "enrolled_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("bot_id", "skill_id", name="pk_bot_skill_enrollment"),
    )
    op.create_index(
        "ix_bot_skill_enrollment_bot_id",
        "bot_skill_enrollment",
        ["bot_id"],
    )

    # ------------------------------------------------------------------
    # Backfill existing bots with the union of:
    #   - the starter pack
    #   - core skills (source_type='file', not under bots/ or integrations/)
    #   - bots/{bot_id}/* skills (bot-authored)
    #   - skills from any integration activated on any of the bot's channels
    #
    # All inserted with source='migration' so the hygiene loop / UI can
    # distinguish them from intentional starter / manual / fetched rows.
    #
    # SKIPS SQLite (the test harness applies the schema with a no-op
    # backfill — there are no existing rows to migrate in tests).
    # ------------------------------------------------------------------
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bot_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM bots")).fetchall()]
    if not bot_ids:
        return

    core_skill_ids = [
        row[0] for row in bind.execute(sa.text(
            "SELECT id FROM skills "
            "WHERE source_type = 'file' "
            "AND id NOT LIKE 'bots/%' "
            "AND id NOT LIKE 'integrations/%'"
        )).fetchall()
    ]

    # Build a map: integration_type -> [skill_id, ...]
    integration_skill_rows = bind.execute(sa.text(
        "SELECT id FROM skills "
        "WHERE source_type = 'integration' AND id LIKE 'integrations/%'"
    )).fetchall()
    integration_skills_by_type: dict[str, list[str]] = {}
    for (sid,) in integration_skill_rows:
        # id format: integrations/{type}/...
        parts = sid.split("/", 2)
        if len(parts) >= 2:
            integration_skills_by_type.setdefault(parts[1], []).append(sid)

    # Set of valid skill IDs in the catalog (for FK safety)
    all_skill_ids = {
        row[0] for row in bind.execute(sa.text("SELECT id FROM skills")).fetchall()
    }

    insert_sql = sa.text(
        "INSERT INTO bot_skill_enrollment (bot_id, skill_id, source) "
        "VALUES (:bot_id, :skill_id, :source) "
        "ON CONFLICT (bot_id, skill_id) DO NOTHING"
    )

    for bot_id in bot_ids:
        union: set[str] = set()

        # 1. Starter pack
        union.update(STARTER_SKILL_IDS)

        # 2. Core skills
        union.update(core_skill_ids)

        # 3. Bot-authored
        bot_authored = [
            row[0] for row in bind.execute(sa.text(
                "SELECT id FROM skills WHERE id LIKE :prefix"
            ), {"prefix": f"bots/{bot_id}/%"}).fetchall()
        ]
        union.update(bot_authored)

        # 4. Skills from integrations activated on any channel of this bot
        activated_types = [
            row[0] for row in bind.execute(sa.text(
                "SELECT DISTINCT ci.integration_type "
                "FROM channel_integrations ci "
                "JOIN channels c ON c.id = ci.channel_id "
                "WHERE c.bot_id = :bot_id AND ci.activated = true"
            ), {"bot_id": bot_id}).fetchall()
        ]
        for itype in activated_types:
            union.update(integration_skills_by_type.get(itype, []))

        # FK safety: only enroll skills that exist in the catalog right now
        valid = [sid for sid in union if sid in all_skill_ids]
        for sid in valid:
            bind.execute(insert_sql, {"bot_id": bot_id, "skill_id": sid, "source": "migration"})


def downgrade() -> None:
    op.drop_index("ix_bot_skill_enrollment_bot_id", table_name="bot_skill_enrollment")
    op.drop_table("bot_skill_enrollment")
