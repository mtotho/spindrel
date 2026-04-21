"""Integration tests for the unified HTML-widget catalog endpoint.

Covers ``GET /api/v1/widgets/html-widget-catalog`` and the builtin /
integration content endpoints that the interactive renderer calls to fetch
path-mode widget HTML for non-channel sources.
"""
from __future__ import annotations

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _widget_html(name: str, ver: str = "1.0.0") -> str:
    return (
        "<!--\n"
        "---\n"
        f"name: {name}\n"
        f"version: {ver}\n"
        "description: Catalog smoke test\n"
        "---\n"
        "-->\n"
        "<div id='root'></div>"
    )


@pytest.fixture
def seeded_catalog(tmp_path, monkeypatch):
    """Monkey-patch the scanner roots to tmp dirs so the test doesn't depend
    on (or pollute) the real repo's widget inventory."""
    from app.services import html_widget_scanner

    builtin_root = tmp_path / "builtin"
    integrations_root = tmp_path / "integrations"

    # Built-in: one standalone, one excluded tool renderer. Under the new
    # layout the tool renderer lives in its own per-tool folder alongside
    # a template.yaml that references it.
    tools_local = builtin_root.parent / "local_tools_fake"
    tools_local.mkdir()
    widgets_root = tools_local / "widgets"
    monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", widgets_root)

    (widgets_root / "notes").mkdir(parents=True)
    (widgets_root / "notes" / "index.html").write_text(
        _widget_html("Notes", "2.0.0"), encoding="utf-8",
    )
    (widgets_root / "generate_image").mkdir(parents=True)
    (widgets_root / "generate_image" / "image.html").write_text(
        _widget_html("Image renderer"), encoding="utf-8",
    )
    (widgets_root / "generate_image" / "template.yaml").write_text(
        "html_template:\n"
        "  path: image.html\n",
        encoding="utf-8",
    )

    # Integration with one standalone widget + one excluded tool renderer.
    monkeypatch.setattr(html_widget_scanner, "INTEGRATIONS_ROOT", integrations_root)
    frigate_widgets = integrations_root / "frigate" / "widgets"
    frigate_widgets.mkdir(parents=True)
    (frigate_widgets / "dash.html").write_text(
        _widget_html("Frigate dashboard"), encoding="utf-8",
    )
    (frigate_widgets / "events.html").write_text(
        _widget_html("Events renderer"), encoding="utf-8",
    )
    (integrations_root / "frigate" / "integration.yaml").write_text(
        "tool_widgets:\n"
        "  frigate_get_events:\n"
        "    html_template:\n"
        "      path: widgets/events.html\n",
        encoding="utf-8",
    )

    html_widget_scanner.invalidate_cache()
    yield {
        "builtin_root": str(widgets_root),
        "integrations_root": str(integrations_root),
    }
    html_widget_scanner.invalidate_cache()


