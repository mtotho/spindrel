"""Migrate channel.config.pinned_widgets → channel:<uuid> dashboards.

Each channel with a non-empty ``config['pinned_widgets']`` list gets an
implicit ``WidgetDashboard`` row (slug=``channel:<uuid>``) and one
``WidgetDashboardPin`` row per entry. The JSONB field is then cleared.

After this migration the UI and context-injection paths read pins from
``widget_dashboard_pins`` exclusively — no dual read paths. The JSONB
key stays on the model for back-compat of already-deployed binaries in
the short rollout window (``.get("pinned_widgets") or []`` falls
through cleanly on an empty list), then reads disappear in the same
release's code changes.

Revision ID: 213
Revises: 212
"""
from __future__ import annotations

import json
import uuid as uuid_mod

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID

revision = "213"
down_revision = "212"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Reflected bound tables — safer than raw SQL across dialects (SQLite
    # in tests, Postgres in prod) because SQLAlchemy quotes and casts
    # properly. We stay close to Core to avoid importing ORM models, which
    # the migrations layer shouldn't depend on.
    channels = sa.table(
        "channels",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("name", sa.Text()),
        sa.column("config", JSONB()),
    )
    dashboards = sa.table(
        "widget_dashboards",
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("icon", sa.Text()),
        sa.column("pin_to_rail", sa.Boolean()),
    )
    pins = sa.table(
        "widget_dashboard_pins",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("dashboard_key", sa.Text()),
        sa.column("position", sa.Integer()),
        sa.column("source_kind", sa.Text()),
        sa.column("source_channel_id", PgUUID(as_uuid=True)),
        sa.column("source_bot_id", sa.Text()),
        sa.column("tool_name", sa.Text()),
        sa.column("tool_args", JSONB()),
        sa.column("widget_config", JSONB()),
        sa.column("envelope", JSONB()),
        sa.column("display_label", sa.Text()),
        sa.column("grid_layout", JSONB()),
    )

    rows = conn.execute(
        sa.select(channels.c.id, channels.c.name, channels.c.config)
    ).fetchall()

    for ch_id, ch_name, cfg in rows:
        cfg = cfg or {}
        widgets = cfg.get("pinned_widgets") or []
        if not widgets:
            continue

        slug = f"channel:{ch_id}"

        # Idempotency: skip if the channel dashboard already exists.
        # Previous migration attempts leave rows behind; don't double-insert.
        existing = conn.execute(
            sa.select(dashboards.c.slug).where(dashboards.c.slug == slug)
        ).scalar_one_or_none()

        if existing is None:
            conn.execute(
                sa.insert(dashboards).values(
                    slug=slug,
                    name=ch_name or f"Channel {str(ch_id)[:8]}",
                    icon=None,
                    pin_to_rail=False,
                )
            )

        # Existing pins (from a half-run) — key off tool_name+source_bot_id
        # +position so re-running this migration doesn't duplicate.
        existing_keys = {
            (row.tool_name, row.source_bot_id, row.position)
            for row in conn.execute(
                sa.select(
                    pins.c.tool_name, pins.c.source_bot_id, pins.c.position,
                ).where(pins.c.dashboard_key == slug)
            ).fetchall()
        }

        for w in widgets:
            pos = int(w.get("position") or 0)
            tool_name = w.get("tool_name") or ""
            bot_id = w.get("bot_id")
            if (tool_name, bot_id, pos) in existing_keys:
                continue
            envelope = w.get("envelope") or {}
            if isinstance(envelope, str):
                try:
                    envelope = json.loads(envelope)
                except Exception:
                    envelope = {}
            conn.execute(
                sa.insert(pins).values(
                    id=uuid_mod.uuid4(),
                    dashboard_key=slug,
                    position=pos,
                    source_kind="channel",
                    source_channel_id=ch_id,
                    source_bot_id=bot_id,
                    tool_name=tool_name,
                    tool_args={},
                    widget_config=w.get("config") or {},
                    envelope=envelope,
                    display_label=w.get("display_name"),
                    grid_layout={},
                )
            )

        # Clear the JSONB field — one storage path from now on.
        new_cfg = {k: v for k, v in cfg.items() if k != "pinned_widgets"}
        conn.execute(
            sa.update(channels)
            .where(channels.c.id == ch_id)
            .values(config=new_cfg)
        )


def downgrade() -> None:
    """Best-effort reverse: for each channel:<uuid> dashboard, fold pins
    back into channels.config['pinned_widgets'] and drop the dashboard.

    Not expected to run in production — the forward migration is
    one-shot and the frontend will lose track of per-pin grid_layout
    if we go back. Provided for test parity with the rest of the
    migration chain.
    """
    conn = op.get_bind()

    channels = sa.table(
        "channels",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("config", JSONB()),
    )
    dashboards = sa.table(
        "widget_dashboards",
        sa.column("slug", sa.Text()),
    )
    pins = sa.table(
        "widget_dashboard_pins",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("dashboard_key", sa.Text()),
        sa.column("position", sa.Integer()),
        sa.column("source_channel_id", PgUUID(as_uuid=True)),
        sa.column("source_bot_id", sa.Text()),
        sa.column("tool_name", sa.Text()),
        sa.column("widget_config", JSONB()),
        sa.column("envelope", JSONB()),
        sa.column("display_label", sa.Text()),
    )

    rows = conn.execute(
        sa.select(dashboards.c.slug).where(dashboards.c.slug.like("channel:%"))
    ).fetchall()

    for (slug,) in rows:
        try:
            ch_id = uuid_mod.UUID(slug.split(":", 1)[1])
        except Exception:
            continue

        pin_rows = conn.execute(
            sa.select(
                pins.c.id, pins.c.position, pins.c.source_bot_id,
                pins.c.tool_name, pins.c.widget_config, pins.c.envelope,
                pins.c.display_label,
            ).where(pins.c.dashboard_key == slug).order_by(pins.c.position)
        ).fetchall()

        restored = [
            {
                "id": str(r.id),
                "tool_name": r.tool_name or "",
                "display_name": r.display_label or r.tool_name or "",
                "bot_id": r.source_bot_id or "",
                "envelope": r.envelope or {},
                "position": r.position,
                "pinned_at": "",
                "config": r.widget_config or {},
            }
            for r in pin_rows
        ]

        cfg = conn.execute(
            sa.select(channels.c.config).where(channels.c.id == ch_id)
        ).scalar_one_or_none() or {}
        cfg = dict(cfg)
        cfg["pinned_widgets"] = restored
        conn.execute(
            sa.update(channels).where(channels.c.id == ch_id).values(config=cfg)
        )

        conn.execute(sa.delete(pins).where(pins.c.dashboard_key == slug))
        conn.execute(sa.delete(dashboards).where(dashboards.c.slug == slug))
