"""Project Factory contract flow.

This intentionally stays model-free: it validates the durable surfaces that
nightly/agentic Project work will use before a live harness agent does the
expensive part.
"""

from __future__ import annotations

import uuid

import pytest

from tests.e2e.harness.client import E2EClient


pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_issue_intake_to_work_pack_to_reviewed_project_run(client: E2EClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    project = await client.create_project({
        "name": f"Factory E2E {suffix}",
        "slug": f"factory-e2e-{suffix}",
        "root_path": f"scratch/project-factory-e2e/{suffix}",
        "metadata_": {"e2e": True, "scenario": "project_factory_flow"},
    })
    channel = await client.create_channel({
        "name": f"Factory E2E {suffix}",
        "client_id": client.new_client_id("e2e-factory"),
        "bot_id": client.default_bot_id,
        "project_id": project["id"],
        "private": True,
    })

    broken_widget = await client.create_issue_intake({
        "channel_id": channel["id"],
        "title": f"Factory E2E broken widget {suffix}",
        "summary": "Workspace Review opens but the task list never refreshes.",
        "observed_behavior": "The task list stays stale after a new run is created.",
        "expected_behavior": "New Project coding runs appear without a manual refresh.",
        "steps": ["Open Workspace Review", "Launch a Project coding run", "Check the run list"],
        "severity": "warning",
        "category_hint": "bug",
        "project_hint": project["slug"],
        "tags": ["project-factory", "review"],
    })
    review_gap = await client.create_issue_intake({
        "channel_id": channel["id"],
        "title": f"Factory E2E missing review marker {suffix}",
        "summary": "Accepted Project coding runs need durable reviewed provenance.",
        "observed_behavior": "A reviewer can accept work without a linked review session.",
        "expected_behavior": "Accepted runs link back to the review session and summary.",
        "steps": ["Create a run receipt", "Create a review session", "Accept the run"],
        "severity": "warning",
        "category_hint": "bug",
        "project_hint": project["slug"],
        "tags": ["project-factory", "review"],
    })
    planning_note = await client.create_issue_intake({
        "channel_id": channel["id"],
        "title": f"Factory E2E future planning note {suffix}",
        "summary": "Consider richer planning notes before launching broad product changes.",
        "severity": "info",
        "category_hint": "idea",
        "project_hint": project["slug"],
        "tags": ["planning"],
    })

    conversational = await client.execute_admin_tool(
        "create_issue_work_packs",
        bot_id=client.default_bot_id,
        channel_id=channel["id"],
        arguments={
            "packs": [{
                "title": f"Factory E2E conversational pack {suffix}",
                "summary": "A normal Project-bound agent can turn a planning conversation into a proposed work pack.",
                "category": "needs_info",
                "confidence": "medium",
                "conversation_summary": "The user and agent discussed a future planning item.",
            }],
        },
    )
    assert conversational["error"] is None
    conversational_pack = conversational["result"]["work_packs"][0]
    assert conversational_pack["status"] == "needs_info"
    assert conversational_pack["metadata"]["source"] == "conversation"
    assert conversational_pack["source_item_ids"]

    code_pack = await client.create_issue_work_pack({
        "title": f"Factory E2E review refresh pack {suffix}",
        "summary": "Fix stale Project Review run list and durable reviewed provenance together.",
        "category": "code_bug",
        "confidence": "high",
        "source_item_ids": [broken_widget["id"], review_gap["id"]],
        "launch_prompt": "Implement the Project Review refresh/provenance fix and include e2e evidence.",
        "project_id": project["id"],
        "channel_id": channel["id"],
        "metadata": {"scenario": "project_factory_flow", "kind": "code"},
    })
    second_code_pack = await client.create_issue_work_pack({
        "title": f"Factory E2E batch launch pack {suffix}",
        "summary": "A second code pack should launch in the same operator batch.",
        "category": "code_bug",
        "confidence": "medium",
        "source_item_ids": [broken_widget["id"]],
        "launch_prompt": "Implement a small Project Factory batch-launch verification change and include evidence.",
        "project_id": project["id"],
        "channel_id": channel["id"],
        "metadata": {"scenario": "project_factory_flow", "kind": "batch-code"},
    })
    needs_info_pack = await client.create_issue_work_pack({
        "title": f"Factory E2E planning note pack {suffix}",
        "summary": "Future planning note should not launch implementation without a plan.",
        "category": "needs_info",
        "confidence": "low",
        "source_item_ids": [planning_note["id"]],
        "project_id": project["id"],
        "channel_id": channel["id"],
        "metadata": {"scenario": "project_factory_flow", "kind": "planning"},
    })

    edited_code_pack = await client.update_issue_work_pack(code_pack["id"], {
        "title": f"Factory E2E reviewed refresh pack {suffix}",
        "summary": "Reviewed cockpit should preserve sources while refining the Project Review refresh/provenance work.",
        "confidence": "high",
        "source_item_ids": [broken_widget["id"], review_gap["id"]],
        "launch_prompt": "Implement the Project Review refresh/provenance fix with e2e evidence and screenshot proof.",
        "project_id": project["id"],
        "channel_id": channel["id"],
    })
    assert edited_code_pack["title"].startswith("Factory E2E reviewed refresh pack")
    assert edited_code_pack["latest_review_action"]["action"] == "edited"
    assert {item["id"] for item in edited_code_pack["source_items"]} == {broken_widget["id"], review_gap["id"]}

    dismissed_planning = await client.transition_issue_work_pack(
        needs_info_pack["id"],
        "dismiss",
        note="Factory e2e verifies non-code planning notes can be parked.",
    )
    assert dismissed_planning["status"] == "dismissed"
    assert dismissed_planning["latest_review_action"]["action"] == "dismiss"
    reopened_planning = await client.transition_issue_work_pack(needs_info_pack["id"], "reopen")
    assert reopened_planning["status"] == "proposed"
    needs_info_pack = await client.transition_issue_work_pack(
        needs_info_pack["id"],
        "needs-info",
        note="Factory e2e returns the planning note to needs-info before launch.",
    )
    assert needs_info_pack["status"] == "needs_info"
    assert needs_info_pack["latest_review_action"]["action"] == "needs_info"

    packs = await client.list_issue_work_packs()
    assert any(pack["id"] == code_pack["id"] and pack["status"] == "proposed" for pack in packs)
    assert any(pack["id"] == second_code_pack["id"] and pack["status"] == "proposed" for pack in packs)
    assert any(pack["id"] == needs_info_pack["id"] and pack["status"] == "needs_info" for pack in packs)
    assert any(pack["id"] == conversational_pack["id"] and pack["metadata"]["source"] == "conversation" for pack in packs)

    launched = await client.batch_launch_issue_work_packs_project_runs(
        work_pack_ids=[code_pack["id"], second_code_pack["id"]],
        project_id=project["id"],
        channel_id=channel["id"],
        note="Factory e2e launches the reviewed code packs together.",
    )
    assert launched["count"] == 2
    assert launched["launch_batch_id"].startswith("issue-work-pack-batch:")
    assert {pack["id"] for pack in launched["work_packs"]} == {code_pack["id"], second_code_pack["id"]}
    assert {pack["metadata"]["launch_batch_id"] for pack in launched["work_packs"]} == {launched["launch_batch_id"]}
    assert all(pack["status"] == "launched" for pack in launched["work_packs"])
    assert {run["launch_batch_id"] for run in launched["runs"]} == {launched["launch_batch_id"]}
    run = next(run for run in launched["runs"] if run["source_work_pack_id"] == code_pack["id"])
    task_id = run["task"]["id"]
    assert run["source_work_pack_id"] == code_pack["id"]

    review_batches = await client.list_project_review_batches(project["id"])
    launch_batch = next(batch for batch in review_batches if batch["id"] == launched["launch_batch_id"])
    assert launch_batch["status"] in {"pending", "running"}
    assert launch_batch["run_count"] == 2
    assert set(launch_batch["task_ids"]) == {item["task"]["id"] for item in launched["runs"]}
    assert {pack["id"] for pack in launch_batch["source_work_packs"]} == {code_pack["id"], second_code_pack["id"]}

    receipt = await client.create_project_run_receipt(project["id"], {
        "task_id": task_id,
        "bot_id": client.default_bot_id,
        "idempotency_key": f"project-factory-e2e:{suffix}",
        "status": "needs_review",
        "summary": "Factory e2e deterministic coding receipt.",
        "handoff_type": "github_pr",
        "handoff_url": f"https://github.com/example/project-factory-e2e/pull/{suffix}",
        "branch": f"e2e/factory-{suffix}",
        "base_branch": "development",
        "commit_sha": "0" * 40,
        "changed_files": [{"path": "FACTORY_E2E.md", "status": "modified"}],
        "tests": [{"command": "pytest tests/e2e/scenarios/test_project_factory_flow.py", "status": "passed"}],
        "screenshots": [{"path": "docs/images/project-workspace-runs.png", "status": "referenced"}],
        "metadata": {"scenario": "project_factory_flow", "work_pack_id": code_pack["id"]},
    })
    assert receipt["task_id"] == task_id
    assert receipt["handoff_url"].endswith(f"/{suffix}")

    review_batches = await client.list_project_review_batches(project["id"])
    launch_batch = next(batch for batch in review_batches if batch["id"] == launched["launch_batch_id"])
    assert launch_batch["status"] == "ready_for_review"
    assert launch_batch["evidence"]["tests_count"] == 1
    assert launch_batch["evidence"]["screenshots_count"] == 1

    review = await client.create_project_review_session(project["id"], {
        "channel_id": channel["id"],
        "task_ids": [task_id],
        "prompt": "Review the selected factory e2e run. Accept without merging.",
        "merge_method": "squash",
    })
    review_context = await client.get_project_review_context(project["id"], review["id"])
    assert review_context["ok"] is True
    assert review_context["readiness"]["ready"] is True
    assert review_context["selected_task_ids"] == [task_id]
    assert review_context["selected_runs"][0]["launch_batch_id"] == launched["launch_batch_id"]
    assert review_context["selected_runs"][0]["receipt"]["id"] == receipt["id"]

    review_batches = await client.list_project_review_batches(project["id"])
    launch_batch = next(batch for batch in review_batches if batch["id"] == launched["launch_batch_id"])
    assert launch_batch["status"] == "reviewing"
    assert launch_batch["active_review_task"]["task_id"] == review["id"]

    finalized = await client.finalize_project_review(project["id"], {
        "review_task_id": review["id"],
        "run_task_id": task_id,
        "outcome": "accepted",
        "summary": "Factory e2e review accepted the deterministic Project run.",
        "details": {"checks": "passed", "scenario": "project_factory_flow"},
        "merge": False,
        "merge_method": "squash",
    })
    assert finalized["ok"] is True
    assert finalized["status"] == "reviewed"
    assert finalized["run"]["review"]["status"] == "reviewed"
    assert finalized["run"]["review"]["review_task_id"] == review["id"]
    assert finalized["run"]["review"]["reviewed_by"] == "agent"
    reviewed_packs = await client.list_issue_work_packs(status="launched")
    reviewed_code_pack = next(pack for pack in reviewed_packs if pack["id"] == code_pack["id"])
    assert reviewed_code_pack["latest_review_action"]["action"] == "reviewed"
    assert reviewed_code_pack["latest_review_action"]["review_task_id"] == review["id"]
    assert reviewed_code_pack["latest_review_action"]["launch_batch_id"] == launched["launch_batch_id"]

    remaining_needs_info = await client.list_issue_work_packs(status="needs_info")
    assert any(pack["id"] == needs_info_pack["id"] and pack["launched_task_id"] is None for pack in remaining_needs_info)
