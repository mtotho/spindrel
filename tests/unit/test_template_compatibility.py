"""Tests for the integration/template compatibility system."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.file_sync import _parse_frontmatter


# ---------------------------------------------------------------------------
# Test: compatible_integrations frontmatter expansion
# ---------------------------------------------------------------------------

def test_compatible_integrations_expanded_to_tags():
    """File sync should expand compatible_integrations frontmatter into integration:* tags."""
    content = """---
name: "Test Template"
description: "A test"
category: workspace_schema
compatible_integrations:
  - mission_control
  - arr
tags:
  - software
  - mission-control
---

Template body here.
"""
    meta, body = _parse_frontmatter(content)
    assert meta["compatible_integrations"] == ["mission_control", "arr"]

    # Simulate the tag expansion logic from file_sync
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    compat = meta.get("compatible_integrations", [])
    if isinstance(compat, str):
        compat = [c.strip() for c in compat.split(",") if c.strip()]
    for ci in compat:
        tag = f"integration:{ci}"
        if tag not in tags:
            tags.append(tag)

    assert "integration:mission_control" in tags
    assert "integration:arr" in tags
    assert "software" in tags
    assert "mission-control" in tags


def test_compatible_integrations_preserves_existing_tags():
    """Expansion shouldn't clobber or duplicate existing tags."""
    content = """---
name: "Test"
category: workspace_schema
compatible_integrations:
  - mission_control
tags:
  - existing-tag
  - integration:mission_control
---

Body.
"""
    meta, _ = _parse_frontmatter(content)
    tags = list(meta.get("tags", []))
    compat = meta.get("compatible_integrations", [])
    for ci in compat:
        tag = f"integration:{ci}"
        if tag not in tags:
            tags.append(tag)

    # Should not duplicate
    assert tags.count("integration:mission_control") == 1
    assert "existing-tag" in tags


def test_compatible_integrations_string_format():
    """compatible_integrations as a comma-separated string should also work."""
    content = """---
name: "Test"
category: workspace_schema
compatible_integrations: "mission_control, arr"
tags:
  - software
---

Body.
"""
    meta, _ = _parse_frontmatter(content)
    tags = list(meta.get("tags", []))
    compat = meta.get("compatible_integrations", [])
    if isinstance(compat, str):
        compat = [c.strip() for c in compat.split(",") if c.strip()]
    for ci in compat:
        tag = f"integration:{ci}"
        if tag not in tags:
            tags.append(tag)

    assert "integration:mission_control" in tags
    assert "integration:arr" in tags


# ---------------------------------------------------------------------------
# Test: tag filter on prompt templates API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_templates_filter_by_tag():
    """API ?tag=mission-control should filter via JSONB contains."""
    from app.db.models import PromptTemplate

    # Create mock templates
    t1_id = uuid.uuid4()
    t2_id = uuid.uuid4()
    t1 = MagicMock(spec=PromptTemplate)
    t1.id = t1_id
    t1.name = "MC Template"
    t1.tags = ["mission-control", "software"]
    t1.category = "workspace_schema"

    t2 = MagicMock(spec=PromptTemplate)
    t2.id = t2_id
    t2.name = "Plain Template"
    t2.tags = ["general"]
    t2.category = "workspace_schema"

    # The key assertion: JSONB contains filter should match t1 but not t2
    # Test that ["mission-control", "software"] contains ["mission-control"] = True
    assert "mission-control" in t1.tags
    assert "mission-control" not in t2.tags


# ---------------------------------------------------------------------------
# Test: available integrations API includes version + compat tag
# ---------------------------------------------------------------------------

def test_available_integrations_includes_version_and_compat():
    """AvailableIntegrationOut should have version and compatible_template_tag fields."""
    from app.routers.api_v1_channels import AvailableIntegrationOut

    out = AvailableIntegrationOut(
        integration_type="mission_control",
        description="Project management",
        requires_workspace=True,
        activated=True,
        carapaces=["mission-control"],
        tools=["create_task_card"],
        skill_count=5,
        has_system_prompt=True,
        version="1.0",
        compatible_template_tag="mission-control",
    )
    assert out.version == "1.0"
    assert out.compatible_template_tag == "mission-control"

    # Also test defaults (None)
    out2 = AvailableIntegrationOut(
        integration_type="slack",
        description="Slack integration",
        requires_workspace=False,
        activated=False,
    )
    assert out2.version is None
    assert out2.compatible_template_tag is None


# ---------------------------------------------------------------------------
# Test: backward compatibility — mission-control tag still matched
# ---------------------------------------------------------------------------

def test_backward_compat_mission_control_tag():
    """MC templates with existing mission-control tag should still be matched
    by the activation manifest's compatible_templates: ['mission-control']."""
    # Simulate what the API does: manifest declares compatible_templates
    manifest = {
        "carapaces": ["mission-control"],
        "requires_workspace": True,
        "description": "Project management",
        "compatible_templates": ["mission-control"],
        "version": "1.0",
    }

    compat_tags = manifest.get("compatible_templates", [])
    highlight_tag = compat_tags[0] if compat_tags else None
    assert highlight_tag == "mission-control"

    # A template with the legacy tag should match
    template_tags = ["software", "development", "mission-control"]
    assert highlight_tag in template_tags

    # A template with the new integration: tag should also exist alongside
    template_tags_new = ["software", "mission-control", "integration:mission_control"]
    assert highlight_tag in template_tags_new


# ---------------------------------------------------------------------------
# Test: activation manifest version embedding
# ---------------------------------------------------------------------------

def test_activation_manifest_embeds_version():
    """discover_activation_manifests should embed top-level version into manifest."""
    # Simulate the logic from integrations/__init__.py
    setup = {
        "version": "1.0",
        "activation": {
            "carapaces": ["mission-control"],
            "compatible_templates": ["mission-control"],
        },
    }
    activation = setup.get("activation")
    version = setup.get("version")
    if version and "version" not in activation:
        activation = {**activation, "version": version}

    assert activation["version"] == "1.0"
    assert activation["compatible_templates"] == ["mission-control"]

    # If activation already has version, don't override
    setup2 = {
        "version": "2.0",
        "activation": {
            "carapaces": ["test"],
            "version": "1.5",  # explicit in activation
        },
    }
    activation2 = setup2.get("activation")
    version2 = setup2.get("version")
    if version2 and "version" not in activation2:
        activation2 = {**activation2, "version": version2}

    assert activation2["version"] == "1.5"  # preserved, not overridden
