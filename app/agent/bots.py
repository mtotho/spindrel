import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

BOTS_DIR = Path("bots")

_registry: dict[str, "BotConfig"] = {}


@dataclass
class MemoryConfig:
    enabled: bool = False
    cross_session: bool = False
    cross_client: bool = False
    cross_bot: bool = False
    prompt: str | None = None
    similarity_threshold: float = 0.45
    wipe_on_session_delete: bool = False


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
    persona: bool = False
    context_compaction: bool = True
    compaction_interval: int | None = None
    compaction_keep_turns: int | None = None
    compaction_model: str | None = None
    audio_input: str = "transcribe"  # "transcribe" or "native"
    memory: MemoryConfig = field(default_factory=MemoryConfig)


def load_bots(bots_dir: Path = BOTS_DIR) -> None:
    _registry.clear()
    if not bots_dir.exists():
        logger.warning("Bots directory %s does not exist", bots_dir)
        return
    for path in bots_dir.glob("*.yaml"):
        with open(path) as f:
            data = yaml.safe_load(f)
        mem_data = data.get("memory", {})
        memory_cfg = MemoryConfig(
            enabled=mem_data.get("enabled", False),
            cross_session=mem_data.get("cross_session", False),
            cross_client=mem_data.get("cross_client", False),
            cross_bot=mem_data.get("cross_bot", False),
            prompt=mem_data.get("prompt"),
            similarity_threshold=mem_data.get("similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD),
            wipe_on_session_delete=mem_data.get("wipe_on_session_delete", settings.WIPE_MEMORY_ON_SESSION_DELETE),
        )

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
            persona=data.get("persona", False),
            context_compaction=data.get("context_compaction", True),
            compaction_interval=data.get("compaction_interval", settings.COMPACTION_INTERVAL),
            compaction_keep_turns=data.get("compaction_keep_turns", settings.COMPACTION_KEEP_TURNS),
            compaction_model=data.get("compaction_model", settings.COMPACTION_MODEL),
            audio_input=data.get("audio_input", "transcribe"),
            memory=memory_cfg,
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
