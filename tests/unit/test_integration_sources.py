"""Integration source resolver regressions.

External integrations under SPINDREL_HOME/HOME_LOCAL_DIR must be visible to
every integration-owned surface, not only catalog/setup discovery.
"""
from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def test_iter_integration_sources_uses_external_override(tmp_path, monkeypatch):
    from integrations import discovery

    repo = tmp_path / "repo-integrations"
    packages = tmp_path / "packages"
    external = tmp_path / "spindrel-home"
    for base in (repo, packages, external):
        (base / "weather").mkdir(parents=True)
    (repo / "repo_only").mkdir()

    monkeypatch.setattr(discovery, "_INTEGRATIONS_DIR", repo)
    monkeypatch.setattr(discovery, "_PACKAGES_DIR", packages)
    monkeypatch.setattr(discovery, "all_integration_dirs", lambda: [repo, packages, external])

    sources = {source.integration_id: source for source in discovery.iter_integration_sources()}

    assert sources["weather"].path == (external / "weather").resolve()
    assert sources["weather"].source == "external"
    assert sources["weather"].is_external is True
    assert sources["repo_only"].path == (repo / "repo_only").resolve()
    assert sources["repo_only"].source == "integration"


def test_resolve_integration_path_rejects_traversal(tmp_path, monkeypatch):
    from integrations import discovery

    base = tmp_path / "spindrel-home"
    (base / "safe" / "widgets").mkdir(parents=True)
    monkeypatch.setattr(discovery, "all_integration_dirs", lambda: [base])

    resolved = discovery.resolve_integration_path("safe", "widgets")
    assert resolved == (base / "safe" / "widgets").resolve()
    assert discovery.resolve_integration_path("../safe", "widgets") is None
    assert discovery.resolve_integration_path("safe", "widgets", "..", "..") is None


def test_external_integration_widgets_are_scanned_and_excluded(tmp_path, monkeypatch):
    from app.services import html_widget_scanner
    from integrations.discovery import IntegrationSource

    root = tmp_path / "spindrel-home" / "bennieloggins"
    _write(
        root / "widgets" / "status.html",
        """\
        <!--
        ---
        name: Bennie Status
        description: External status
        version: 1.0.0
        ---
        -->
        <div>Bennie</div>
        """,
    )
    _write(
        root / "widgets" / "tool_renderer.html",
        """\
        <!--
        ---
        name: Tool renderer
        ---
        -->
        <div>tool</div>
        """,
    )
    _write(
        root / "integration.yaml",
        """\
        id: bennieloggins
        tool_widgets:
          external_tool:
            html_template:
              path: widgets/tool_renderer.html
        """,
    )
    monkeypatch.setattr(html_widget_scanner, "BUILTIN_WIDGET_ROOT", tmp_path / "missing")
    monkeypatch.setattr(
        "integrations.discovery.iter_integration_sources",
        lambda: [
            IntegrationSource(
                integration_id="bennieloggins",
                path=root.resolve(),
                source="external",
                is_external=True,
            )
        ],
    )

    groups = html_widget_scanner.scan_all_integrations()

    assert [(group_id, [entry["slug"] for entry in entries]) for group_id, entries in groups] == [
        ("bennieloggins", ["status"])
    ]


@pytest.mark.asyncio
async def test_external_integration_widget_content_and_manifest_resolve(tmp_path, monkeypatch):
    from app.routers.api_v1_widgets import library
    from app.services import widget_contracts
    from integrations.discovery import IntegrationSource

    root = tmp_path / "spindrel-home" / "bennieloggins"
    _write(root / "widgets" / "status" / "index.html", "<div>Bennie</div>")
    _write(
        root / "widgets" / "status" / "widget.yaml",
        """\
        name: Bennie Status
        version: 1.0.0
        description: External status
        """,
    )
    monkeypatch.setattr(
        "integrations.discovery.iter_integration_sources",
        lambda: [
            IntegrationSource(
                integration_id="bennieloggins",
                path=root.resolve(),
                source="external",
                is_external=True,
            )
        ],
    )

    content = await library.read_integration_widget_content(
        integration_id="bennieloggins",
        path="status/index.html",
    )
    manifest = await library.get_widget_manifest(
        db=None,
        scope="integration",
        integration_id="bennieloggins",
        path="status/index.html",
    )
    manifest_path = widget_contracts._resolve_html_widget_manifest_path(
        {
            "source_kind": "integration",
            "source_integration_id": "bennieloggins",
            "source_path": "status/index.html",
        },
        source_bot_id=None,
    )

    assert content["content"] == "<div>Bennie</div>"
    assert manifest["manifest"]["name"] == "Bennie Status"
    assert manifest_path == root.resolve() / "widgets" / "status" / "widget.yaml"


def test_external_integration_widget_py_bundle_resolves(tmp_path, monkeypatch):
    from app.services import widget_py
    from integrations.discovery import IntegrationSource

    root = tmp_path / "spindrel-home" / "bennieloggins"
    _write(
        root / "widgets" / "status" / "widget.py",
        """\
        from spindrel.widget import on_action

        @on_action("ping")
        def ping(args):
            return {"ok": True}
        """,
    )
    monkeypatch.setattr(
        "integrations.discovery.iter_integration_sources",
        lambda: [
            IntegrationSource(
                integration_id="bennieloggins",
                path=root.resolve(),
                source="external",
                is_external=True,
            )
        ],
    )
    pin = SimpleNamespace(
        envelope={
            "source_kind": "integration",
            "source_integration_id": "bennieloggins",
            "source_path": "status/index.html",
        },
        source_channel_id=uuid.uuid4(),
        source_bot_id=None,
    )

    bundle_dir = widget_py._resolve_bundle_dir(pin)

    assert bundle_dir == root.resolve() / "widgets" / "status"


def test_external_integration_harnesses_are_discovered(tmp_path, monkeypatch):
    from app.services import agent_harnesses
    from integrations.discovery import IntegrationSource

    root = tmp_path / "spindrel-home" / "bennieloggins"
    _write(
        root / "harness.py",
        """\
        from app.services.agent_harnesses import register_runtime

        register_runtime("bennie-runtime", object())
        """,
    )
    monkeypatch.setattr(
        "integrations.discovery.iter_integration_sources",
        lambda: [
            IntegrationSource(
                integration_id="bennieloggins",
                path=root.resolve(),
                source="external",
                is_external=True,
            )
        ],
    )

    agent_harnesses.HARNESS_REGISTRY.pop("bennie-runtime", None)
    try:
        with patch("app.services.integration_settings.is_active", return_value=True):
            agent_harnesses.discover_and_load_harnesses()
        assert "bennie-runtime" in agent_harnesses.HARNESS_REGISTRY
    finally:
        agent_harnesses.HARNESS_REGISTRY.pop("bennie-runtime", None)


def test_scaffold_dir_uses_effective_external_integration_dirs(tmp_path):
    from app.tools.local import admin_integrations

    root = tmp_path / "spindrel-home"
    root.mkdir()

    with patch("app.services.paths.effective_integration_dirs", return_value=[str(root)]):
        assert admin_integrations._get_scaffold_dir() == root.resolve()
