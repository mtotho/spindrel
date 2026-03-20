import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.engine import async_session
from app.db.models import Bot as BotRow

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
class KnowledgeConfig:
    enabled: bool = False
    cross_bot: bool = False
    cross_client: bool = False #in slack, this is per channel or cross channel
    similarity_threshold: float = 0.45


@dataclass
class FilesystemIndexConfig:
    root: str
    patterns: list[str] = field(default_factory=lambda: ["**/*.py", "**/*.md", "**/*.yaml"])
    cooldown_seconds: int = 300
    watch: bool = False
    similarity_threshold: float | None = None  # overrides FS_INDEX_SIMILARITY_THRESHOLD


@dataclass
class HostExecCommandEntry:
    name: str                                         # binary name, or "*" for wildcard
    subcommands: list[str] = field(default_factory=list)  # empty = all subcommands allowed


@dataclass
class HostExecConfig:
    enabled: bool = False
    dry_run: bool = False
    working_dirs: list[str] = field(default_factory=list)
    commands: list[HostExecCommandEntry] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    env_passthrough: list[str] = field(default_factory=list)
    timeout: int | None = None            # None = use HOST_EXEC_DEFAULT_TIMEOUT
    max_output_bytes: int | None = None   # None = use HOST_EXEC_MAX_OUTPUT_BYTES


@dataclass
class FilesystemAccessEntry:
    path: str
    mode: str = "read"                    # "read" | "write" | "readwrite"


@dataclass
class BotConfig:
    id: str
    name: str
    model: str
    system_prompt: str
    mcp_servers: list[str] = field(default_factory=list)
    local_tools: list[str] = field(default_factory=list)
    pinned_tools: list[str] = field(default_factory=list)
    tool_retrieval: bool = True
    tool_similarity_threshold: float | None = None
    client_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    rag: bool = False
    persona: bool = False
    context_compaction: bool = True
    compaction_interval: int | None = None
    compaction_keep_turns: int | None = None
    compaction_model: str | None = None
    memory_knowledge_compaction_prompt: str | None = None # Optional prompt. Before compaction, the agent will be given this prompt to determine what memories or knowledge chunks to include.
    audio_input: str = "transcribe"  # "transcribe" or "native"
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    filesystem_indexes: list[FilesystemIndexConfig] = field(default_factory=list)
    docker_sandbox_profiles: list[str] = field(default_factory=list)
    host_exec: HostExecConfig = field(default_factory=HostExecConfig)
    filesystem_access: list[FilesystemAccessEntry] = field(default_factory=list)
    slack_display_name: str | None = None
    slack_icon_emoji: str | None = None
    slack_icon_url: str | None = None


