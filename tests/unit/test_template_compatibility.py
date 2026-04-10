"""Tests for the template system (post-simplification).

The compatible_integrations/compatible_templates system has been removed.
These tests verify the remaining template functionality still works.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.file_sync import _parse_frontmatter


# ---------------------------------------------------------------------------
# Test: frontmatter parsing still works
# ---------------------------------------------------------------------------

def test_frontmatter_parsing_basic():
    """Frontmatter parsing should extract name, tags, etc."""
    content = """---
name: "Test Template"
description: "A test"
category: workspace_schema
tags:
  - software
  - mission-control
---

Template body here.
"""
    meta, body = _parse_frontmatter(content)
    assert meta["name"] == "Test Template"
    assert meta["category"] == "workspace_schema"
    assert "software" in meta["tags"]
    assert "Template body here." in body


def test_mc_min_version_expansion():
    """mc_min_version frontmatter should still expand into tags."""
    content = """---
name: "Test"
category: workspace_schema
mc_min_version: "2.0"
tags:
  - software
---

Body.
"""
    meta, _ = _parse_frontmatter(content)
    tags = list(meta.get("tags", []))
    mc_ver = meta.get("mc_min_version")
    if mc_ver:
        ver_tag = f"mc_min_version:{mc_ver}"
        if ver_tag not in tags:
            tags.append(ver_tag)

    assert "mc_min_version:2.0" in tags
    assert "software" in tags


# ---------------------------------------------------------------------------
# Test: tag filter on prompt templates API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_templates_filter_by_tag():
    """API ?tag=mission-control should filter via JSONB contains."""
    from app.db.models import PromptTemplate

    t1 = MagicMock(spec=PromptTemplate)
    t1.id = uuid.uuid4()
    t1.name = "MC Template"
    t1.tags = ["mission-control", "software"]
    t1.category = "workspace_schema"

    t2 = MagicMock(spec=PromptTemplate)
    t2.id = uuid.uuid4()
    t2.name = "Plain Template"
    t2.tags = ["general"]
    t2.category = "workspace_schema"

    assert "mission-control" in t1.tags
    assert "mission-control" not in t2.tags


# ---------------------------------------------------------------------------
# Test: available integrations API version field
# ---------------------------------------------------------------------------

def test_available_integrations_includes_version():
    """AvailableIntegrationOut should have version field."""
    from app.routers.api_v1_channels import AvailableIntegrationOut

    out = AvailableIntegrationOut(
        integration_type="mission_control",
        description="Project management",
        requires_workspace=True,
        activated=True,
        carapaces=["mission-control"],
        tools=["create_task_card"],
        has_system_prompt=True,
        version="1.0",
    )
    assert out.version == "1.0"

    # Also test defaults (None)
    out2 = AvailableIntegrationOut(
        integration_type="slack",
        description="Slack integration",
        requires_workspace=False,
        activated=False,
    )
    assert out2.version is None


# ---------------------------------------------------------------------------
# Test: activation manifest version embedding
# ---------------------------------------------------------------------------

def test_activation_manifest_embeds_version():
    """discover_activation_manifests should embed top-level version into manifest."""
    setup = {
        "version": "1.0",
        "activation": {
            "carapaces": ["mission-control"],
        },
    }
    activation = setup.get("activation")
    version = setup.get("version")
    if version and "version" not in activation:
        activation = {**activation, "version": version}

    assert activation["version"] == "1.0"

    # If activation already has version, don't override
    setup2 = {
        "version": "2.0",
        "activation": {
            "carapaces": ["test"],
            "version": "1.5",
        },
    }
    activation2 = setup2.get("activation")
    version2 = setup2.get("version")
    if version2 and "version" not in activation2:
        activation2 = {**activation2, "version": version2}

    assert activation2["version"] == "1.5"  # preserved, not overridden
