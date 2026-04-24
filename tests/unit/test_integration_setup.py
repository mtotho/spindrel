"""Unit tests for integration setup status discovery."""
import os
from unittest.mock import patch

import pytest


class TestDiscoverSetupStatus:
    def test_returns_list(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_entry_shape(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        for entry in results:
            assert "id" in entry
            assert "name" in entry
            assert "status" in entry
            assert entry["status"] in ("ready", "partial", "not_configured")
            assert isinstance(entry["env_vars"], list)
            assert isinstance(entry["has_router"], bool)
            assert isinstance(entry["has_dispatcher"], bool)
            assert isinstance(entry["has_hooks"], bool)
            assert isinstance(entry["has_tools"], bool)

    def test_env_var_shape(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        for entry in results:
            for var in entry["env_vars"]:
                assert "key" in var
                assert "required" in var
                assert "description" in var
                assert "is_set" in var
                assert isinstance(var["is_set"], bool)

    def test_slack_integration_discovered(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        slack = next((r for r in results if r["id"] == "slack"), None)
        assert slack is not None
        assert slack["has_router"] is True
        # Phase F: legacy dispatcher.py was deleted; SlackRenderer
        # superseded it. The discovery scanner doesn't yet flag
        # renderer.py separately, so we just assert that one of the
        # delivery files is present rather than the literal old shape.
        assert slack["has_hooks"] is True
        # Should have env vars from setup.py
        keys = [v["key"] for v in slack["env_vars"]]
        assert "SLACK_BOT_TOKEN" in keys
        assert "SLACK_APP_TOKEN" in keys

    def test_example_integration_discovered(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        example = next((r for r in results if r["id"] == "example"), None)
        assert example is not None
        assert example["has_router"] is True

    def test_github_integration_discovered(self):
        from integrations import discover_setup_status
        from pathlib import Path
        gh_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "github"
        if not gh_dir.is_dir():
            pytest.skip("integrations/github not present")
        results = discover_setup_status()
        gh = next((r for r in results if r["id"] == "github"), None)
        assert gh is not None
        assert gh["has_router"] is True
        # Phase G replaced the github dispatcher with a renderer.
        assert gh["has_renderer"] is True
        assert gh["has_dispatcher"] is False
        # hooks.py deleted — auto_register_from_manifest handles metadata
        assert gh["has_hooks"] is False
        assert gh["has_tools"] is True
        # Should have webhook
        assert gh["webhook"] is not None
        assert gh["webhook"]["path"] == "/integrations/github/webhook"

    def test_status_ready_when_env_vars_set(self):
        from integrations import discover_setup_status
        from pathlib import Path
        gh_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "github"
        if not gh_dir.is_dir():
            pytest.skip("integrations/github not present")
        env = {
            "GITHUB_TOKEN": "ghp_test",
            "GITHUB_WEBHOOK_SECRET": "secret123",
        }
        with patch.dict(os.environ, env):
            results = discover_setup_status()
        gh = next((r for r in results if r["id"] == "github"), None)
        assert gh is not None
        assert gh["status"] == "ready"

    def test_status_partial_when_some_env_vars_set(self):
        from integrations import discover_setup_status
        from pathlib import Path
        gh_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "github"
        if not gh_dir.is_dir():
            pytest.skip("integrations/github not present")
        env = {"GITHUB_TOKEN": "ghp_test"}
        # Clear GITHUB_WEBHOOK_SECRET if set
        clean = {"GITHUB_WEBHOOK_SECRET": ""}
        with patch.dict(os.environ, {**env, **clean}):
            # Ensure GITHUB_WEBHOOK_SECRET is truly empty
            os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
            results = discover_setup_status()
        gh = next((r for r in results if r["id"] == "github"), None)
        assert gh is not None
        assert gh["status"] == "partial"

    def test_status_not_configured_when_no_env_vars(self):
        from integrations import discover_setup_status
        from pathlib import Path
        gh_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "github"
        if not gh_dir.is_dir():
            pytest.skip("integrations/github not present")
        # Clear all github env vars
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
            os.environ.pop("GITHUB_BOT_LOGIN", None)
            results = discover_setup_status()
        gh = next((r for r in results if r["id"] == "github"), None)
        assert gh is not None
        assert gh["status"] == "not_configured"

    def test_base_url_applied_to_webhook(self):
        from integrations import discover_setup_status
        from pathlib import Path
        gh_dir = Path(__file__).resolve().parent.parent.parent / "integrations" / "github"
        if not gh_dir.is_dir():
            pytest.skip("integrations/github not present")
        results = discover_setup_status(base_url="https://example.com")
        gh = next((r for r in results if r["id"] == "github"), None)
        assert gh is not None
        assert gh["webhook"]["url"] == "https://example.com/integrations/github/webhook"

    def test_readme_loaded(self):
        from integrations import discover_setup_status
        results = discover_setup_status()
        slack = next((r for r in results if r["id"] == "slack"), None)
        assert slack is not None
        assert slack["readme"] is not None
        assert "Slack" in slack["readme"]

    def test_local_companion_exposes_machine_control_metadata(self):
        from integrations import discover_setup_status

        results = discover_setup_status()
        companion = next((r for r in results if r["id"] == "local_companion"), None)

        assert companion is not None
        assert "machine_control" in companion.get("provides", [])
        assert companion["machine_control"]["provider_id"] == "local_companion"
        assert companion["machine_control"]["driver"] == "companion"

    def test_ssh_exposes_machine_control_metadata(self):
        from integrations import discover_setup_status

        results = discover_setup_status()
        ssh = next((r for r in results if r["id"] == "ssh"), None)

        assert ssh is not None
        assert "machine_control" in ssh.get("provides", [])
        assert ssh["machine_control"]["provider_id"] == "ssh"
        assert ssh["machine_control"]["driver"] == "ssh"
        assert isinstance(ssh["machine_control"].get("profile_fields"), list)
        assert isinstance(ssh["machine_control"].get("enroll_fields"), list)
