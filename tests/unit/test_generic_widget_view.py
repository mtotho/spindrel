"""Unit tests for the generic JSON → component-tree auto-renderer."""
from __future__ import annotations

import json

import pytest

from app.services.generic_widget_view import render_generic_view


def _components(env) -> list[dict]:
    assert env.body is not None
    return json.loads(env.body)["components"]


def _types(components: list[dict]) -> list[str]:
    return [c.get("type") for c in components]


def _first_of(components: list[dict], type_: str) -> dict:
    for c in components:
        if c.get("type") == type_:
            return c
    raise AssertionError(f"no {type_!r} component in {_types(components)}")


class TestScalarObject:
    def test_flat_object_renders_as_properties(self):
        env = render_generic_view(
            {"name": "pikachu", "level": 25, "trained": True, "nickname": None},
            tool_name="describe_pokemon",
        )
        comps = _components(env)
        # Tool name becomes a leading heading; top-level scalars render as
        # an inline properties block.
        assert _types(comps)[0] == "heading"
        assert comps[0]["text"] == "Describe Pokemon"
        props = _first_of(comps, "properties")
        assert props.get("layout") == "inline"
        labels = {i["label"]: i["value"] for i in props["items"]}
        assert labels["Name"] == "pikachu"
        assert labels["Level"] == "25"
        assert labels["Trained"] == "Yes"
        assert labels["Nickname"] == "—"
        assert env.refreshable is False
        assert env.content_type == "application/vnd.spindrel.components+json"
        assert env.tool_name == "describe_pokemon"

    def test_no_heading_when_tool_name_blank(self):
        env = render_generic_view({"x": 1})
        comps = _components(env)
        assert "heading" not in _types(comps)

    def test_camel_and_snake_keys_humanized(self):
        env = render_generic_view({"firstName": "Ash", "last_name": "Ketchum"})
        items = _first_of(_components(env), "properties")["items"]
        labels = {i["label"] for i in items}
        assert labels == {"First Name", "Last Name"}

    def test_long_string_value_truncated(self):
        env = render_generic_view({"bio": "x" * 1000})
        items = _first_of(_components(env), "properties")["items"]
        bio = items[0]["value"]
        assert bio.endswith("…")
        assert len(bio) <= 201  # cap + ellipsis


