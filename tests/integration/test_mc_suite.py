"""Integration tests for the Mission Control widget suite (Phase B.6).

Verifies dashboard-scoped shared-DB behavior by creating multiple pins that
all declare ``db.shared: mission-control`` and round-tripping data through
``ctx.db`` handlers (called via the /widget-actions endpoint with
``dispatch: widget_handler``).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from tests.integration.conftest import AUTH_HEADERS


_CHANNEL_ID_A = uuid.UUID("aaaa0000-0000-0000-0000-000000000101")
_CHANNEL_ID_B = uuid.UUID("aaaa0000-0000-0000-0000-000000000102")

_BOT = BotConfig(
    id="test-bot",
    name="Test Bot",
    model="test/model",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
)


def _envelope(channel_id: uuid.UUID, bundle: str) -> dict:
    return {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "",
        # Paths that resolve INTO _BUILTIN_WIDGET_DIR trigger the built-in
        # redirect in widget_db — but suite-shared DBs bypass that redirect
        # entirely (resolve_suite_db_path uses dashboard_key, not bundle dir).
        "source_path": f"widgets/{bundle}/index.html",
        "source_channel_id": str(channel_id),
        "source_bot_id": "test-bot",
        "plain_body": bundle,
        "display": "inline",
    }


@pytest.fixture()
async def seeded(db_session, tmp_path, monkeypatch):
    """Seed a bot + API key so create_pin's validation passes.

    Also points ``get_channel_workspace_root`` at the parent of the built-in
    widgets dir so the MC bundles (living under
    ``app/tools/local/widgets/mc_*``) resolve via the envelope's
    ``source_path: widgets/mc_*/index.html``.
    """
    from app.db.models import ApiKey, Bot

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="test-key",
        key_hash="testhash",
        key_prefix="test-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot_row = Bot(
        id="test-bot",
        name="Test Bot",
        display_name="Test Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot_row)
    await db_session.flush()

    # Isolate the suite DB path to tmp_path so parallel test runs don't
    # collide.
    from app.services import paths as paths_mod
    monkeypatch.setattr(
        paths_mod, "local_workspace_base", lambda: str(tmp_path),
    )

    # Point workspace root at the parent of the real built-in widgets dir
    # (the directory containing mc_* on disk) so source_path="widgets/mc_*/index.html"
    # resolves into the real bundle source tree. We locate it from this test
    # file so it works whether run from the repo root or inside Docker.
    from pathlib import Path
    widgets_parent = (
        Path(__file__).resolve().parents[2] / "app" / "tools" / "local"
    )
    assert (widgets_parent / "widgets" / "mc_tasks" / "widget.py").is_file(), (
        f"mc_tasks bundle missing at {widgets_parent}"
    )
    monkeypatch.setattr(
        "app.services.channel_workspace.get_channel_workspace_root",
        lambda channel_id, bot: str(widgets_parent),
    )
    return tmp_path


@pytest.fixture()
async def channel_a(db_session):
    from app.db.models import Channel
    ch = Channel(
        id=_CHANNEL_ID_A,
        name="channel-a",
        bot_id="test-bot",
        client_id="test-client-a",
    )
    db_session.add(ch)
    await db_session.flush()
    return _CHANNEL_ID_A


@pytest.fixture()
async def channel_b(db_session):
    from app.db.models import Channel
    ch = Channel(
        id=_CHANNEL_ID_B,
        name="channel-b",
        bot_id="test-bot",
        client_id="test-client-b",
    )
    db_session.add(ch)
    await db_session.flush()
    return _CHANNEL_ID_B


def _bot_patch():
    return patch("app.agent.bots.get_bot", return_value=_BOT)


async def _create_pin(db_session, bundle: str, channel_id: uuid.UUID):
    from app.services.dashboard_pins import create_pin
    return await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="emit_html_widget",
        envelope=_envelope(channel_id, bundle),
        source_channel_id=channel_id,
        source_bot_id="test-bot",
        display_label=bundle,
        dashboard_key=f"channel:{channel_id}",
    )


# ---------------------------------------------------------------------------
# Cross-bundle DB sharing on the same dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_and_tasks_share_one_db_on_same_dashboard(
    client, seeded, db_session, channel_a,
):
    """mc_timeline and mc_tasks pinned on the same channel dashboard must
    see the same SQLite DB — a row inserted via mc_tasks's handler shows
    up when mc_timeline issues an identical query through its own pin."""
    with _bot_patch():
        timeline_pin = await _create_pin(db_session, "mc_timeline", channel_a)
        tasks_pin = await _create_pin(db_session, "mc_tasks", channel_a)

    # Add a task via the mc_tasks bundle's @on_action("add_task").
    with _bot_patch():
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(tasks_pin.id),
                "handler": "add_task",
                "args": {"title": "Write the B.6 test"},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, body

    # Now issue a db_query through the mc_timeline pin — it should see
    # the same row because both bundles share the suite DB.
    with _bot_patch():
        qry = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(timeline_pin.id),
                "sql": "SELECT title, kind FROM items WHERE title = ?",
                "params": ["Write the B.6 test"],
            },
            headers=AUTH_HEADERS,
        )
    assert qry.json()["ok"] is True, qry.json()
    rows = qry.json()["db_result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "task"


@pytest.mark.asyncio
async def test_different_dashboards_isolated(
    client, seeded, db_session, channel_a, channel_b,
):
    """Pins on different dashboards see different DBs."""
    with _bot_patch():
        tasks_a = await _create_pin(db_session, "mc_tasks", channel_a)
        tasks_b = await _create_pin(db_session, "mc_tasks", channel_b)

    with _bot_patch():
        await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(tasks_a.id),
                "handler": "add_task",
                "args": {"title": "A-only task"},
            },
            headers=AUTH_HEADERS,
        )

    with _bot_patch():
        qry_b = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(tasks_b.id),
                "sql": "SELECT title FROM items WHERE title = ?",
                "params": ["A-only task"],
            },
            headers=AUTH_HEADERS,
        )
    assert qry_b.json()["ok"] is True
    assert qry_b.json()["db_result"]["rows"] == []


@pytest.mark.asyncio
async def test_user_scoped_pin_resolves_suite_db_without_bot(
    client, seeded, db_session, channel_a,
):
    """User-scoped suite pins (``source_bot_id = None``) must still reach
    the suite DB. The DB path is keyed on ``dashboard_key`` and the bundle
    directory is a server-wide ``BUILTIN_WIDGET_ROOT`` subtree — neither
    requires a bot. Regression: session 15 shipped user-scoped pins but
    ``resolve_db_path`` and ``_resolve_bundle_dir`` both still required
    ``source_bot_id``, so every ``db.query`` inside a user-scoped MC
    widget failed with "pin missing source_bot_id — cannot resolve DB path".
    """
    from app.services.dashboard_pins import create_pin

    # Build an envelope shaped exactly like the suite pin endpoint produces
    # for the builtin MC suite (source_kind="builtin", no bot, no channel).
    envelope = {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "",
        "plain_body": "mc_tasks",
        "display": "inline",
        "source_path": "mc_tasks/index.html",
        "source_kind": "builtin",
        "display_label": "mc_tasks",
    }
    with _bot_patch():
        user_scoped_pin = await create_pin(
            db_session,
            source_kind="adhoc",
            tool_name="emit_html_widget",
            envelope=envelope,
            source_channel_id=None,
            source_bot_id=None,
            display_label="mc_tasks",
            dashboard_key="default",
        )
    assert user_scoped_pin.source_bot_id is None
    assert user_scoped_pin.source_channel_id is None

    # The widget's first render calls `sp.db.query` — that goes through
    # /widget-actions with dispatch=db_query. It used to throw; now it
    # should return an empty result (new suite DB, migrations just ran).
    with _bot_patch():
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(user_scoped_pin.id),
                "sql": "SELECT id, title FROM items WHERE kind = 'task'",
                "params": [],
            },
            headers=AUTH_HEADERS,
        )
    body = resp.json()
    assert body["ok"] is True, body
    assert body["db_result"]["rows"] == []


@pytest.mark.asyncio
async def test_kanban_move_emits_timeline_row(
    client, seeded, db_session, channel_a,
):
    """Moving a kanban card across columns inserts a timeline_event row,
    which mc_timeline then surfaces."""
    with _bot_patch():
        kanban_pin = await _create_pin(db_session, "mc_kanban", channel_a)
        timeline_pin = await _create_pin(db_session, "mc_timeline", channel_a)

    with _bot_patch():
        # Seed columns.
        await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(kanban_pin.id),
                "handler": "seed_default_columns",
                "args": {},
            },
            headers=AUTH_HEADERS,
        )
        # Look up the first and last columns.
        cols = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(kanban_pin.id),
                "sql": "SELECT id FROM kanban_columns ORDER BY position ASC",
                "params": [],
            },
            headers=AUTH_HEADERS,
        )
    col_rows = cols.json()["db_result"]["rows"]
    assert len(col_rows) == 3
    first_col = col_rows[0]["id"]
    last_col = col_rows[-1]["id"]

    # Add a card in the first column, then move it to the last column.
    with _bot_patch():
        await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(kanban_pin.id),
                "handler": "add_card",
                "args": {"column_id": first_col, "title": "Cross-col move"},
            },
            headers=AUTH_HEADERS,
        )
        # Find the card id.
        cards = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(kanban_pin.id),
                "sql": "SELECT id FROM items WHERE title = ? AND kind = 'kanban_card'",
                "params": ["Cross-col move"],
            },
            headers=AUTH_HEADERS,
        )
    card_id = cards.json()["db_result"]["rows"][0]["id"]

    with _bot_patch():
        await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(kanban_pin.id),
                "handler": "move_card",
                "args": {"card_id": card_id, "column_id": last_col},
            },
            headers=AUTH_HEADERS,
        )

        # Timeline should see the echo event.
        tl = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(timeline_pin.id),
                "sql": "SELECT title, source_kind FROM items WHERE kind = 'timeline_event' "
                       "ORDER BY datetime(created_at) DESC",
                "params": [],
            },
            headers=AUTH_HEADERS,
        )
    tl_rows = tl.json()["db_result"]["rows"]
    assert len(tl_rows) >= 1
    assert any(r["source_kind"] == "kanban" for r in tl_rows)
    assert any("Cross-col move" in r["title"] for r in tl_rows)
