"""Add provider_id columns alongside model fields.

Every model configuration field should store its provider_id so the correct
LLM provider is used at call time, rather than guessing from the bot's
default provider.

- channels.compaction_model_provider_id
- bots.compaction_model_provider_id
- bots.attachment_summary_model_provider_id

Revision ID: 193
Revises: 192
"""

import sqlalchemy as sa
from alembic import op

revision: str = "193"
down_revision: str = "192"


def upgrade() -> None:
    op.add_column("channels", sa.Column("compaction_model_provider_id", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("compaction_model_provider_id", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("attachment_summary_model_provider_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "attachment_summary_model_provider_id")
    op.drop_column("bots", "compaction_model_provider_id")
    op.drop_column("channels", "compaction_model_provider_id")
