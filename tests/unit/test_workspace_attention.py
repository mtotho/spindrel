import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Session, Task, ToolCall, TraceEvent
from app.services.workspace_attention import (
    acknowledge_attention_item,
    acknowledge_attention_items_bulk,
    assign_attention_item,
    build_attention_assignment_block,
    create_user_attention_item,
    detect_structured_attention_once,
    list_attention_items,
    mark_attention_responded,
    place_attention_item,
    report_attention_assignment,
    resolve_attention_item,
)
from app.dependencies import ApiKeyAuth


@pytest.mark.asyncio
async def test_place_attention_item_dedupes_active_items(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    first = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Needs a look",
        message="first",
        dedupe_key="stable",
    )
    second = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Needs a look",
        message="updated",
        dedupe_key="stable",
    )

    assert second.id == first.id
    assert second.message == "updated"
    assert second.occurrence_count == 2


@pytest.mark.asyncio
async def test_acknowledge_attention_item_hides_grouped_occurrences(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )
    await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )

    acknowledged = await acknowledge_attention_item(db_session, item.id)

    assert acknowledged.status == "acknowledged"
    assert acknowledged.occurrence_count == 2
    visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )
    assert visible == []


@pytest.mark.asyncio
async def test_acknowledge_attention_item_hides_last_occurrence_until_new_one(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )
    acknowledged = await acknowledge_attention_item(db_session, item.id)

    assert acknowledged.status == "acknowledged"
    visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )
    assert visible == []

    reopened = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )

    assert reopened.id == item.id
    assert reopened.status == "open"
    assert reopened.occurrence_count == 2


@pytest.mark.asyncio
async def test_acknowledged_structured_item_does_not_reopen_for_same_source_event(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
        source_event_key="tool_call:one",
    )
    acknowledged = await acknowledge_attention_item(db_session, item.id)
    reopened = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
        source_event_key="tool_call:one",
    )

    assert acknowledged.status == "acknowledged"
    assert reopened.id == item.id
    assert reopened.status == "acknowledged"
    assert reopened.occurrence_count == 1


@pytest.mark.asyncio
async def test_acknowledged_structured_item_reopens_for_new_source_event(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
        source_event_key="tool_call:one",
    )
    await acknowledge_attention_item(db_session, item.id)
    reopened = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
        source_event_key="tool_call:two",
    )

    assert reopened.id == item.id
    assert reopened.status == "open"
    assert reopened.occurrence_count == 2


@pytest.mark.asyncio
async def test_bulk_acknowledge_target_scope_only_hides_that_target(db_session):
    channel_id = uuid.uuid4()
    other_channel_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"),
        Channel(id=other_channel_id, name="Other", bot_id="bot-a", client_id="other"),
    ])
    await db_session.commit()
    first = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="First",
        dedupe_key="first",
    )
    second = await place_attention_item(
        db_session,
        source_type="user",
        source_id="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Second",
        dedupe_key="second",
    )
    other = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=other_channel_id,
        target_kind="channel",
        target_id=str(other_channel_id),
        title="Other",
        dedupe_key="other",
    )

    updated = await acknowledge_attention_items_bulk(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:write"], name="writer"),
        scope="target",
        target_kind="channel",
        target_id=str(channel_id),
        channel_id=channel_id,
    )

    assert {item.id for item in updated} == {first.id, second.id}
    assert (await db_session.get(type(first), first.id)).status == "acknowledged"
    assert (await db_session.get(type(second), second.id)).status == "acknowledged"
    assert (await db_session.get(type(other), other.id)).status == "open"


@pytest.mark.asyncio
async def test_bulk_acknowledge_workspace_visible_respects_system_visibility(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    bot_item = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Bot warning",
        dedupe_key="bot-warning",
    )
    system_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Trace error",
        dedupe_key="trace-error",
    )

    writer_updates = await acknowledge_attention_items_bulk(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:write"], name="writer"),
        scope="workspace_visible",
    )
    assert {item.id for item in writer_updates} == {bot_item.id}
    assert (await db_session.get(type(bot_item), bot_item.id)).status == "acknowledged"
    assert (await db_session.get(type(system_item), system_item.id)).status == "open"

    admin_updates = await acknowledge_attention_items_bulk(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:write"], name="admin"),
        scope="workspace_visible",
    )
    assert {item.id for item in admin_updates} == {system_item.id}
    assert (await db_session.get(type(system_item), system_item.id)).status == "acknowledged"


@pytest.mark.asyncio
async def test_resolved_attention_item_reopens_as_new_row(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    first = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )
    await resolve_attention_item(db_session, first.id, resolved_by="user:test")
    second = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
    )

    assert second.id != first.id
    assert second.status == "open"


