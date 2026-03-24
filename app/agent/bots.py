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
    cross_channel: bool = False
    cross_client: bool = False
    cross_bot: bool = False
    prompt: str | None = None
    similarity_threshold: float = 0.45
    wipe_on_session_delete: bool = False

@dataclass
class KnowledgeConfig:
    enabled: bool = False


@dataclass
class SkillConfig:
    id: str
    mode: str = "on_demand"          # "on_demand" | "pinned" | "rag"
    similarity_threshold: float | None = None  # only used when mode="rag"


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
class BotSandboxConfig:
    enabled: bool = False
    unrestricted: bool = False   # if True, command allowlist is ignored when running in sandbox
    image: str = "python:3.12-slim"
    network: str = "none"
    env: dict = field(default_factory=dict)
    ports: list = field(default_factory=list)
    mounts: list = field(default_factory=list)  # [{host_path, container_path, mode}]
    user: str = ""


@dataclass
class WorkspaceDockerConfig:
    image: str = "python:3.12-slim"
    network: str = "none"
    env: dict = field(default_factory=dict)
    ports: list = field(default_factory=list)
    mounts: list = field(default_factory=list)  # [{host_path, container_path, mode}]
    user: str = ""
    read_only_root: bool = False
    cpus: float | None = None
    memory: str | None = None


@dataclass
class WorkspaceHostConfig:
    root: str = ""  # custom root; empty = auto (~/.agent-workspaces/<bot_id>/)
    commands: list[HostExecCommandEntry] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    env_passthrough: list[str] = field(default_factory=list)


@dataclass
class WorkspaceIndexingConfig:
    enabled: bool = True
    patterns: list[str] = field(default_factory=lambda: ["**/*.py", "**/*.md", "**/*.yaml"])
    similarity_threshold: float | None = None
    top_k: int | None = None
    watch: bool = True
    cooldown_seconds: int = 300


@dataclass
class WorkspaceConfig:
    enabled: bool = False
    type: str = "docker"  # "docker" | "host"
    docker: WorkspaceDockerConfig = field(default_factory=WorkspaceDockerConfig)
    host: WorkspaceHostConfig = field(default_factory=WorkspaceHostConfig)
    timeout: int | None = None
    max_output_bytes: int | None = None
    indexing: WorkspaceIndexingConfig = field(default_factory=WorkspaceIndexingConfig)


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
    skills: list[SkillConfig] = field(default_factory=list)
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
    display_name: str | None = None
    avatar_url: str | None = None
    integration_config: dict = field(default_factory=dict)
    # Bot-level overrides for tool result summarization. Keys: enabled (bool|None),
    # threshold (int|None), model (str|None), max_tokens (int|None), exclude_tools (list[str]).
    # None values inherit from global TOOL_RESULT_SUMMARIZE_* settings.
    tool_result_config: dict = field(default_factory=dict)
    # Bot-level overrides for pre-turn context compression. Keys: enabled (bool|None),
    # model (str|None), threshold (int|None), keep_turns (int|None).
    # None values inherit from global CONTEXT_COMPRESSION_* settings.
    compression_config: dict = field(default_factory=dict)
    # Per-bot RAG injection limits (chars per item). None = use global settings.
    knowledge_max_inject_chars: int | None = None
    memory_max_inject_chars: int | None = None
    # Delegation
    delegate_bots: list[str] = field(default_factory=list)   # allowed bot_ids for delegation
    harness_access: list[str] = field(default_factory=list)  # allowed harness names
    # Model elevation (per-bot overrides; None = inherit from channel or global)
    elevation_enabled: bool | None = None
    elevation_threshold: float | None = None
    elevated_model: str | None = None
    # Provider
    model_provider_id: str | None = None  # DB provider_configs.id; None = use .env fallback
    # Bot-local execution sandbox
    bot_sandbox: BotSandboxConfig = field(default_factory=BotSandboxConfig)
    # Unified workspace config
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)

    @property
    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills]


