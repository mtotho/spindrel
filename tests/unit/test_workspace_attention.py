import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, IssueWorkPack, Project, Session, Task, ToolCall, TraceEvent, WorkspaceAttentionItem
from app.routers.api_v1_workspace_attention import resolve_attention as resolve_attention_route
from app.services.workspace_attention import (
    _is_operator_triage_sweep_candidate,
    _normalize_triage_suggested_action,
    _tool_attention_classification,
    acknowledge_attention_item,
    acknowledge_attention_items_bulk,
    assign_attention_item,
    build_attention_brief_from_serialized,
    build_attention_assignment_block,
    create_attention_triage_run,
    create_conversational_issue_work_packs,
    create_issue_intake_note,
    create_manual_issue_work_pack,
    create_user_attention_item,
    detect_structured_attention_once,
    get_attention_triage_run,
    list_attention_triage_runs,
    list_attention_items,
    launch_issue_work_packs_project_runs,
    mark_attention_responded,
    place_attention_item,
    publish_issue_intake,
    record_attention_triage_feedback,
    report_bot_issue,
    report_attention_assignment,
    report_attention_triage_batch,
    report_issue_work_packs,
    resolve_attention_item,
    serialize_issue_work_pack,
    transition_issue_work_pack,
    update_issue_work_pack,
)
from app.services.workspace_command_center import build_command_center
from app.dependencies import ApiKeyAuth
from app.domain.errors import ValidationError


def test_operator_triage_sweep_candidate_only_includes_untriaged_or_failed_visible_items():
    def item(status: str, state: str | None = None):
        evidence = {}
        if state is not None:
            evidence["operator_triage"] = {"state": state}
        return SimpleNamespace(status=status, evidence=evidence)

    assert _is_operator_triage_sweep_candidate(item("open")) is True
    assert _is_operator_triage_sweep_candidate(item("responded")) is True
    assert _is_operator_triage_sweep_candidate(item("responded", "failed")) is True
    assert _is_operator_triage_sweep_candidate(item("responded", "ready_for_review")) is False
    assert _is_operator_triage_sweep_candidate(item("acknowledged", "failed")) is False
    assert _is_operator_triage_sweep_candidate(item("responded", "processed")) is False
    assert _is_operator_triage_sweep_candidate(item("open", "running")) is False


def test_operator_triage_suggested_action_hides_internal_route_terms():
    assert _normalize_triage_suggested_action("Route to developer channel.") == "Open a code fix."
    assert _normalize_triage_suggested_action("Route to development after review.") == "Open a code fix after review."


def test_attention_brief_groups_fix_packs_and_owner_decisions():
    items = [
        {
            "id": "item-code-1",
            "title": "view_spatial_canvas failed",
            "message": "Invalid focus_token.",
            "severity": "critical",
            "target_kind": "channel",
            "target_id": "channel-a",
            "channel_name": "Gardening With Sprout",
            "occurrence_count": 7,
            "evidence": {
                "operator_triage": {
                    "state": "ready_for_review",
                    "classification": "likely_spindrel_code_issue",
                    "route": "developer_channel",
                    "summary": "Repeated focus token failures point to stale token handling.",
                    "suggested_action": "Open a code fix for token lifecycle.",
                },
            },
        },
        {
            "id": "item-code-2",
            "title": "view_spatial_canvas failed",
            "message": "AttributeError: display_name",
            "severity": "critical",
            "target_kind": "channel",
            "target_id": "channel-b",
            "channel_name": "Quality Assurance",
            "occurrence_count": 3,
            "evidence": {
                "operator_triage": {
                    "state": "ready_for_review",
                    "classification": "likely_spindrel_code_issue",
                    "route": "developer_channel",
                    "summary": "Display name access needs a safe fallback.",
                },
            },
        },
        {
            "id": "item-decision",
            "title": "pin_spatial_widget failed",
            "message": "Bot has no API permissions.",
            "severity": "critical",
            "target_kind": "bot",
            "target_id": "sprout",
            "occurrence_count": 1,
            "evidence": {
                "operator_triage": {
                    "state": "ready_for_review",
                    "classification": "user_decision",
                    "route": "owner_channel",
                    "summary": "Sprout needs a permission decision before pinning widgets.",
                },
            },
        },
        {
            "id": "item-quiet",
            "title": "read_file failed",
            "message": "No such file.",
            "severity": "warning",
            "target_kind": "channel",
            "target_id": "channel-c",
            "occurrence_count": 1,
            "evidence": {"classification": "repeated_benign_contract"},
        },
    ]

    brief = build_attention_brief_from_serialized(items)

    assert brief["summary"]["fix_packs"] == 1
    assert brief["summary"]["decisions"] == 1
    assert brief["summary"]["autofix"] == 0
    assert brief["summary"]["quiet"] == 1
    assert brief["next_action"]["kind"] == "decision"
    assert brief["fix_packs"][0]["count"] == 2
    assert brief["fix_packs"][0]["item_ids"] == ["item-code-1", "item-code-2"]
    assert "Start with a regression test" in brief["fix_packs"][0]["prompt"]


def test_attention_brief_prioritizes_autofix_before_generic_fix_packs():
    items = [
        {
            "id": "item-code",
            "title": "call_api failed",
            "message": "Missing request schema.",
            "severity": "critical",
            "target_kind": "channel",
            "target_id": "channel-a",
            "occurrence_count": 3,
            "evidence": {
                "operator_triage": {
                    "state": "ready_for_review",
                    "classification": "likely_spindrel_code_issue",
                    "route": "developer_channel",
                    "summary": "The API contract needs a code fix.",
                },
            },
        },
    ]
    autofix_queue = [{
        "receipt_id": "receipt-1",
        "action_id": "enable_core_agent_tools",
        "summary": "Requested readiness repair: enable core tools",
    }]

    brief = build_attention_brief_from_serialized(items, autofix_queue=autofix_queue)

    assert brief["summary"]["autofix"] == 1
    assert brief["autofix_queue"] == autofix_queue
    assert brief["next_action"]["kind"] == "autofix"
    assert brief["next_action"]["receipt_id"] == "receipt-1"


