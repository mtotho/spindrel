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
        integration_names = ["mission_control", "github", "gmail", "frigate", "arr"]
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

    def test_mc_carapace_includes_workspace_guidance(self):
        """MC carapace system_prompt_fragment should include workspace file org."""
        import yaml
        from pathlib import Path

        carapace_path = Path("integrations/mission_control/carapaces/mission-control.yaml")
        if not carapace_path.exists():
            pytest.skip("MC carapace not found")

        data = yaml.safe_load(carapace_path.read_text())
        fragment = data.get("system_prompt_fragment", "")
        assert "Workspace File Organization" in fragment
        assert "tasks.md" in fragment
        assert "status.md" in fragment
        assert "never edit directly" in fragment
