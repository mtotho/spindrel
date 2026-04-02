"""MCP server registry: DB-backed config with YAML seeding."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.tools.mcp import MCPServerConfig, _servers

logger = logging.getLogger(__name__)


async def load_mcp_servers() -> None:
    """Load all enabled MCP servers from DB into the in-memory _servers dict."""
    from app.db.engine import async_session
    from app.db.models import MCPServer
    from app.services.encryption import decrypt

    _servers.clear()

    async with async_session() as db:
        rows = (
            await db.execute(select(MCPServer).where(MCPServer.is_enabled == True))  # noqa: E712
        ).scalars().all()

    for row in rows:
        api_key = decrypt(row.api_key) if row.api_key else ""
        _servers[row.id] = MCPServerConfig(
            name=row.id,
            url=row.url,
            api_key=api_key,
        )

    logger.info("Loaded %d MCP server(s) from DB", len(_servers))


async def seed_from_yaml(config_path: Path = Path("mcp.yaml")) -> None:
    """One-time migration: if mcp_servers table is empty and mcp.yaml exists, seed from file."""
    import yaml

    from app.db.engine import async_session
    from app.db.models import MCPServer
    from app.services.encryption import encrypt
    from app.tools.mcp import _resolve_env_vars

    if not config_path.exists():
        logger.info("No mcp.yaml at %s, skipping seed", config_path)
        return

    async with async_session() as db:
        count = (
            await db.execute(select(MCPServer))
        ).scalars().first()
        if count is not None:
            logger.info("MCP servers table already populated, skipping YAML seed")
            return

        with open(config_path) as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            logger.warning("mcp.yaml at %s is empty or invalid", config_path)
            return

        seeded = 0
        for name, conf in data.items():
            if not isinstance(conf, dict) or "url" not in conf:
                logger.warning("MCP server '%s' missing 'url' in YAML, skipping", name)
                continue

            url = _resolve_env_vars(str(conf["url"]))
            raw_key = _resolve_env_vars(str(conf.get("api_key", "")))
            api_key = encrypt(raw_key) if raw_key else None

            server = MCPServer(
                id=name,
                display_name=name,
                url=url,
                api_key=api_key,
                is_enabled=True,
                source="file",
                source_path=str(config_path),
            )
            db.add(server)
            seeded += 1

        await db.commit()
        logger.info("Seeded %d MCP server(s) from %s", seeded, config_path)


def list_server_names() -> list[str]:
    """Return sorted list of available MCP server IDs from the in-memory registry."""
    return sorted(_servers.keys())
