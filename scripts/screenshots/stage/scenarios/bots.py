"""Bot seeders. All IDs prefixed ``screenshot-`` so teardown is trivial."""
from __future__ import annotations

from ..client import SpindrelClient

SCREENSHOT_BOT_PREFIX = "screenshot-"

DEMO_BOTS = [
    {
        "id": f"{SCREENSHOT_BOT_PREFIX}orchestrator",
        "name": "Orion",
        "model": "claude-sonnet-4-6",
        "system_prompt": "You coordinate household automation and reply briefly.",
    },
    {
        "id": f"{SCREENSHOT_BOT_PREFIX}researcher",
        "name": "Vega",
        "model": "claude-haiku-4-5",
        "system_prompt": "You run web research and summarize concisely.",
    },
    {
        "id": f"{SCREENSHOT_BOT_PREFIX}ops",
        "name": "Lyra",
        "model": "gpt-5",
        "system_prompt": "You run day-to-day ops tasks.",
    },
]


def ensure_demo_bots(client: SpindrelClient) -> list[str]:
    ids: list[str] = []
    for spec in DEMO_BOTS:
        client.ensure_bot(
            bot_id=spec["id"],
            name=spec["name"],
            model=spec["model"],
            system_prompt=spec["system_prompt"],
        )
        ids.append(spec["id"])
    return ids


def teardown_demo_bots(client: SpindrelClient) -> None:
    for spec in DEMO_BOTS:
        client.delete_bot(spec["id"])
