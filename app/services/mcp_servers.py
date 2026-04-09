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

    if not config_path.exists() or not config_path.is_file():
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


async def seed_from_integrations() -> None:
    """Seed MCP servers declared in integration manifests.

    Each integration.yaml can declare ``mcp_servers`` with either a ``url``
    (external, already running) or ``image`` (container, admin runs manually
    in v1).  Entries are inserted with ``source = 'integration:<id>'``.
    Uses ON CONFLICT DO NOTHING — never overwrites existing entries.
    """
    import os
    import re

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.engine import async_session
    from app.db.models import MCPServer
    from app.services.encryption import encrypt
    from app.services.integration_manifests import get_all_manifests
    from app.services.integration_settings import get_value as get_setting

    def _interpolate(template: str, integration_id: str) -> str:
        """Replace ${VAR} references with DB settings → env var fallback."""
        def _resolve(m: re.Match) -> str:
            key = m.group(1)
            return get_setting(integration_id, key) or os.environ.get(key, "")
        return re.sub(r"\$\{([^}]+)\}", _resolve, template)

    manifests = get_all_manifests()
    seeded = 0

    async with async_session() as db:
        for integration_id, manifest in manifests.items():
            mcp_servers = manifest.get("mcp_servers")
            if not mcp_servers or not isinstance(mcp_servers, list):
                continue

            for srv in mcp_servers:
                if not isinstance(srv, dict) or "id" not in srv:
                    logger.warning(
                        "Integration '%s' has MCP server entry without 'id' — skipping",
                        integration_id,
                    )
                    continue

                server_id = srv["id"]
                url = _interpolate(srv.get("url", ""), integration_id)
                display_name = srv.get("display_name", server_id)

                # Resolve API key from env var reference
                api_key_env = srv.get("api_key_env")
                raw_key = get_setting(integration_id, api_key_env) if api_key_env else ""
                if not raw_key and api_key_env:
                    raw_key = os.environ.get(api_key_env, "")
                api_key = encrypt(raw_key) if raw_key else None

                # Store image/port/env info in config for future container management
                config: dict = {}
                for ckey in ("image", "port", "env", "config"):
                    if ckey in srv:
                        if ckey == "config":
                            config.update(srv[ckey])
                        else:
                            config[ckey] = srv[ckey]

                stmt = pg_insert(MCPServer).values(
                    id=server_id,
                    display_name=display_name,
                    url=url,
                    api_key=api_key,
                    is_enabled=bool(url),  # only enable if URL is set
                    config=config,
                    source=f"integration:{integration_id}",
                    source_path=manifest.get("source_path"),
                ).on_conflict_do_nothing(index_elements=["id"])
                await db.execute(stmt)
                seeded += 1

        await db.commit()

    if seeded:
        logger.info("Seeded %d MCP server(s) from integration manifests", seeded)


def list_server_names() -> list[str]:
    """Return sorted list of available MCP server IDs from the in-memory registry."""
    return sorted(_servers.keys())
