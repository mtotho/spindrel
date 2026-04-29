"""Architecture guards and focused behavior tests for exec task hosting."""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import task_exec_host
from app.agent.task_exec_host import TaskExecHostDeps
from app.db.models import Task


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "app" / "agent" / "tasks.py"
TASK_EXEC_HOST = REPO_ROOT / "app" / "agent" / "task_exec_host.py"


class _FakeDb:
    def __init__(self, *tasks: Task):
        self.rows = {task.id: task for task in tasks}
        self.added: list[Task] = []
        self.commits = 0

    async def get(self, model: type[Task], item_id: uuid.UUID) -> Task | None:
        return self.rows.get(item_id)

    def add(self, task: Task) -> None:
        self.added.append(task)
        if getattr(task, "id", None) is not None:
            self.rows[task.id] = task

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, task: Task) -> None:
        return None


class _SessionFactory:
    def __init__(self, db: _FakeDb):
        self.db = db

    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> _FakeDb:
        return self.db

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def _bot(
    *,
    workspace_enabled: bool = True,
    shared_workspace_id: uuid.UUID | None = None,
    bot_sandbox_enabled: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="bot-1",
        docker_sandbox_profiles=None,
        workspace=SimpleNamespace(enabled=workspace_enabled),
        shared_workspace_id=shared_workspace_id,
        bot_sandbox=SimpleNamespace(enabled=bot_sandbox_enabled),
    )


def _deps(
    db: _FakeDb,
    *,
    bot: SimpleNamespace | None = None,
    workspace_result: SimpleNamespace | None = None,
    timeout: int = 30,
) -> tuple[TaskExecHostDeps, list[dict], SimpleNamespace, SimpleNamespace]:
    records: list[dict] = []
    workspace_service = SimpleNamespace(
        exec=AsyncMock(
            return_value=workspace_result
            or SimpleNamespace(
                stdout="ok",
                stderr="",
                exit_code=0,
                truncated=False,
                duration_ms=12,
            )
        )
    )
    sandbox_service = SimpleNamespace(
        get_instance_for_bot=AsyncMock(),
        exec=AsyncMock(),
        exec_bot_local=AsyncMock(),
    )

    deps = TaskExecHostDeps(
        async_session=_SessionFactory(db),
        settings=SimpleNamespace(DOCKER_SANDBOX_ENABLED=True),
        get_bot=lambda bot_id: bot or _bot(),
        build_exec_script=lambda command, args, cwd, stream_to: (
            f"{command}|{args}|{cwd}|{stream_to}"
        ),
        sandbox_service=sandbox_service,
        workspace_service=workspace_service,
        resolve_task_timeout=lambda task: timeout,
        fire_task_complete=AsyncMock(),
        mark_task_failed_in_db=AsyncMock(),
        publish_turn_ended=AsyncMock(),
        publish_turn_ended_safe=AsyncMock(),
        schedule_exec_completion_record=lambda **kwargs: records.append(kwargs),
        sleep=AsyncMock(),
    )
    return deps, records, workspace_service, sandbox_service


def _exec_task(**overrides) -> Task:
    values = {
        "id": uuid.uuid4(),
        "bot_id": "bot-1",
        "client_id": "client-1",
        "session_id": uuid.uuid4(),
        "channel_id": uuid.uuid4(),
        "prompt": "echo hi",
        "status": "pending",
        "task_type": "exec",
        "dispatch_type": "none",
        "dispatch_config": {},
        "execution_config": {"command": "echo", "args": ["hi"]},
    }
    values.update(overrides)
    return Task(**values)


def test_exec_task_wrapper_stays_small_and_patchable():
    source = TASKS.read_text()
    wrapper = _function_node(TASKS, "run_exec_task")
    deps = _function_node(TASKS, "_task_exec_deps")
    assert wrapper.end_lineno is not None
    assert wrapper.end_lineno - wrapper.lineno + 1 <= 10

    wrapper_source = ast.get_source_segment(source, wrapper) or ""
    deps_source = ast.get_source_segment(source, deps) or ""
    assert "run_exec_task_host" in wrapper_source

    for needle in (
        "async_session=async_session",
        "settings=settings",
        "get_bot=get_bot",
        "build_exec_script=build_exec_script",
        "sandbox_service=sandbox_service",
        "workspace_service=workspace_service",
        "resolve_task_timeout=resolve_task_timeout",
        "fire_task_complete=_fire_task_complete",
        "mark_task_failed_in_db=_mark_task_failed_in_db",
        "publish_turn_ended=_publish_turn_ended",
        "publish_turn_ended_safe=_publish_turn_ended_safe",
        "schedule_exec_completion_record=schedule_exec_completion_record",
        "sleep=asyncio.sleep",
    ):
        assert needle in deps_source


