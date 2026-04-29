"""Architecture guards for channel response read-model ownership."""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROUTER = REPO_ROOT / "app" / "routers" / "api_v1_channels.py"
ADMIN_ROUTER = REPO_ROOT / "app" / "routers" / "api_v1_admin" / "channels.py"
SCHEMAS = REPO_ROOT / "app" / "schemas" / "channels.py"
READ_MODELS = REPO_ROOT / "app" / "services" / "channel_read_models.py"


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def test_channel_response_schemas_live_in_shared_schema_module():
    schema_classes = _class_names(SCHEMAS)
    expected = {
        "AdminChannelOut",
        "ChannelBotMemberOut",
        "ChannelDetailOut",
        "ChannelEntitySummary",
        "ChannelListItemOut",
        "ChannelListOut",
        "ChannelSettingsOut",
        "ChannelOut",
        "IntegrationBindingOut",
        "ProjectSummaryOut",
    }
    assert expected <= schema_classes

    forbidden_router_classes = expected | {"ChannelOut"}
    for router in (PUBLIC_ROUTER, ADMIN_ROUTER):
        assert _class_names(router).isdisjoint(forbidden_router_classes)


def test_admin_channel_router_does_not_import_public_router_internals():
    source = ADMIN_ROUTER.read_text()
    assert "from app.routers.api_v1_channels import" not in source
    assert "app.routers.api_v1_channels." not in source


def test_channel_read_model_service_owns_projection_helpers():
    source = READ_MODELS.read_text()
    for name in (
        "build_admin_channel_out",
        "build_admin_channel_settings_out",
        "build_public_channel_out",
        "enrich_bot_members",
        "load_admin_activity_maps",
    ):
        assert f"def {name}" in source or f"async def {name}" in source

    public_source = PUBLIC_ROUTER.read_text()
    admin_source = ADMIN_ROUTER.read_text()
    assert "ProjectSummaryOut.model_validate" not in public_source
    assert "ProjectSummaryOut.model_validate" not in admin_source
    assert "ChannelOut.model_validate" not in public_source
    assert "ChannelOut.model_validate" not in admin_source
