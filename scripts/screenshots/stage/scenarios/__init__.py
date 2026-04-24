"""Scenario stagers. Each returns a StagedState dataclass consumed by the capture layer."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StagedState:
    """Opaque handle returned by each stager; used to resolve capture-spec
    route placeholders like ``/channels/:id`` → ``/channels/<real-uuid>``.
    """
    channels: dict[str, str] = field(default_factory=dict)     # label -> channel_id
    bots: dict[str, str] = field(default_factory=dict)         # label -> bot_id
    pins: dict[str, str] = field(default_factory=dict)         # label -> pin_id
    tasks: dict[str, str] = field(default_factory=dict)        # label -> task_id
    dashboards: dict[str, str] = field(default_factory=dict)   # label -> dashboard_key
