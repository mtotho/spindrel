"""Tests for ENDPOINT_CATALOG completeness and consistency."""
import pytest

from app.services.api_keys import ENDPOINT_CATALOG, ALL_SCOPES


class TestEndpointCatalogStructure:
    """Every catalog entry must have required fields and valid scope references."""

    def test_required_fields_present(self):
        """Every entry needs method, path, description, and scope."""
        required = {"method", "path", "description", "scope"}
        for i, entry in enumerate(ENDPOINT_CATALOG):
            missing = required - set(entry.keys())
            assert not missing, (
                f"Entry {i} ({entry.get('method', '?')} {entry.get('path', '?')}) "
                f"missing required fields: {missing}"
            )

    def test_no_duplicate_method_path_scope_triples(self):
        """No two entries should have the same (method, path, scope) triple.

        The same endpoint may appear under different scopes (e.g. channels.config:write
        and channels.heartbeat:write both use PUT /channels/{id}/config), so we key
        on the full triple rather than just method+path.
        """
        seen: dict[tuple, int] = {}
        for i, entry in enumerate(ENDPOINT_CATALOG):
            key = (entry["method"], entry["path"], entry["scope"])
            assert key not in seen, (
                f"Duplicate ({key[0]} {key[1]} scope={key[2]}) at entries {seen[key]} and {i}"
            )
            seen[key] = i

    def test_scopes_are_valid(self):
        """Every non-None scope in the catalog must appear in ALL_SCOPES."""
        for entry in ENDPOINT_CATALOG:
            scope = entry["scope"]
            if scope is not None:
                assert scope in ALL_SCOPES, (
                    f"Unknown scope {scope!r} in {entry['method']} {entry['path']}. "
                    f"Add it to ALL_SCOPES or fix the catalog entry."
                )

    def test_methods_are_valid_http(self):
        for entry in ENDPOINT_CATALOG:
            assert entry["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE"), (
                f"Invalid HTTP method {entry['method']!r} in {entry['path']}"
            )


class TestWorkspaceEndpointsCoverage:
    """Spot-check that key workspace endpoints exist in the catalog."""

    @pytest.fixture
    def catalog_paths(self):
        return {(e["method"], e["path"]) for e in ENDPOINT_CATALOG}

    def test_workspace_bot_crud(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{id}/bots") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{id}/bots/{bot_id}") in catalog_paths
        assert ("PUT", "/api/v1/workspaces/{id}/bots/{bot_id}") in catalog_paths
        assert ("DELETE", "/api/v1/workspaces/{id}/bots/{bot_id}") in catalog_paths

    def test_workspace_channels(self, catalog_paths):
        assert ("GET", "/api/v1/workspaces/{id}/channels") in catalog_paths

    def test_workspace_reindex(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{id}/reindex") in catalog_paths
        assert ("POST", "/api/v1/workspaces/{id}/reindex-skills") in catalog_paths

    def test_workspace_skills(self, catalog_paths):
        assert ("GET", "/api/v1/workspaces/{id}/skills") in catalog_paths

    def test_workspace_file_ops(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{id}/files/mkdir") in catalog_paths
        assert ("POST", "/api/v1/workspaces/{id}/files/move") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{id}/files/index-status") in catalog_paths

    def test_workspace_pull_and_cron(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{id}/pull") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{id}/cron-jobs") in catalog_paths

    def test_workspace_indexing_config(self, catalog_paths):
        assert ("GET", "/api/v1/workspaces/{id}/indexing") in catalog_paths
        assert ("PUT", "/api/v1/workspaces/{id}/bots/{bot_id}/indexing") in catalog_paths
