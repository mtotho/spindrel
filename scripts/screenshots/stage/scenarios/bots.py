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


# Spatial-canvas demo cast. Mirrors the persona mix visible in the canvas hero
# shots — household, dev, ops, log, and image personas — so the screenshot
# delivers the "many bots, one workspace" read at a glance. IDs use the
# ``screenshot-spatial-`` prefix so teardown is bounded and never collides
# with flagship's ``screenshot-orchestrator/researcher/ops``.
SPATIAL_BOT_PREFIX = f"{SCREENSHOT_BOT_PREFIX}spatial-"

DEMO_SPATIAL_BOTS = [
    {"id": f"{SPATIAL_BOT_PREFIX}orchestrator", "name": "Orchestrator", "model": "claude-sonnet-4-6",
     "system_prompt": "You coordinate household + workspace automation."},
    {"id": f"{SPATIAL_BOT_PREFIX}sprout", "name": "Sprout", "model": "claude-haiku-4-5",
     "system_prompt": "You watch over the gardens and propose seasonal tasks."},
    {"id": f"{SPATIAL_BOT_PREFIX}crumb", "name": "Crumb", "model": "claude-haiku-4-5",
     "system_prompt": "You help plan baking, manage the sourdough starter, and stage recipes."},
    {"id": f"{SPATIAL_BOT_PREFIX}patch", "name": "Patch", "model": "claude-sonnet-4-6",
     "system_prompt": "You triage incoming developer commits and surface review-worthy diffs."},
    {"id": f"{SPATIAL_BOT_PREFIX}bennie", "name": "Bennie Bot", "model": "claude-haiku-4-5",
     "system_prompt": "You track the dog's health, vet visits, and feeding schedule."},
    {"id": f"{SPATIAL_BOT_PREFIX}dev", "name": "Dev Bot", "model": "claude-sonnet-4-6",
     "system_prompt": "You help build, test, and ship code in this workspace."},
    {"id": f"{SPATIAL_BOT_PREFIX}image", "name": "Image Bot", "model": "claude-haiku-4-5",
     "system_prompt": "You generate, organize, and tag images on request."},
    {"id": f"{SPATIAL_BOT_PREFIX}log", "name": "Log Bot", "model": "claude-haiku-4-5",
     "system_prompt": "You audit system logs, surface anomalies, and summarize quietly."},
    {"id": f"{SPATIAL_BOT_PREFIX}michael", "name": "Michael Bot", "model": "claude-sonnet-4-6",
     "system_prompt": "You're the personal assistant — calendar, inbox, follow-ups."},
    {"id": f"{SPATIAL_BOT_PREFIX}home-assistant", "name": "Home Assistant", "model": "claude-haiku-4-5",
     "system_prompt": "You bridge to Home Assistant and answer device + scene questions."},
    {"id": f"{SPATIAL_BOT_PREFIX}kathy", "name": "Kathy Assistant", "model": "claude-haiku-4-5",
     "system_prompt": "You help draft messages, track conversations, and send replies."},
    {"id": f"{SPATIAL_BOT_PREFIX}penny", "name": "Penny", "model": "claude-haiku-4-5",
     "system_prompt": "You manage the grocery list and meal planning."},
]


def ensure_spatial_demo_bots(client: SpindrelClient) -> list[str]:
    ids: list[str] = []
    for spec in DEMO_SPATIAL_BOTS:
        client.ensure_bot(
            bot_id=spec["id"],
            name=spec["name"],
            model=spec["model"],
            system_prompt=spec["system_prompt"],
        )
        ids.append(spec["id"])
    return ids


def teardown_spatial_demo_bots(client: SpindrelClient) -> None:
    for spec in DEMO_SPATIAL_BOTS:
        client.delete_bot(spec["id"])
