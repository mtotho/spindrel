"""Pin: complex `when` shapes (`all` / `any` / `not` / `param`) round-trip
through the admin API verbatim — no key dropped, no shape coerced.

Pipeline Canvas tab classifies non-simple `when` as read-only and routes the
user to the JSON tab for editing. That contract relies on the backend
preserving the structure.
"""
import pytest
from httpx import AsyncClient

from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


COMPLEX_WHEN_SHAPES = [
    {"all": [{"step": "s1", "status": "done"}, {"not": {"param": "skip", "equals": True}}]},
    {"any": [{"step": "s1", "output_contains": "x"}, {"step": "s2", "output_not_contains": "y"}]},
    {"not": {"param": "dry_run", "equals": True}},
    {"param": "feature_flag", "equals": "on"},
    {"all": [{"any": [{"step": "a", "status": "done"}]}, {"step": "b", "status": "failed"}]},
]


@pytest.mark.parametrize("when", COMPLEX_WHEN_SHAPES)
async def test_complex_when_survives_round_trip(client: AsyncClient, when: dict):
    steps = [
        {"id": "s1", "type": "agent", "prompt": "first", "on_failure": "abort"},
        {"id": "s2", "type": "agent", "prompt": "second", "on_failure": "abort"},
        {"id": "s3", "type": "tool", "tool_name": "noop", "when": when, "on_failure": "abort"},
    ]
    resp = await client.post(
        "/api/v1/admin/tasks",
        headers=AUTH_HEADERS,
        json={
            "bot_id": "test-bot",
            "prompt": "",
            "task_type": "pipeline",
            "steps": steps,
        },
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]

    get_resp = await client.get(f"/api/v1/admin/tasks/{task_id}", headers=AUTH_HEADERS)
    assert get_resp.status_code == 200
    fetched_when = get_resp.json()["steps"][2]["when"]
    # Structural equality — Postgres JSONB normalizes key order.
    assert fetched_when == when


async def test_patch_does_not_reshape_when(client: AsyncClient):
    create = await client.post(
        "/api/v1/admin/tasks",
        headers=AUTH_HEADERS,
        json={
            "bot_id": "test-bot",
            "prompt": "",
            "task_type": "pipeline",
            "steps": [
                {"id": "s1", "type": "agent", "prompt": "first", "on_failure": "abort"},
                {"id": "s2", "type": "agent", "prompt": "second", "on_failure": "abort"},
            ],
        },
    )
    assert create.status_code == 201
    task_id = create.json()["id"]

    complex_when = {"all": [{"step": "s1", "status": "done"}, {"not": {"param": "skip"}}]}
    new_steps = [
        {"id": "s1", "type": "agent", "prompt": "first", "on_failure": "abort"},
        {"id": "s2", "type": "agent", "prompt": "second", "when": complex_when, "on_failure": "abort"},
    ]
    patch = await client.patch(
        f"/api/v1/admin/tasks/{task_id}",
        headers=AUTH_HEADERS,
        json={"steps": new_steps},
    )
    assert patch.status_code == 200
    assert patch.json()["steps"][1]["when"] == complex_when
