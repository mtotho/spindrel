"""Drop deprecated knowledge-system schema.

Removes 5 tables (`memories`, `bot_knowledge`, `knowledge_pins`,
`knowledge_access`, `knowledge_writes`) and 1 column on `bots`
(`knowledge_max_inject_chars`). All code references were removed in prior
cleanup (2026-04-16); this migration completes the deprecation at the
schema level.

The tables evolved over many revisions (006 → 157) with column shape
changes in 035/036/037/038 and pgvector halfvec index migrations in 157.
Reconstructing the final-state schema in downgrade would require
transcribing dozens of create_table / alter_column calls and stays
brittle. Production data is unrecoverable either way — the code that
wrote these rows no longer exists — so the downgrade raises
NotImplementedError rather than pretending a revival path exists.
Dev-environment rollbacks should use a fresh database.

Revision ID: 205
Revises: 204
"""
from alembic import op


revision = "205"
down_revision = "204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("knowledge_writes")
    op.drop_table("knowledge_access")
    op.drop_table("knowledge_pins")
    op.drop_table("bot_knowledge")
    op.drop_table("memories")
    op.drop_column("bots", "knowledge_max_inject_chars")


def downgrade() -> None:
    raise NotImplementedError(
        "Migration 205 drops the knowledge-system schema. The dropped tables "
        "evolved across revisions 003/005/006/013/035-038/043/157 with "
        "column shape changes and pgvector halfvec index rebuilds. A faithful "
        "downgrade would be brittle, and the code that populated these rows "
        "no longer exists. Use a fresh database for rollback."
    )
