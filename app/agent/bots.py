import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import HTTPException

logger = logging.getLogger(__name__)

BOTS_DIR = Path("bots")

_registry: dict[str, "BotConfig"] = {}


@dataclass
class BotConfig:
    id: str
    name: str
    model: str
    system_prompt: str
    mcp_servers: list[str] = field(default_factory=list)
    local_tools: list[str] = field(default_factory=list)
    client_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    rag: bool = False
    context_compaction: bool = True
    compaction_interval: int | None = None
    compaction_model: str | None = None
    voice: dict | None = None


def load_bots(bots_dir: Path = BOTS_DIR) -> None:
    _registry.clear()
    if not bots_dir.exists():
        logger.warning("Bots directory %s does not exist", bots_dir)
        return
    for path in bots_dir.glob("*.yaml"):
        with open(path) as f:
            data = yaml.safe_load(f)
        bot = BotConfig(
            id=data["id"],
            name=data.get("name", data["id"]),
            model=data["model"],
            system_prompt=data.get("system_prompt", "You are a helpful assistant."),
            mcp_servers=data.get("mcp_servers", []),
            local_tools=data.get("local_tools", []),
            client_tools=data.get("client_tools", []),
            skills=data.get("skills", []),
            rag=data.get("rag", False),
            context_compaction=data.get("context_compaction", True),
            compaction_interval=data.get("compaction_interval"),
            compaction_model=data.get("compaction_model"),
            voice=data.get("voice"),
        )
        _registry[bot.id] = bot
        logger.info("Loaded bot: %s (%s)", bot.id, bot.name)


def list_bots() -> list[BotConfig]:
    return list(_registry.values())


def get_bot(bot_id: str) -> BotConfig:
    bot = _registry.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_id}")
    return bot