@pytest.mark.asyncio
async def test_non_admin_visibility_excludes_system_items(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Trace error",
    )
    await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Bot warning",
    )

    visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:read"], name="user-key"),
    )
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert [item.title for item in visible] == ["Bot warning"]
    assert {item.title for item in admin_visible} == {"Trace error", "Bot warning"}


@pytest.mark.asyncio
async def test_non_admin_visibility_includes_user_items(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()

    item = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Manual follow-up",
        message="Check the deploy queue.",
    )

    visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:read"], name="user-key"),
    )

    assert [row.id for row in visible] == [item.id]


@pytest.mark.asyncio
async def test_next_heartbeat_assignment_injects_block_and_report_updates_item(db_session, bot_registry):
    bot_registry.register("bot-a")
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    item = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Manual follow-up",
        message="Check the deploy queue.",
        next_steps=["Summarize blockers"],
    )

    assigned = await assign_attention_item(
        db_session,
        item.id,
        bot_id="bot-a",
        mode="next_heartbeat",
        instructions="Look only; report findings.",
        assigned_by="user:test",
    )
    block = await build_attention_assignment_block(db_session, channel_id=channel_id, bot_id="bot-a")

    assert assigned.assignment_status == "assigned"
    assert assigned.assignment_task_id is None
    assert str(item.id) in block
    assert "Look only; report findings." in block

    reported = await report_attention_assignment(
        db_session,
        item.id,
        bot_id="bot-a",
        findings="Queue is empty.",
    )

    assert reported.assignment_status == "reported"
    assert reported.assignment_report == "Queue is empty."
    assert reported.status == "responded"


@pytest.mark.asyncio
async def test_run_now_assignment_creates_attention_task(db_session, bot_registry):
    bot_registry.register("bot-a")
    session_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="Ops",
        bot_id="bot-a",
        client_id="ops",
        active_session_id=session_id,
    ))
    await db_session.commit()
    item = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Manual follow-up",
    )

    assigned = await assign_attention_item(
        db_session,
        item.id,
        bot_id="bot-a",
        mode="run_now",
        instructions="Investigate only.",
        assigned_by="user:test",
    )

    assert assigned.assignment_status == "running"
    assert assigned.assignment_task_id is not None
    task = await db_session.get(Task, assigned.assignment_task_id)
    assert task is not None
    assert task.task_type == "attention_assignment"
    assert task.callback_config["attention_item_id"] == str(item.id)
    assert task.execution_config["tools"] == ["report_attention_assignment"]


@pytest.mark.asyncio
async def test_mark_attention_responded_keeps_item_open_until_resolved(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    item = await place_attention_item(
        db_session,
        source_type="bot",
        source_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Needs reply",
        requires_response=True,
    )

    responded = await mark_attention_responded(db_session, item.id, responded_by="user:test")

    assert responded.status == "responded"
    assert responded.resolved_at is None
    assert responded.responded_at is not None


@pytest.mark.asyncio
async def test_structured_detector_groups_tool_trace_and_heartbeat_failures(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    heartbeat_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    db_session.add(ChannelHeartbeat(id=heartbeat_id, channel_id=channel_id))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="bot-a",
        tool_name="run_script",
        tool_type="local",
        status="error",
        error="boom 123",
        created_at=datetime.now(timezone.utc),
    ))
    db_session.add(TraceEvent(
        session_id=session_id,
        bot_id="bot-a",
        event_type="error",
        data={"error": "boom 456"},
        created_at=datetime.now(timezone.utc),
    ))
    db_session.add(HeartbeatRun(
        heartbeat_id=heartbeat_id,
        status="error",
        error="heartbeat boom",
        run_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    assert created == 3

    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )
    assert {item.title for item in admin_visible} == {"run_script failed", "Trace error", "Heartbeat failed"}


@pytest.mark.asyncio
async def test_structured_detector_suppresses_single_noisy_file_tool_error(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="bot-a",
        tool_name="read_file",
        tool_type="local",
        status="error",
        error="No such file or directory: notes.txt",
        created_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert created == 0
    assert admin_visible == []


@pytest.mark.asyncio
async def test_structured_detector_surfaces_repeated_noisy_file_tool_error(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    for _ in range(3):
        db_session.add(ToolCall(
            session_id=session_id,
            bot_id="bot-a",
            tool_name="read_file",
            tool_type="local",
            status="error",
            error="No such file or directory: notes.txt",
            created_at=datetime.now(timezone.utc),
        ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert created == 1
    assert [item.title for item in admin_visible] == ["read_file failed"]
    assert admin_visible[0].occurrence_count == 3
