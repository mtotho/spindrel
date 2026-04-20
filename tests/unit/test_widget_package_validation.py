"""Unit tests for the widget-package validator."""
from __future__ import annotations

import pytest

from app.services.widget_package_validation import validate_package


MINIMAL_YAML = "template:\n  v: 1\n  components: []\n"


class TestMinimalValidity:
    def test_minimal_ok(self):
        result = validate_package(MINIMAL_YAML)
        assert result.ok
        assert not result.errors
        assert result.template is not None

    def test_full_ok_with_transform_and_state_poll(self):
        yaml_body = (
            "content_type: application/vnd.spindrel.components+json\n"
            "display: inline\n"
            "transform: self:transform\n"
            "template:\n"
            "  v: 1\n"
            "  components:\n"
            "    - type: status\n"
            "      text: Hello\n"
            "state_poll:\n"
            "  refresh_interval_seconds: 10\n"
            "  template:\n"
            "    v: 1\n"
            "    components: []\n"
        )
        code = "def transform(data, components):\n    return components\n"
        result = validate_package(yaml_body, code)
        assert result.ok
        assert not result.errors
        assert not result.warnings


class TestSchemaErrors:
    def test_bad_yaml_syntax(self):
        result = validate_package("template:\n  v: 1\n  components: [")
        assert not result.ok
        assert any(e.phase == "yaml" for e in result.errors)

    def test_missing_template_key(self):
        result = validate_package("other_key: 1\n")
        assert not result.ok
        assert any("Missing required 'template'" in e.message for e in result.errors)

    def test_wrong_schema_version(self):
        result = validate_package("template:\n  v: 2\n  components: []\n")
        assert not result.ok
        assert any("template.v must be 1" in e.message for e in result.errors)

    def test_components_not_a_list(self):
        result = validate_package("template:\n  v: 1\n  components: 'not a list'\n")
        assert not result.ok
        assert any("components must be a list" in e.message for e in result.errors)

    def test_invalid_transform_ref(self):
        yaml_body = (
            "transform: bad_no_colon\n"
            "template:\n"
            "  v: 1\n"
            "  components: []\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("module:func" in e.message for e in result.errors)

    def test_state_poll_interval_must_be_positive_int(self):
        yaml_body = (
            "template:\n  v: 1\n  components: []\n"
            "state_poll:\n"
            "  refresh_interval_seconds: 0\n"
            "  template:\n    v: 1\n    components: []\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("positive integer" in e.message for e in result.errors)


class TestPythonErrors:
    def test_syntax_error_in_code(self):
        result = validate_package(MINIMAL_YAML, "def broken(:")
        assert not result.ok
        assert any(e.phase == "python" for e in result.errors)


class TestComponentTree:
    """Component-tree validation via Pydantic schema (P0-1)."""

    def _yaml_with_components(self, components_block: str) -> str:
        return f"template:\n  v: 1\n  components:\n{components_block}"

    def test_valid_heading(self):
        yaml_body = self._yaml_with_components(
            "    - type: heading\n      text: Hello\n      level: 2\n"
        )
        assert validate_package(yaml_body).ok

    def test_heading_missing_required_text(self):
        yaml_body = self._yaml_with_components("    - type: heading\n      level: 2\n")
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("text" in e.message.lower() for e in result.errors)

    def test_button_missing_required_action(self):
        yaml_body = self._yaml_with_components(
            "    - type: button\n      label: Click\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("action" in e.message.lower() for e in result.errors)

    def test_unknown_type_is_warning_not_error(self):
        yaml_body = self._yaml_with_components(
            "    - type: martian_widget\n      anything: goes\n"
        )
        result = validate_package(yaml_body)
        assert result.ok, f"unknown type should warn, not error: {result.errors}"
        assert any("martian_widget" in w.message for w in result.warnings)

    def test_missing_type_is_error(self):
        yaml_body = self._yaml_with_components("    - text: no type field\n")
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("type" in e.message.lower() for e in result.errors)

    def test_unknown_field_is_error_on_known_type(self):
        # Catches typos like `defaultOpn` instead of `defaultOpen`
        yaml_body = self._yaml_with_components(
            "    - type: section\n      label: Foo\n      defaultOpn: true\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok

    def test_enum_accepts_known_literal(self):
        yaml_body = self._yaml_with_components(
            "    - type: status\n      text: OK\n      color: success\n"
        )
        assert validate_package(yaml_body).ok

    def test_enum_accepts_templated_string(self):
        yaml_body = self._yaml_with_components(
            "    - type: status\n      text: OK\n      color: \"{{status | status_color}}\"\n"
        )
        assert validate_package(yaml_body).ok

    def test_enum_rejects_unknown_literal(self):
        yaml_body = self._yaml_with_components(
            "    - type: status\n      text: OK\n      color: neon\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("color" in e.message.lower() for e in result.errors)

    def test_section_validates_children_recursively(self):
        yaml_body = self._yaml_with_components(
            "    - type: section\n"
            "      label: Outer\n"
            "      children:\n"
            "        - type: heading\n"
            "          level: 2\n"  # missing required 'text'
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("children" in e.message for e in result.errors)

    def test_list_field_accepts_fully_templated_string(self):
        # Home Assistant pattern: items: "{{data.success | map: ...}}"
        yaml_body = self._yaml_with_components(
            "    - type: properties\n"
            "      layout: inline\n"
            "      items: \"{{data | map: {label: type, value: name}}}\"\n"
        )
        assert validate_package(yaml_body).ok

    def test_list_field_rejects_plain_scalar(self):
        yaml_body = self._yaml_with_components(
            "    - type: properties\n"
            "      items: not a list and not templated\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok

    def test_table_accepts_each_block_for_rows(self):
        yaml_body = self._yaml_with_components(
            "    - type: table\n"
            "      columns: [A, B]\n"
            "      rows:\n"
            "        each: \"{{items}}\"\n"
            "        template: [\"{{_.a}}\", \"{{_.b}}\"]\n"
        )
        assert validate_package(yaml_body).ok

    def test_each_block_at_top_level_is_error(self):
        yaml_body = self._yaml_with_components(
            "    - each: \"{{items}}\"\n      template: []\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("each-blocks are not allowed" in e.message for e in result.errors)

    def test_when_allowed_on_every_component(self):
        yaml_body = self._yaml_with_components(
            "    - type: heading\n      text: X\n      when: \"{{show}}\"\n"
        )
        assert validate_package(yaml_body).ok

    def test_state_poll_template_components_validated(self):
        yaml_body = (
            "template:\n  v: 1\n  components: []\n"
            "state_poll:\n"
            "  refresh_interval_seconds: 10\n"
            "  template:\n"
            "    v: 1\n"
            "    components:\n"
            "      - type: heading\n"  # missing text
        )
        result = validate_package(yaml_body)
        assert not result.ok
        assert any("state_poll.template.components" in e.message for e in result.errors)

    def test_button_action_shape_validated(self):
        yaml_body = self._yaml_with_components(
            "    - type: button\n"
            "      label: Go\n"
            "      action:\n"
            "        dispatch: not_a_real_dispatch\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok

    def test_fragment_type_reserved_for_p1_1(self):
        # Reserved — doesn't warn as unknown, and requires a ref
        yaml_body = self._yaml_with_components(
            "    - type: fragment\n      ref: shared\n"
        )
        assert validate_package(yaml_body).ok

    def test_fragment_missing_ref_is_error(self):
        yaml_body = self._yaml_with_components(
            "    - type: fragment\n"
        )
        result = validate_package(yaml_body)
        assert not result.ok


class TestRealCoreWidgets:
    """Load every shipped core ``widgets/<tool>/template.yaml`` and assert it validates."""

    def test_all_core_widgets_validate(self):
        import pathlib
        import yaml as yamllib

        from app.services.widget_package_validation import _validate_parsed_definition

        widgets_root = (
            pathlib.Path(__file__).resolve().parents[2]
            / "app" / "tools" / "local" / "widgets"
        )
        yaml_files = sorted(widgets_root.glob("*/template.yaml"))
        assert yaml_files, "no core widget template.yaml files found"

        failures: list[str] = []
        for path in yaml_files:
            with open(path) as f:
                widget_def = yamllib.safe_load(f)
            if not isinstance(widget_def, dict):
                continue
            tool_name = path.parent.name
            errs, _ = _validate_parsed_definition(widget_def)
            if errs:
                for e in errs:
                    failures.append(f"{tool_name}: {e.message}")
        assert not failures, "Core widget validation failures:\n" + "\n".join(failures)

    def test_all_integration_widgets_validate(self):
        """Integration manifests under integrations/*/integration.yaml."""
        import pathlib
        import yaml as yamllib

        from app.services.widget_package_validation import _validate_parsed_definition

        integrations_dir = (
            pathlib.Path(__file__).resolve().parents[2] / "integrations"
        )
        manifests = sorted(integrations_dir.glob("*/integration.yaml"))

        failures: list[str] = []
        for path in manifests:
            with open(path) as f:
                parsed = yamllib.safe_load(f)
            if not isinstance(parsed, dict):
                continue
            widgets = parsed.get("tool_widgets") or {}
            for tool_name, widget_def in widgets.items():
                if tool_name.startswith("_") or not isinstance(widget_def, dict):
                    continue
                errs, _ = _validate_parsed_definition(widget_def)
                if errs:
                    for e in errs:
                        failures.append(
                            f"{path.parent.name}/{tool_name}: {e.message}"
                        )
        assert not failures, (
            "Integration widget validation failures:\n" + "\n".join(failures)
        )


class TestWipWarnings:
    def test_self_ref_without_function_is_warning_not_error(self):
        yaml_body = (
            "transform: self:missing\n"
            "template:\n"
            "  v: 1\n"
            "  components: []\n"
        )
        result = validate_package(yaml_body, "x = 1\n")
        assert result.ok  # error-free, saveable
        assert any("does not define 'missing'" in w.message for w in result.warnings)

    def test_self_ref_with_function_no_warning(self):
        yaml_body = (
            "transform: self:do_thing\n"
            "template:\n"
            "  v: 1\n"
            "  components: []\n"
        )
        code = "def do_thing(d, c):\n    return c\n"
        result = validate_package(yaml_body, code)
        assert result.ok
        assert not result.warnings