@pytest.mark.asyncio
async def test_publish_issue_intake_creates_conversational_attention_item(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Spindrel Dev", bot_id="codex", client_id="spindrel-dev"))
    await db_session.commit()

    item = await publish_issue_intake(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        title="Runs page clips review evidence",
        summary="The review row hides the merge receipt after launch.",
        observed_behavior="Merge receipt is below the fold.",
        expected_behavior="The row should scroll or frame the receipt.",
        steps=["Open Mission Control Review", "Launch a work pack"],
        category_hint="quality",
        tags=["ui", "review"],
    )

    assert item.source_type == "bot"
    assert item.source_id == "codex"
    assert item.channel_id == channel_id
    assert item.target_kind == "channel"
    assert item.requires_response is True
    assert item.evidence["issue_intake"]["source"] == "conversation"
    assert item.evidence["issue_intake"]["category_hint"] == "quality"
    assert item.evidence["issue_intake"]["steps"] == ["Open Mission Control Review", "Launch a work pack"]


async def test_create_issue_intake_note_creates_user_issue_intake(db_session):
    item = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="Project Factory note",
        summary="A rough issue note should be triageable later.",
        category_hint="quality",
        tags=["e2e"],
    )

    assert item.source_type == "user"
    assert item.target_kind == "system"
    assert item.evidence["issue_intake"]["source"] == "user"
    assert item.evidence["issue_intake"]["category_hint"] == "quality"


async def test_create_manual_issue_work_pack_links_source_items(db_session):
    item = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="Runs row lacks review evidence",
        summary="The review cockpit should show receipt provenance.",
    )

    pack = await create_manual_issue_work_pack(
        db_session,
        actor="api_key:e2e",
        title="Expose review evidence in Project Runs",
        summary="Surface receipt and review provenance on the run row.",
        category="code_bug",
        confidence="high",
        source_item_ids=[str(item.id)],
        launch_prompt="Implement the review evidence display and publish a receipt.",
    )

    assert pack.status == "proposed"
    assert pack.source_item_ids == [str(item.id)]
    refreshed = await db_session.get(type(item), item.id)
    triage = refreshed.evidence["issue_triage"]
    assert triage["state"] == "packed"
    assert triage["work_pack_ids"] == [str(pack.id)]


@pytest.mark.asyncio
async def test_update_issue_work_pack_records_review_provenance_and_source_summaries(db_session):
    first = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="Old evidence",
        summary="Old source should be replaceable.",
    )
    second = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="New evidence",
        summary="New source should serialize for review.",
    )
    pack = await create_manual_issue_work_pack(
        db_session,
        actor="api_key:e2e",
        title="Initial pack",
        summary="Initial summary",
        category="code_bug",
        confidence="medium",
        source_item_ids=[str(first.id)],
    )

    updated = await update_issue_work_pack(
        db_session,
        pack.id,
        actor="api_key:e2e",
        fields={
            "title": "Edited pack",
            "summary": "Edited summary",
            "category": "test_failure",
            "confidence": "high",
            "source_item_ids": [str(second.id)],
            "launch_prompt": "Run the focused regression.",
        },
    )

    assert updated.title == "Edited pack"
    assert updated.category == "test_failure"
    assert updated.confidence == "high"
    assert updated.source_item_ids == [str(second.id)]
    assert updated.metadata_["latest_review_action"]["action"] == "edited"
    serialized = await serialize_issue_work_pack(db_session, updated)
    assert serialized["latest_review_action"]["action"] == "edited"
    assert serialized["source_items"][0]["title"] == "New evidence"


@pytest.mark.asyncio
async def test_work_pack_review_actions_gate_launch_and_reopen(db_session):
    item = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="Needs operator decision",
        summary="The pack should be reviewed before launch.",
    )
    pack = await create_manual_issue_work_pack(
        db_session,
        actor="api_key:e2e",
        title="Decision pack",
        summary="Review me.",
        category="code_bug",
        confidence="medium",
        source_item_ids=[str(item.id)],
    )

    dismissed = await transition_issue_work_pack(
        db_session,
        pack.id,
        actor="api_key:e2e",
        action="dismiss",
        note="Duplicate of a tracked issue.",
    )
    assert dismissed.status == "dismissed"
    assert dismissed.metadata_["latest_review_action"]["note"] == "Duplicate of a tracked issue."

    reopened = await transition_issue_work_pack(
        db_session,
        pack.id,
        actor="api_key:e2e",
        action="reopen",
        note="Still actionable after review.",
    )
    assert reopened.status == "proposed"

    needs_info = await transition_issue_work_pack(
        db_session,
        pack.id,
        actor="api_key:e2e",
        action="needs_info",
        note="Need reproduction details.",
    )
    assert needs_info.status == "needs_info"
    assert [entry["action"] for entry in needs_info.metadata_["review_actions"][-3:]] == ["dismiss", "reopen", "needs_info"]


