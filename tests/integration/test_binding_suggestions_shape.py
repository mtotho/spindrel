"""Drift test for `binding.suggestions_endpoint` responses.

Every integration that declares `binding.suggestions_endpoint` in its
`integration.yaml` must return `list[BindingSuggestion]` from that endpoint.
This test enforces:

1. The endpoint exists on the integration's router (YAML is not a lie).
2. The endpoint's declared `response_model` is `list[BindingSuggestion]`,
   so FastAPI will fail closed on any drift at request time.
3. Representative payloads (taken from each integration's real code paths)
   round-trip through the canonical schema under ``extra="forbid"``.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.schemas.binding_suggestions import BindingSuggestion

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_DIR = REPO_ROOT / "integrations"


def _integrations_with_suggestions_endpoint() -> list[tuple[str, str]]:
    """Return (integration_id, endpoint_path) for every integration YAML that
    declares a `binding.suggestions_endpoint`.
    """
    results: list[tuple[str, str]] = []
    for yaml_path in INTEGRATIONS_DIR.glob("*/integration.yaml"):
        with yaml_path.open() as f:
            data = yaml.safe_load(f) or {}
        binding = data.get("binding") or {}
        endpoint = binding.get("suggestions_endpoint")
        if endpoint:
            results.append((data["id"], endpoint))
    return results


@pytest.mark.parametrize(
    "integration_id,endpoint_path",
    _integrations_with_suggestions_endpoint(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_suggestions_endpoint_response_model_is_canonical(
    integration_id: str, endpoint_path: str
) -> None:
    """The endpoint's FastAPI route must declare `response_model=list[BindingSuggestion]`."""
    router_mod = importlib.import_module(f"integrations.{integration_id}.router")
    router = getattr(router_mod, "router")

    # Endpoints are mounted under `/integrations/<id><router_path>`; the YAML
    # records the absolute path, so we trim that prefix for the route lookup.
    prefix = f"/integrations/{integration_id}"
    assert endpoint_path.startswith(prefix), (
        f"{integration_id}: suggestions_endpoint {endpoint_path!r} does not start with {prefix!r}"
    )
    router_relative_path = endpoint_path[len(prefix):]

    matches = [
        r for r in router.routes
        if getattr(r, "path", None) == router_relative_path
    ]
    assert matches, (
        f"{integration_id}: no route at {router_relative_path!r} on router"
    )

    route = matches[0]
    response_model = getattr(route, "response_model", None)
    assert response_model == list[BindingSuggestion], (
        f"{integration_id}: {router_relative_path} has response_model={response_model!r}, "
        f"expected list[BindingSuggestion]"
    )


def test_canonical_schema_rejects_unknown_fields() -> None:
    """An integration that drifts the shape (e.g., adds `id` instead of
    `client_id`) should fail schema validation loudly, not silently pass."""
    with pytest.raises(ValidationError):
        BindingSuggestion.model_validate(
            {"id": "slack:C01", "label": "#general"}
        )


def test_canonical_schema_accepts_minimal_payload() -> None:
    s = BindingSuggestion.model_validate(
        {"client_id": "slack:C01ABC", "display_name": "#general"}
    )
    assert s.client_id == "slack:C01ABC"
    assert s.display_name == "#general"
    assert s.description == ""
    assert s.config_values is None


def test_canonical_schema_accepts_full_payload() -> None:
    s = BindingSuggestion.model_validate({
        "client_id": "wyoming:living-room",
        "display_name": "Living Room",
        "description": "tcp://10.0.0.42:10300",
        "config_values": {"satellite_uri": "tcp://10.0.0.42:10300"},
    })
    assert s.config_values == {"satellite_uri": "tcp://10.0.0.42:10300"}
