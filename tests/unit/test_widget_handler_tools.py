"""Unit tests for app.services.widget_handler_tools — the bot↔widget bridge.

Covers:
- list_widget_handler_tools picks up bot-callable handlers from channel pins
- bot-owned pins on other dashboards (global:*) are visible
- bot_callable=false handlers are filtered out
- slug collisions get deterministic hash suffixes
- resolve_widget_handler is the inverse mapping
- is_widget_handler_tool_name correctly classifies names
- broken manifest yaml doesn't poison the whole tool pool
"""
from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import ApiKey, Bot, WidgetDashboard, WidgetDashboardPin
from app.services.widget_handler_tools import (
    TOOL_NAME_PREFIX,
    _safe_slug,
    is_widget_handler_tool_name,
    list_widget_handler_tools,
    resolve_widget_handler,
)
from app.services.widget_py import clear_module_cache


_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000099")
_BOT_ID = "handler-bot"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_module_cache()
    yield
    clear_module_cache()


def _make_bot() -> BotConfig:
    return BotConfig(
        id=_BOT_ID,
        name="Handler Bot",
        model="test/model",
        system_prompt="",
        memory=MemoryConfig(enabled=False),
    )


def _ws_root_patches(ws_root: Path):
    return (
        patch("app.agent.bots.get_bot", return_value=_make_bot()),
        patch(
            "app.services.channel_workspace.get_channel_workspace_root",
            return_value=str(ws_root),
        ),
    )


def _write_bundle(bundle_dir: Path, yaml_body: str) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "index.html").write_text("<!-- test -->")
    (bundle_dir / "widget.yaml").write_text(textwrap.dedent(yaml_body).lstrip())
    (bundle_dir / "widget.py").write_text("")


async def _seed_dashboard(db_session, slug: str) -> None:
    existing = await db_session.get(WidgetDashboard, slug)
    if existing is None:
        db_session.add(WidgetDashboard(slug=slug, name=slug))
        await db_session.flush()


async def _seed_bot(db_session) -> None:
    existing = await db_session.get(Bot, _BOT_ID)
    if existing is not None:
        return
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="handler-key",
        key_hash="handlerhash",
        key_prefix="handler-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    db_session.add(Bot(
        id=_BOT_ID, name="Handler Bot", display_name="Handler Bot",
        model="test/model", system_prompt="", api_key_id=api_key.id,
    ))
    await db_session.flush()


async def _seed_pin(
    db_session, *, bundle_rel: str, dashboard_key: str = "default",
    display_label: str | None = None, position: int = 0,
) -> WidgetDashboardPin:
    await _seed_bot(db_session)
    await _seed_dashboard(db_session, dashboard_key)
    pin = WidgetDashboardPin(
        dashboard_key=dashboard_key,
        position=position,
        source_kind="adhoc",
        source_channel_id=_CHANNEL_ID,
        source_bot_id=_BOT_ID,
        tool_name="emit_html_widget",
        tool_args={},
        widget_config={},
        display_label=display_label,
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "",
            "source_path": f"{bundle_rel}/index.html",
            "source_channel_id": str(_CHANNEL_ID),
            "source_bot_id": _BOT_ID,
        },
        grid_layout={"x": 0, "y": 0, "w": 6, "h": 6},
    )
    db_session.add(pin)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(pin)
    return pin


_TODO_MANIFEST = """
    name: Todo
    version: 1.0.0
    description: Todo list
    handlers:
      - name: list_todos
        description: List todos for this pin.
        bot_callable: true
        safety_tier: readonly
      - name: add_todo
        description: Add a todo to this list.
        triggers: [add todo, remember to]
        args:
          title:
            type: string
            description: Task text
            required: true
        returns:
          type: object
          properties:
            id: {type: string}
        bot_callable: true
        safety_tier: mutating
      - name: internal_helper
        description: Not bot-callable.
        bot_callable: false
"""


class TestSafeSlug:
    def test_lowercases_and_dashes(self):
        assert _safe_slug("MC Tasks") == "mc-tasks"
        assert _safe_slug("My Widget!!") == "my-widget"

    def test_empty_falls_back(self):
        assert _safe_slug("") == "widget"
        assert _safe_slug("---") == "widget"

    def test_bounds_length(self):
        assert len(_safe_slug("a" * 200)) == 48


class TestIsWidgetHandlerToolName:
    def test_widget_prefix_with_two_segments(self):
        assert is_widget_handler_tool_name("widget.todo.add_todo") is True

    def test_widget_prefix_without_handler(self):
        assert is_widget_handler_tool_name("widget.todo") is False

    def test_other_tool_namespaces(self):
        assert is_widget_handler_tool_name("get_weather") is False
        assert is_widget_handler_tool_name("mcp:server:tool") is False