@pytest.mark.asyncio
async def test_launched_issue_work_pack_cannot_be_rewritten(db_session):
    item = await create_issue_intake_note(
        db_session,
        actor="api_key:e2e",
        channel_id=None,
        title="Already launched",
        summary="Launched handoff should stay immutable.",
    )
    pack = await create_manual_issue_work_pack(
        db_session,
        actor="api_key:e2e",
        title="Immutable pack",
        summary="Launch history matters.",
        category="code_bug",
        confidence="medium",
        source_item_ids=[str(item.id)],
    )
    pack.status = "launched"
    await db_session.commit()

    with pytest.raises(ValidationError, match="Launched work packs cannot be edited"):
        await update_issue_work_pack(db_session, pack.id, actor="api_key:e2e", fields={"title": "Rewrite"})
    with pytest.raises(ValidationError, match="Launched work packs cannot be dismissed"):
        await transition_issue_work_pack(db_session, pack.id, actor="api_key:e2e", action="dismiss")


@pytest.mark.asyncio
async def test_create_conversational_issue_work_packs_auto_creates_source_intake(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="codex",
        client_id="project-agent-work-packs",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    packs = await create_conversational_issue_work_packs(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        session_id=session_id,
        triage_receipt={
            "summary": "Grouped the planning conversation into one launchable Project Factory pack.",
            "grouping_rationale": "The requested work is one coherent implementation unit.",
            "launch_readiness": "Ready after human review; requires tests and screenshots.",
            "follow_up_questions": ["Confirm final UI copy before launch."],
            "excluded_items": ["Future scheduler ideas stay out of this pack."],
        },
        packs=[{
            "title": "Split Project Factory into work units",
            "summary": "Create proposed work packs from the planning conversation.",
            "category": "code_bug",
            "confidence": "high",
            "conversation_summary": "User and Codex planned the next project-factory phase.",
            "launch_prompt": "Implement the conversational work-pack creation primitive.",
        }],
    )

    assert len(packs) == 1
    pack = packs[0]
    assert pack.status == "proposed"
    assert pack.project_id == project_id
    assert pack.channel_id == channel_id
    assert pack.metadata_["source"] == "conversation"
    assert pack.metadata_["created_by"] == "bot:codex"
    assert pack.metadata_["conversation"]["bot_id"] == "codex"
    assert pack.metadata_["conversation"]["session_id"] == str(session_id)
    assert pack.metadata_["triage_receipt_id"].startswith("issue-triage-receipt:")
    assert pack.metadata_["triage_receipt"]["summary"] == "Grouped the planning conversation into one launchable Project Factory pack."
    serialized = await serialize_issue_work_pack(db_session, pack)
    assert serialized["triage_receipt_id"] == pack.metadata_["triage_receipt_id"]
    assert serialized["triage_receipt"]["launch_readiness"] == "Ready after human review; requires tests and screenshots."
    assert pack.source_item_ids and len(pack.source_item_ids) == 1

    source = await db_session.get(WorkspaceAttentionItem, uuid.UUID(pack.source_item_ids[0]))
    assert source is not None
    assert source.evidence["issue_intake"]["source"] == "conversation"
    assert source.evidence["issue_triage"]["state"] == "packed"
    assert source.evidence["issue_triage"]["source"] == "conversation"
    assert source.evidence["issue_triage"]["work_pack_ids"] == [str(pack.id)]
    assert source.evidence["issue_triage"]["triage_receipt_id"] == pack.metadata_["triage_receipt_id"]
    assert source.evidence["issue_triage"]["triage_receipt_summary"] == pack.metadata_["triage_receipt"]["summary"]


@pytest.mark.asyncio
async def test_report_issue_work_packs_rejects_normal_conversation_context(db_session):
    with pytest.raises(ValidationError, match="requires a triage task context"):
        await report_issue_work_packs(
            db_session,
            bot_id="codex",
            triage_task_id=None,
            packs=[{
                "title": "Not allowed here",
                "summary": "The triage reporter must remain task-scoped.",
                "category": "code_bug",
                "confidence": "medium",
                "source_item_ids": [str(uuid.uuid4())],
            }],
        )


@pytest.mark.asyncio
async def test_create_issue_work_packs_tool_uses_normal_agent_channel_context(
    db_session,
    patched_async_sessions,
    agent_context,
    monkeypatch,
):
    from app.tools import registry
    from app.tools.local import workspace_attention as attention_tools

    monkeypatch.setattr(attention_tools, "async_session", patched_async_sessions)
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="codex",
        client_id="project-agent-tool-work-packs",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()
    agent_context(bot_id="codex", channel_id=channel_id, session_id=uuid.uuid4())

    assert "create_issue_work_packs" in registry._tools
    assert registry.get_tool_context_requirements("create_issue_work_packs") == (True, True)

    raw = await attention_tools.create_issue_work_packs(packs=[{
        "title": "Conversation-generated work pack",
        "summary": "A normal Project-bound agent should be able to publish this pack.",
        "category": "code_bug",
        "confidence": "medium",
    }], triage_receipt={"summary": "One coherent Project-bound work pack."})
    payload = json.loads(raw)

    assert payload["count"] == 1
    assert payload["work_packs"][0]["metadata"]["source"] == "conversation"
    assert payload["work_packs"][0]["project_id"] == str(project_id)
    assert payload["work_packs"][0]["triage_receipt"]["summary"] == "One coherent Project-bound work pack."


@pytest.mark.asyncio
async def test_batch_launch_issue_work_packs_creates_runs_with_shared_batch_id(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel",
        root_path="common/projects/spindrel",
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="codex",
        client_id="project-agent-batch-launch",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    packs = await create_conversational_issue_work_packs(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        packs=[
            {
                "title": "Fix first bug",
                "summary": "First batch item.",
                "category": "code_bug",
                "confidence": "high",
                "launch_prompt": "Fix first bug, run tests, capture screenshots, and publish a receipt.",
            },
            {
                "title": "Fix second bug",
                "summary": "Second batch item.",
                "category": "code_bug",
                "confidence": "medium",
                "launch_prompt": "Fix second bug, run tests, capture screenshots, and publish a receipt.",
            },
        ],
    )

    result = await launch_issue_work_packs_project_runs(
        db_session,
        pack_ids=[pack.id for pack in packs],
        project_id=project_id,
        channel_id=channel_id,
        actor="admin",
        note="Launch overnight batch.",
    )

    assert result["count"] == 2
    assert result["launch_batch_id"].startswith("issue-work-pack-batch:")
    assert len(result["runs"]) == 2
    refreshed = [await db_session.get(IssueWorkPack, pack.id) for pack in packs]
    assert {pack.status for pack in refreshed if pack is not None} == {"launched"}
    assert {pack.metadata_["launch_batch_id"] for pack in refreshed if pack is not None} == {result["launch_batch_id"]}
    assert all(pack.launched_task_id for pack in refreshed if pack is not None)
    for pack in refreshed:
        assert pack is not None
        latest = pack.metadata_["latest_review_action"]
        assert latest["action"] == "launched"
        assert latest["note"] == "Launch overnight batch."
        task = await db_session.get(Task, pack.launched_task_id)
        assert task is not None
        assert task.execution_config["project_coding_run"]["source_work_pack_id"] == str(pack.id)
        assert task.execution_config["project_coding_run"]["launch_batch_id"] == result["launch_batch_id"]
    assert {run["launch_batch_id"] for run in result["runs"]} == {result["launch_batch_id"]}


@pytest.mark.asyncio
async def test_batch_launch_issue_work_packs_blocks_whole_batch_when_any_pack_is_not_launchable(db_session):
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    project = Project(
        id=project_id,
        workspace_id=workspace_id,
        name="Spindrel",
        slug="spindrel-batch-block",
        root_path="common/projects/spindrel",
    )
    channel = Channel(
        id=channel_id,
        name="Project Agent",
        bot_id="codex",
        client_id="project-agent-batch-block",
        project_id=project_id,
        workspace_id=workspace_id,
    )
    db_session.add_all([project, channel])
    await db_session.commit()

    packs = await create_conversational_issue_work_packs(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        packs=[
            {
                "title": "Ready pack",
                "summary": "This pack is launchable.",
                "category": "code_bug",
                "confidence": "high",
                "launch_prompt": "Fix the ready pack.",
            },
            {
                "title": "Needs answer",
                "summary": "This pack needs another answer.",
                "category": "needs_info",
                "confidence": "low",
            },
        ],
    )

    with pytest.raises(ValidationError, match="need more information"):
        await launch_issue_work_packs_project_runs(
            db_session,
            pack_ids=[pack.id for pack in packs],
            project_id=project_id,
            channel_id=channel_id,
            actor="admin",
        )

    refreshed = [await db_session.get(IssueWorkPack, pack.id) for pack in packs]
    assert [pack.status for pack in refreshed if pack is not None] == ["proposed", "needs_info"]
    assert all(pack.launched_task_id is None for pack in refreshed if pack is not None)


@pytest.mark.asyncio
async def test_report_issue_work_packs_groups_intake_and_marks_items(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Spindrel Dev", bot_id="codex", client_id="spindrel-dev-packs"))
    await db_session.commit()
    first = await publish_issue_intake(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        title="Runs page clips review evidence",
        summary="The review row hides the merge receipt after launch.",
    )
    second = await publish_issue_intake(
        db_session,
        bot_id="codex",
        channel_id=channel_id,
        title="Runs page launch button is confusing",
        summary="The target chooser does not make the selected channel obvious.",
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="orchestrator",
        channel_id=channel_id,
        status="running",
        task_type="issue_intake_triage",
        prompt="triage",
        callback_config={"issue_intake_triage": True, "attention_item_ids": [str(first.id), str(second.id)]},
    )
    db_session.add(task)
    await db_session.commit()

    packs = await report_issue_work_packs(
        db_session,
        bot_id="orchestrator",
        triage_task_id=task.id,
        triage_receipt={
            "summary": "Grouped two review-surface issues into one implementation pack.",
            "grouping_rationale": "Both notes concern the Project review cockpit evidence framing.",
            "launch_readiness": "Ready for human review before launch.",
            "follow_up_questions": ["Confirm whether copy changes should be included."],
        },
        packs=[{
            "title": "Improve Project review evidence framing",
            "summary": "The Project review cockpit should frame launch and merge evidence clearly.",
            "category": "code_bug",
            "confidence": "high",
            "source_item_ids": [str(first.id), str(second.id)],
            "launch_prompt": "Fix the Project review cockpit evidence framing.",
        }],
    )

    assert len(packs) == 1
    assert packs[0].status == "proposed"
    assert packs[0].source_item_ids == [str(first.id), str(second.id)]
    refreshed = await db_session.get(IssueWorkPack, packs[0].id)
    assert refreshed is not None
    assert refreshed.metadata_["triage_receipt"]["summary"] == "Grouped two review-surface issues into one implementation pack."
    refreshed_first = await db_session.get(type(first), first.id)
    assert refreshed_first.evidence["issue_triage"]["state"] == "packed"
    assert refreshed_first.evidence["issue_triage"]["work_pack_ids"] == [str(packs[0].id)]
    assert refreshed_first.evidence["issue_triage"]["triage_receipt_id"] == refreshed.metadata_["triage_receipt_id"]


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
async def test_resolve_attention_item_preserves_optional_resolution_metadata(db_session):
    root = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:recent-server-errors",
        channel_id=None,
        target_kind="system",
        target_id="server-health",
        title="Root server error",
        severity="error",
        dedupe_key="root-server-error",
    )
    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:recent-server-errors",
        channel_id=None,
        target_kind="system",
        target_id="server-health",
        title="Server error",
        severity="error",
        dedupe_key="server-error",
        evidence={"kind": "recent_server_error"},
    )

    resolved = await resolve_attention_item(
        db_session,
        item.id,
        resolved_by="api_key:ops",
        resolution="duplicate",
        note="Covered by the root finding.",
        duplicate_of=root.id,
    )

    assert resolved.status == "resolved"
    assert resolved.evidence["kind"] == "recent_server_error"
    assert resolved.evidence["resolution"]["resolution"] == "duplicate"
    assert resolved.evidence["resolution"]["note"] == "Covered by the root finding."
    assert resolved.evidence["resolution"]["duplicate_of"] == str(root.id)
    assert resolved.evidence["resolution"]["resolved_by"] == "api_key:ops"


@pytest.mark.asyncio
async def test_resolve_attention_route_keeps_empty_body_compatibility(db_session):
    item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:recent-server-errors",
        channel_id=None,
        target_kind="system",
        target_id="server-health",
        title="Server error",
        severity="error",
        dedupe_key="server-error-empty-body",
    )

    payload = await resolve_attention_route(
        item.id,
        body=None,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:write"], name="ops-key"),
        db=db_session,
    )

    assert payload["item"]["status"] == "resolved"
    assert payload["item"]["evidence"] == {}


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
async def test_auto_signal_cooldown_keeps_acknowledged_repeats_hidden(db_session):
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
    repeated = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Tool failed",
        dedupe_key="tool-x",
        source_event_key="tool_call:two",
        reopen_after=timedelta(hours=24),
    )

    assert repeated.id == item.id
    assert repeated.status == "acknowledged"
    assert repeated.occurrence_count == 2


