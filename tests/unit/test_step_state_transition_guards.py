"""Phase F.1 — step state transition guards drift-seam sweep.

Seam class: silent-UPDATE (unguarded status flip).

`on_pipeline_step_completed` at app/services/step_executor.py:1448 writes
`state["status"] = "done" if status == "complete" else "failed"` without
checking the prior state. A double-callback (generic hook dispatcher fires
twice; retry resume; parent restart replays completion) silently overwrites
a terminal step.

The same drift class as Phase D's `decide_approval` stale-ToolCall pin:
contracts here pin current last-writer-wins behavior so future hardening has
a regression surface. If drift is confirmed as a live bug it's logged in
[[Loose Ends]] — do not fix in the same session.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_db_ctx(task_row, child_row=None, child_id=None):
    db = AsyncMock()

    def _get(model, pk):
        if pk == task_row.id:
            return task_row
        if child_id is not None and pk == child_id:
            return child_row
        return None

    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db


def _parent(step_states, steps=None):
    parent = MagicMock()
    parent.id = uuid.uuid4()
    parent.steps = steps or [{"id": "s0", "type": "agent"}]
    parent.step_states = step_states
    return parent


def _child(child_id, result="ok", error=None):
    child = MagicMock()
    child.id = child_id
    child.result = result
    child.error = error
    return child


class TestHappyPathTransitions:
    """Running → done / running → failed with fresh child result."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_running_completes_then_status_flips_to_done(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent([{"status": "running", "result": None, "error": None}])
        child_id = uuid.uuid4()
        child = _child(child_id, result="fresh result")
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["status"] == "done"
        assert persisted[0]["result"] == "fresh result"
        assert persisted[0]["completed_at"] is not None
        mock_advance.assert_awaited_once()
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_running_fails_with_abort_then_finalizes_pipeline(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent(
            [{"status": "running", "result": None, "error": None}],
            steps=[{"id": "s0", "type": "agent", "on_failure": "abort"}],
        )
        child_id = uuid.uuid4()
        child = _child(child_id, result=None, error="child blew up")
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "failed", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["status"] == "failed"
        assert persisted[0]["error"] == "child blew up"
        mock_finalize.assert_awaited_once()
        mock_advance.assert_not_called()


class TestDriftPinsUnguardedOverwrite:
    """Pin current contract: terminal states are overwritten on re-entry.

    If the callback fires twice for the same step_index (e.g. generic hook
    dispatcher double-fire, pipeline resume after restart), the second call
    rewrites state["status"] + result + completed_at with NO pre-check.

    These are drift pins — they document the current last-writer-wins
    behavior. A future hardening PR that adds a guard (e.g. "skip if
    already terminal") should update these tests in the same edit.
    """

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_already_done_reentered_then_result_silently_overwritten(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent([{
            "status": "done",
            "result": "original answer",
            "error": None,
            "completed_at": "2026-04-18T10:00:00+00:00",
        }])
        child_id = uuid.uuid4()
        child = _child(child_id, result="replay answer")
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["status"] == "done"
        assert persisted[0]["result"] == "replay answer"
        assert persisted[0]["completed_at"] != "2026-04-18T10:00:00+00:00"

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_already_failed_reentered_with_complete_then_flips_to_done(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent([{
            "status": "failed",
            "result": None,
            "error": "prior failure reason",
            "completed_at": "2026-04-18T10:00:00+00:00",
        }])
        child_id = uuid.uuid4()
        child = _child(child_id, result="late success", error=None)
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["status"] == "done"
        assert persisted[0]["error"] is None


class TestEarlyReturnGuards:
    """step_index OOB and missing parent both short-circuit before mutating."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_parent_missing_then_returns_without_persist(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        missing_id = uuid.uuid4()
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = ctx

        child = _child(uuid.uuid4())
        await on_pipeline_step_completed(str(missing_id), 0, "complete", child)

        mock_persist.assert_not_called()
        mock_advance.assert_not_called()
        mock_finalize.assert_not_called()


class TestResultTruncation:
    """Oversized result is truncated at step_def max_chars with a suffix."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_result_exceeds_max_chars_then_truncated_with_suffix(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent(
            [{"status": "running", "result": None, "error": None}],
            steps=[{"id": "s0", "type": "agent", "result_max_chars": 50}],
        )
        child_id = uuid.uuid4()
        big = "x" * 200
        child = _child(child_id, result=big)
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["result"] == "x" * 50 + "... [truncated]"

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_when_result_under_default_max_chars_then_untruncated(
        self, mock_session, mock_persist, mock_finalize, mock_advance,
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = _parent([{"status": "running", "result": None, "error": None}])
        child_id = uuid.uuid4()
        child = _child(child_id, result="short")
        mock_session.return_value, _ = _make_db_ctx(parent, child, child_id)

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        persisted = mock_persist.call_args[0][1]
        assert persisted[0]["result"] == "short"
