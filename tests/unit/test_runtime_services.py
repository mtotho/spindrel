import pytest


def _manifests():
    return {
        "web_search": {
            "runtime_services": {
                "requires": [
                    {
                        "capability": "browser.playwright",
                        "override_setting": "PLAYWRIGHT_WS_URL",
                        "when": {"setting": "WEB_SEARCH_MODE", "values": ["searxng"]},
                    }
                ]
            }
        },
        "browser_automation": {
            "runtime_services": {
                "provides": [
                    {
                        "capability": "browser.playwright",
                        "protocol": "cdp",
                        "browser": "chromium",
                        "endpoint": "ws://playwright-${SPINDREL_INSTANCE_ID}:3000",
                        "service": "playwright",
                    }
                ]
            }
        },
    }


class TestRuntimeServices:
    def test_resolves_external_override_first(self, monkeypatch):
        import app.services.runtime_services as rs

        manifests = _manifests()
        monkeypatch.setattr(rs, "get_all_manifests", lambda: manifests)
        monkeypatch.setattr(rs, "get_manifest", lambda iid: manifests.get(iid))
        monkeypatch.setattr(rs, "get_value", lambda iid, key, default="": {
            ("web_search", "WEB_SEARCH_MODE"): "searxng",
            ("web_search", "PLAYWRIGHT_WS_URL"): "ws://external:3000",
        }.get((iid, key), default))

        resolved = rs.resolve_runtime_requirement("web_search", "browser.playwright")

        assert resolved.source == "external"
        assert resolved.endpoint == "ws://external:3000"
        assert resolved.provider_integration_id is None

    def test_resolves_shared_provider_when_no_override(self, monkeypatch):
        import app.services.runtime_services as rs

        manifests = _manifests()
        monkeypatch.setattr(rs.settings, "SPINDREL_INSTANCE_ID", "local")
        monkeypatch.setattr(rs, "get_all_manifests", lambda: manifests)
        monkeypatch.setattr(rs, "get_manifest", lambda iid: manifests.get(iid))
        monkeypatch.setattr(rs, "get_value", lambda iid, key, default="": {
            ("web_search", "WEB_SEARCH_MODE"): "searxng",
        }.get((iid, key), default))

        resolved = rs.resolve_runtime_requirement("web_search", "browser.playwright")

        assert resolved.source == "integration"
        assert resolved.provider_integration_id == "browser_automation"
        assert resolved.endpoint == "ws://playwright-local:3000"
        assert resolved.protocol == "cdp"

    def test_inactive_requirement_does_not_enable_provider(self, monkeypatch):
        import app.services.runtime_services as rs

        manifests = _manifests()
        monkeypatch.setattr(rs, "get_all_manifests", lambda: manifests)
        monkeypatch.setattr(rs, "get_manifest", lambda iid: manifests.get(iid))
        monkeypatch.setattr(rs, "get_value", lambda iid, key, default="": {
            ("web_search", "WEB_SEARCH_MODE"): "ddgs",
        }.get((iid, key), default))

        assert rs.required_provider_ids("web_search") == []
        resolved = rs.resolve_runtime_requirement("web_search", "browser.playwright")
        assert resolved.source == "missing"
        assert resolved.endpoint is None

    @pytest.mark.asyncio
    async def test_ensure_required_providers_enabled_only_new_statuses(self, monkeypatch):
        import app.services.runtime_services as rs

        manifests = _manifests()
        statuses = {"browser_automation": "available"}
        applied = []
        monkeypatch.setattr(rs, "get_all_manifests", lambda: manifests)
        monkeypatch.setattr(rs, "get_manifest", lambda iid: manifests.get(iid))
        monkeypatch.setattr(rs, "get_value", lambda iid, key, default="": {
            ("web_search", "WEB_SEARCH_MODE"): "searxng",
        }.get((iid, key), default))

        async def fake_set_status(integration_id, status):
            statuses[integration_id] = status
            applied.append((integration_id, status))

        monkeypatch.setattr("app.services.integration_settings.get_status", lambda iid: statuses.get(iid, "available"))
        monkeypatch.setattr("app.services.integration_settings.set_status", fake_set_status)

        enabled = await rs.ensure_required_providers_enabled("web_search")

        assert enabled == ["browser_automation"]
        assert applied == [("browser_automation", "enabled")]