@pytest.mark.asyncio
async def test_report_bot_issue_prioritizes_and_collapses_matching_system_signal(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    signal = "auto-signal:tool:ops"
    system_item = await place_attention_item(
        db_session,
        source_type="system",
        source_id="system:structured-errors",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="search_memory failed",
        message="Decimal is not JSON serializable",
        severity="critical",
        dedupe_key="tool-search-memory",
        evidence={"auto_signal": {"signature": signal, "kind": "tool_call", "tool_name": "search_memory"}},
    )
    bot_report = await report_bot_issue(
        db_session,
        bot_id="bot-a",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Memory search cannot serialize result",
        summary="search_memory repeatedly fails with Decimal JSON serialization.",
        category="needs_fix",
        suggested_action="Fix Decimal serialization in search_memory responses.",
        severity="error",
        evidence={"signal_signature": signal, "tool_name": "search_memory", "error": "Decimal is not JSON serializable"},
    )

    refreshed_system = await db_session.get(type(system_item), system_item.id)
    assert refreshed_system.status == "acknowledged"
    assert (bot_report.evidence or {})["report_issue"]["category"] == "needs_fix"
    assert (bot_report.evidence or {})["collapsed_system_signals"][0]["collapsed_item_id"] == str(system_item.id)

    visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )
    assert visible[0].id == bot_report.id
    assert system_item.id not in {item.id for item in visible}


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
async def test_next_heartbeat_assignment_requires_channel_heartbeat_bot(db_session, bot_registry):
    bot_registry.register("bot-a")
    bot_registry.register("bot-b")
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
    )

    with pytest.raises(ValidationError, match="channel heartbeat bot"):
        await assign_attention_item(
            db_session,
            item.id,
            bot_id="bot-b",
            mode="next_heartbeat",
        )


