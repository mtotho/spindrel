"""Unit tests for workspace template behavior.

Templates are optional — no fallback injection. Integration carapaces
teach file organization directly via their system_prompt_fragment.
"""
import importlib

import pytest


class TestTemplateSystemCleanup:
    """Tests verifying the template system is clean after simplification."""

    @pytest.mark.asyncio
    async def test_compatible_templates_removed_from_manifests(self):
        """All integration manifests should no longer have compatible_templates."""
        integration_names = ["github", "gmail", "frigate", "arr"]
        for name in integration_names:
            try:
                mod = importlib.import_module(f"integrations.{name}.setup")
                setup = getattr(mod, "SETUP", {})
                activation = setup.get("activation", {})
                assert "compatible_templates" not in activation, (
                    f"integrations/{name}/setup.py still has compatible_templates"
                )
            except ImportError:
                pass  # integration not installed in test env