def _parse_skill_entry(entry) -> SkillConfig:
    """Parse a skill entry (string or dict) into a SkillConfig."""
    if isinstance(entry, str):
        return SkillConfig(id=entry)
    if isinstance(entry, dict):
        return SkillConfig(
            id=entry["id"],
            mode=entry.get("mode", "on_demand"),
            similarity_threshold=entry.get("similarity_threshold"),
        )
    return SkillConfig(id=str(entry))


def _normalize_skill_entry(entry) -> dict:
    """Normalize a skill entry (string or dict) into a dict for DB storage."""
    if isinstance(entry, str):
        return {"id": entry, "mode": "on_demand"}
    if isinstance(entry, dict):
        result = {"id": entry["id"], "mode": entry.get("mode", "on_demand")}
        if entry.get("similarity_threshold") is not None:
            result["similarity_threshold"] = entry["similarity_threshold"]
        return result
    return {"id": str(entry), "mode": "on_demand"}


def _bot_row_to_config(row: BotRow) -> BotConfig:
    """Convert a DB BotRow to a BotConfig dataclass."""
    mem = row.memory_config or {}
    memory_cfg = MemoryConfig(
        enabled=mem.get("enabled", False),
        cross_channel=mem.get("cross_channel", False),
        cross_client=mem.get("cross_client", False),
        cross_bot=mem.get("cross_bot", False),
        prompt=mem.get("prompt"),
        similarity_threshold=mem.get("similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD),
        wipe_on_session_delete=mem.get("wipe_on_session_delete", settings.WIPE_MEMORY_ON_SESSION_DELETE),
    )
    know = row.knowledge_config or {}
    knowledge_cfg = KnowledgeConfig(
        enabled=know.get("enabled", False),
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
    bs_raw = row.bot_sandbox or {}
    bot_sandbox_cfg = BotSandboxConfig(
        enabled=bs_raw.get("enabled", False),
        unrestricted=bs_raw.get("unrestricted", False),
        image=bs_raw.get("image", "python:3.12-slim"),
        network=bs_raw.get("network", "none"),
        env=bs_raw.get("env", {}),
        ports=bs_raw.get("ports", []),
        mounts=bs_raw.get("mounts", []),
        user=bs_raw.get("user", ""),
    )
    ws_raw = row.workspace or {}
    ws_docker_raw = ws_raw.get("docker", {})
    ws_host_raw = ws_raw.get("host", {})
    ws_indexing_raw = ws_raw.get("indexing", {})
    workspace_cfg = WorkspaceConfig(
        enabled=ws_raw.get("enabled", False),
        type=ws_raw.get("type", "docker"),
        docker=WorkspaceDockerConfig(
            image=ws_docker_raw.get("image", "python:3.12-slim"),
            network=ws_docker_raw.get("network", "none"),
            env=ws_docker_raw.get("env", {}),
            ports=ws_docker_raw.get("ports", []),
            mounts=ws_docker_raw.get("mounts", []),
            user=ws_docker_raw.get("user", ""),
            read_only_root=ws_docker_raw.get("read_only_root", False),
            cpus=ws_docker_raw.get("cpus"),
            memory=ws_docker_raw.get("memory"),
        ),
        host=WorkspaceHostConfig(
            root=ws_host_raw.get("root", ""),
            commands=[
                HostExecCommandEntry(
                    name=c["name"],
                    subcommands=c.get("subcommands", []),
                )
                for c in ws_host_raw.get("commands", [])
            ],
            blocked_patterns=ws_host_raw.get("blocked_patterns", []),
            env_passthrough=ws_host_raw.get("env_passthrough", []),
        ),
        timeout=ws_raw.get("timeout"),
        max_output_bytes=ws_raw.get("max_output_bytes"),
        indexing=WorkspaceIndexingConfig(
            enabled=ws_indexing_raw.get("enabled", True),
            patterns=ws_indexing_raw.get("patterns", ["**/*.py", "**/*.md", "**/*.yaml"]),
            similarity_threshold=ws_indexing_raw.get("similarity_threshold"),
            top_k=ws_indexing_raw.get("top_k"),
            watch=ws_indexing_raw.get("watch", True),
            cooldown_seconds=ws_indexing_raw.get("cooldown_seconds", 300),
        ),
    )
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
        skills=[_parse_skill_entry(e) for e in (row.skills or [])],
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
        display_name=row.display_name,
        avatar_url=row.avatar_url,
        integration_config=row.integration_config or {},
        tool_result_config=row.tool_result_config or {},
        compression_config=row.compression_config or {},
        knowledge_max_inject_chars=row.knowledge_max_inject_chars,
        memory_max_inject_chars=row.memory_max_inject_chars,
        delegate_bots=list(row.delegation_config.get("delegate_bots", [])) if row.delegation_config else [],
        harness_access=list(row.delegation_config.get("harness_access", [])) if row.delegation_config else [],
        elevation_enabled=row.elevation_enabled,
        elevation_threshold=row.elevation_threshold,
        elevated_model=row.elevated_model,
        model_provider_id=row.model_provider_id,
        bot_sandbox=bot_sandbox_cfg,
        workspace=workspace_cfg,
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
        "skills": [_normalize_skill_entry(e) for e in data.get("skills", [])],
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
            "cross_channel": mem_data.get("cross_channel", False),
            "cross_client": mem_data.get("cross_client", False),
            "cross_bot": mem_data.get("cross_bot", False),
            "prompt": mem_data.get("prompt"),
            "similarity_threshold": mem_data.get("similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD),
            "wipe_on_session_delete": mem_data.get("wipe_on_session_delete", settings.WIPE_MEMORY_ON_SESSION_DELETE),
        },
        "knowledge_config": {
            "enabled": know_data.get("enabled", False),
        },
        "filesystem_indexes": data.get("filesystem_indexes", []),
        "host_exec_config": _parse_host_exec_yaml(data.get("host_exec", {})),
        "filesystem_access": [
            {"path": e["path"], "mode": e.get("mode", "read")}
            for e in data.get("filesystem_access", [])
        ],
        "display_name": data.get("display_name"),
        "avatar_url": data.get("avatar_url"),
        "integration_config": data.get("integration_config", {}),
        "tool_result_config": data.get("tool_result_config", {}),
        "compression_config": data.get("compression_config", {}),
        "knowledge_max_inject_chars": data.get("knowledge_max_inject_chars"),
        "memory_max_inject_chars": data.get("memory_max_inject_chars"),
        "delegation_config": {
            "delegate_bots": data.get("delegate_bots", []),
            "harness_access": data.get("harness_access", []),
        },
        "workspace": data.get("workspace", {"enabled": False}),
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


def resolve_bot_id(hint: str) -> BotConfig | None:
    """Fuzzy-resolve a bot by ID or name hint. Returns the best match or None.

    Resolution order (first match wins):
    1. Exact ID match
    2. Case-insensitive ID match
    3. Exact name match (case-insensitive)
    4. Substring of ID  (e.g. "google" → "google_bot")
    5. Substring of name (e.g. "lmgtfy" matches "Let Me Google That For You")
    6. Word-overlap score on name tokens (e.g. "let me google" hits "Let Me Google…")
    """
    if not hint or not _registry:
        return None
    h = hint.strip().lower()

    # 1. exact id
    if h in _registry:
        return _registry[h]

    # 2. case-insensitive id
    for bid, bot in _registry.items():
        if bid.lower() == h:
            return bot

    # 3. exact name
    for bot in _registry.values():
        if bot.name.lower() == h:
            return bot

    # 4. substring of id
    for bid, bot in _registry.items():
        if h in bid.lower() or bid.lower() in h:
            return bot

    # 5. substring of name
    for bot in _registry.values():
        name_l = bot.name.lower()
        if h in name_l or name_l in h:
            return bot

    # 6. word-overlap on name (highest overlap wins)
    hint_words = set(h.split())
    best_bot: BotConfig | None = None
    best_score = 0
    for bot in _registry.values():
        name_words = set(bot.name.lower().split())
        # also tokenise the id by splitting on _ and -
        import re as _re
        id_words = set(_re.split(r"[_\-]", bot.id.lower()))
        overlap = len(hint_words & (name_words | id_words))
        if overlap > best_score:
            best_score = overlap
            best_bot = bot
    if best_score > 0:
        return best_bot

    return None