@pytest.mark.asyncio
async def test_next_heartbeat_assignment_block_injects_only_top_priority_item(db_session, bot_registry):
    bot_registry.register("bot-a")
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    low = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Low priority",
        severity="warning",
    )
    high = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="High priority",
        severity="critical",
    )
    await assign_attention_item(db_session, low.id, bot_id="bot-a", mode="next_heartbeat")
    await assign_attention_item(db_session, high.id, bot_id="bot-a", mode="next_heartbeat")

    block = await build_attention_assignment_block(db_session, channel_id=channel_id, bot_id="bot-a")

    assert "High priority" in block
    assert "Low priority" not in block


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
async def test_operator_triage_batch_marks_processed_and_ready_for_review(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    benign = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Recovered blip",
    )
    risky = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Possible defect",
    )

    for item in (benign, risky):
        item.assigned_bot_id = "orchestrator"
        item.assignment_status = "running"
        item.evidence = {
            "operator_triage": {
                "state": "running",
                "task_id": str(uuid.uuid4()),
            },
        }
    await db_session.commit()

    updated = await report_attention_triage_batch(
        db_session,
        bot_id="orchestrator",
        outcomes=[
            {
                "item_id": str(benign.id),
                "classification": "already_recovered",
                "review_required": False,
                "confidence": "high",
                "summary": "The latest run recovered.",
                "suggested_action": "No action.",
            },
            {
                "item_id": str(risky.id),
                "classification": "likely_spindrel_code_issue",
                "review_required": True,
                "confidence": "medium",
                "summary": "Repeated file failures need code review.",
                "suggested_action": "Route to developer channel.",
                "route": "developer_channel",
            },
        ],
    )

    by_id = {item.id: item for item in updated}
    assert by_id[benign.id].status == "acknowledged"
    assert by_id[benign.id].evidence["operator_triage"]["state"] == "processed"
    assert by_id[risky.id].status == "responded"
    assert by_id[risky.id].evidence["operator_triage"]["state"] == "ready_for_review"
    assert by_id[risky.id].evidence["operator_triage"]["route"] == "developer_channel"
    assert by_id[risky.id].evidence["operator_triage"]["suggested_action"] == "Open a code fix."


