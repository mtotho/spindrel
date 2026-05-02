"""Phase 4BG.2 - continuation block in run detail payload."""
from __future__ import annotations

from types import SimpleNamespace

from app.tools.local.project_run_handoff import _project_run_detail_payload


def _project():
    return SimpleNamespace(id="proj-1", name="Demo", root_path="/x/proj")


def test_continuation_block_zero_attempt_for_first_run():
    run = {
        "id": "task-root",
        "task": {"id": "task-root"},
        "continuation_index": 0,
        "continuation_count": 0,
        "root_task_id": "task-root",
        "continuations": [],
        "latest_continuation": None,
    }
    payload = _project_run_detail_payload(_project(), run, selection="task_id")
    cont = payload["continuation"]
    assert cont["attempt"] == 0
    assert cont["is_continuation"] is False
    assert cont["continuation_count"] == 0
    assert cont["root_task_id"] == "task-root"
    assert cont["prior_attempt_task_id"] is None


def test_continuation_block_first_continuation_points_at_root():
    run = {
        "id": "task-c1",
        "task": {"id": "task-c1"},
        "continuation_index": 1,
        "continuation_count": 1,
        "root_task_id": "task-root",
        "continuations": [
            {"task_id": "task-c1", "continuation_index": 1, "id": "r-1", "status": "running",
             "created_at": None, "updated_at": None},
        ],
        "latest_continuation": {"task_id": "task-c1"},
    }
    payload = _project_run_detail_payload(_project(), run, selection="task_id")
    cont = payload["continuation"]
    assert cont["attempt"] == 1
    assert cont["is_continuation"] is True
    assert cont["prior_attempt_task_id"] == "task-root", (
        "first continuation's prior is the root task, not itself"
    )


def test_continuation_block_deeper_continuation_walks_chain():
    run = {
        "id": "task-c3",
        "task": {"id": "task-c3"},
        "continuation_index": 3,
        "continuation_count": 3,
        "root_task_id": "task-root",
        "continuations": [
            {"task_id": "task-c1", "continuation_index": 1, "id": "r-1", "status": "completed",
             "created_at": None, "updated_at": None},
            {"task_id": "task-c2", "continuation_index": 2, "id": "r-2", "status": "completed",
             "created_at": None, "updated_at": None},
            {"task_id": "task-c3", "continuation_index": 3, "id": "r-3", "status": "running",
             "created_at": None, "updated_at": None},
        ],
        "latest_continuation": {"task_id": "task-c3"},
    }
    payload = _project_run_detail_payload(_project(), run, selection="task_id")
    cont = payload["continuation"]
    assert cont["attempt"] == 3
    assert cont["prior_attempt_task_id"] == "task-c2"
