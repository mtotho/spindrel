"""Integration tests for the dashboard bot tools.

Covers the full flow against a real SQLite-in-memory DB:

  - ``describe_dashboard`` reports ``visible_in_chat`` correctly.
  - ``pin_widget`` lands a builtin widget at first-free-slot.
  - ``move_pins`` updates zone + coords atomically.
  - ``unpin_widget`` removes the row and emits sensible narrative.
  - ``promote_panel`` / ``demote_panel`` round-trip panel mode.

Rather than patch the `async_session` factory everywhere it might get
imported, we patch it on `app.db.engine` — the single import all the
tools use — so every tool call opens a session on the test engine.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WidgetTemplatePackage

@contextmanager
def _patch_tool_engine(engine):
    """Make every tool call open a session on the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch("app.db.engine.async_session", factory):
        yield


@pytest.fixture()
async def channel_id(db_session):
    """Seed a channel + its implicit dashboard so tools have a target."""
    from app.db.models import Channel

    cid = uuid.uuid4()
    ch = Channel(
        id=cid,
        name="test-channel",
        bot_id="test-bot",
    )
    db_session.add(ch)
    await db_session.commit()
    return cid


@pytest.fixture()
async def bot_with_key(db_session):
    """Register a bot in the DB with an active API key — required by the
    interactive-HTML pin flow."""
    from app.db.models import ApiKey, Bot

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="test-key",
        key_hash="hash",
        key_prefix="pfx",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot = Bot(
        id="test-bot",
        name="Test Bot",
        display_name="Test Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot)
    await db_session.commit()
    return bot


# ---------------------------------------------------------------------------
# describe_dashboard
# ---------------------------------------------------------------------------


class TestDescribeDashboard:
    @pytest.mark.asyncio
    async def test_empty_channel_dashboard(self, engine, channel_id):
        from app.agent.context import current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard

        with _patch_tool_engine(engine):
            token = current_channel_id.set(channel_id)
            try:
                raw = await describe_dashboard()
            finally:
                current_channel_id.reset(token)

        result = json.loads(raw)
        assert "error" not in result
        assert result["dashboard_key"] == f"channel:{channel_id}"
        assert result["pins"] == []
        assert "CHAT VIEW" in result["ascii_preview"]
        assert "FULL DASHBOARD VIEW" in result["ascii_preview"]

    @pytest.mark.asyncio
    async def test_errors_without_channel_or_key(self, engine):
        from app.tools.local.dashboard_tools import describe_dashboard

        with _patch_tool_engine(engine):
            raw = await describe_dashboard()

        result = json.loads(raw)
        assert "error" in result
        assert "no dashboard_key" in result["error"]

    @pytest.mark.asyncio
    async def test_visible_in_chat_flag(self, engine, channel_id, bot_with_key):
        """Pins in rail/header/dock should report True; grid False."""
        from app.services.dashboard_pins import apply_layout_bulk, create_pin
        from app.services.dashboards import ensure_channel_dashboard
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            await ensure_channel_dashboard(db, channel_id)
            # Create 3 pins across 3 zones (rail/grid/dock).
            for zone_label in ("rail", "dock", "grid"):
                envelope = {
                    "content_type": "application/vnd.spindrel.components+json",
                    "body": '{"v":1,"components":[]}',
                    "display_label": f"{zone_label}-widget",
                }
                pin = await create_pin(
                    db,
                    source_kind="adhoc",
                    tool_name="test_tool",
                    envelope=envelope,
                    source_channel_id=channel_id,
                    dashboard_key=f"channel:{channel_id}",
                )
                await apply_layout_bulk(
                    db,
                    [{"id": str(pin.id), "x": 0, "y": 0, "w": 1, "h": 1, "zone": zone_label}],
                    dashboard_key=f"channel:{channel_id}",
                )

        from app.agent.context import current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard

        with _patch_tool_engine(engine):
            token = current_channel_id.set(channel_id)
            try:
                raw = await describe_dashboard()
            finally:
                current_channel_id.reset(token)

        result = json.loads(raw)
        pins_by_zone = {p["zone"]: p for p in result["pins"]}
        assert pins_by_zone["rail"]["visible_in_chat"] is True
        assert pins_by_zone["dock"]["visible_in_chat"] is True
        assert pins_by_zone["grid"]["visible_in_chat"] is False

    @pytest.mark.asyncio
    async def test_view_param_chat_only(self, engine, channel_id):
        from app.agent.context import current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard

        with _patch_tool_engine(engine):
            token = current_channel_id.set(channel_id)
            try:
                raw = await describe_dashboard(view="chat")
            finally:
                current_channel_id.reset(token)

        result = json.loads(raw)
        assert "CHAT VIEW" in result["ascii_preview"]
        assert "FULL DASHBOARD VIEW" not in result["ascii_preview"]


# ---------------------------------------------------------------------------
# pin_widget
# ---------------------------------------------------------------------------


def _fake_builtin_entry(slug: str = "mc_kanban") -> dict:
    return {
        "path": f"{slug}/index.html",
        "slug": slug,
        "name": slug.replace("_", " ").title(),
        "description": f"Test widget {slug}",
        "display_label": slug.replace("_", " ").title(),
        "version": "0.0.0",
        "author": None,
        "tags": [],
        "icon": None,
        "is_bundle": True,
        "is_loose": False,
        "has_manifest": False,
        "size": 100,
        "modified_at": 0.0,
        "source": "builtin",
        "integration_id": None,
        "extra_csp": None,
    }


class TestPinWidget:
    @pytest.mark.asyncio
    async def test_pins_builtin_widget_to_channel_dashboard(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="mc_kanban",
                    source_kind="builtin",
                    zone="rail",
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result
        assert result["zone"] == "rail"
        assert result["grid_layout"]["w"] == 1  # rail default
        assert result["grid_layout"]["h"] == 4  # rail default
        assert uuid.UUID(result["pin_id"])  # parseable

    @pytest.mark.asyncio
    async def test_refuses_duplicate_pin(self, engine, channel_id, bot_with_key):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                first = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                ))
                assert "error" not in first, first
                second = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="rail",
                ))
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert "error" in second
        assert "already pinned" in second["error"]

    @pytest.mark.asyncio
    async def test_pins_native_library_widget_and_creates_instance(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="core/notes_native",
                    source_kind="library",
                    zone="grid",
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result
        assert result["tool_name"] == "core/notes_native"
        assert result["widget_instance_id"]

    @pytest.mark.asyncio
    async def test_invoke_widget_action_updates_native_notes(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, invoke_widget_action, pin_widget

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="core/notes_native",
                    source_kind="library",
                    zone="grid",
                ))
                assert "error" not in pin, pin
                action = json.loads(await invoke_widget_action(
                    pin_id=pin["pin_id"],
                    action="replace_body",
                    args={"body": "Buy milk"},
                ))
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert action["ok"] is True
        assert action["result"]["body"] == "Buy milk"
        notes_pin = next(p for p in described["pins"] if p["id"] == pin["pin_id"])
        assert any(a["id"] == "replace_body" for a in notes_pin["available_actions"])
        assert notes_pin["envelope"]["body"]["state"]["body"] == "Buy milk"

    @pytest.mark.asyncio
    async def test_auth_scope_bot_stamps_source_bot_id(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, pin_widget

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                await pin_widget(
                    widget="mc_kanban",
                    source_kind="builtin",
                    zone="grid",
                    auth_scope="bot",
                )
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        pins = described["pins"]
        assert len(pins) == 1
        assert pins[0]["source_bot_id"] == "test-bot"

    @pytest.mark.asyncio
    async def test_auth_scope_user_leaves_bot_id_null(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, pin_widget

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                await pin_widget(
                    widget="mc_kanban",
                    source_kind="builtin",
                    zone="grid",
                    auth_scope="user",  # default
                )
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        pins = described["pins"]
        assert pins[0]["source_bot_id"] is None

    @pytest.mark.asyncio
    async def test_unknown_widget_returns_error(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="nonexistent-widget",
                    source_kind="builtin",
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" in result
        assert "nonexistent-widget" in result["error"]


# ---------------------------------------------------------------------------
# pin_widget — library source (widget:// bundles)
# ---------------------------------------------------------------------------


def _seed_bot_library_widget(ws_root, name: str, body: str = "<p>hi</p>"):
    """Create a widget://bot/<name>/ bundle on disk for tests to resolve."""
    import os as _os
    bundle = _os.path.join(ws_root, ".widget_library", name)
    _os.makedirs(bundle, exist_ok=True)
    with open(_os.path.join(bundle, "index.html"), "w") as f:
        f.write(body)
    return bundle


class TestPinWidgetLibrary:
    @pytest.mark.asyncio
    async def test_pins_bot_library_widget(
        self, engine, channel_id, bot_with_key, tmp_path,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, pin_widget

        _seed_bot_library_widget(str(tmp_path), "home_control")

        with _patch_tool_engine(engine), patch(
            "app.services.workspace.workspace_service.get_workspace_root",
            return_value=str(tmp_path),
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="home_control",
                    source_kind="library",
                    zone="grid",
                )
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result
        assert uuid.UUID(result["pin_id"])
        assert result["zone"] == "grid"

        pins = described["pins"]
        assert len(pins) == 1
        env = pins[0]["envelope"]
        assert env["source_kind"] == "library"
        assert env["source_library_ref"] == "bot/home_control"

    @pytest.mark.asyncio
    async def test_accepts_explicit_bot_scope_prefix(
        self, engine, channel_id, bot_with_key, tmp_path,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        _seed_bot_library_widget(str(tmp_path), "home_control")

        with _patch_tool_engine(engine), patch(
            "app.services.workspace.workspace_service.get_workspace_root",
            return_value=str(tmp_path),
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="bot/home_control",
                    source_kind="library",
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result

    @pytest.mark.asyncio
    async def test_accepts_widget_uri_input(
        self, engine, channel_id, bot_with_key, tmp_path,
    ):
        """`widget://bot/home_control/index.html` is accepted; trailing path stripped."""
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, pin_widget

        _seed_bot_library_widget(str(tmp_path), "home_control")

        with _patch_tool_engine(engine), patch(
            "app.services.workspace.workspace_service.get_workspace_root",
            return_value=str(tmp_path),
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="widget://bot/home_control/index.html",
                    source_kind="library",
                )
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert "error" not in json.loads(raw)
        env = described["pins"][0]["envelope"]
        assert env["source_library_ref"] == "bot/home_control"

    @pytest.mark.asyncio
    async def test_refuses_duplicate_library_pin(
        self, engine, channel_id, bot_with_key, tmp_path,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        _seed_bot_library_widget(str(tmp_path), "home_control")

        with _patch_tool_engine(engine), patch(
            "app.services.workspace.workspace_service.get_workspace_root",
            return_value=str(tmp_path),
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                first = json.loads(await pin_widget(
                    widget="home_control", source_kind="library", zone="grid",
                ))
                assert "error" not in first, first
                second = json.loads(await pin_widget(
                    widget="home_control", source_kind="library", zone="rail",
                ))
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert "error" in second
        assert "already pinned" in second["error"]

    @pytest.mark.asyncio
    async def test_unknown_library_widget_returns_error(
        self, engine, channel_id, bot_with_key, tmp_path,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import pin_widget

        # No bundle seeded — resolution must fail cleanly.
        with _patch_tool_engine(engine), patch(
            "app.services.workspace.workspace_service.get_workspace_root",
            return_value=str(tmp_path),
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await pin_widget(
                    widget="nonexistent_widget",
                    source_kind="library",
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_pins_template_tool_renderer_as_adhoc_widget(
        self, engine, db_session, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import describe_dashboard, pin_widget

        db_session.add(WidgetTemplatePackage(
            tool_name="fake_template_tool",
            name="fake template tool",
            yaml_template=(
                "display: inline\n"
                "display_label: 'Hello {{name}}'\n"
                "template:\n"
                "  v: 1\n"
                "  components:\n"
                "    - type: heading\n"
                "      text: 'Hi {{name}}'\n"
                "      level: 3\n"
            ),
            source="user",
            is_readonly=False,
            is_active=True,
            content_hash="hash-template-pin",
            version=1,
        ))
        await db_session.commit()

        async def _call_local_tool(name: str, args_json: str) -> str:
            assert name == "fake_template_tool"
            args = json.loads(args_json)
            return json.dumps({"name": args.get("name", "missing")})

        with _patch_tool_engine(engine):
            with patch("app.tools.registry.is_local_tool", lambda name: name == "fake_template_tool"), patch(
                "app.tools.registry.call_local_tool",
                _call_local_tool,
            ), patch(
                "app.tools.registry.get_tool_context_requirements",
                lambda name: (True, False),
            ):
                ch_tok = current_channel_id.set(channel_id)
                bot_tok = current_bot_id.set("test-bot")
                try:
                    raw = await pin_widget(
                        widget="fake_template_tool",
                        source_kind="library",
                        auth_scope="bot",
                        tool_args={"name": "Template"},
                    )
                    described = json.loads(await describe_dashboard())
                finally:
                    current_channel_id.reset(ch_tok)
                    current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result
        pins = described["pins"]
        assert len(pins) == 1
        assert pins[0]["tool_name"] == "fake_template_tool"
        assert pins[0]["tool_args"] == {"name": "Template"}
        body = json.loads(pins[0]["envelope"]["body"])
        assert body["components"][0]["text"] == "Hi Template"


# ---------------------------------------------------------------------------
# move_pins
# ---------------------------------------------------------------------------


class TestMovePins:
    @pytest.mark.asyncio
    async def test_moves_pin_zone_and_coords(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            describe_dashboard, move_pins, pin_widget,
        )

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                ))
                pid = pin["pin_id"]

                moved = json.loads(await move_pins(
                    moves=[{"pin_id": pid, "zone": "dock", "x": 0, "y": 2, "w": 1, "h": 3}],
                ))
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert moved["updated"] == 1
        assert "error" not in moved
        assert described["pins"][0]["zone"] == "dock"
        assert described["pins"][0]["grid_layout"] == {"x": 0, "y": 2, "w": 1, "h": 3}

    @pytest.mark.asyncio
    async def test_move_preserves_omitted_fields_within_zone(
        self, engine, channel_id, bot_with_key,
    ):
        """When only x/y change, w/h should retain current values.

        A zone change can legitimately clamp coords via
        ``_normalize_zone_coords`` (header forces h=1; rail/dock force w=1),
        so we verify preservation inside the same zone.
        """
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            describe_dashboard, move_pins, pin_widget,
        )

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                    x=0, y=0, w=4, h=4,
                ))
                pid = pin["pin_id"]

                # Change only x/y (stay in grid). w/h should preserve.
                await move_pins(moves=[{"pin_id": pid, "x": 6, "y": 4}])
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert described["pins"][0]["zone"] == "grid"
        # Coords updated.
        assert described["pins"][0]["grid_layout"]["x"] == 6
        assert described["pins"][0]["grid_layout"]["y"] == 4
        # Preserved from the original pin_widget call.
        assert described["pins"][0]["grid_layout"]["w"] == 4
        assert described["pins"][0]["grid_layout"]["h"] == 4

    @pytest.mark.asyncio
    async def test_move_to_header_normalizes_h_to_1(
        self, engine, channel_id, bot_with_key,
    ):
        """Moving to header zone clamps h=1 via the service's
        ``_normalize_zone_coords`` — header pins are always single-row."""
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            describe_dashboard, move_pins, pin_widget,
        )

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                    x=0, y=0, w=4, h=4,
                ))
                pid = pin["pin_id"]

                await move_pins(moves=[{"pin_id": pid, "zone": "header"}])
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert described["pins"][0]["zone"] == "header"
        # Clamped by _normalize_zone_coords.
        assert described["pins"][0]["grid_layout"]["h"] == 1
        assert described["pins"][0]["grid_layout"]["y"] == 0
        # Width preserved.
        assert described["pins"][0]["grid_layout"]["w"] == 4

    @pytest.mark.asyncio
    async def test_rejects_unknown_pin_id(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_channel_id
        from app.tools.local.dashboard_tools import move_pins

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            try:
                raw = await move_pins(
                    moves=[{"pin_id": str(uuid.uuid4()), "zone": "rail"}],
                )
            finally:
                current_channel_id.reset(ch_tok)

        result = json.loads(raw)
        assert "error" in result
        assert "not on dashboard" in result["error"]


# ---------------------------------------------------------------------------
# unpin_widget
# ---------------------------------------------------------------------------


class TestUnpinWidget:
    @pytest.mark.asyncio
    async def test_unpins_existing_widget(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            describe_dashboard, pin_widget, unpin_widget,
        )

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                ))
                pid = pin["pin_id"]

                unpin = json.loads(await unpin_widget(pin_id=pid))
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        assert unpin["ok"] is True
        assert described["pins"] == []

    @pytest.mark.asyncio
    async def test_invalid_pin_id_returns_error(self, engine):
        from app.tools.local.dashboard_tools import unpin_widget

        with _patch_tool_engine(engine):
            raw = await unpin_widget(pin_id="not-a-uuid")

        result = json.loads(raw)
        assert "error" in result
        assert "invalid pin_id" in result["error"]


# ---------------------------------------------------------------------------
# promote_panel / demote_panel
# ---------------------------------------------------------------------------


class TestPanelMode:
    @pytest.mark.asyncio
    async def test_promote_then_demote_round_trip(
        self, engine, channel_id, bot_with_key,
    ):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            demote_panel, describe_dashboard, pin_widget, promote_panel,
        )

        with _patch_tool_engine(engine), patch(
            "app.services.html_widget_scanner.scan_builtin",
            return_value=[_fake_builtin_entry("mc_kanban")],
        ):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                pin = json.loads(await pin_widget(
                    widget="mc_kanban", source_kind="builtin", zone="grid",
                ))
                pid = pin["pin_id"]

                prom = json.loads(await promote_panel(pin_id=pid))
                assert "error" not in prom
                assert prom["pin"]["is_main_panel"] is True

                described_after_promote = json.loads(await describe_dashboard())
                assert "Panel mode" in described_after_promote["ascii_preview"]

                dem = json.loads(await demote_panel(pin_id=pid))
                assert "error" not in dem
                assert dem["pin"]["is_main_panel"] is False
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)


class TestSetDashboardChrome:
    @pytest.mark.asyncio
    async def test_set_borderless_only(self, engine, channel_id, bot_with_key):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import (
            describe_dashboard, set_dashboard_chrome,
        )

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await set_dashboard_chrome(borderless=True)
                described = json.loads(await describe_dashboard())
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" not in result, result
        assert result["grid_config"].get("borderless") is True
        # hover_scrollbars not set → absent or False.
        assert result["grid_config"].get("hover_scrollbars") in (None, False)
        # Dashboard actually persists the update.
        assert described["dashboard"]["grid_config"].get("borderless") is True

    @pytest.mark.asyncio
    async def test_set_both_flags(self, engine, channel_id, bot_with_key):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import set_dashboard_chrome

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await set_dashboard_chrome(
                    borderless=True, hover_scrollbars=True,
                )
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert result["grid_config"]["borderless"] is True
        assert result["grid_config"]["hover_scrollbars"] is True

    @pytest.mark.asyncio
    async def test_preserves_preset(self, engine, channel_id, bot_with_key):
        """Chrome change must NOT clobber existing preset."""
        from app.agent.context import current_bot_id, current_channel_id
        from app.services.dashboards import ensure_channel_dashboard, update_dashboard
        from app.tools.local.dashboard_tools import set_dashboard_chrome
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            await ensure_channel_dashboard(db, channel_id)
            await update_dashboard(
                db, f"channel:{channel_id}",
                {"grid_config": {"layout_type": "grid", "preset": "fine"}},
            )

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await set_dashboard_chrome(borderless=True)
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert result["grid_config"]["borderless"] is True
        # Preset preserved.
        assert result["grid_config"]["preset"] == "fine"
        assert result["grid_config"]["layout_type"] == "grid"

    @pytest.mark.asyncio
    async def test_empty_call_is_rejected(self, engine, channel_id, bot_with_key):
        from app.agent.context import current_bot_id, current_channel_id
        from app.tools.local.dashboard_tools import set_dashboard_chrome

        with _patch_tool_engine(engine):
            ch_tok = current_channel_id.set(channel_id)
            bot_tok = current_bot_id.set("test-bot")
            try:
                raw = await set_dashboard_chrome()
            finally:
                current_channel_id.reset(ch_tok)
                current_bot_id.reset(bot_tok)

        result = json.loads(raw)
        assert "error" in result
        assert "at least one" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