@pytest.mark.asyncio
async def test_operator_triage_run_records_model_override(db_session, bot_registry, monkeypatch):
    bot_registry.register("orchestrator", name="Operator", model="default/operator")
    operator_channel_id = uuid.uuid4()
    operator_session_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    operator_channel = Channel(
        id=operator_channel_id,
        name="Operator",
        bot_id="orchestrator",
        client_id="orchestrator:home",
        protected=True,
        private=True,
    )
    db_session.add_all([
        operator_channel,
        Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"),
    ])
    await db_session.commit()
    await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Needs triage",
    )

    async def fake_operator_channel(_db):
        return operator_channel

    async def fake_spawn_ephemeral_session(_db, **_kwargs):
        return SimpleNamespace(id=operator_session_id)

    monkeypatch.setattr("app.services.workspace_attention._operator_channel", fake_operator_channel)
    monkeypatch.setattr("app.services.sub_sessions.spawn_ephemeral_session", fake_spawn_ephemeral_session)

    run = await create_attention_triage_run(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:write"], name="admin"),
        actor="user:test",
        model_override="gpt-5.4",
        model_provider_id_override="openai-main",
    )

    task = await db_session.get(Task, uuid.UUID(run["task_id"]))
    assert task is not None
    assert task.execution_config["model_override"] == "gpt-5.4"
    assert task.execution_config["model_provider_id_override"] == "openai-main"
    assert task.execution_config["effective_model"] == "gpt-5.4"
    assert run["effective_model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_operator_triage_run_reuses_active_run_instead_of_spawning_duplicate(db_session, bot_registry, monkeypatch):
    bot_registry.register("orchestrator", name="Operator", model="default/operator")
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    parent_channel_id = uuid.uuid4()
    task_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    first = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Needs triage",
    )
    second = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Also needs triage",
    )
    for item in (first, second):
        item.assigned_bot_id = "orchestrator"
        item.assignment_status = "running"
        item.assignment_task_id = task_id
        item.evidence = {
            "operator_triage": {
                "state": "running",
                "task_id": str(task_id),
                "session_id": str(session_id),
                "parent_channel_id": str(parent_channel_id),
                "operator_bot_id": "orchestrator",
                "started_at": "2026-04-29T12:00:00+00:00",
            },
        }
    await db_session.commit()

    spawn = AsyncMock()
    monkeypatch.setattr("app.services.sub_sessions.spawn_ephemeral_session", spawn)

    run = await create_attention_triage_run(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:write"], name="admin"),
        actor="user:test",
    )

    spawn.assert_not_awaited()
    assert run["task_id"] == str(task_id)
    assert run["session_id"] == str(session_id)
    assert run["parent_channel_id"] == str(parent_channel_id)
    assert run["item_count"] == 2
    assert run["effective_model"] == "default/operator"


@pytest.mark.asyncio
async def test_operator_triage_run_excludes_reviewed_items_and_preserves_run_session(db_session, bot_registry, monkeypatch):
    bot_registry.register("orchestrator", name="Operator", model="default/operator")
    operator_channel_id = uuid.uuid4()
    operator_channel = Channel(
        id=operator_channel_id,
        name="Operator",
        bot_id="orchestrator",
        client_id="orchestrator:home",
        protected=True,
        private=True,
    )
    channel_id = uuid.uuid4()
    db_session.add_all([
        operator_channel,
        Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"),
    ])
    await db_session.commit()
    reviewed_session_id = uuid.uuid4()
    reviewed_task_id = uuid.uuid4()
    reviewed = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Already reviewed",
    )
    fresh = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Fresh issue",
    )
    reviewed.status = "responded"
    reviewed.assigned_bot_id = "orchestrator"
    reviewed.assignment_status = "reported"
    reviewed.assignment_task_id = reviewed_task_id
    reviewed.evidence = {
        "operator_triage": {
            "state": "ready_for_review",
            "task_id": str(reviewed_task_id),
            "session_id": str(reviewed_session_id),
            "parent_channel_id": str(operator_channel_id),
            "classification": "needs_review",
        },
    }
    await db_session.commit()

    async def fake_operator_channel(_db):
        return operator_channel

    async def fake_spawn_ephemeral_session(_db, **_kwargs):
        session = Session(
            id=uuid.uuid4(),
            client_id="orchestrator:home",
            bot_id="orchestrator",
            channel_id=operator_channel_id,
            parent_channel_id=operator_channel_id,
        )
        db_session.add(session)
        await db_session.flush()
        return session

    monkeypatch.setattr("app.services.workspace_attention._operator_channel", fake_operator_channel)
    monkeypatch.setattr("app.services.sub_sessions.spawn_ephemeral_session", fake_spawn_ephemeral_session)

    run = await create_attention_triage_run(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:write"], name="admin"),
        actor="user:test",
    )

    assert run["item_count"] == 1
    task = await db_session.get(Task, uuid.UUID(run["task_id"]))
    assert task is not None
    assert task.callback_config["attention_item_ids"] == [str(fresh.id)]
    run_session = await db_session.get(Session, uuid.UUID(run["session_id"]))
    assert run_session is not None
    assert run_session.source_task_id == task.id

    refreshed_reviewed = await db_session.get(type(reviewed), reviewed.id)
    refreshed_fresh = await db_session.get(type(fresh), fresh.id)
    assert refreshed_reviewed.evidence["operator_triage"]["session_id"] == str(reviewed_session_id)
    assert refreshed_reviewed.evidence["operator_triage"]["task_id"] == str(reviewed_task_id)
    assert refreshed_fresh.evidence["operator_triage"]["session_id"] == run["session_id"]


