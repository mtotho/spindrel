"""merge project setup and widget agency migration heads

Revision ID: 274_merge_project_widget_heads
Revises: 273_project_setup_runs, 273_widget_agency_receipts
Create Date: 2026-04-29
"""
from __future__ import annotations


revision = "274_merge_project_widget_heads"
down_revision = ("273_project_setup_runs", "273_widget_agency_receipts")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
