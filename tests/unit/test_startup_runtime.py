"""Tests for startup runtime lifecycle ownership."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import startup_runtime


class _FakeTask:
    def __init__(self, name: str):
        self.name = name
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


async def _marker_coro() -> None:
    return None


def _worker_factory(*_args, **_kwargs):
    return _marker_coro()


def _patch_safe_create_task(monkeypatch, events: list[str]):
    def _safe(coro, *, name: str = ""):
        if hasattr(coro, "close"):
            coro.close()
        events.append(f"schedule:{name}")
        return _FakeTask(name)

    monkeypatch.setattr(startup_runtime, "safe_create_task", _safe)


def test_boot_background_services_schedule_expected_workers(monkeypatch):
    events: list[str] = []
    _patch_safe_create_task(monkeypatch, events)

    class _SharedWorkspaceService:
        ensured: list[str] = []

        def ensure_host_dirs(self, workspace_id: str) -> None:
            self.ensured.append(workspace_id)

        def get_host_root(self, workspace_id: str) -> str:
            return f"/tmp/ws-{workspace_id}"

    fake_shared_service = _SharedWorkspaceService()
    import app.services.shared_workspace as shared_workspace_mod
    import app.agent.fs_watcher as fs_watcher_mod

    monkeypatch.setattr(
        shared_workspace_mod,
        "shared_workspace_service",
        fake_shared_service,
    )
    monkeypatch.setattr(fs_watcher_mod, "start_shared_workspace_watchers", _worker_factory)
    monkeypatch.setattr(startup_runtime, "index_filesystems_and_start_watchers", _worker_factory)
    monkeypatch.setattr(startup_runtime, "background_warmup", _worker_factory)

    handle = startup_runtime.StartupRuntimeHandle()
    startup_runtime.start_boot_background_services(
        handle,
        shared_workspace_rows=[
            SimpleNamespace(id="a", name="Alpha"),
            SimpleNamespace(id="b", name="Beta"),
        ],
    )

    assert fake_shared_service.ensured == ["a", "b"]
    assert events == ["schedule:sw_watchers", "schedule:fs_index", "schedule:bg_warmup"]
    assert [task.name for task in handle.workers] == [
        "sw_watchers",
        "fs_index",
        "bg_warmup",
    ]


def test_boot_filesystem_worker_does_not_force_reindex_workspaces():
    source = Path(startup_runtime.__file__).read_text()
    node = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "index_filesystems_and_start_watchers"
    )
    body = ast.get_source_segment(source, node) or ""

    assert "start_watchers" in body
    assert "reindex_bot" not in body
    assert "index_directory" not in body
    assert "force=True" not in body


@pytest.mark.asyncio
async def test_ready_runtime_recovers_before_launching_dependent_workers(monkeypatch):
    events: list[str] = []
    _patch_safe_create_task(monkeypatch, events)
    monkeypatch.setattr(startup_runtime.settings, "CONFIG_STATE_FILE", "")

    async def _recover_heartbeat():
        events.append("recover:heartbeat")

    async def _recover_outbox():
        events.append("recover:outbox")

    async def _register_widgets():
        events.append("register:widgets")

    def _start_renderers(_handle):
        events.append("start:renderers")

    monkeypatch.setattr(startup_runtime, "recover_heartbeat_runs_before_worker", _recover_heartbeat)
    monkeypatch.setattr(startup_runtime, "recover_outbox_before_drainer", _recover_outbox)
    monkeypatch.setattr(startup_runtime, "register_widget_events_on_startup", _register_widgets)
    monkeypatch.setattr(startup_runtime, "start_renderer_dispatchers", _start_renderers)

    import app.agent.fs_watcher as fs_watcher_mod
    import app.agent.tasks as tasks_mod
    import app.services.attachment_retention as attachment_retention_mod
    import app.services.attachment_summarizer as attachment_summarizer_mod
    import app.services.data_retention as data_retention_mod
    import app.services.heartbeat as heartbeat_mod
    import app.services.integration_processes as integration_processes_mod
    import app.services.outbox_drainer as outbox_drainer_mod
    import app.services.pin_contract as pin_contract_mod
    import app.services.unread as unread_mod
    import app.services.usage_spike as usage_spike_mod
    import app.services.workspace_attention as workspace_attention_mod

    monkeypatch.setattr(tasks_mod, "task_worker", _worker_factory)
    monkeypatch.setattr(heartbeat_mod, "heartbeat_worker", _worker_factory)
    monkeypatch.setattr(usage_spike_mod, "usage_spike_worker", _worker_factory)
    monkeypatch.setattr(fs_watcher_mod, "periodic_reindex_worker", _worker_factory)
    monkeypatch.setattr(attachment_summarizer_mod, "attachment_sweep_worker", _worker_factory)
    monkeypatch.setattr(attachment_retention_mod, "attachment_retention_worker", _worker_factory)
    monkeypatch.setattr(data_retention_mod, "data_retention_worker", _worker_factory)
    monkeypatch.setattr(pin_contract_mod, "pin_contract_drift_worker", _worker_factory)
    monkeypatch.setattr(outbox_drainer_mod, "outbox_drainer_worker", _worker_factory)
    monkeypatch.setattr(workspace_attention_mod, "structured_attention_worker", _worker_factory)
    monkeypatch.setattr(unread_mod, "unread_reminder_worker", _worker_factory)
    monkeypatch.setattr(
        integration_processes_mod,
        "process_manager",
        SimpleNamespace(
            start_auto_start_processes=_worker_factory,
            shutdown_all=AsyncMock(),
        ),
    )

    handle = startup_runtime.StartupRuntimeHandle()
    await startup_runtime.start_ready_runtime_services(handle)

    assert events.index("recover:heartbeat") < events.index("schedule:heartbeat_worker")
    assert events.index("recover:outbox") < events.index("schedule:outbox_drainer")
    assert "start:renderers" in events
    assert events[-1] == "register:widgets"


@pytest.mark.asyncio
async def test_widget_startup_registration_is_best_effort(monkeypatch, caplog):
    import app.services.widget_events as widget_events_mod

    async def _boom():
        raise RuntimeError("bad widget")

    monkeypatch.setattr(widget_events_mod, "register_all_pins_on_startup", _boom)

    await startup_runtime.register_widget_events_on_startup()

    assert "widget_events: startup registration failed" in caplog.text


def test_start_renderer_dispatchers_uses_registered_renderer_snapshot(monkeypatch):
    events: list[str] = []

    class _Renderer:
        integration_id = "fake"

    class _Dispatcher:
        def __init__(self, renderer, resolver):
            self.renderer = renderer
            self.resolver = resolver

        def start(self) -> None:
            events.append(f"started:{self.renderer.integration_id}")

    import app.integrations.renderer_registry as registry_mod
    import app.services.channel_renderers as channel_renderers_mod

    monkeypatch.setattr(registry_mod, "all_renderers", lambda: {"fake": _Renderer()})
    monkeypatch.setattr(channel_renderers_mod, "IntegrationDispatcherTask", _Dispatcher)

    handle = startup_runtime.StartupRuntimeHandle()
    startup_runtime.start_renderer_dispatchers(handle)

    assert events == ["started:fake"]
    assert len(handle.renderer_dispatchers) == 1


@pytest.mark.asyncio
async def test_shutdown_stops_runtime_resources(monkeypatch):
    events: list[str] = []
    process_manager = SimpleNamespace(shutdown_all=AsyncMock(side_effect=lambda: events.append("processes")))
    dispatcher = SimpleNamespace(stop=AsyncMock(side_effect=lambda: events.append("dispatcher")))
    worker = _FakeTask("worker")
    handle = startup_runtime.StartupRuntimeHandle(
        workers=[worker],
        renderer_dispatchers=[dispatcher],
        process_manager=process_manager,
    )

    import app.services.channel_events as channel_events_mod
    import app.services.user_events as user_events_mod
    import app.services.widget_events as widget_events_mod

    async def _unregister_widgets():
        events.append("widgets")

    async def _close_renderer_clients():
        events.append("clients")

    monkeypatch.setattr(widget_events_mod, "unregister_all_on_shutdown", _unregister_widgets)
    monkeypatch.setattr(channel_events_mod, "signal_shutdown", lambda: events.append("channel-signal"))
    monkeypatch.setattr(user_events_mod, "signal_shutdown", lambda: events.append("user-signal"))
    monkeypatch.setattr(startup_runtime, "close_renderer_http_clients", _close_renderer_clients)

    await startup_runtime.shutdown_runtime_services(handle)

    assert worker.cancelled is True
    assert events == [
        "widgets",
        "channel-signal",
        "user-signal",
        "dispatcher",
        "clients",
        "processes",
    ]


def test_main_lifespan_keeps_runtime_machinery_out_of_inline_body():
    source = Path("app/main.py").read_text()
    tree = ast.parse(source)
    lifespan = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )

    nested_async_defs = {
        node.name
        for node in ast.walk(lifespan)
        if isinstance(node, ast.AsyncFunctionDef) and node is not lifespan
    }
    imported_names = {
        alias.name
        for node in ast.walk(lifespan)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "background_warmup" not in nested_async_defs
    assert "session_cleanup_worker" not in nested_async_defs
    assert "IntegrationDispatcherTask" not in imported_names
