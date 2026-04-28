import pytest


class TestBootstrapIntegrationIntent:
    @pytest.mark.asyncio
    async def test_applies_only_missing_lifecycle_statuses(self, monkeypatch):
        from app.services import integration_settings as settings

        settings._cache.clear()
        settings._cache[("slack", settings.STATUS_KEY)] = "available"
        applied = []

        async def fake_set_status(integration_id, status):
            settings._cache[(integration_id, settings.STATUS_KEY)] = status
            applied.append((integration_id, status))

        monkeypatch.setattr(settings, "set_status", fake_set_status)

        result = await settings.apply_bootstrap_integrations("web_search, slack, browser_automation")

        assert result == ["web_search", "browser_automation"]
        assert applied == [
            ("web_search", "enabled"),
            ("browser_automation", "enabled"),
        ]
        assert settings.get_status("slack") == "available"

    @pytest.mark.asyncio
    async def test_blank_intent_is_noop(self, monkeypatch):
        from app.services import integration_settings as settings

        calls = []

        async def fake_set_status(integration_id, status):
            calls.append((integration_id, status))

        monkeypatch.setattr(settings, "set_status", fake_set_status)

        assert await settings.apply_bootstrap_integrations("  ") == []
        assert calls == []

