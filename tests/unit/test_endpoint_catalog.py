"""Tests for the auto-generated endpoint catalog."""
import pytest

from app.services.api_keys import ALL_SCOPES


def _build_catalog():
    """Build the endpoint catalog from the real FastAPI app."""
    from app.main import app
    from app.services.endpoint_catalog import build_endpoint_catalog
    return build_endpoint_catalog(app)


@pytest.fixture(scope="module")
def catalog():
    return _build_catalog()


class TestEndpointCatalogStructure:
    """Every catalog entry must have required fields and valid scope references."""

    def test_catalog_not_empty(self, catalog):
        assert len(catalog) > 100, f"Expected 100+ endpoints, got {len(catalog)}"

    def test_required_fields_present(self, catalog):
        """Every entry needs method, path, description, and scope."""
        required = {"method", "path", "description", "scope"}
        for i, entry in enumerate(catalog):
            missing = required - set(entry.keys())
            assert not missing, (
                f"Entry {i} ({entry.get('method', '?')} {entry.get('path', '?')}) "
                f"missing required fields: {missing}"
            )

    def test_no_duplicate_method_path_scope_triples(self, catalog):
        """No two entries should have the same (method, path, scope) triple."""
        seen: dict[tuple, int] = {}
        for i, entry in enumerate(catalog):
            key = (entry["method"], entry["path"], entry["scope"])
            assert key not in seen, (
                f"Duplicate ({key[0]} {key[1]} scope={key[2]}) at entries {seen[key]} and {i}"
            )
            seen[key] = i

    def test_scopes_are_valid(self, catalog):
        """Every non-None scope in the catalog must appear in ALL_SCOPES."""
        for entry in catalog:
            scope = entry["scope"]
            if scope is not None:
                assert scope in ALL_SCOPES, (
                    f"Unknown scope {scope!r} in {entry['method']} {entry['path']}. "
                    f"Add it to ALL_SCOPES or fix the catalog entry."
                )

    def test_methods_are_valid_http(self, catalog):
        for entry in catalog:
            assert entry["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE"), (
                f"Invalid HTTP method {entry['method']!r} in {entry['path']}"
            )


class TestScopeCoverage:
    """Verify that routes are properly scoped (not just relying on router-level auth)."""

    def test_most_routes_have_scopes(self, catalog):
        """The majority of catalog entries should have a non-None scope."""
        scoped = [e for e in catalog if e["scope"] is not None]
        ratio = len(scoped) / len(catalog) if catalog else 0
        assert ratio > 0.9, (
            f"Only {len(scoped)}/{len(catalog)} ({ratio:.0%}) entries have scopes. "
            f"Expected >90%."
        )


class TestWorkspaceEndpointsCoverage:
    """Spot-check that key workspace endpoints exist in the catalog."""

    @pytest.fixture
    def catalog_paths(self, catalog):
        return {(e["method"], e["path"]) for e in catalog}

    def test_workspace_bot_crud(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{workspace_id}/bots") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{workspace_id}/bots/{bot_id}") in catalog_paths
        assert ("PUT", "/api/v1/workspaces/{workspace_id}/bots/{bot_id}") in catalog_paths
        assert ("DELETE", "/api/v1/workspaces/{workspace_id}/bots/{bot_id}") in catalog_paths

    def test_workspace_channels(self, catalog_paths):
        assert ("GET", "/api/v1/workspaces/{workspace_id}/channels") in catalog_paths

    def test_workspace_reindex(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{workspace_id}/reindex") in catalog_paths

    def test_workspace_file_ops(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{workspace_id}/files/mkdir") in catalog_paths
        assert ("POST", "/api/v1/workspaces/{workspace_id}/files/move") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{workspace_id}/files/index-status") in catalog_paths

    def test_workspace_pull_and_cron(self, catalog_paths):
        assert ("POST", "/api/v1/workspaces/{workspace_id}/pull") in catalog_paths
        assert ("GET", "/api/v1/workspaces/{workspace_id}/cron-jobs") in catalog_paths

    def test_workspace_indexing_config(self, catalog_paths):
        assert ("GET", "/api/v1/workspaces/{workspace_id}/indexing") in catalog_paths
        assert ("PUT", "/api/v1/workspaces/{workspace_id}/bots/{bot_id}/indexing") in catalog_paths
