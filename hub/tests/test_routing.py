"""Tests for hub reverse-proxy routing."""

import json
import os
import sys
import tempfile
import threading
import time
import socketserver
import urllib.request
import urllib.error

import pytest

# Ensure hub dir is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from serve import resolve_bot_route, BOT_ROUTES, BOTS_DIR, HubHandler


# ---------------------------------------------------------------------------
# Unit tests for resolve_bot_route
# ---------------------------------------------------------------------------


class TestResolveRoute:
    """Unit tests for route resolution logic."""

    def test_crumb_index(self, tmp_path, monkeypatch):
        """/ crumb/ resolves to baking-bot/web/index.html."""
        web = tmp_path / "baking-bot" / "web"
        web.mkdir(parents=True)
        (web / "index.html").write_text("<h1>Crumb</h1>")

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/crumb/")
        assert err is None
        assert path.endswith("index.html")

    def test_crumb_subpath(self, tmp_path, monkeypatch):
        """/crumb/style.css resolves to baking-bot/web/style.css."""
        web = tmp_path / "baking-bot" / "web"
        web.mkdir(parents=True)
        (web / "style.css").write_text("body{}")

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/crumb/style.css")
        assert err is None
        assert path.endswith("style.css")

    def test_crumb_data_route(self, tmp_path, monkeypatch):
        """/crumb/data/status.json serves from baking-bot/data/."""
        data = tmp_path / "baking-bot" / "data"
        data.mkdir(parents=True)
        (data / "status.json").write_text('{"ok":true}')

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/crumb/data/status.json")
        assert err is None
        assert "data" in path
        assert path.endswith("status.json")

    def test_garden_route(self, tmp_path, monkeypatch):
        """/garden/ resolves to olivia-bot/web/index.html."""
        web = tmp_path / "olivia-bot" / "web"
        web.mkdir(parents=True)
        (web / "index.html").write_text("<h1>Garden</h1>")

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/garden/")
        assert err is None
        assert path.endswith("index.html")

    def test_missing_bot_dir_returns_not_found(self, tmp_path, monkeypatch):
        """Bot web dir doesn't exist → not_found."""
        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/haos/")
        assert path is None
        assert err == "not_found"

    def test_missing_file_returns_not_found(self, tmp_path, monkeypatch):
        """Bot dir exists but file doesn't → not_found."""
        web = tmp_path / "baking-bot" / "web"
        web.mkdir(parents=True)

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/crumb/nonexistent.js")
        assert path is None
        assert err == "not_found"

    def test_no_match_returns_no_match(self):
        """Unrecognized prefix → no_match (fall through to hub)."""
        path, err = resolve_bot_route("/api/bots")
        assert path is None
        assert err == "no_match"

    def test_hub_root_no_match(self):
        """Hub root → no_match."""
        path, err = resolve_bot_route("/index.html")
        assert path is None
        assert err == "no_match"

    def test_path_traversal_blocked(self, tmp_path, monkeypatch):
        """Path traversal attempts are blocked."""
        web = tmp_path / "baking-bot" / "web"
        web.mkdir(parents=True)
        (web / "index.html").write_text("ok")

        monkeypatch.setattr("serve.BOTS_DIR", str(tmp_path))
        path, err = resolve_bot_route("/crumb/../../etc/passwd")
        assert path is None
        assert err in ("not_found", "forbidden")


# ---------------------------------------------------------------------------
# Integration tests — live server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_server():
    """Start a hub server on a random port for integration tests."""
    hub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    original_dir = os.getcwd()
    os.chdir(hub_dir)

    port = 18437
    for attempt in range(5):
        try:
            server = socketserver.TCPServer(("127.0.0.1", port + attempt), HubHandler)
            port = port + attempt
            break
        except OSError:
            continue
    else:
        pytest.skip("Could not find free port")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    os.chdir(original_dir)


class TestBotStatusAPI:
    """Tests for /api/bot-status/<id> endpoint."""

    def test_existing_bot(self, live_server):
        """Returns JSON for a bot with status.json."""
        # dev_bot has status.json
        resp = urllib.request.urlopen(f"{live_server}/api/bot-status/dev_bot")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data.get("bot_id") == "dev_bot"

    def test_missing_bot_404(self, live_server):
        """Returns 404 for nonexistent bot."""
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{live_server}/api/bot-status/nonexistent_xyz")
        assert exc_info.value.code == 404


class TestBotDashboardRouting:
    """Integration tests for bot dashboard reverse-proxy routes."""

    def test_crumb_serves_baking_bot(self, live_server):
        """If baking-bot/web/index.html exists, /crumb/ serves it."""
        index = os.path.join(BOTS_DIR, 'baking-bot', 'web', 'index.html')
        if not os.path.isfile(index):
            pytest.skip("baking-bot/web/index.html not present")
        resp = urllib.request.urlopen(f"{live_server}/crumb/")
        assert resp.status == 200

    def test_nonexistent_bot_web_404(self, live_server):
        """Bot route where web dir doesn't exist returns 404."""
        # haos-bot/web likely doesn't exist
        bot_web = os.path.join(BOTS_DIR, 'haos-bot', 'web')
        if os.path.isdir(bot_web):
            pytest.skip("haos-bot/web exists, can't test 404")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{live_server}/haos/")
        assert exc_info.value.code == 404


class TestHubRootServing:
    """Hub root still serves correctly."""

    def test_index_html(self, live_server):
        """Hub index.html is served at root."""
        resp = urllib.request.urlopen(f"{live_server}/index.html")
        assert resp.status == 200
        html = resp.read().decode()
        assert "Thoth Hub" in html

    def test_nav_links_present(self, live_server):
        """Nav links for bot dashboards are in index.html."""
        resp = urllib.request.urlopen(f"{live_server}/index.html")
        html = resp.read().decode()
        assert '/crumb/' in html
        assert '/garden/' in html
        assert '/haos/' in html
        assert '/sag/' in html
