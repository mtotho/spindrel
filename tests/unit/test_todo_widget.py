"""Unit tests for the Todo widget — handlers, manifest, ordering invariants."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import ApiKey, Bot, WidgetDashboard, WidgetDashboardPin
from app.services.widget_manifest import parse_manifest
from app.services.widget_py import clear_module_cache, invoke_action

_CHANNEL_ID = uuid.UUID("dddd0000-0000-0000-0000-000000000101")
_BOT_ID = "todo-bot"

# The todo bundle on disk — we resolve to it via patched workspace root.
_TODO_BUNDLE = (
    Path(__file__).resolve().parents[2]
    / "app" / "tools" / "local" / "widgets" / "todo"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_module_cache()
    yield
    clear_module_cache()


def _make_bot() -> BotConfig:
    return BotConfig(
        id=_BOT_ID, name="Todo Bot", model="test/model",
        system_prompt="", memory=MemoryConfig(enabled=False),
    )


async def _seed_pin(db_session, tmp_path) -> WidgetDashboardPin:
    """Seed bot + dashboard + pin pointing at the real todo bundle."""
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="todo-key",
        key_hash="todohash",
        key_prefix="todo-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    db_session.add(Bot(
        id=_BOT_ID, name="Todo Bot", display_name="Todo Bot",
        model="test/model", system_prompt="", api_key_id=api_key.id,
    ))
    await db_session.flush()

    db_session.add(WidgetDashboard(slug=f"channel:{_CHANNEL_ID}", name="ch"))
    await db_session.flush()

    pin = WidgetDashboardPin(
        dashboard_key=f"channel:{_CHANNEL_ID}",
        position=0,
        source_kind="adhoc",
        source_channel_id=_CHANNEL_ID,
        source_bot_id=_BOT_ID,
        tool_name="emit_html_widget",
        tool_args={},
        widget_config={},
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "",
            "source_path": "widgets/todo/index.html",
            "source_channel_id": str(_CHANNEL_ID),
            "source_bot_id": _BOT_ID,
        },
        grid_layout={"x": 0, "y": 0, "w": 4, "h": 6},
    )
    db_session.add(pin)
    await db_session.commit()
    await db_session.refresh(pin)
    return pin


def _patches(tmp_path: Path):
    """Point widget resolution at the real todo bundle + an isolated DB dir."""
    from app.services import paths as paths_mod
    # Workspace root = parent of the `widgets/` dir containing our bundle.
    widgets_parent = _TODO_BUNDLE.parent.parent  # app/tools/local/
    return [
        patch("app.agent.bots.get_bot", return_value=_make_bot()),
        patch(
            "app.services.channel_workspace.get_channel_workspace_root",
            lambda channel_id, bot: str(widgets_parent),
        ),
        patch.object(paths_mod, "local_workspace_base", lambda: str(tmp_path)),
    ]


class TestManifest:
    def test_todo_bundle_parses(self):
        m = parse_manifest(_TODO_BUNDLE / "widget.yaml")
        assert m.name == "Todo"
        handler_names = sorted(h.name for h in m.handlers if h.bot_callable)
        assert handler_names == ["add_todo", "delete_todo", "list_todos", "toggle_done"]
        # list_todos is readonly, others mutating.
        tiers = {h.name: h.safety_tier for h in m.handlers}
        assert tiers["list_todos"] == "readonly"
        assert tiers["add_todo"] == "mutating"
        assert tiers["toggle_done"] == "mutating"
        assert tiers["delete_todo"] == "mutating"


class TestHandlers:
    @pytest.mark.asyncio
    async def test_add_and_list_roundtrip(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            r = await invoke_action(pin, "add_todo", {"title": "Buy milk"})
            assert r["title"] == "Buy milk"
            assert r["id"]

            rows = await invoke_action(pin, "list_todos", {})
        assert len(rows) == 1
        assert rows[0]["title"] == "Buy milk"
        assert rows[0]["done"] is False

    @pytest.mark.asyncio
    async def test_add_rejects_empty(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            with pytest.raises(ValueError, match="title is required"):
                await invoke_action(pin, "add_todo", {"title": "   "})

    @pytest.mark.asyncio
    async def test_toggle_flips_done(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            r = await invoke_action(pin, "add_todo", {"title": "X"})
            tid = r["id"]

            t1 = await invoke_action(pin, "toggle_done", {"id": tid})
            assert t1["done"] is True
            t2 = await invoke_action(pin, "toggle_done", {"id": tid})
            assert t2["done"] is False

    @pytest.mark.asyncio
    async def test_toggle_rejects_unknown_id(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            with pytest.raises(ValueError, match="unknown todo id"):
                await invoke_action(pin, "toggle_done", {"id": "no-such-id"})

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            r = await invoke_action(pin, "add_todo", {"title": "X"})
            tid = r["id"]
            d1 = await invoke_action(pin, "delete_todo", {"id": tid})
            assert d1["deleted"] is True
            d2 = await invoke_action(pin, "delete_todo", {"id": tid})
            assert d2["deleted"] is False

    @pytest.mark.asyncio
    async def test_list_orders_undone_first(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            r1 = await invoke_action(pin, "add_todo", {"title": "First"})
            r2 = await invoke_action(pin, "add_todo", {"title": "Second"})
            r3 = await invoke_action(pin, "add_todo", {"title": "Third"})
            # Mark first done → it should slide to the bottom.
            await invoke_action(pin, "toggle_done", {"id": r1["id"]})
            rows = await invoke_action(pin, "list_todos", {})
        assert [row["title"] for row in rows] == ["Second", "Third", "First"]
        assert rows[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_rejects_overlong_title(self, db_session, tmp_path):
        pin = await _seed_pin(db_session, tmp_path)
        with _patches(tmp_path)[0], _patches(tmp_path)[1], _patches(tmp_path)[2]:
            with pytest.raises(ValueError, match="too long"):
                await invoke_action(pin, "add_todo", {"title": "x" * 501})
