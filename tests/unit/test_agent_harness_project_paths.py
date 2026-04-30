from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.agent_harnesses.project import resolve_harness_paths
from app.services.projects import WorkSurface


@pytest.mark.asyncio
async def test_harness_uses_channel_work_surface_before_bot_harness_workdir(monkeypatch) -> None:
    channel_id = uuid.uuid4()
    channel = SimpleNamespace(id=channel_id)
    bot = SimpleNamespace(id="bot", harness_workdir="/tmp/bypass")
    surface = WorkSurface(
        kind="channel",
        root_host_path="/tmp/channel-surface",
        display_path=f"/workspace/channels/{channel_id}",
        index_root_host_path="/tmp/shared",
        index_prefix=f"channels/{channel_id}",
        knowledge_index_prefix=f"channels/{channel_id}/knowledge-base",
        workspace_id=str(uuid.uuid4()),
        channel_id=str(channel_id),
    )

    class _DB:
        async def get(self, _model, value):
            assert value == channel_id
            return channel

    monkeypatch.setattr(
        "app.services.agent_harnesses.project.workspace_service.ensure_host_dir",
        lambda *_args, **_kwargs: "/tmp/bot-workspace",
    )
    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_channel_work_surface",
        AsyncMock(return_value=surface),
    )

    result = await resolve_harness_paths(_DB(), channel_id=channel_id, bot=bot)

    assert result.workdir == "/tmp/channel-surface"
    assert result.source == "channel_work_surface"
    assert result.project_dir is None
    assert result.work_surface is surface