def _bot_row_to_config(row: BotRow) -> BotConfig:
    """Convert a DB BotRow to a BotConfig dataclass."""
    mem = row.memory_config or {}
    memory_cfg = MemoryConfig(
        enabled=mem.get("enabled", False),
        cross_session=mem.get("cross_session", False),
        cross_client=mem.get("cross_client", False),
        cross_bot=mem.get("cross_bot", False),
        prompt=mem.get("prompt"),
        similarity_threshold=mem.get("similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD),
        wipe_on_session_delete=mem.get("wipe_on_session_delete", settings.WIPE_MEMORY_ON_SESSION_DELETE),
    )
    know = row.knowledge_config or {}
    knowledge_cfg = KnowledgeConfig(
        enabled=know.get("enabled", False),
        cross_bot=know.get("cross_bot", False),
        cross_client=know.get("cross_client", False),
        similarity_threshold=know.get("similarity_threshold", 0.45),
    )
    fs_raw = row.filesystem_indexes or []
    filesystem_indexes = [
        FilesystemIndexConfig(
            root=entry["root"],
            patterns=entry.get("patterns", ["**/*.py", "**/*.md", "**/*.yaml"]),
            cooldown_seconds=entry.get("cooldown_seconds", 300),
            watch=entry.get("watch", False),
            similarity_threshold=entry.get("similarity_threshold"),
        )
        for entry in fs_raw
    ]
    he_raw = row.host_exec_config or {}
    host_exec_cfg = HostExecConfig(
        enabled=he_raw.get("enabled", False),
        dry_run=he_raw.get("dry_run", False),
        working_dirs=he_raw.get("working_dirs", []),
        commands=[
            HostExecCommandEntry(
                name=c["name"],
                subcommands=c.get("subcommands", []),
            )
            for c in he_raw.get("commands", [])
        ],
        blocked_patterns=he_raw.get("blocked_patterns", []),
        env_passthrough=he_raw.get("env_passthrough", []),
        timeout=he_raw.get("timeout"),
        max_output_bytes=he_raw.get("max_output_bytes"),
    )
    fs_access_raw = row.filesystem_access or []
    filesystem_access = [
        FilesystemAccessEntry(
            path=e["path"],
            mode=e.get("mode", "read"),
        )
        for e in fs_access_raw
    ]
    return BotConfig(
        id=row.id,
        name=row.name,
        model=row.model,
        system_prompt=row.system_prompt or "",
        mcp_servers=row.mcp_servers or [],
        local_tools=row.local_tools or [],
        pinned_tools=row.pinned_tools or [],
        tool_retrieval=row.tool_retrieval,
        tool_similarity_threshold=row.tool_similarity_threshold,
        client_tools=row.client_tools or [],
        skills=row.skills or [],
        rag=False,
        persona=row.persona,
        context_compaction=row.context_compaction,
        compaction_interval=row.compaction_interval,
        compaction_keep_turns=row.compaction_keep_turns,
        compaction_model=row.compaction_model,
        memory_knowledge_compaction_prompt=row.memory_knowledge_compaction_prompt,
        audio_input=row.audio_input or "transcribe",
        memory=memory_cfg,
        knowledge=knowledge_cfg,
        filesystem_indexes=filesystem_indexes,
        docker_sandbox_profiles=row.docker_sandbox_profiles or [],
        host_exec=host_exec_cfg,
        filesystem_access=filesystem_access,
        slack_display_name=row.slack_display_name,
        slack_icon_emoji=row.slack_icon_emoji,
        slack_icon_url=row.slack_icon_url,
    )


def _parse_host_exec_yaml(he: dict) -> dict:
    """Normalize host_exec YAML block into the JSONB dict stored in the DB."""
    return {
        "enabled": he.get("enabled", False),
        "dry_run": he.get("dry_run", False),
        "working_dirs": he.get("working_dirs", []),
        "commands": [
            {"name": c["name"], "subcommands": c.get("subcommands", [])}
            if isinstance(c, dict) else {"name": c, "subcommands": []}
            for c in he.get("commands", [])
        ],
        "blocked_patterns": he.get("blocked_patterns", []),
        "env_passthrough": he.get("env_passthrough", []),
        "timeout": he.get("timeout"),
        "max_output_bytes": he.get("max_output_bytes"),
    }


def _yaml_data_to_row_dict(data: dict) -> dict:
    """Convert YAML bot data dict to a dict suitable for inserting into bots table."""
    mem_data = data.get("memory", {})
    know_data = data.get("knowledge", {})
    return {
        "id": data["id"],
        "name": data.get("name", data["id"]),
        "model": data["model"],
        "system_prompt": data.get("system_prompt", "You are a helpful assistant."),
        "local_tools": data.get("local_tools", []),
        "mcp_servers": data.get("mcp_servers", []),
        "client_tools": data.get("client_tools", []),
        "pinned_tools": data.get("pinned_tools", []),
        "skills": data.get("skills", []),
        "docker_sandbox_profiles": data.get("docker_sandbox_profiles", []),
        "tool_retrieval": data.get("tool_retrieval", True),
        "tool_similarity_threshold": data.get("tool_similarity_threshold"),
        "persona": data.get("persona", False),
        "context_compaction": data.get("context_compaction", True),
        "compaction_interval": data.get("compaction_interval"),
        "compaction_keep_turns": data.get("compaction_keep_turns"),
        "compaction_model": data.get("compaction_model"),
        "memory_knowledge_compaction_prompt": data.get("memory_knowledge_compaction_prompt"),
        "audio_input": data.get("audio_input", "transcribe"),
        "memory_config": {
            "enabled": mem_data.get("enabled", False),
            "cross_session": mem_data.get("cross_session", False),
            "cross_client": mem_data.get("cross_client", False),
            "cross_bot": mem_data.get("cross_bot", False),
            "prompt": mem_data.get("prompt"),
            "similarity_threshold": mem_data.get("similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD),
            "wipe_on_session_delete": mem_data.get("wipe_on_session_delete", settings.WIPE_MEMORY_ON_SESSION_DELETE),
        },
        "knowledge_config": {
            "enabled": know_data.get("enabled", False),
            "cross_bot": know_data.get("cross_bot", False),
            "cross_client": know_data.get("cross_client", False),
            "similarity_threshold": know_data.get("similarity_threshold", 0.45),
        },
        "filesystem_indexes": data.get("filesystem_indexes", []),
        "host_exec_config": _parse_host_exec_yaml(data.get("host_exec", {})),
        "filesystem_access": [
            {"path": e["path"], "mode": e.get("mode", "read")}
            for e in data.get("filesystem_access", [])
        ],
        "slack_display_name": data.get("slack_display_name"),
        "slack_icon_emoji": data.get("slack_icon_emoji"),
        "slack_icon_url": data.get("slack_icon_url"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


async def seed_bots_from_yaml(bots_dir: Path = BOTS_DIR) -> None:
    """Seed bots from YAML files into DB — only if id doesn't already exist."""
    if not bots_dir.exists():
        logger.info("No bots directory at %s, skipping seed", bots_dir)
        return

    yaml_files = list(bots_dir.glob("*.yaml"))
    if not yaml_files:
        return

    async with async_session() as db:
        for path in yaml_files:
            with open(path) as f:
                data = yaml.safe_load(f)
            if not data or "id" not in data:
                continue
            row_dict = _yaml_data_to_row_dict(data)
            stmt = pg_insert(BotRow).values(**row_dict).on_conflict_do_nothing(index_elements=["id"])
            await db.execute(stmt)
        await db.commit()
    logger.info("Seeded bots from YAML (seed-once, no overwrites)")


async def load_bots() -> None:
    """Load all bots from DB into the in-memory registry."""
    _registry.clear()
    async with async_session() as db:
        rows = (await db.execute(select(BotRow))).scalars().all()
    for row in rows:
        bot = _bot_row_to_config(row)
        _registry[bot.id] = bot
        logger.info("Loaded bot: %s (%s)", bot.id, bot.name)
    logger.info("Loaded %d bot(s) from DB", len(_registry))


async def reload_bots() -> None:
    """Re-populate registry from DB — called after admin edits."""
    await load_bots()


def list_bots() -> list[BotConfig]:
    return list(_registry.values())


def get_bot(bot_id: str) -> BotConfig:
    bot = _registry.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_id}")
    return bot
