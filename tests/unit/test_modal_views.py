"""Tests for the Slack schema ↔ Block Kit translator."""
from __future__ import annotations

from integrations.slack.modal_views import (
    _ACTION_SUFFIX,
    schema_to_view,
    values_from_view,
)


class TestSchemaToView:
    def test_text_field(self):
        view = schema_to_view(
            callback_id="cb1",
            title="Feedback",
            schema={"name": {"type": "text", "label": "Your name", "required": True}},
        )
        assert view["type"] == "modal"
        assert view["callback_id"] == "cb1"
        blocks = view["blocks"]
        assert blocks[0]["type"] == "input"
        assert blocks[0]["block_id"] == "name"
        assert blocks[0]["optional"] is False
        assert blocks[0]["element"]["type"] == "plain_text_input"
        assert blocks[0]["element"]["action_id"] == f"name{_ACTION_SUFFIX}"

    def test_textarea_field(self):
        view = schema_to_view(
            callback_id="c", title="t",
            schema={"body": {"type": "textarea", "label": "Details"}},
        )
        el = view["blocks"][0]["element"]
        assert el["type"] == "plain_text_input"
        assert el["multiline"] is True

    def test_select_field_with_choices(self):
        view = schema_to_view(
            callback_id="c", title="t",
            schema={
                "severity": {
                    "type": "select", "label": "Severity",
                    "choices": [
                        {"label": "Low", "value": "low"},
                        {"label": "High", "value": "high"},
                    ],
                },
            },
        )
        el = view["blocks"][0]["element"]
        assert el["type"] == "static_select"
        assert len(el["options"]) == 2
        assert el["options"][0]["value"] == "low"
        assert el["options"][1]["text"]["text"] == "High"

    def test_number_and_date_and_url_fields(self):
        view = schema_to_view(
            callback_id="c", title="t",
            schema={
                "count": {"type": "number", "label": "n"},
                "when": {"type": "date", "label": "d"},
                "site": {"type": "url", "label": "u"},
            },
        )
        elements = [b["element"]["type"] for b in view["blocks"]]
        assert elements == ["number_input", "datepicker", "url_text_input"]

    def test_optional_field(self):
        view = schema_to_view(
            callback_id="c", title="t",
            schema={"note": {"type": "text", "label": "Note", "required": False}},
        )
        assert view["blocks"][0]["optional"] is True

    def test_private_metadata_included(self):
        view = schema_to_view(
            callback_id="c", title="t", schema={},
            private_metadata="{\"channel_id\": \"X\"}",
        )
        assert view["private_metadata"] == "{\"channel_id\": \"X\"}"


class TestValuesFromView:
    def _submission(self, action_id, payload):
        return {
            "state": {
                "values": {
                    "field1": {action_id: payload},
                },
            },
        }

    def test_plain_text(self):
        view = self._submission(f"field1{_ACTION_SUFFIX}", {
            "type": "plain_text_input", "value": "hello",
        })
        assert values_from_view(view) == {"field1": "hello"}

    def test_select_returns_value_not_label(self):
        view = self._submission(f"field1{_ACTION_SUFFIX}", {
            "type": "static_select",
            "selected_option": {"text": {"text": "High"}, "value": "high"},
        })
        assert values_from_view(view) == {"field1": "high"}

    def test_number(self):
        view = self._submission(f"field1{_ACTION_SUFFIX}", {
            "type": "number_input", "value": "3.14",
        })
        assert values_from_view(view) == {"field1": 3.14}

    def test_date(self):
        view = self._submission(f"field1{_ACTION_SUFFIX}", {
            "type": "datepicker", "selected_date": "2026-05-01",
        })
        assert values_from_view(view) == {"field1": "2026-05-01"}

    def test_ignores_actions_without_expected_suffix(self):
        view = self._submission("unexpected_action_id", {
            "type": "plain_text_input", "value": "hello",
        })
        assert values_from_view(view) == {}

    def test_empty_state_returns_empty(self):
        assert values_from_view({}) == {}
