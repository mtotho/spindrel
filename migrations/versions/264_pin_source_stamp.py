"""widget pin source_stamp column

Adds ``widget_dashboard_pins.source_stamp TEXT NULL``. Stamp encodes a digest
of the live source backing the pin's contract metadata (preset content_hash,
bundle file digest, native instance state timestamp, tool template digest).
The read path eventually serves snapshot fields verbatim while a background
reconciler watches for stamp drift; the column is nullable during the
backfill phase.

Revision ID: 264_pin_source_stamp
Revises: 263_spatial_landmarks
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "264_pin_source_stamp"
down_revision = "263_spatial_landmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE widget_dashboard_pins "
        "ADD COLUMN IF NOT EXISTS source_stamp TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE widget_dashboard_pins DROP COLUMN IF EXISTS source_stamp"
    )
