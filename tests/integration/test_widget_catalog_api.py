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
