"""Manifest signing Phase 2: persist HMAC signature on skills + widget
templates so verify-on-read can refuse tampered rows for autonomous
origins.

NULL signatures are treated as "Phase 1 unsigned" — the audit emits a
warning but loads still proceed. After Phase 2 ships and the operator
runs `POST /api/v1/admin/manifest/trust-current-state`, every existing
row gets a signature and verify-on-read becomes the canonical defense.

Revision ID: 289_add_manifest_signature
Revises: 288_widget_token_revocations
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "289_add_manifest_signature"
down_revision = "288_widget_token_revocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("signature", sa.Text(), nullable=True),
    )
    op.add_column(
        "widget_template_packages",
        sa.Column("signature", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("widget_template_packages", "signature")
    op.drop_column("skills", "signature")