def test_exec_policy_does_not_drift_back_to_tasks_wrapper():
    source = TASKS.read_text()
    wrapper_source = ast.get_source_segment(source, _function_node(TASKS, "run_exec_task")) or ""

    for forbidden in (
        "asyncio.wait_for",
        "build_exec_script",
        "schedule_exec_completion_record",
        "No sandbox available",
        "notify_parent",
        "output_dispatch_config",
        "exec_bot_local",
    ):
        assert forbidden not in wrapper_source


def test_exec_host_owns_sandbox_workspace_and_completion_policy():
    source = TASK_EXEC_HOST.read_text()

    for needle in (
        "TaskExecHostDeps",
        "asyncio.wait_for",
        "build_exec_script",
        "schedule_exec_completion_record",
        "get_instance_for_bot",
        "workspace_service.exec",
        "exec_bot_local",
        "No sandbox available for exec task",
        "notify_parent",
        "publish_turn_ended_safe",
    ):
        assert needle in source


@pytest.mark.asyncio
async def test_exec_host_success_persists_records_publishes_and_parent_callback():
    parent_session_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    task = _exec_task(
        dispatch_config={"existing": True},
        execution_config={
            "command": "echo",
            "args": ["hi"],
            "working_directory": "/workspace",
            "stream_to": "/tmp/out",
            "output_dispatch_type": "channel",
            "output_dispatch_config": {"reply_in_thread": True},
            "source_correlation_id": str(correlation_id),
        },
        callback_config={
            "notify_parent": True,
            "parent_bot_id": "parent-bot",
            "parent_session_id": str(parent_session_id),
            "parent_client_id": "parent-client",
        },
    )
    db = _FakeDb(task)
    result = SimpleNamespace(
        stdout="hello",
        stderr="warn",
        exit_code=0,
        truncated=False,
        duration_ms=12,
    )
    deps, records, workspace_service, _sandbox_service = _deps(db, workspace_result=result)

    await task_exec_host.run_exec_task(task, deps=deps)

    assert task.status == "complete"
    assert task.result == "hello\n[stderr]\nwarn\n[exit 0, 12ms]"
    deps.fire_task_complete.assert_awaited_once_with(task, "complete")
    workspace_service.exec.assert_awaited_once()
    assert records == [
        {
            "command": "echo",
            "task_id": task.id,
            "session_id": task.session_id,
            "client_id": task.client_id,
            "bot_id": task.bot_id,
            "correlation_id": correlation_id,
            "exit_code": 0,
            "duration_ms": 12,
            "truncated": False,
            "result_text": task.result,
            "error": None,
        }
    ]
    deps.publish_turn_ended.assert_awaited_once()
    publish_kwargs = deps.publish_turn_ended.await_args.kwargs
    assert publish_kwargs["result"] == task.result

    callback_tasks = [item for item in db.added if item.task_type == "callback"]
    assert len(callback_tasks) == 1
    callback = callback_tasks[0]
    assert callback.bot_id == "parent-bot"
    assert callback.session_id == parent_session_id
    assert callback.parent_task_id == task.id
    assert callback.dispatch_type == "channel"
    assert callback.dispatch_config == {"reply_in_thread": True}
    assert callback.prompt == f"[Exec task completed: echo]\n\n{task.result}"


@pytest.mark.asyncio
async def test_exec_host_timeout_marks_failed_and_publishes_safe_error(monkeypatch):
    task = _exec_task()
    db = _FakeDb(task)
    deps, records, _workspace_service, _sandbox_service = _deps(db, timeout=7)

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(task_exec_host.asyncio, "wait_for", fake_wait_for)

    await task_exec_host.run_exec_task(task, deps=deps)

    deps.mark_task_failed_in_db.assert_awaited_once_with(task.id, error="Timed out after 7s")
    deps.fire_task_complete.assert_awaited_once_with(task, "failed")
    deps.publish_turn_ended_safe.assert_awaited_once()
    assert deps.publish_turn_ended_safe.await_args.kwargs["error"] == "Timed out after 7s"
    assert records == []


@pytest.mark.asyncio
async def test_exec_host_failure_records_without_safe_publish_for_generic_errors():
    task = _exec_task()
    db = _FakeDb(task)
    deps, records, _workspace_service, _sandbox_service = _deps(
        db,
        bot=_bot(workspace_enabled=False, bot_sandbox_enabled=False),
    )

    await task_exec_host.run_exec_task(task, deps=deps)

    deps.mark_task_failed_in_db.assert_awaited_once()
    failure_kwargs = deps.mark_task_failed_in_db.await_args.kwargs
    assert failure_kwargs["error"] == "No sandbox available for exec task"
    deps.fire_task_complete.assert_awaited_once_with(task, "failed")
    deps.publish_turn_ended.assert_not_awaited()
    deps.publish_turn_ended_safe.assert_not_awaited()
    assert len(records) == 1
    assert records[0]["command"] == "echo"
    assert records[0]["exit_code"] == -1
    assert records[0]["error"] == "No sandbox available for exec task"