@pytest.mark.asyncio
async def test_operator_triage_run_retries_failed_items_without_rewriting_reviewed_items(db_session, bot_registry, monkeypatch):
    bot_registry.register("orchestrator", name="Operator", model="default/operator")
    operator_channel_id = uuid.uuid4()
    operator_session_id = uuid.uuid4()
    operator_channel = Channel(
        id=operator_channel_id,
        name="Operator",
        bot_id="orchestrator",
        client_id="orchestrator:home",
        protected=True,
        private=True,
    )
    channel_id = uuid.uuid4()
    db_session.add_all([
        operator_channel,
        Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"),
    ])
    await db_session.commit()
    failed = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Retry me",
    )
    reviewed = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Do not retry",
    )
    failed.status = "responded"
    failed.evidence = {"operator_triage": {"state": "failed", "session_id": str(uuid.uuid4())}}
    reviewed.status = "responded"
    reviewed.evidence = {"operator_triage": {"state": "ready_for_review", "session_id": str(uuid.uuid4())}}
    await db_session.commit()

    async def fake_operator_channel(_db):
        return operator_channel

    async def fake_spawn_ephemeral_session(_db, **_kwargs):
        return SimpleNamespace(id=operator_session_id, source_task_id=None, title=None)

    monkeypatch.setattr("app.services.workspace_attention._operator_channel", fake_operator_channel)
    monkeypatch.setattr("app.services.sub_sessions.spawn_ephemeral_session", fake_spawn_ephemeral_session)

    run = await create_attention_triage_run(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:write"], name="admin"),
        actor="user:test",
    )

    task = await db_session.get(Task, uuid.UUID(run["task_id"]))
    assert task.callback_config["attention_item_ids"] == [str(failed.id)]
    refreshed_failed = await db_session.get(type(failed), failed.id)
    refreshed_reviewed = await db_session.get(type(reviewed), reviewed.id)
    assert refreshed_failed.evidence["operator_triage"]["state"] == "running"
    assert refreshed_failed.evidence["operator_triage"]["session_id"] == str(operator_session_id)
    assert refreshed_reviewed.evidence["operator_triage"]["state"] == "ready_for_review"
    assert refreshed_reviewed.evidence["operator_triage"]["session_id"] != str(operator_session_id)


@pytest.mark.asyncio
async def test_operator_triage_feedback_wrong_reopens_processed_item_for_review(db_session, monkeypatch):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    await db_session.commit()
    item = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Badly classified",
    )
    item.status = "acknowledged"
    item.evidence = {
        "operator_triage": {
            "state": "processed",
            "classification": "benign",
            "summary": "Marked benign.",
        },
    }
    await db_session.commit()
    monkeypatch.setattr(
        "app.services.workspace_attention._append_operator_triage_memory",
        lambda *_args, **_kwargs: None,
    )

    reviewed = await record_attention_triage_feedback(
        db_session,
        item.id,
        verdict="wrong",
        actor="user:test",
        note="This should have stayed visible.",
    )

    assert reviewed.status == "responded"
    assert reviewed.evidence["operator_triage"]["review"]["verdict"] == "wrong"
    assert reviewed.evidence["operator_triage"]["review"]["note"] == "This should have stayed visible."


@pytest.mark.asyncio
async def test_operator_triage_run_history_includes_processed_acknowledged_items(db_session):
    channel_id = uuid.uuid4()
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="orchestrator:home", bot_id="orchestrator", channel_id=channel_id))
    await db_session.commit()
    benign = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Recovered tool error",
    )
    risky = await create_user_attention_item(
        db_session,
        actor="user:test",
        channel_id=channel_id,
        target_kind="channel",
        target_id=str(channel_id),
        title="Likely platform bug",
    )
    task = Task(
        id=task_id,
        bot_id="orchestrator",
        client_id="orchestrator:home",
        channel_id=channel_id,
        session_id=session_id,
        prompt="triage",
        title="Operator triage",
        status="complete",
        task_type="attention_triage",
        callback_config={"attention_triage": True, "attention_item_ids": [str(benign.id), str(risky.id)]},
        execution_config={"model_override": "gpt-5.4"},
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    for item in (benign, risky):
        item.assigned_bot_id = "orchestrator"
        item.assignment_status = "running"
        item.assignment_task_id = task_id
        item.evidence = {
            "operator_triage": {
                "state": "running",
                "task_id": str(task_id),
                "session_id": str(session_id),
                "parent_channel_id": str(channel_id),
            },
        }
    await db_session.commit()

    await report_attention_triage_batch(
        db_session,
        bot_id="orchestrator",
        outcomes=[
            {
                "item_id": str(benign.id),
                "classification": "already_recovered",
                "review_required": False,
                "summary": "Recovered.",
            },
            {
                "item_id": str(risky.id),
                "classification": "likely_spindrel_code_issue",
                "review_required": True,
                "summary": "Needs review.",
            },
        ],
    )

    runs = await list_attention_triage_runs(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:read"], name="admin"),
    )
    run = next(entry for entry in runs if entry["task_id"] == str(task_id))
    assert run["status"] == "complete"
    assert run["effective_model"] == "gpt-5.4"
    assert run["counts"]["processed"] == 1
    assert run["counts"]["ready_for_review"] == 1
    assert {item["title"] for item in run["items"]} == {"Recovered tool error", "Likely platform bug"}
    assert next(item for item in run["items"] if item["title"] == "Recovered tool error")["status"] == "acknowledged"

    detail = await get_attention_triage_run(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin", "channels:read"], name="admin"),
        task_id=task_id,
    )
    assert detail["counts"] == run["counts"]


@pytest.mark.asyncio
async def test_command_center_groups_assignments_with_blocked_heartbeat_state(db_session, bot_registry):
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
    )
    await assign_attention_item(db_session, item.id, bot_id="bot-a", mode="next_heartbeat")

    data = await build_command_center(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["channels:read"], name="user-key"),
    )

    assert data["summary"]["assigned"] == 1
    assert data["summary"]["blocked"] == 1
    assert data["bots"][0]["bot_id"] == "bot-a"
    assert data["bots"][0]["active_assignment"]["queue_state"]["blocked"] is True


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


