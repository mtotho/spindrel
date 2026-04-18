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


class TestScalarObject:
    def test_flat_object_renders_as_properties(self):
        env = render_generic_view(
            {"name": "pikachu", "level": 25, "trained": True, "nickname": None},
            tool_name="describe_pokemon",
        )
        comps = _components(env)
        assert _types(comps)[0] == "properties"
        items = comps[0]["items"]
        labels = {i["label"]: i["value"] for i in items}
        assert labels["Name"] == "pikachu"
        assert labels["Level"] == "25"
        assert labels["Trained"] == "Yes"
        assert labels["Nickname"] == "—"
        assert env.refreshable is False
        assert env.content_type == "application/vnd.spindrel.components+json"
        assert env.tool_name == "describe_pokemon"

    def test_camel_and_snake_keys_humanized(self):
        env = render_generic_view({"firstName": "Ash", "last_name": "Ketchum"})
        items = _components(env)[0]["items"]
        labels = {i["label"] for i in items}
        assert labels == {"First Name", "Last Name"}

    def test_long_string_value_truncated(self):
        env = render_generic_view({"bio": "x" * 1000})
        items = _components(env)[0]["items"]
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
        assert _types(comps)[0] == "table"
        tbl = comps[0]
        assert tbl["columns"] == ["Id", "Name", "Role"]
        assert tbl["rows"] == [
            ["1", "Alice", "admin"],
            ["2", "Bob", "user"],
            ["3", "Carol", "user"],
        ]

    def test_column_union_across_rows(self):
        env = render_generic_view(
            [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
        )
        tbl = _components(env)[0]
        assert tbl["columns"] == ["A", "B", "C"]
        assert tbl["rows"][1] == ["3", "—", "4"]

    def test_columns_capped(self):
        item = {f"k{i}": i for i in range(15)}
        env = render_generic_view([item, item])
        comps = _components(env)
        tbl = comps[0]
        assert len(tbl["columns"]) == 8
        # Overflow hint present.
        texts = [c.get("content", "") for c in comps if c.get("type") == "text"]
        assert any("more column" in t for t in texts)


class TestScalarArray:
    def test_scalar_array_renders_as_indexed_properties(self):
        env = render_generic_view(["alpha", "beta", "gamma"])
        comps = _components(env)
        assert _types(comps)[0] == "properties"
        items = comps[0]["items"]
        assert [i["label"] for i in items] == ["[0]", "[1]", "[2]"]
        assert [i["value"] for i in items] == ["alpha", "beta", "gamma"]

    def test_empty_array_renders_empty_message(self):
        env = render_generic_view([])
        comps = _components(env)
        assert any(
            c.get("type") == "text" and "Empty" in c.get("content", "")
            for c in comps
        )


class TestNesting:
    def test_nested_object_gets_heading_and_properties(self):
        env = render_generic_view(
            {
                "status": "online",
                "address": {"city": "SF", "zip": "94110"},
            }
        )
        comps = _components(env)
        types = _types(comps)
        # Top-level scalars first, then heading + nested properties.
        assert types[0] == "properties"
        assert "heading" in types
        assert types.count("properties") == 2

    def test_nested_sections_capped(self):
        data = {f"section_{i}": {"v": i} for i in range(10)}
        env = render_generic_view(data)
        comps = _components(env)
        headings = [c for c in comps if c.get("type") == "heading"]
        # Cap = 3 nested sections rendered inline.
        assert len(headings) == 3
        texts = [c.get("content", "") for c in comps if c.get("type") == "text"]
        assert any("more section" in t for t in texts)


class TestEdgeCases:
    def test_null_result(self):
        env = render_generic_view(None)
        comps = _components(env)
        assert _types(comps) == ["text"]
        assert comps[0]["content"] == "—"

    def test_scalar_result(self):
        env = render_generic_view("just a string")
        items = _components(env)[0]["items"]
        assert items == [{"label": "Value", "value": "just a string"}]

    def test_stringified_json_is_parsed(self):
        env = render_generic_view('{"x": 1, "y": 2}')
        items = _components(env)[0]["items"]
        labels = {i["label"]: i["value"] for i in items}
        assert labels == {"X": "1", "Y": "2"}

    def test_non_json_string_rendered_as_value(self):
        env = render_generic_view("hello world, not json")
        items = _components(env)[0]["items"]
        assert items[0]["value"] == "hello world, not json"

    def test_large_payload_truncation_replaces_components(self):
        # A 50-row × 8-col table where each cell is near the per-value cap —
        # serialized body exceeds the 50KB envelope cap and trips the
        # "too large" fallback.
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
        assert comps[0]["type"] == "code"

    def test_envelope_is_not_refreshable(self):
        env = render_generic_view({"a": 1})
        assert env.refreshable is False
        assert env.refresh_interval_seconds is None

    def test_empty_object_shows_placeholder(self):
        env = render_generic_view({})
        comps = _components(env)
        assert _types(comps) == ["text"]
