import uuid

import pytest

from app.db.models import Session
from app.routers import sessions as sessions_router
from app.services import session_plan_mode as spm
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


class TestSessionMessagesRouter:
    async def test_get_session_messages_hides_internal_rows_but_keeps_pipeline_steps(self, client, db_session):
        session_id = uuid.uuid4()
        db_session.add(Session(id=session_id, client_id=f"router-client-{uuid.uuid4().hex[:8]}", bot_id="test-bot"))
        await db_session.flush()

        hidden_intermediate = Message(
            session_id=session_id,
            role="assistant",
            content="intermediate tool row",
            metadata_={"hidden": True},
        )
        visible_final = Message(
            session_id=session_id,
            role="assistant",
            content="final assistant row",
            tool_calls=[{
                "id": "call-1",
                "name": "file",
                "arguments": "{\"operation\":\"edit\",\"path\":\"notes.md\"}",
                "surface": "transcript",
                "summary": {
                    "kind": "diff",
                    "subject_type": "file",
                    "label": "Edited notes.md",
                    "path": "notes.md",
                    "diff_stats": {"additions": 1, "deletions": 1},
                },
            }],
            metadata_={
                "assistant_turn_body": {
                    "version": 1,
                    "items": [
                        {"id": "text:1", "kind": "text", "text": "Before edit.\n"},
                        {"id": "tool:call-1", "kind": "tool_call", "toolCallId": "call-1"},
                        {"id": "text:2", "kind": "text", "text": "Done.\n"},
                    ],
                },
                "tool_results": [{
                    "content_type": "application/vnd.spindrel.diff+text",
                    "body": "@@ -1 +1 @@\n-old\n+new",
                    "plain_body": "Edited notes.md",
                    "display": "inline",
                    "truncated": False,
                    "record_id": "result-edit",
                    "byte_size": 24,
                }],
            },
        )
        visible_pipeline_step = Message(
            session_id=session_id,
            role="assistant",
            content="pipeline child row",
            metadata_={"hidden": True, "pipeline_step": True},
        )
        db_session.add_all([hidden_intermediate, visible_final, visible_pipeline_step])
        await db_session.commit()

        resp = await client.get(f"/sessions/{session_id}/messages", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        messages = body["messages"]
        assert body["has_more"] is False
        assert [message["content"] for message in messages if message["role"] == "assistant"] == [
            "final assistant row",
            "pipeline child row",
        ]
        final_row = next(message for message in messages if message["content"] == "final assistant row")
        assert final_row["tool_calls"][0]["id"] == "call-1"
        assert final_row["metadata"]["assistant_turn_body"]["items"][1]["toolCallId"] == "call-1"
        assert final_row["metadata"]["tool_results"][0]["content_type"] == "application/vnd.spindrel.diff+text"

    async def test_get_session_messages_preserves_widget_owned_tool_rows(self, client, db_session):
        session_id = uuid.uuid4()
        db_session.add(Session(id=session_id, client_id=f"router-client-{uuid.uuid4().hex[:8]}", bot_id="test-bot"))
        await db_session.flush()

        widget_row = Message(
            session_id=session_id,
            role="assistant",
            content="Succeeded on retry.",
            tool_calls=[{
                "id": "call-search",
                "name": "web_search",
                "arguments": '{"q":"weather in Lambertville NJ today"}',
                "surface": "widget",
                "summary": {
                    "kind": "result",
                    "subject_type": "widget",
                    "label": "Widget available",
                    "target_label": "Web search",
                },
            }],
            metadata_={
                "assistant_turn_body": {
                    "version": 1,
                    "items": [
                        {"id": "tool:call-search", "kind": "tool_call", "toolCallId": "call-search"},
                        {"id": "text:1", "kind": "text", "text": "Succeeded on retry."},
                    ],
                },
                "tool_results": [{
                    "content_type": "application/vnd.spindrel.html+interactive",
                    "body": "<html><body>widget</body></html>",
                    "plain_body": "Web search",
                    "display": "inline",
                    "truncated": False,
                    "record_id": "widget-1",
                    "byte_size": 32,
                }],
            },
        )
        db_session.add(widget_row)
        await db_session.commit()

        resp = await client.get(f"/sessions/{session_id}/messages", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        message = body["messages"][0]
        assert message["tool_calls"][0]["surface"] == "widget"
        assert message["metadata"]["assistant_turn_body"]["items"][0]["toolCallId"] == "call-search"
        assert message["metadata"]["tool_results"][0]["content_type"] == "application/vnd.spindrel.html+interactive"

    async def test_plan_endpoints_return_revision_history_and_reject_stale_approve(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(spm, "get_bot", lambda _bot_id: type("Bot", (), {"id": "test-bot"})())
        monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))

        session_id = uuid.uuid4()
        session = Session(
            id=session_id,
            client_id=f"router-client-{uuid.uuid4().hex[:8]}",
            bot_id="test-bot",
            channel_id=uuid.uuid4(),
            metadata_={},
        )
        db_session.add(session)
        await db_session.flush()

        spm.enter_session_plan_mode(session)
        spm.create_session_plan(
            session,
            title="Plan Hardening",
            summary="Draft one",
            scope="Initial scope",
            acceptance_criteria=["The current revision can be approved."],
        )
        spm.publish_session_plan(
            session,
            title="Plan Hardening",
            summary="Draft two",
            scope="Revised scope",
            acceptance_criteria=["The current revision can be approved."],
            steps=[
                {"id": "audit", "label": "Audit current behavior"},
                {"id": "ship", "label": "Ship the remaining fixes"},
            ],
        )
        await db_session.commit()

        plan_resp = await client.get(f"/sessions/{session_id}/plan", headers=AUTH_HEADERS)

        assert plan_resp.status_code == 200
        body = plan_resp.json()
        assert body["revision"] == 2
        assert body["accepted_revision"] in (0, None)
        assert [entry["revision"] for entry in body["revisions"]] == [2, 1]

        diff_resp = await client.get(
            f"/sessions/{session_id}/plan/diff?from_revision=1&to_revision=2",
            headers=AUTH_HEADERS,
        )

        assert diff_resp.status_code == 200
        diff_body = diff_resp.json()
        assert diff_body["from_revision"] == 1
        assert diff_body["to_revision"] == 2
        assert "scope" in diff_body["changed_sections"]
        assert "Revised scope" in diff_body["diff"]

        stale_approve = await client.post(
            f"/sessions/{session_id}/plan/approve",
            headers=AUTH_HEADERS,
            json={"revision": 1},
        )

        assert stale_approve.status_code == 409
        assert "revision mismatch" in stale_approve.json()["detail"].lower()

        approve = await client.post(
            f"/sessions/{session_id}/plan/approve",
            headers=AUTH_HEADERS,
            json={"revision": 2},
        )
        assert approve.status_code == 200
        approved_body = approve.json()
        assert approved_body["runtime"]["current_step_id"] == "audit"
        assert approved_body["validation"]["ok"] is True

        replan = await client.post(
            f"/sessions/{session_id}/plan/replan",
            headers=AUTH_HEADERS,
            json={
                "revision": 2,
                "reason": "Audit found the plan is missing a gate.",
                "affected_step_ids": ["audit"],
                "evidence": "test evidence",
            },
        )
        assert replan.status_code == 200
        replan_body = replan.json()
        assert replan_body["mode"] == spm.PLAN_MODE_PLANNING
        assert replan_body["revision"] == 3
        assert replan_body["accepted_revision"] == 2
        assert replan_body["runtime"]["replan"]["from_revision"] == 2
        assert replan_body["validation"]["ok"] is False

    async def test_plan_review_adherence_persists_semantic_review(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(spm, "get_bot", lambda _bot_id: type("Bot", (), {"id": "test-bot"})())
        monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))

        correlation_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = Session(
            id=session_id,
            client_id=f"router-client-{uuid.uuid4().hex[:8]}",
            bot_id="test-bot",
            channel_id=uuid.uuid4(),
            metadata_={},
        )
        db_session.add(session)
        await db_session.flush()

        spm.create_session_plan(
            session,
            title="Review Adherence",
            summary="Check that outcomes are evidence-backed.",
            scope="Plan execution review.",
            acceptance_criteria=["The review is persisted on the plan."],
            steps=[{"id": "verify", "label": "Verify the change"}],
        )
        spm.approve_session_plan(session)
        spm.record_plan_progress_outcome(
            session,
            outcome="verification",
            summary="Ran the focused regression check.",
            step_id="verify",
            evidence="pytest tests/unit/test_session_plan_mode.py -q",
            correlation_id=str(correlation_id),
            turn_id="turn-1",
        )

        async def _fake_review(_db, target_session, *, correlation_id=None):
            return spm.record_plan_semantic_review(
                target_session,
                {
                    "correlation_id": correlation_id,
                    "step_id": "verify",
                    "outcome": "verification",
                    "verdict": spm.PLAN_SEMANTIC_REVIEW_SUPPORTED,
                    "confidence": 0.84,
                    "reason": "The turn includes a passing verification command and matching outcome.",
                    "recommended_action": "continue",
                },
            )

        monkeypatch.setattr(sessions_router, "review_plan_adherence", _fake_review)
        await db_session.commit()

        resp = await client.post(
            f"/sessions/{session_id}/plan/review-adherence",
            headers=AUTH_HEADERS,
            json={},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["runtime"]["semantic_status"] == "ok"
        assert body["runtime"]["latest_semantic_review"]["verdict"] == "supported"
        assert body["adherence"]["latest_semantic_review"]["correlation_id"] == str(correlation_id)
        assert body["adherence"]["semantic_reviews"][-1]["recommended_action"] == "continue"