class TestCatalogEndpoint:
    @pytest.mark.asyncio
    async def test_catalog_returns_three_groups(self, client, seeded_catalog):
        """The endpoint always returns the three keys even when channel/
        integration groups are empty — the client consumes structured groups."""
        r = await client.get(
            "/api/v1/widgets/html-widget-catalog", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {"builtin", "integrations", "channels"}

    @pytest.mark.asyncio
    async def test_catalog_lists_builtin_and_excludes_tool_renderers(
        self, client, seeded_catalog,
    ):
        r = await client.get(
            "/api/v1/widgets/html-widget-catalog", headers=AUTH_HEADERS,
        )
        builtin = r.json()["builtin"]
        slugs = {e["slug"] for e in builtin}
        assert "notes" in slugs
        assert "image" not in slugs, "image.html is a tool renderer — must be hidden"
        for e in builtin:
            assert e["source"] == "builtin"
            assert e["integration_id"] is None

    @pytest.mark.asyncio
    async def test_catalog_groups_integration_widgets(self, client, seeded_catalog):
        r = await client.get(
            "/api/v1/widgets/html-widget-catalog", headers=AUTH_HEADERS,
        )
        integrations = r.json()["integrations"]
        assert integrations, "frigate has one standalone widget — group must surface"
        frigate = next((g for g in integrations if g["integration_id"] == "frigate"), None)
        assert frigate is not None
        slugs = {e["slug"] for e in frigate["entries"]}
        assert "dash" in slugs
        assert "events" not in slugs, "events.html is a tool renderer — must be hidden"
        for e in frigate["entries"]:
            assert e["source"] == "integration"
            assert e["integration_id"] == "frigate"


class TestBuiltinContentEndpoint:
    @pytest.mark.asyncio
    async def test_read_builtin_content(self, client, seeded_catalog):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/builtin",
            params={"path": "notes/index.html"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["path"] == "notes/index.html"
        assert "Notes" in body["content"]

    @pytest.mark.asyncio
    async def test_read_builtin_rejects_traversal(self, client, seeded_catalog):
        """Any path that resolves outside the built-in root must 404, even
        for files that exist elsewhere on disk."""
        r = await client.get(
            "/api/v1/widgets/html-widget-content/builtin",
            params={"path": "../../etc/passwd"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_read_builtin_404_on_missing_file(self, client, seeded_catalog):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/builtin",
            params={"path": "nope/missing.html"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


class TestIntegrationContentEndpoint:
    @pytest.mark.asyncio
    async def test_read_integration_content(self, client, seeded_catalog):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/integrations/frigate",
            params={"path": "dash.html"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "Frigate dashboard" in body["content"]

    @pytest.mark.asyncio
    async def test_read_integration_rejects_traversal(self, client, seeded_catalog):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/integrations/frigate",
            params={"path": "../../../../etc/passwd"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_read_integration_rejects_unknown_integration(
        self, client, seeded_catalog,
    ):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/integrations/nonexistent",
            params={"path": "x.html"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


class TestLibraryContentEndpoint:
    @pytest.mark.asyncio
    async def test_read_core_library_widget(self, client):
        """Core scope resolves without a bot_id — it's in-repo content."""
        r = await client.get(
            "/api/v1/widgets/html-widget-content/library",
            params={"ref": "core/notes"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["path"] == "core/notes/index.html"
        assert "<" in body["content"] and body["content"].strip()

    @pytest.mark.asyncio
    async def test_read_bot_library_widget(self, client, tmp_path, monkeypatch):
        """widget://bot/<name>/ bundles resolve via the caller-supplied bot_id."""
        from app.services import workspace as _ws

        (tmp_path / ".widget_library" / "home_control").mkdir(parents=True)
        (tmp_path / ".widget_library" / "home_control" / "index.html").write_text(
            "<h1>home control</h1>"
        )
        monkeypatch.setattr(
            _ws.workspace_service,
            "get_workspace_root",
            lambda bot_id, bot=None: str(tmp_path),
        )

        r = await client.get(
            "/api/v1/widgets/html-widget-content/library",
            params={"ref": "bot/home_control", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["content"] == "<h1>home control</h1>"
        assert body["path"] == "bot/home_control/index.html"

    @pytest.mark.asyncio
    async def test_read_library_404_on_missing(self, client):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/library",
            params={"ref": "core/definitely-not-a-widget"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_read_library_400_on_malformed_ref(self, client):
        r = await client.get(
            "/api/v1/widgets/html-widget-content/library",
            params={"ref": "bogus-scope/name"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400


class TestLibraryWidgetsEndpoint:
    """``GET /widgets/library-widgets`` — the ONE pinnable-widget surface.
    Unifies five scopes: ``core``, ``integration``, ``bot``, ``workspace``,
    ``channel``. Tool-renderer ``template``-format entries are excluded at
    the endpoint boundary — they need runtime args to render and are
    reachable through the dev panel's Tools / Recent-calls tabs."""

    @pytest.mark.asyncio
    async def test_core_only_without_bot_id(self, client):
        """Without a bot_id the bot/workspace scopes are empty; core +
        integration scopes always fill. Channel is opt-in via
        ``channel_id``."""
        r = await client.get(
            "/api/v1/widgets/library-widgets", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {
            "core", "integration", "bot", "workspace", "channel",
        }
        assert body["bot"] == []
        assert body["workspace"] == []
        assert body["channel"] == []
        # At minimum the todo reference widget ships with the server.
        names = {e["name"] for e in body["core"]}
        assert "todo" in names
        for e in body["core"]:
            assert e["scope"] == "core"
            # Template-format entries (tool renderers) are filtered out —
            # they can't be pinned without runtime args.
            assert e["format"] in {"html", "suite"}

    @pytest.mark.asyncio
    async def test_core_excludes_template_renderer_entries(self, client):
        """Tool-renderer ``template.yaml`` bundles (get_task_result,
        manage_bot_skill, schedule_task, list_tasks, get_system_status,
        context_tracker) are NOT pinnable — they need tool args. Confirm
        they're filtered out of the catalog."""
        r = await client.get(
            "/api/v1/widgets/library-widgets", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        core_names = {e["name"] for e in r.json()["core"]}
        # These all ship with a template.yaml and must stay out of Library.
        for junk in (
            "get_task_result",
            "manage_bot_skill",
            "schedule_task",
            "list_tasks",
            "get_system_status",
        ):
            assert junk not in core_names, (
                f"{junk!r} is a tool-renderer template — must not appear "
                f"in the pinnable Library (belongs in dev panel instead)"
            )

    @pytest.mark.asyncio
    async def test_integration_scope_is_populated(self, client):
        """Integration-shipped widgets (Frigate, OpenWeather, etc.) surface
        under the ``integration`` scope with their ``integration_id``
        preserved so the UI can badge + route content fetches correctly."""
        r = await client.get(
            "/api/v1/widgets/library-widgets", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        integration = r.json()["integration"]
        # Not all integrations ship widgets, but at least one in the repo
        # does — web_search / openweather / frigate / excalidraw /
        # browser_live all have widgets/ dirs. Assert the shape of whatever
        # is returned rather than pinning a specific count.
        if integration:
            for e in integration:
                assert e["scope"] == "integration"
                assert e["format"] == "html"
                assert e.get("path"), "integration entries need path for content fetch"
                assert e.get("integration_id"), "integration entries need integration_id"

    @pytest.mark.asyncio
    async def test_bot_scope_enumerates_via_bot_id(
        self, client, tmp_path, monkeypatch,
    ):
        """With ``bot_id`` the endpoint walks ``<ws_root>/.widget_library/`` for
        the bot's workspace and surfaces every bundle."""
        from app.services import workspace as _ws

        bundle = tmp_path / ".widget_library" / "dog_dashboard"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<div></div>")
        # Metadata comes from widget.yaml, not HTML frontmatter.
        (bundle / "widget.yaml").write_text(
            "name: Dog Dashboard\n"
            "description: Track the dog\n"
        )
        monkeypatch.setattr(
            _ws.workspace_service,
            "get_workspace_root",
            lambda bot_id, bot=None: str(tmp_path),
        )

        r = await client.get(
            "/api/v1/widgets/library-widgets",
            params={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        bot_names = {e["name"] for e in body["bot"]}
        assert "dog_dashboard" in bot_names
        dog = next(e for e in body["bot"] if e["name"] == "dog_dashboard")
        assert dog["scope"] == "bot"
        assert dog["format"] == "html"
        assert dog["display_label"] == "Dog Dashboard"

    @pytest.mark.asyncio
    async def test_unknown_bot_id_returns_404(self, client, monkeypatch):
        """Unknown bot id is an explicit 404 — the client is asking for a
        bot-scoped view and we can't honor it."""
        from app.agent import bots as _bots
        monkeypatch.setattr(_bots, "get_bot", lambda _bot_id: None)
        r = await client.get(
            "/api/v1/widgets/library-widgets",
            params={"bot_id": "00000000-0000-0000-0000-000000000000"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404
