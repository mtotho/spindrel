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
