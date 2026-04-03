"""MCP Server CRUD + test: /mcp-servers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, MCPServer as MCPServerRow
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MCPServerOut(BaseModel):
    id: str
    display_name: str
    url: str
    is_enabled: bool = True
    has_api_key: bool = False
    config: dict = {}
    source: str = "manual"
    source_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MCPServerCreateIn(BaseModel):
    id: str
    display_name: str
    url: str
    api_key: Optional[str] = None
    is_enabled: bool = True
    config: dict = {}


class MCPServerUpdateIn(BaseModel):
    display_name: Optional[str] = None
    url: Optional[str] = None
    api_key: Optional[str] = None
    is_enabled: Optional[bool] = None
    config: Optional[dict] = None


class MCPServerTestResult(BaseModel):
    ok: bool
    message: str
    tool_count: int = 0
    tools: list[str] = []


class MCPServerTestInlineIn(BaseModel):
    url: str
    api_key: Optional[str] = None


def _server_to_out(row: MCPServerRow) -> MCPServerOut:
    return MCPServerOut(
        id=row.id,
        display_name=row.display_name,
        url=row.url,
        is_enabled=row.is_enabled,
        has_api_key=bool(row.api_key),
        config=row.config or {},
        source=row.source,
        source_path=row.source_path,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/mcp-servers", response_model=list[MCPServerOut])
async def admin_list_mcp_servers(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    rows = (
        await db.execute(select(MCPServerRow).order_by(MCPServerRow.created_at))
    ).scalars().all()
    return [_server_to_out(r) for r in rows]


@router.get("/mcp-servers/{server_id}", response_model=MCPServerOut)
async def admin_get_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    row = await db.get(MCPServerRow, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_out(row)


@router.post("/mcp-servers", response_model=MCPServerOut, status_code=201)
async def admin_create_mcp_server(
    body: MCPServerCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    sid = body.id.strip()
    if not sid or not body.display_name.strip() or not body.url.strip():
        raise HTTPException(status_code=422, detail="id, display_name, and url are required")

    existing = await db.get(MCPServerRow, sid)
    if existing:
        raise HTTPException(status_code=409, detail=f"MCP server '{sid}' already exists")

    from app.services.encryption import encrypt

    api_key_value = body.api_key.strip() if body.api_key else None
    if api_key_value:
        api_key_value = encrypt(api_key_value)

    now = datetime.now(timezone.utc)
    row = MCPServerRow(
        id=sid,
        display_name=body.display_name.strip(),
        url=body.url.strip(),
        api_key=api_key_value,
        is_enabled=body.is_enabled,
        config=body.config,
        source="manual",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        import logging as _log
        _log.getLogger(__name__).exception("MCP server create failed")
        raise HTTPException(status_code=400, detail="Failed to create MCP server. Check server logs for details.")

    await _reload_mcp()
    return _server_to_out(row)


@router.put("/mcp-servers/{server_id}", response_model=MCPServerOut)
async def admin_update_mcp_server(
    server_id: str,
    body: MCPServerUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    row = await db.get(MCPServerRow, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    from app.services.encryption import encrypt

    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.url is not None:
        row.url = body.url.strip()
    if body.api_key is not None:
        raw_key = body.api_key.strip() or None
        row.api_key = encrypt(raw_key) if raw_key else None
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    if body.config is not None:
        row.config = body.config

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    await _reload_mcp()
    return _server_to_out(row)


@router.delete("/mcp-servers/{server_id}")
async def admin_delete_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    # Check if any bots reference this server
    bot_rows = (await db.execute(select(BotRow))).scalars().all()
    bots_using = [b.id for b in bot_rows if server_id in (b.mcp_servers or [])]
    if bots_using:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: referenced by bots {', '.join(bots_using)}",
        )

    row = await db.get(MCPServerRow, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    await db.delete(row)
    await db.commit()

    await _reload_mcp()
    return {"ok": True}


@router.post("/mcp-servers/{server_id}/test", response_model=MCPServerTestResult)
async def admin_test_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    row = await db.get(MCPServerRow, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    from app.services.encryption import decrypt

    api_key = decrypt(row.api_key) if row.api_key else ""
    return await _test_mcp_connection(row.url, api_key)


@router.post("/mcp-servers/test-inline", response_model=MCPServerTestResult)
async def admin_test_mcp_server_inline(
    body: MCPServerTestInlineIn,
    _auth: str = Depends(verify_auth_or_user),
):
    return await _test_mcp_connection(body.url.strip(), (body.api_key or "").strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _reload_mcp() -> None:
    """Reload MCP servers from DB and clear tool cache."""
    from app.services.mcp_servers import load_mcp_servers
    from app.tools.mcp import _cache

    await load_mcp_servers()
    _cache.clear()


async def _test_mcp_connection(url: str, api_key: str) -> MCPServerTestResult:
    """Fetch tools/list from an MCP server and return results."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                url,
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
                headers=headers,
            )
            if resp.status_code != 200:
                return MCPServerTestResult(
                    ok=False,
                    message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                from app.tools.mcp import _parse_sse_json
                data = _parse_sse_json(resp.text)
            else:
                data = resp.json()

            tools = data.get("result", {}).get("tools", [])
            tool_names = [t.get("name", "") for t in tools]
            return MCPServerTestResult(
                ok=True,
                message=f"Connected ({len(tools)} tools)",
                tool_count=len(tools),
                tools=tool_names,
            )
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("MCP connection test failed: %s", exc)
        return MCPServerTestResult(ok=False, message="Connection failed. Check server logs for details.")