class TestObjectArray:
    def test_homogeneous_dict_array_renders_as_table(self):
        env = render_generic_view(
            [
                {"id": 1, "name": "Alice", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
                {"id": 3, "name": "Carol", "role": "user"},
            ]
        )
        comps = _components(env)
        tbl = _first_of(comps, "table")
        assert tbl["columns"] == ["Id", "Name", "Role"]
        assert tbl["rows"] == [
            ["1", "Alice", "admin"],
            ["2", "Bob", "user"],
            ["3", "Carol", "user"],
        ]

    def test_column_union_across_rows(self):
        env = render_generic_view([{"a": 1, "b": 2}, {"a": 3, "c": 4}])
        tbl = _first_of(_components(env), "table")
        assert tbl["columns"] == ["A", "B", "C"]
        assert tbl["rows"][1] == ["3", "—", "4"]

    def test_columns_capped(self):
        item = {f"k{i}": i for i in range(15)}
        env = render_generic_view([item, item])
        comps = _components(env)
        tbl = _first_of(comps, "table")
        assert len(tbl["columns"]) == 8
        texts = [c.get("content", "") for c in comps if c.get("type") == "text"]
        assert any("more column" in t for t in texts)


class TestScalarArray:
    def test_scalar_array_renders_as_indexed_properties(self):
        env = render_generic_view(["alpha", "beta", "gamma"])
        comps = _components(env)
        props = _first_of(comps, "properties")
        assert [i["label"] for i in props["items"]] == ["[0]", "[1]", "[2]"]
        assert [i["value"] for i in props["items"]] == ["alpha", "beta", "gamma"]

    def test_empty_array_renders_empty_message(self):
        env = render_generic_view([])
        comps = _components(env)
        assert any(
            c.get("type") == "text" and "Empty" in c.get("content", "")
            for c in comps
        )


class TestNesting:
    def test_nested_object_wrapped_in_collapsible_section(self):
        env = render_generic_view(
            {
                "status": "online",
                "address": {"city": "SF", "zip": "94110"},
            }
        )
        comps = _components(env)
        # Top-level scalar → inline properties; nested dict → section
        # (collapsible, defaultOpen=True because it's the first nested field).
        assert _types(comps)[0] == "properties"
        section = _first_of(comps, "section")
        assert section["label"] == "Address"
        assert section["collapsible"] is True
        assert section["defaultOpen"] is True
        # Section children contain inline properties for the nested scalars.
        assert section["children"][0]["type"] == "properties"
        assert section["children"][0].get("layout") == "inline"

    def test_first_two_sections_open_rest_closed(self):
        data = {f"section_{i}": {"v": i} for i in range(4)}
        env = render_generic_view(data)
        sections = [c for c in _components(env) if c.get("type") == "section"]
        # 4 sections, all within the cap — no overflow wrapper.
        assert len(sections) == 4
        assert [s["defaultOpen"] for s in sections] == [True, True, False, False]

    def test_overflow_sections_wrapped_in_collapsible(self):
        data = {f"section_{i}": {"v": i} for i in range(10)}
        env = render_generic_view(data)
        comps = _components(env)
        sections = [c for c in comps if c.get("type") == "section"]
        # 5 visible sections + 1 overflow wrapper = 6 total.
        assert len(sections) == 6
        overflow = sections[-1]
        assert "more section" in overflow["label"]
        assert overflow["collapsible"] is True
        assert overflow["defaultOpen"] is False
        # Overflow contains the remaining 5 sections as children.
        assert len(overflow["children"]) == 5


class TestSystemStatusMirror:
    """The generic view should produce the same tree shape as hand-authored
    templates like ``get_system_status``: heading → status pill → sections."""

    def test_heading_plus_status_pill_for_multi_collection_object(self):
        env = render_generic_view(
            {
                "bots": [{"id": 1}, {"id": 2}],
                "channels": [{"id": "c1"}],
                "integrations": [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}],
            },
            tool_name="get_system_status",
        )
        comps = _components(env)
        assert comps[0]["type"] == "heading"
        assert comps[0]["text"] == "Get System Status"
        assert comps[1]["type"] == "status"
        pill = comps[1]["text"]
        assert "2 bots" in pill
        assert "1 channels" in pill
        assert "3 integrations" in pill
        assert comps[1]["color"] == "success"

    def test_no_status_pill_without_collections(self):
        env = render_generic_view(
            {"name": "x", "flag": True}, tool_name="tiny_tool"
        )
        comps = _components(env)
        assert _types(comps) == ["heading", "properties"]

    def test_top_level_array_summary_pill(self):
        env = render_generic_view(
            [{"id": i} for i in range(5)], tool_name="list_things"
        )
        comps = _components(env)
        assert comps[0]["text"] == "List Things"
        assert comps[1]["type"] == "status"
        assert "5 items" in comps[1]["text"]


