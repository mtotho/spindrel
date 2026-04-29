"""Architecture guards for the admin usage router split."""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER_PATH = REPO_ROOT / "app" / "routers" / "api_v1_admin" / "usage.py"
APP_ROOT = REPO_ROOT / "app"


def test_usage_router_remains_thin_endpoint_adapter():
    source = ROUTER_PATH.read_text()
    tree = ast.parse(source)

    endpoint_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
    }
    assert endpoint_names == {
        "usage_anomalies",
        "agent_smell",
        "usage_summary",
        "usage_logs",
        "usage_breakdown",
        "usage_timeseries",
        "debug_pricing",
        "usage_forecast",
        "admin_provider_health",
    }

    forbidden_router_details = {
        "TraceEvent",
        "ProviderModel",
        "ProviderConfig",
        "UsageSpike",
        "BotToolEnrollment",
        "select(",
        "func.",
        "_fetch_token_usage_events",
        "_load_pricing_map",
        "_resolve_event_cost",
    }
    for detail in forbidden_router_details:
        assert detail not in source

    assert len(source.splitlines()) < 300


def test_production_code_does_not_import_usage_router_internals():
    offenders: list[tuple[str, str]] = []
    forbidden_imports = (
        "from app.routers.api_v1_admin.usage import",
        "import app.routers.api_v1_admin.usage",
        "app.routers.api_v1_admin.usage.",
    )

    for path in APP_ROOT.rglob("*.py"):
        if path == ROUTER_PATH:
            continue
        source = path.read_text()
        for forbidden in forbidden_imports:
            if forbidden in source:
                offenders.append((str(path.relative_to(REPO_ROOT)), forbidden))

    assert offenders == []
