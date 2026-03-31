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
from app.db.models import Bot as BotRow, SharedWorkspaceBot

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
class IndexSegment:
    """Per-path-prefix config overrides within a bot's indexing config."""
    path_prefix: str                          # e.g. "src/", "docs/"
    embedding_model: str | None = None        # None = inherit base
    patterns: list[str] | None = None
    similarity_threshold: float | None = None
    top_k: int | None = None
    watch: bool | None = None
    channel_id: str | None = None             # None = all channels; set = only RAG'd for this channel


@dataclass
class WorkspaceIndexingConfig:
    enabled: bool = True
    patterns: list[str] = field(default_factory=lambda: ["**/*.py", "**/*.md", "**/*.yaml"])
    similarity_threshold: float | None = None
    top_k: int | None = None
    watch: bool = True
    cooldown_seconds: int = 300
    include_bots: list[str] = field(default_factory=list)  # index other bots' directories too
    embedding_model: str | None = None
    segments: list[IndexSegment] = field(default_factory=list)


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
    base_prompt: bool = True
    context_compaction: bool = True
    compaction_interval: int | None = None
    compaction_keep_turns: int | None = None
    compaction_model: str | None = None
    memory_knowledge_compaction_prompt: str | None = None # Optional prompt. Before compaction, the agent will be given this prompt to determine what memories or knowledge chunks to include.
    compaction_prompt_template_id: str | None = None
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
    # Per-bot RAG injection limits (chars per item). None = use global settings.
    knowledge_max_inject_chars: int | None = None
    memory_max_inject_chars: int | None = None
    # Delegation
    delegate_bots: list[str] = field(default_factory=list)   # allowed bot_ids for delegation
    harness_access: list[str] = field(default_factory=list)  # allowed harness names
    cross_workspace_access: bool = False  # if True, channel workspace tools can see/search all bots' channels
    # Model elevation (per-bot overrides; None = inherit from channel or global)
    elevation_enabled: bool | None = None
    elevation_threshold: float | None = None
    elevated_model: str | None = None
    # LLM sampling parameters (temperature, max_tokens, etc.)
    model_params: dict = field(default_factory=dict)
    # Provider
    model_provider_id: str | None = None  # DB provider_configs.id; None = use .env fallback
    # Ordered fallback models (tried in sequence when primary model fails)
    fallback_models: list[dict] = field(default_factory=list)
    # Bot-local execution sandbox
    bot_sandbox: BotSandboxConfig = field(default_factory=BotSandboxConfig)
    # Unified workspace config
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    # Owner user (for user-scoped cross-bot memory)
    user_id: str | None = None  # UUID string of owner user
    # Shared workspace membership (populated from shared_workspace_bots junction)
    shared_workspace_id: str | None = None  # UUID string
    shared_workspace_role: str | None = None  # 'member' | 'orchestrator'
    shared_workspace_cwd: str | None = None  # resolved cwd override
    # Carapaces (composable skill+tool bundles)
    carapaces: list[str] = field(default_factory=list)
    # Context pruning (trim old tool results at assembly time)
    context_pruning: bool | None = None
    context_pruning_keep_turns: int | None = None
    # History mode: "file" (default) | "summary" | "structured"
    history_mode: str = "file"
    # Scoped API key permissions (populated from linked ApiKey)
    api_permissions: list[str] = field(default_factory=list)
    # How to inject API docs into context: "pinned"|"rag"|"on_demand"|None (disabled)
    api_docs_mode: str | None = None
    # Memory scheme: "workspace-files" = file-based memory (replaces DB memory/knowledge)
    memory_scheme: str | None = None
    # System prompt from workspace file
    system_prompt_workspace_file: bool = False
    system_prompt_write_protected: bool = False
    # Cached for three-tier indexing resolution (populated by load_bots)
    _workspace_raw: dict = field(default_factory=dict)
    _ws_indexing_config: dict | None = None

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
    # Shared workspace bots always have workspace enabled — the shared workspace
    # manages the container/root, so the bot-level toggle is irrelevant.
    _in_shared_ws = bool(getattr(row, "_sw_workspace_id", None))
    workspace_cfg = WorkspaceConfig(
        enabled=ws_raw.get("enabled", False) or _in_shared_ws,
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
            include_bots=ws_indexing_raw.get("include_bots", []),
            embedding_model=ws_indexing_raw.get("embedding_model"),
            segments=[
                IndexSegment(
                    path_prefix=seg["path_prefix"],
                    embedding_model=seg.get("embedding_model"),
                    patterns=seg.get("patterns"),
                    similarity_threshold=seg.get("similarity_threshold"),
                    top_k=seg.get("top_k"),
                    watch=seg.get("watch"),
                )
                for seg in ws_indexing_raw.get("segments", [])
                if isinstance(seg, dict) and "path_prefix" in seg
            ],
        ),
    )
    # Read user_id (UUID → string)
    _user_id = str(row.user_id) if getattr(row, "user_id", None) else None

    # Read shared workspace membership (set by load_bots via _shared_workspace_cache)
    _sw_id = getattr(row, "_sw_workspace_id", None)
    _sw_role = getattr(row, "_sw_role", None)
    _sw_cwd = getattr(row, "_sw_cwd_override", None)

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
        base_prompt=getattr(row, "base_prompt", True),
        context_compaction=row.context_compaction,
        compaction_interval=row.compaction_interval,
        compaction_keep_turns=row.compaction_keep_turns,
        compaction_model=row.compaction_model,
        memory_knowledge_compaction_prompt=row.memory_knowledge_compaction_prompt,
        compaction_prompt_template_id=str(row.compaction_prompt_template_id) if getattr(row, "compaction_prompt_template_id", None) else None,
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
        knowledge_max_inject_chars=row.knowledge_max_inject_chars,
        memory_max_inject_chars=row.memory_max_inject_chars,
        delegate_bots=list(row.delegation_config.get("delegate_bots", [])) if row.delegation_config else [],
        harness_access=list(row.delegation_config.get("harness_access", [])) if row.delegation_config else [],
        cross_workspace_access=bool(row.delegation_config.get("cross_workspace_access", False)) if row.delegation_config else False,
        model_params=row.model_params or {},
        elevation_enabled=row.elevation_enabled,
        elevation_threshold=row.elevation_threshold,
        elevated_model=row.elevated_model,
        model_provider_id=row.model_provider_id,
        fallback_models=row.fallback_models or [],
        bot_sandbox=bot_sandbox_cfg,
        workspace=workspace_cfg,
        user_id=_user_id,
        shared_workspace_id=str(_sw_id) if _sw_id else None,
        shared_workspace_role=_sw_role,
        carapaces=row.carapaces or [],
        context_pruning=getattr(row, "context_pruning", None),
        context_pruning_keep_turns=getattr(row, "context_pruning_keep_turns", None),
        history_mode=row.history_mode or "file",
        api_docs_mode=getattr(row, "api_docs_mode", None),
        memory_scheme=getattr(row, "memory_scheme", None),
        system_prompt_workspace_file=getattr(row, "system_prompt_workspace_file", False),
        system_prompt_write_protected=getattr(row, "system_prompt_write_protected", False),
        shared_workspace_cwd=_sw_cwd,
        _workspace_raw=ws_raw,
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
        "base_prompt": data.get("base_prompt", True),
        "context_compaction": data.get("context_compaction", True),
        "compaction_interval": data.get("compaction_interval"),
        "compaction_keep_turns": data.get("compaction_keep_turns"),
        "compaction_model": data.get("compaction_model"),
        "memory_knowledge_compaction_prompt": data.get("memory_knowledge_compaction_prompt"),
        "compaction_prompt_template_id": data.get("compaction_prompt_template_id"),
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
        "knowledge_max_inject_chars": data.get("knowledge_max_inject_chars"),
        "memory_max_inject_chars": data.get("memory_max_inject_chars"),
        "delegation_config": {
            "delegate_bots": data.get("delegate_bots", []),
            "harness_access": data.get("harness_access", []),
            "cross_workspace_access": data.get("cross_workspace_access", False),
        },
        "fallback_models": data.get("fallback_models", []),
        "workspace": data.get("workspace", {"enabled": False}),
        "carapaces": data.get("carapaces", []),
        "context_pruning": data.get("context_pruning"),
        "context_pruning_keep_turns": data.get("context_pruning_keep_turns"),
        "history_mode": data.get("history_mode", "file"),
        "memory_scheme": data.get("memory_scheme"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


SYSTEM_BOTS_DIR = Path(__file__).parent.parent / "data" / "system_bots"


async def seed_bots_from_yaml(bots_dir: Path = BOTS_DIR) -> None:
    """Seed bots from YAML files into DB — only if id doesn't already exist.

    Scans both the system bots directory (app/data/system_bots/) and the
    user bots directory (bots/).
    """
    source_dirs = [SYSTEM_BOTS_DIR, bots_dir]
    yaml_files: list[Path] = []
    for d in source_dirs:
        if d.exists():
            yaml_files.extend(d.glob("*.yaml"))

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
        # Load shared workspace memberships
        sw_rows = (await db.execute(select(SharedWorkspaceBot))).scalars().all()
        # Batch-fetch workspace indexing_config for cascade resolution
        ws_ids = {r.workspace_id for r in sw_rows}
        ws_indexing_map: dict[str, dict | None] = {}
        if ws_ids:
            from app.db.models import SharedWorkspace
            ws_objs = (await db.execute(
                select(SharedWorkspace.id, SharedWorkspace.indexing_config)
                .where(SharedWorkspace.id.in_(ws_ids))
            )).all()
            ws_indexing_map = {str(r.id): r.indexing_config for r in ws_objs}
    # Batch-fetch API key scopes for bots with api_key_id
    _api_key_scopes: dict[str, list[str]] = {}  # bot_id -> scopes
    _bot_key_ids = {row.id: row.api_key_id for row in rows if getattr(row, "api_key_id", None)}
    if _bot_key_ids:
        try:
            from app.db.models import ApiKey
            _key_ids = list(set(_bot_key_ids.values()))
            async with async_session() as _ak_db:
                _ak_rows = (await _ak_db.execute(
                    select(ApiKey.id, ApiKey.scopes, ApiKey.is_active)
                    .where(ApiKey.id.in_(_key_ids))
                )).all()
            _key_scope_map = {r.id: r.scopes for r in _ak_rows if r.is_active}
            for bot_id, key_id in _bot_key_ids.items():
                if key_id in _key_scope_map:
                    _api_key_scopes[bot_id] = _key_scope_map[key_id] or []
        except Exception:
            logger.warning("Failed to load API key scopes for bots", exc_info=True)

    sw_by_bot = {r.bot_id: r for r in sw_rows}
    for row in rows:
        # Attach shared workspace info as transient attributes
        sw = sw_by_bot.get(row.id)
        if sw:
            row._sw_workspace_id = sw.workspace_id
            row._sw_role = sw.role
            row._sw_cwd_override = sw.cwd_override
        else:
            row._sw_workspace_id = None
            row._sw_role = None
            row._sw_cwd_override = None
        bot = _bot_row_to_config(row)
        # Cache workspace-level indexing config for three-tier resolution
        if sw and sw.workspace_id:
            bot._ws_indexing_config = ws_indexing_map.get(str(sw.workspace_id))
        # Populate API permissions from linked key
        if row.id in _api_key_scopes:
            bot.api_permissions = _api_key_scopes[row.id]
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