class TestCountPairPromotion:
    def test_logs_count_pair_folds_count_into_label(self):
        env = render_generic_view(
            {
                "poopLogs": {
                    "logs": [
                        {"date": "2026-04-18", "moisture": 8},
                        {"date": "2026-04-17", "moisture": 7},
                    ],
                    "count": 2,
                }
            }
        )
        section = _first_of(_components(env), "section")
        assert section["label"] == "Poop Logs · 2"
        # Children should be the table itself — no separate "Count" row.
        child_types = [c.get("type") for c in section["children"]]
        assert "table" in child_types
        for child in section["children"]:
            if child.get("type") == "properties":
                labels = {i["label"] for i in child["items"]}
                assert "Count" not in labels

    def test_count_pair_with_scalar_siblings(self):
        env = render_generic_view(
            {
                "recentVisits": {
                    "visits": [{"date": "2026-04-18"}],
                    "count": 1,
                    "lastVisitDays": 3,
                }
            }
        )
        section = _first_of(_components(env), "section")
        assert section["label"] == "Recent Visits · 1"
        # Scalar siblings above the table.
        props = next(
            c for c in section["children"] if c.get("type") == "properties"
        )
        labels = {i["label"] for i in props["items"]}
        assert labels == {"Last Visit Days"}

    def test_non_pair_shape_falls_through(self):
        # "count" exists but no whitelisted list key → no promotion.
        env = render_generic_view(
            {"stuff": {"items_renamed": [{"x": 1}], "count": 1}}
        )
        section = _first_of(_components(env), "section")
        assert section["label"] == "Stuff"  # no "· N" suffix


class TestNestedHomogeneousArrayPromotion:
    """Arrays-of-homogeneous-objects one level deep should render as inline
    tables, not as truncated JSON-string rows — the biggest visual win."""

    def test_nested_array_renders_as_inline_table(self):
        env = render_generic_view(
            {
                "report": {
                    "logs": [
                        {"date": "2026-04-18", "value": 1},
                        {"date": "2026-04-17", "value": 2},
                    ],
                    "total": 3,
                }
            }
        )
        section = _first_of(_components(env), "section")
        # The inner object has logs + a non-count scalar → no count-pair
        # promotion; goes through _components_for_flat_object, which must
        # now promote the logs array to a table.
        child_types = [c.get("type") for c in section["children"]]
        assert "table" in child_types
        # Verify the scalar sibling still renders as properties.
        assert "properties" in child_types
        # The logs value should NOT appear as a JSON-string properties row.
        for child in section["children"]:
            if child.get("type") == "properties":
                for item in child["items"]:
                    assert not item["value"].startswith('[{')


class TestEdgeCases:
    def test_null_result(self):
        env = render_generic_view(None)
        comps = _components(env)
        assert _types(comps) == ["text"]
        assert comps[0]["content"] == "—"

    def test_scalar_result(self):
        env = render_generic_view("just a string")
        comps = _components(env)
        assert _types(comps) == ["properties"]
        assert comps[0]["items"] == [{"label": "Value", "value": "just a string"}]

    def test_stringified_json_is_parsed(self):
        env = render_generic_view('{"x": 1, "y": 2}')
        props = _first_of(_components(env), "properties")
        labels = {i["label"]: i["value"] for i in props["items"]}
        assert labels == {"X": "1", "Y": "2"}

    def test_non_json_string_rendered_as_value(self):
        env = render_generic_view("hello world, not json")
        comps = _components(env)
        assert comps[0]["items"][0]["value"] == "hello world, not json"

    def test_large_payload_truncation_replaces_components(self):
        row = {f"c{i}": "x" * 200 for i in range(8)}
        big = [dict(row) for _ in range(50)]
        env = render_generic_view(big)
        body = json.loads(env.body)
        assert len(env.body.encode("utf-8")) < 50_000
        types = [c.get("type") for c in body["components"]]
        assert "status" in types
        assert any(
            c.get("text", "").startswith("Result too large")
            for c in body["components"]
        )

    def test_heterogeneous_array_falls_back_to_code(self):
        env = render_generic_view([1, "two", {"three": 3}])
        comps = _components(env)
        assert _first_of(comps, "code")["language"] == "json"

    def test_envelope_is_not_refreshable(self):
        env = render_generic_view({"a": 1})
        assert env.refreshable is False
        assert env.refresh_interval_seconds is None

    def test_empty_object_shows_placeholder(self):
        env = render_generic_view({})
        comps = _components(env)
        assert any(
            c.get("type") == "text" and "Empty" in c.get("content", "")
            for c in comps
        )
