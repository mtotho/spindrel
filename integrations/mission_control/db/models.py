"""MC-owned SQLAlchemy models for the local SQLite database.

All Mission Control state lives here — separate from the core PostgreSQL database.
channel_id is stored as Text (not FK) because this is a different DB entirely.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MCBase(DeclarativeBase):
    pass


class McKanbanColumn(MCBase):
    __tablename__ = "mc_kanban_columns"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(Text, index=True)
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    cards: Mapped[list[McKanbanCard]] = relationship(
        back_populates="column", cascade="all, delete-orphan",
    )


class McKanbanCard(MCBase):
    __tablename__ = "mc_kanban_cards"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(Text, index=True)
    column_id: Mapped[str] = mapped_column(Text, ForeignKey("mc_kanban_columns.id"))
    card_id: Mapped[str] = mapped_column(Text, unique=True)  # "mc-a1b2c3"
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(Text, default="medium")
    assigned: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_date: Mapped[str] = mapped_column(Text, default="")
    started_date: Mapped[str] = mapped_column(Text, default="")
    completed_date: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    column: Mapped[McKanbanColumn] = relationship(back_populates="cards")


class McTimelineEvent(MCBase):
    __tablename__ = "mc_timeline_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(Text, index=True)
    event_date: Mapped[str] = mapped_column(Text)  # "YYYY-MM-DD"
    event_time: Mapped[str] = mapped_column(Text)  # "HH:MM"
    event: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class McPlan(MCBase):
    __tablename__ = "mc_plans"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(Text, index=True)
    plan_id: Mapped[str] = mapped_column(Text, unique=True)  # "plan-a1b2c3"
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_date: Mapped[str] = mapped_column(Text, default="")
    approved_date: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    steps: Mapped[list[McPlanStep]] = relationship(
        back_populates="plan", cascade="all, delete-orphan",
        order_by="McPlanStep.position",
    )


class McPlanStep(MCBase):
    __tablename__ = "mc_plan_steps"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("mc_plans.id"))
    position: Mapped[int] = mapped_column(Integer)  # 1-based
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # core Task UUID
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    plan: Mapped[McPlan] = relationship(back_populates="steps")
