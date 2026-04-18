"""Tests for POST /api/v1/admin/widget-packages/generic-render.

Auto-renders any JSON tool result as a dashboard card, used when a tool has
no bespoke widget template.
"""
from __future__ import annotations

import json

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


class TestGenericRender:
    @pytest.mark.asyncio
    async def test_renders_flat_object_as_properties(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/generic-render",
            json={
                "tool_name": "some_untemplated_tool",
                "raw_result": {"status": "ok", "count": 42},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        env = data["envelope"]
        assert env["content_type"] == "application/vnd.spindrel.components+json"
        assert env["refreshable"] is False
        body = json.loads(env["body"])
        types = [c.get("type") for c in body["components"]]
        assert "properties" in types

    @pytest.mark.asyncio
    async def test_renders_object_array_as_table(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/generic-render",
            json={
                "tool_name": "list_users",
                "raw_result": [
                    {"id": 1, "name": "Alice"},
                    {"id": 2, "name": "Bob"},
                ],
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = json.loads(r.json()["envelope"]["body"])
        assert body["components"][0]["type"] == "table"
        assert body["components"][0]["columns"] == ["Id", "Name"]

    @pytest.mark.asyncio
    async def test_accepts_stringified_raw_result(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/generic-render",
            json={
                "tool_name": "string_tool",
                "raw_result": '{"a": 1, "b": 2}',
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = json.loads(r.json()["envelope"]["body"])
        assert body["components"][0]["type"] == "properties"

    @pytest.mark.asyncio
    async def test_null_result_renders_placeholder(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/generic-render",
            json={"tool_name": "noop", "raw_result": None},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = json.loads(r.json()["envelope"]["body"])
        assert body["components"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_requires_tool_name(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/generic-render",
            json={"raw_result": {"x": 1}},
            headers=AUTH_HEADERS,
        )
        # Pydantic: tool_name is required.
        assert r.status_code == 422
