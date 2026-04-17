"""Unit tests for widget fragment resolution (P1-1)."""
from __future__ import annotations

from app.services.widget_fragments import resolve_fragments


class TestSpread:
    def test_list_body_spreads_at_parent_list_position(self):
        widget_def = {
            "fragments": {
                "head": [
                    {"type": "heading", "text": "Hi"},
                    {"type": "status", "text": "OK"},
                ],
            },
            "template": {
                "v": 1,
                "components": [
                    {"type": "fragment", "ref": "head"},
                    {"type": "divider"},
                ],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        comps = resolved["template"]["components"]
        assert [c["type"] for c in comps] == ["heading", "status", "divider"]
        assert "fragments" not in resolved

    def test_dict_body_replaces_one_for_one(self):
        widget_def = {
            "fragments": {
                "banner": {"type": "heading", "text": "Banner", "level": 1},
            },
            "template": {
                "v": 1,
                "components": [
                    {"type": "fragment", "ref": "banner"},
                ],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        assert resolved["template"]["components"] == [
            {"type": "heading", "text": "Banner", "level": 1},
        ]


class TestBothPositions:
    def test_expands_in_template_and_state_poll_template(self):
        widget_def = {
            "fragments": {
                "cancel": {
                    "type": "button", "label": "Cancel",
                    "action": {"dispatch": "tool", "tool": "cancel_task"},
                },
            },
            "template": {
                "v": 1,
                "components": [{"type": "fragment", "ref": "cancel"}],
            },
            "state_poll": {
                "template": {
                    "v": 1,
                    "components": [{"type": "fragment", "ref": "cancel"}],
                },
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        assert resolved["template"]["components"][0]["type"] == "button"
        assert resolved["state_poll"]["template"]["components"][0]["type"] == "button"


class TestNested:
    def test_nested_section_children_are_expanded(self):
        widget_def = {
            "fragments": {
                "props": {
                    "type": "properties", "layout": "inline",
                    "items": [{"label": "A", "value": "1"}],
                },
            },
            "template": {
                "v": 1,
                "components": [
                    {
                        "type": "section",
                        "label": "Outer",
                        "children": [{"type": "fragment", "ref": "props"}],
                    },
                ],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        section = resolved["template"]["components"][0]
        assert section["children"][0]["type"] == "properties"

    def test_fragment_can_reference_other_fragment(self):
        widget_def = {
            "fragments": {
                "inner": {"type": "heading", "text": "Inner", "level": 3},
                "outer": [
                    {"type": "fragment", "ref": "inner"},
                    {"type": "divider"},
                ],
            },
            "template": {
                "v": 1,
                "components": [{"type": "fragment", "ref": "outer"}],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        comps = resolved["template"]["components"]
        assert [c["type"] for c in comps] == ["heading", "divider"]


class TestErrors:
    def test_unknown_ref_is_error(self):
        widget_def = {
            "fragments": {"known": {"type": "heading", "text": "H"}},
            "template": {
                "v": 1,
                "components": [{"type": "fragment", "ref": "missing"}],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert any("missing" in e for e in errors)

    def test_missing_ref_field_is_error(self):
        widget_def = {
            "fragments": {"x": {"type": "heading", "text": "H"}},
            "template": {
                "v": 1,
                "components": [{"type": "fragment"}],
            },
        }
        _, errors = resolve_fragments(widget_def)
        assert errors  # non-empty string ref

    def test_cycle_is_detected(self):
        widget_def = {
            "fragments": {
                "a": [{"type": "fragment", "ref": "b"}],
                "b": [{"type": "fragment", "ref": "a"}],
            },
            "template": {
                "v": 1,
                "components": [{"type": "fragment", "ref": "a"}],
            },
        }
        _, errors = resolve_fragments(widget_def)
        assert any("cycle" in e for e in errors)

    def test_list_body_in_scalar_position_is_error(self):
        widget_def = {
            "fragments": {"many": [{"type": "heading", "text": "X"}]},
            "template": {
                "v": 1,
                "components": [
                    {
                        "type": "section",
                        "label": "S",
                        # children is a list — that's fine. But a single
                        # widget_action position, for example, needs a dict.
                        "children": [
                            # This is fine (list-position spread):
                            {"type": "fragment", "ref": "many"},
                        ],
                    },
                ],
            },
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []  # the above is a legal spread
        # Now test the illegal case: list body at dict-scalar position
        widget_def2 = {
            "fragments": {"many": [{"type": "heading", "text": "X"}]},
            "template": {
                "v": 1,
                "components": [
                    {
                        "type": "section",
                        "label": "S",
                        # header (invented non-standard key) expects a single
                        # node — fragments here should be dict-bodied
                        "header": {"type": "fragment", "ref": "many"},
                        "children": [],
                    },
                ],
            },
        }
        _, errors2 = resolve_fragments(widget_def2)
        assert any("list body" in e for e in errors2)


class TestNoOp:
    def test_no_fragments_returns_unchanged(self):
        widget_def = {
            "template": {"v": 1, "components": [{"type": "divider"}]},
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        assert resolved is widget_def  # same object — no deepcopy when no work


class TestStatePollDefaulting:
    """state_poll.template defaulting to template is wired in _register_widgets,
    not in resolve_fragments — it's a loader concern. Covered separately in
    test_widget_templates.py. Here we only assert that state_poll without
    template gets past fragment resolution without synthesizing anything."""

    def test_state_poll_without_template_unchanged_by_resolver(self):
        widget_def = {
            "fragments": {"x": {"type": "divider"}},
            "template": {
                "v": 1,
                "components": [{"type": "fragment", "ref": "x"}],
            },
            "state_poll": {"refresh_interval_seconds": 10},
        }
        resolved, errors = resolve_fragments(widget_def)
        assert errors == []
        # state_poll stays as-is (no template synthesized here)
        assert resolved["state_poll"] == {"refresh_interval_seconds": 10}
