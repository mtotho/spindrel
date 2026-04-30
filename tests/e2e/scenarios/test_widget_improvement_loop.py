"""E2E coverage for the widget improvement bot loop.

These scenarios intentionally go through the real bot/task path. The tests
seed an isolated channel dashboard with duplicate native widgets, create a
normal scheduled task from the quick run preset, and then run it immediately
through the admin task API.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tests.e2e.harness.assertions import assert_no_error_events
from tests.e2e.harness.client import E2EClient


pytestmark = pytest.mark.e2e


PRESET_ID = "widget_improvement_healthcheck"
RECEIPT_REASON = "e2e duplicate usefulness consolidation"
NATIVE_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"
WIDGET_TOOLS = [
    "assess_widget_usefulness",
    "describe_dashboard",
    "check_dashboard_widgets",
    "check_widget",
    "inspect_widget_pin",
    "move_pins",
    "unpin_widget",
    "pin_widget",
    "set_dashboard_chrome",
]
SPATIAL_STEWARD_TOOLS = [
    "get_skill",
    "view_spatial_canvas",
    "inspect_spatial_widget_scene",
    "preview_spatial_widget_changes",
    "pin_spatial_widget",
    "move_spatial_widget",
    "resize_spatial_widget",
    "remove_spatial_widget",
]


def _dashboard_key(channel_id: str) -> str:
    return f"channel:{channel_id}"


def _native_envelope(widget_ref: str, label: str, *, source_bot_id: str) -> dict[str, Any]:
    return {
        "content_type": NATIVE_CONTENT_TYPE,
        "body": {
            "widget_ref": widget_ref,
            "widget_kind": "native_app",
            "display_label": label,
            "state": {
                "body": f"# {label}\n\nSeeded by the widget improvement e2e loop.",
                "items": [],
            },
            "config": {},
            "actions": [],
        },
        "plain_body": f"{label} seeded by the widget improvement e2e loop.",
        "display": "inline",
        "display_label": label,
        "source_bot_id": source_bot_id,
    }


async def _make_temp_bot(client: E2EClient, *, tools: list[str] | None = None) -> str:
    return await client.create_temp_bot(
        client.config.default_model,
        tools=tools or WIDGET_TOOLS,
        system_prompt=(
            "You are an E2E widget improvement bot. Follow tool instructions exactly. "
            "When asked to assess widgets, call the requested widget tool before answering. "
            "When an exact pin_id and reason are provided, use those literal values. "
            "Keep final answers concise."
        ),
    )


async def _make_spatial_steward_bot(client: E2EClient) -> str:
    return await client.create_temp_bot(
        client.config.default_model,
        tools=SPATIAL_STEWARD_TOOLS,
        system_prompt=(
            "You are an E2E spatial widget steward. Load the requested skill when asked. "
            "Before changing spatial widgets, inspect the current spatial widget scene and "
            "preview the exact operation you intend to apply. Never call a spatial widget "
            "mutation tool before its matching preview. Use literal coordinates, sizes, "
            "labels, and widget refs from the user request."
        ),
    )


async def _make_channel(
    client: E2EClient,
    *,
    bot_id: str,
    mode: str,
) -> tuple[str, str]:
    client_id = client.new_client_id("e2e-widget-loop")
    channel = await client.create_channel({
        "client_id": client_id,
        "bot_id": bot_id,
        "name": f"E2E widget loop {client_id.rsplit(':', 1)[-1]}",
        "category": "E2E",
    })
    channel_id = str(channel.get("id") or client.derive_channel_id(client_id))
    session_id = await client.create_channel_session(channel_id)
    await client.switch_channel_session(channel_id, session_id)
    await client.update_channel_settings(channel_id, {
        "layout_mode": "rail-chat",
        "widget_agency_mode": mode,
    })
    return channel_id, session_id


async def _enable_spatial_widget_policy(
    client: E2EClient,
    *,
    channel_id: str,
    bot_id: str,
) -> None:
    resp = await client.patch(
        f"/api/v1/workspace/spatial/channels/{channel_id}/bots/{bot_id}/policy",
        json={
            "enabled": True,
            "allow_map_view": True,
            "allow_nearby_inspect": True,
            "allow_spatial_widget_management": True,
        },
    )
    resp.raise_for_status()


async def _seed_duplicate_dashboard(
    client: E2EClient,
    *,
    channel_id: str,
    bot_id: str,
) -> list[dict[str, Any]]:
    dashboard_key = _dashboard_key(channel_id)
    specs = [
        ("core/notes_native", "Loop notes primary", {"x": 0, "y": 0, "w": 6, "h": 8}),
        ("core/notes_native", "Loop notes copy", {"x": 6, "y": 0, "w": 6, "h": 8}),
        ("core/todo_native", "Loop todo", {"x": 12, "y": 0, "w": 6, "h": 8}),
    ]
    pins: list[dict[str, Any]] = []
    for widget_ref, label, grid_layout in specs:
        pins.append(
            await client.create_dashboard_pin({
                "source_kind": "channel",
                "tool_name": widget_ref,
                "envelope": _native_envelope(widget_ref, label, source_bot_id=bot_id),
                "source_channel_id": channel_id,
                "source_bot_id": bot_id,
                "display_label": label,
                "dashboard_key": dashboard_key,
                "zone": "grid",
                "grid_layout": grid_layout,
                "widget_origin": {
                    "definition_kind": "native_widget",
                    "instantiation_kind": "native_catalog",
                    "widget_ref": widget_ref,
                },
            })
        )
    return pins


def _task_payload_from_preset(
    preset: dict[str, Any],
    *,
    bot_id: str,
    channel_id: str,
    session_id: str,
    title: str,
    prompt_suffix: str,
) -> dict[str, Any]:
    defaults = dict(preset["task_defaults"])
    return {
        "bot_id": bot_id,
        "channel_id": channel_id,
        "title": title,
        "prompt": f"{defaults['prompt']}\n\n{prompt_suffix}",
        "task_type": defaults["task_type"],
        "scheduled_at": defaults["scheduled_at"],
        "recurrence": defaults["recurrence"],
        "trigger_config": defaults["trigger_config"],
        "skills": defaults["skills"],
        "tools": defaults["tools"],
        "post_final_to_channel": defaults["post_final_to_channel"],
        "history_mode": defaults["history_mode"],
        "history_recent_count": defaults["history_recent_count"],
        "skip_tool_approval": defaults["skip_tool_approval"],
        "session_target": {"mode": "existing", "session_id": session_id},
    }


async def _run_task_from_preset(
    client: E2EClient,
    preset: dict[str, Any],
    *,
    bot_id: str,
    channel_id: str,
    session_id: str,
    title: str,
    prompt_suffix: str,
    task_ids: list[str],
) -> dict[str, Any]:
    task = await client.create_task(
        _task_payload_from_preset(
            preset,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            title=title,
            prompt_suffix=prompt_suffix,
        )
    )
    task_ids.append(str(task["id"]))
    concrete = await client.run_task_now(str(task["id"]))
    task_ids.append(str(concrete["id"]))
    timeout = max(180, int(client.config.request_timeout) * 3)
    return await client.wait_task_terminal(str(concrete["id"]), timeout=timeout)


def _duplicate_recommendation(assessment: dict[str, Any]) -> dict[str, Any]:
    for recommendation in assessment.get("recommendations") or []:
        if recommendation.get("type") == "duplicate":
            pin_ids = recommendation.get("evidence", {}).get("pin_ids") or []
            if len(pin_ids) >= 2:
                return recommendation
    raise AssertionError(f"assessment did not include a duplicate recommendation: {assessment}")


def _pin_ids(pins: list[dict[str, Any]]) -> set[str]:
    return {str(pin["id"]) for pin in pins}


def _pin_by_label(pins: list[dict[str, Any]], label: str) -> dict[str, Any]:
    for pin in pins:
        if pin.get("display_label") == label or pin.get("envelope", {}).get("display_label") == label:
            return pin
    raise AssertionError(f"pin label {label!r} not found in {pins}")


def _messages_blob(messages: list[dict[str, Any]]) -> str:
    return json.dumps(messages, sort_keys=True, default=str)


def _tool_index(result: Any, tool_name: str) -> int:
    try:
        return result.tools_used.index(tool_name)
    except ValueError as exc:
        raise AssertionError(f"tool {tool_name!r} not used; saw {result.tools_used}") from exc


async def _cleanup(
    client: E2EClient,
    *,
    task_ids: list[str],
    pin_ids: list[str],
    channel_id: str | None,
    bot_id: str | None,
) -> None:
    for task_id in reversed(task_ids):
        await client.delete_task(task_id)
    for pin_id in reversed(pin_ids):
        await client.delete_dashboard_pin(pin_id)
    if channel_id:
        await client.delete_channel(channel_id)
    if bot_id:
        await client.delete_bot(bot_id)


@pytest.mark.asyncio
async def test_widget_improvement_task_propose_mode_does_not_mutate(client: E2EClient) -> None:
    bot_id: str | None = None
    channel_id: str | None = None
    task_ids: list[str] = []
    pin_ids: list[str] = []
    try:
        bot_id = await _make_temp_bot(client)
        channel_id, session_id = await _make_channel(client, bot_id=bot_id, mode="propose")
        seeded = await _seed_duplicate_dashboard(client, channel_id=channel_id, bot_id=bot_id)
        pin_ids.extend(str(pin["id"]) for pin in seeded)
        dashboard_key = _dashboard_key(channel_id)

        before = await client.list_dashboard_pins(dashboard_key)
        before_ids = _pin_ids(before)
        assessment = await client.get_channel_widget_usefulness(channel_id)
        assert assessment["widget_agency_mode"] == "propose"
        _duplicate_recommendation(assessment)

        preset = await client.get_run_preset(PRESET_ID)
        finished = await _run_task_from_preset(
            client,
            preset,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            title="E2E widget improvement propose",
            prompt_suffix=(
                "E2E verification constraints:\n"
                f"- First call assess_widget_usefulness with channel_id {channel_id!r}.\n"
                "- Do not call any mutating dashboard tool. In propose mode, return fix suggestions only.\n"
                "- Include the exact phrase 'widget fixes' in the final answer."
            ),
            task_ids=task_ids,
        )

        assert finished["status"] == "complete", finished
        result_text = str(finished.get("result") or "").lower()
        assert "widget fixes" in result_text or "fix" in result_text
        messages = await client.get_session_messages(session_id, limit=50)
        assert "assess_widget_usefulness" in _messages_blob(messages)
        assert _pin_ids(await client.list_dashboard_pins(dashboard_key)) == before_ids
        assert await client.list_widget_agency_receipts(channel_id) == []
    finally:
        await _cleanup(
            client,
            task_ids=task_ids,
            pin_ids=pin_ids,
            channel_id=channel_id,
            bot_id=bot_id,
        )


@pytest.mark.asyncio
async def test_widget_improvement_task_propose_and_fix_records_receipt(client: E2EClient) -> None:
    bot_id: str | None = None
    channel_id: str | None = None
    task_ids: list[str] = []
    pin_ids: list[str] = []
    try:
        bot_id = await _make_temp_bot(client)
        channel_id, session_id = await _make_channel(client, bot_id=bot_id, mode="propose_and_fix")
        seeded = await _seed_duplicate_dashboard(client, channel_id=channel_id, bot_id=bot_id)
        pin_ids.extend(str(pin["id"]) for pin in seeded)
        dashboard_key = _dashboard_key(channel_id)
        before = await client.list_dashboard_pins(dashboard_key)
        before_ids = _pin_ids(before)
        copy_pin_id = str(_pin_by_label(before, "Loop notes copy")["id"])

        assessment = await client.get_channel_widget_usefulness(channel_id)
        assert assessment["widget_agency_mode"] == "propose_and_fix"
        _duplicate_recommendation(assessment)

        marker = f"widget fix applied {uuid.uuid4().hex[:8]}"
        preset = await client.get_run_preset(PRESET_ID)
        finished = await _run_task_from_preset(
            client,
            preset,
            bot_id=bot_id,
            channel_id=channel_id,
            session_id=session_id,
            title="E2E widget improvement propose and fix",
            prompt_suffix=(
                "E2E verification constraints:\n"
                f"- First call assess_widget_usefulness with channel_id {channel_id!r}.\n"
                f"- Then call unpin_widget exactly once for pin_id {copy_pin_id!r}, "
                f"delete_bundle_data false, reason {RECEIPT_REASON!r}.\n"
                f"- Finish with exact phrase '{marker}'."
            ),
            task_ids=task_ids,
        )

        assert finished["status"] == "complete", finished
        assert marker in str(finished.get("result") or ""), finished
        messages = await client.get_session_messages(session_id, limit=50)
        messages_blob = _messages_blob(messages)
        assert "assess_widget_usefulness" in messages_blob
        assert "unpin_widget" in messages_blob

        after = await client.list_dashboard_pins(dashboard_key)
        after_ids = _pin_ids(after)
        assert copy_pin_id not in after_ids
        assert after_ids == before_ids - {copy_pin_id}

        receipts = await client.list_widget_agency_receipts(channel_id)
        assert any(
            receipt.get("action") == "unpin_widget"
            and receipt.get("reason") == RECEIPT_REASON
            and copy_pin_id in set(receipt.get("affected_pin_ids") or [])
            for receipt in receipts
        ), receipts
    finally:
        await _cleanup(
            client,
            task_ids=task_ids,
            pin_ids=pin_ids,
            channel_id=channel_id,
            bot_id=bot_id,
        )


@pytest.mark.asyncio
async def test_widget_improvement_chat_request_returns_proposals_without_mutation(
    client: E2EClient,
) -> None:
    bot_id: str | None = None
    channel_id: str | None = None
    pin_ids: list[str] = []
    try:
        bot_id = await _make_temp_bot(client, tools=["assess_widget_usefulness"])
        channel_id, _session_id = await _make_channel(client, bot_id=bot_id, mode="propose")
        seeded = await _seed_duplicate_dashboard(client, channel_id=channel_id, bot_id=bot_id)
        pin_ids.extend(str(pin["id"]) for pin in seeded)
        dashboard_key = _dashboard_key(channel_id)
        before_ids = _pin_ids(await client.list_dashboard_pins(dashboard_key))

        result = await client.chat_stream(
            (
                f"Call assess_widget_usefulness for channel_id {channel_id} and return concise "
                "widget fixes for duplicate or low-usefulness widgets. Do not mutate widgets."
            ),
            bot_id=bot_id,
            channel_id=channel_id,
            timeout=max(120, int(client.config.request_timeout) * 2),
        )

        assert_no_error_events(result.events)
        assert "assess_widget_usefulness" in result.tools_used
        assert "proposal" in result.response_text.lower() or "duplicate" in result.response_text.lower()
        assert _pin_ids(await client.list_dashboard_pins(dashboard_key)) == before_ids
        assert await client.list_widget_agency_receipts(channel_id) == []
    finally:
        await _cleanup(
            client,
            task_ids=[],
            pin_ids=pin_ids,
            channel_id=channel_id,
            bot_id=bot_id,
        )


@pytest.mark.asyncio
async def test_spatial_widget_steward_previews_exact_pin_before_mutating(
    client: E2EClient,
) -> None:
    bot_id: str | None = None
    channel_id: str | None = None
    spatial_node_ids: list[str] = []
    label = f"E2E spatial steward note {uuid.uuid4().hex[:8]}"
    widget = "core/notes_native"
    world_x = 640
    world_y = 160
    world_w = 360
    world_h = 240
    try:
        bot_id = await _make_spatial_steward_bot(client)
        channel_id, _session_id = await _make_channel(client, bot_id=bot_id, mode="propose_and_fix")
        await _enable_spatial_widget_policy(client, channel_id=channel_id, bot_id=bot_id)

        seed_resp = await client.get("/api/v1/workspace/spatial/nodes")
        seed_resp.raise_for_status()

        result = await client.chat_stream(
            (
                "Load get_skill for widgets/spatial_stewardship. Then call "
                "inspect_spatial_widget_scene for this channel. If a spatial widget "
                f"named {label!r} does not already exist, call preview_spatial_widget_changes "
                "with exactly one operation: "
                f"action='pin', widget={widget!r}, display_label={label!r}, "
                f"world_x={world_x}, world_y={world_y}, world_w={world_w}, world_h={world_h}. "
                "If the preview does not report a worse overlap/clipping state, call "
                "pin_spatial_widget with exactly the same widget, display_label, "
                "world_x, world_y, world_w, and world_h. Reply with 'spatial steward done'."
            ),
            bot_id=bot_id,
            channel_id=channel_id,
            timeout=max(180, int(client.config.request_timeout) * 3),
            approval_decision={"approved": True, "decided_by": "e2e_spatial_steward"},
        )

        assert_no_error_events(result.events)
        assert "spatial steward done" in result.response_text.lower()
        assert _tool_index(result, "inspect_spatial_widget_scene") < _tool_index(
            result,
            "preview_spatial_widget_changes",
        )
        assert _tool_index(result, "preview_spatial_widget_changes") < _tool_index(
            result,
            "pin_spatial_widget",
        )
        tool_blob = json.dumps([event.data for event in result.tool_events], sort_keys=True, default=str)
        assert "Preview spatial widget changes first" not in tool_blob
        assert "Preview this exact spatial widget" not in tool_blob

        nodes_resp = await client.get("/api/v1/workspace/spatial/nodes")
        nodes_resp.raise_for_status()
        nodes = nodes_resp.json()["nodes"]
        pinned = [
            node for node in nodes
            if node.get("widget_pin_id")
            and node.get("pin", {}).get("source_bot_id") == bot_id
            and node.get("pin", {}).get("display_label") == label
        ]
        assert len(pinned) == 1, pinned
        spatial_node_ids.append(str(pinned[0]["id"]))
        assert pinned[0]["pin"]["tool_name"] == widget
        assert pinned[0]["world_x"] == world_x
        assert pinned[0]["world_y"] == world_y
        assert pinned[0]["world_w"] == world_w
        assert pinned[0]["world_h"] == world_h
    finally:
        for node_id in reversed(spatial_node_ids):
            await client.delete(f"/api/v1/workspace/spatial/nodes/{node_id}")
        await _cleanup(
            client,
            task_ids=[],
            pin_ids=[],
            channel_id=channel_id,
            bot_id=bot_id,
        )