# ── _tool_attention_classification matrix ───────────────────────────────────


@pytest.mark.parametrize(
    "tool_name,error_text,repeated,error_kind,retryable,expected",
    [
        # Benign contract kinds are suppressed when one-off.
        ("invoke_widget_action", "Cell already occupied", 1, "validation", None,
         (False, "benign_contract", "info")),
        ("invoke_widget_action", "row not found", 1, "not_found", None,
         (False, "benign_contract", "info")),
        ("invoke_widget_action", "state conflict", 2, "conflict", None,
         (False, "benign_contract", "info")),
        ("call_api", "API grants not configured", 1, "config_missing", None,
         (False, "benign_contract", "info")),
        ("exec_tool", "approval required", 1, "approval_required", None,
         (False, "benign_contract", "info")),
        # Contract kind wins over legacy severe-text heuristics.
        ("call_api", "missing required field: body", 1, "validation", None,
         (False, "benign_contract", "info")),
        # Benign contract failures repeated ≥ 3 times surface as warning.
        ("invoke_widget_action", "Cell already occupied", 3, "validation", None,
         (True, "repeated_benign_contract", "warning")),
        ("invoke_widget_action", "Cell already occupied", 10, "validation", None,
         (True, "repeated_benign_contract", "warning")),
        # Retryable contract failures are visible, but not critical.
        ("call_api", "upstream 429", 1, "rate_limited", True,
         (True, "retryable_contract", "warning")),
        ("slow_tool", "timed out", 1, "timeout", True,
         (True, "retryable_contract", "warning")),
        # Internal contract failures are platform/tool bugs.
        ("anything", "permission denied", 1, "internal", None,
         (True, "platform_contract", "critical")),
        # Severe regex only handles unknown/uncontracted failures.
        ("anything", "Traceback (most recent call last)", 1, None, None,
         (True, "severe", "critical")),
        # Repeated non-domain failures — critical.
        ("custom_tool", "weird state", 3, None, None,
         (True, "repeated", "critical")),
        # Noisy file-tool single failure — suppressed.
        ("read_file", "No such file", 1, None, None,
         (False, "suppressed_noisy_file_tool", "info")),
        # Default — system error pages.
        ("custom_tool", "weird state", 1, None, None,
         (True, "default", "critical")),
        # Unknown error_kind falls through to default branch.
        ("custom_tool", "weird state", 1, "made_up_kind", None,
         (True, "default", "critical")),
    ],
)
def test_tool_attention_classification_matrix(
    tool_name, error_text, repeated, error_kind, retryable, expected,
):
    assert _tool_attention_classification(
        tool_name, error_text, repeated, error_kind=error_kind, retryable=retryable,
    ) == expected


# ── detect_structured_attention_once with error_kind ────────────────────────


@pytest.mark.asyncio
async def test_structured_detector_suppresses_single_benign_domain_error(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="bot-a",
        tool_name="invoke_widget_action",
        tool_type="local",
        status="error",
        error="Cell (15,7,7) is already occupied.",
        error_kind="validation",
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
async def test_structured_detector_surfaces_repeated_benign_domain_as_warning(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    for _ in range(3):
        db_session.add(ToolCall(
            session_id=session_id,
            bot_id="bot-a",
            tool_name="invoke_widget_action",
            tool_type="local",
            status="error",
            error="Cell (15,7,7) is already occupied.",
            error_kind="validation",
            created_at=datetime.now(timezone.utc),
        ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert created == 1
    assert len(admin_visible) == 1
    item = admin_visible[0]
    assert item.title == "invoke_widget_action failed"
    assert item.severity == "warning"
    assert item.evidence.get("classification") == "repeated_benign_contract"
    assert item.evidence.get("error_kind") == "validation"


@pytest.mark.asyncio
async def test_structured_detector_keeps_internal_errors_critical(db_session):
    """Regression guard: real system errors must still page as critical even
    when other benign-domain failures are flowing through."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="bot-a",
        tool_name="invoke_widget_action",
        tool_type="local",
        status="error",
        error="RuntimeError: state corrupted",
        error_kind="internal",
        created_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert created == 1
    assert admin_visible[0].severity == "critical"
    assert admin_visible[0].evidence.get("classification") == "platform_contract"


@pytest.mark.asyncio
async def test_structured_detector_uses_contract_fields_for_review_evidence(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Ops", bot_id="bot-a", client_id="ops"))
    db_session.add(Session(id=session_id, client_id="ops", bot_id="bot-a", channel_id=channel_id))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="bot-a",
        tool_name="call_api",
        tool_type="local",
        status="error",
        error="HTTP 429",
        error_code="http_429",
        error_kind="rate_limited",
        retryable=True,
        retry_after_seconds=30,
        fallback="Wait for retry_after_seconds when provided, then retry with backoff.",
        created_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    created = await detect_structured_attention_once(db_session)
    admin_visible = await list_attention_items(
        db_session,
        auth=ApiKeyAuth(key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"),
    )

    assert created == 1
    item = admin_visible[0]
    assert item.severity == "warning"
    assert item.next_steps == ["Wait for retry_after_seconds when provided, then retry with backoff."]
    assert item.evidence.get("classification") == "retryable_contract"
    assert item.evidence.get("error_code") == "http_429"
    assert item.evidence.get("error_kind") == "rate_limited"
    assert item.evidence.get("retryable") is True
    assert item.evidence.get("retry_after_seconds") == 30
    assert item.evidence.get("fallback") == "Wait for retry_after_seconds when provided, then retry with backoff."
