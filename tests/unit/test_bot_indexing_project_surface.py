from types import SimpleNamespace
from unittest.mock import patch

from app.services.bot_indexing import BotIndexPlan, _resolve_channel


def test_channel_index_plan_can_use_project_surface_root_and_prefix():
    workspace_plan = BotIndexPlan(
        bot_id="bot-1",
        roots=("/bot/workspace",),
        patterns=["**/*.md"],
        embedding_model="text-embedding-3-small",
        similarity_threshold=0.3,
        top_k=10,
        watch=True,
        cooldown_seconds=30,
        segments=None,
        scope="workspace",
        shared_workspace=True,
        skip_stale_cleanup=False,
    )

    with patch("app.services.bot_indexing._resolve_workspace", return_value=workspace_plan):
        plan = _resolve_channel(
            SimpleNamespace(id="bot-1"),
            channel_id="channel-1",
            base_prefix="common/projects/demo",
            base_root="/shared/ws-1",
        )

    assert plan is not None
    assert plan.roots == ("/shared/ws-1",)
    assert plan.patterns == ["common/projects/demo/**/*.md"]
    assert plan.bot_id == "channel:channel-1"