class TestListWidgetHandlerTools:
    @pytest.mark.asyncio
    async def test_returns_bot_callable_only(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)

        pin = await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, resolver = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )

        names = sorted(s["function"]["name"] for s in schemas)
        assert names == ["widget.todo.add_todo", "widget.todo.list_todos"]
        # internal_helper is NOT exposed.
        assert "widget.todo.internal_helper" not in names

        assert "widget.todo.add_todo" in resolver
        pin_resolved, handler_name, tier = resolver["widget.todo.add_todo"]
        assert pin_resolved.id == pin.id
        assert handler_name == "add_todo"
        assert tier == "mutating"

        # list_todos is readonly per manifest.
        _, _, list_tier = resolver["widget.todo.list_todos"]
        assert list_tier == "readonly"

    @pytest.mark.asyncio
    async def test_args_schema_assembled_from_manifest(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)
        await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, _ = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )

        add = next(s for s in schemas if s["function"]["name"] == "widget.todo.add_todo")
        params = add["function"]["parameters"]
        assert params["type"] == "object"
        assert "title" in params["properties"]
        assert params["properties"]["title"]["type"] == "string"
        assert params["required"] == ["title"]
        # Description is prefixed with [DisplayName].
        assert add["function"]["description"].startswith("[")

    @pytest.mark.asyncio
    async def test_no_pins_returns_empty(self, db_session, tmp_path):
        bot_patch, ws_patch = _ws_root_patches(tmp_path)
        with bot_patch, ws_patch:
            schemas, resolver = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )
        assert schemas == []
        assert resolver == {}

    @pytest.mark.asyncio
    async def test_missing_handlers_block_ignored(self, db_session, tmp_path):
        """Pins whose widget.yaml has no handlers: block yield no tools."""
        ws_root = tmp_path / "workspace"
        _write_bundle(
            ws_root / "data" / "widgets" / "plain",
            """
                name: Plain
                version: 1.0.0
                description: No handlers
            """,
        )
        await _seed_pin(
            db_session,
            bundle_rel="data/widgets/plain",
            dashboard_key=f"channel:{_CHANNEL_ID}",
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, resolver = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )
        assert schemas == []
        assert resolver == {}

    @pytest.mark.asyncio
    async def test_slug_collision_gets_hash_suffix(self, db_session, tmp_path):
        """Two pins of the same widget on one channel → deterministic suffixes."""
        ws_root = tmp_path / "workspace"
        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)

        p1 = await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
            display_label="Groceries",
            position=0,
        )
        p2 = await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
            display_label="Work",
            position=1,
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, resolver = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )

        names = sorted(s["function"]["name"] for s in schemas)
        # Four handlers — two per pin, one is filtered out (internal_helper).
        # So 2 pins × 2 bot-callable = 4 tools total.
        assert len(names) == 4
        # All names include a `~hash` suffix because of the collision.
        assert all("~" in n for n in names)
        # Hashes are pin-deterministic.
        pin_ids = {p.id for p in (p1, p2)}
        resolved_pins = {pin.id for (pin, _, _) in resolver.values()}
        assert resolved_pins == pin_ids

    @pytest.mark.asyncio
    async def test_bot_owned_global_pin_visible(self, db_session, tmp_path):
        """A pin on a non-channel dashboard but owned by the calling bot is visible."""
        ws_root = tmp_path / "workspace"
        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)

        # Pin on global:personal, not on the channel dashboard.
        await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key="global:personal",
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, _ = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )

        names = {s["function"]["name"] for s in schemas}
        assert "widget.todo.add_todo" in names


class TestResolveWidgetHandler:
    @pytest.mark.asyncio
    async def test_roundtrips_by_tool_name(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)
        pin = await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            resolved = await resolve_widget_handler(
                db_session, "widget.todo.add_todo", _BOT_ID, str(_CHANNEL_ID),
            )
        assert resolved is not None
        resolved_pin, handler, tier = resolved
        assert resolved_pin.id == pin.id
        assert handler == "add_todo"
        assert tier == "mutating"

    @pytest.mark.asyncio
    async def test_non_widget_prefix_returns_none(self, db_session, tmp_path):
        resolved = await resolve_widget_handler(
            db_session, "some_other_tool", _BOT_ID, str(_CHANNEL_ID),
        )
        assert resolved is None

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_none(self, db_session, tmp_path):
        bot_patch, ws_patch = _ws_root_patches(tmp_path)
        with bot_patch, ws_patch:
            resolved = await resolve_widget_handler(
                db_session, "widget.ghost.do_thing", _BOT_ID, str(_CHANNEL_ID),
            )
        assert resolved is None


class TestManifestErrorResilience:
    @pytest.mark.asyncio
    async def test_malformed_yaml_skipped_not_raised(self, db_session, tmp_path):
        """Broken widget.yaml on one pin should not poison the whole list."""
        ws_root = tmp_path / "workspace"
        broken_dir = ws_root / "data" / "widgets" / "broken"
        broken_dir.mkdir(parents=True, exist_ok=True)
        (broken_dir / "index.html").write_text("<!-- test -->")
        # Missing required 'name' → ManifestError on parse.
        (broken_dir / "widget.yaml").write_text("version: 1.0.0\n")
        (broken_dir / "widget.py").write_text("")

        _write_bundle(ws_root / "data" / "widgets" / "todo", _TODO_MANIFEST)

        await _seed_pin(
            db_session,
            bundle_rel="data/widgets/broken",
            dashboard_key=f"channel:{_CHANNEL_ID}",
            position=0,
        )
        await _seed_pin(
            db_session,
            bundle_rel="data/widgets/todo",
            dashboard_key=f"channel:{_CHANNEL_ID}",
            position=1,
        )
        await _seed_dashboard(db_session, f"channel:{_CHANNEL_ID}")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            schemas, _ = await list_widget_handler_tools(
                db_session, _BOT_ID, str(_CHANNEL_ID),
            )
        # The healthy pin's handlers still surface despite the broken neighbour.
        names = {s["function"]["name"] for s in schemas}
        assert "widget.todo.add_todo" in names
