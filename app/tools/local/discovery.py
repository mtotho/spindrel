"""Tool discovery tools — look up schemas and manage the persistent tool working set."""
import json
import logging

from app.agent.context import current_bot_id
from app.tools.registry import _tools, register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_tool_info",
        "description": (
            "Look up a tool by name, enroll it into your persistent working set, and "
            "activate it for this turn. Returns the full OpenAI function schema AND "
            "adds the tool to your callable tools for the next iteration, so you can "
            "invoke it immediately after. The enrollment persists across turns, so you "
            "won't need to re-fetch the schema next time. Use this when you see a tool "
            "listed in the 'available tools (not yet loaded)' index."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The exact name of the tool to look up.",
                },
            },
            "required": ["tool_name"],
        },
    },
}, requires_bot_context=True, tool_metadata={
    "domains": ["tool_schema"],
    "intent_tags": ["load tool schema", "tool enrollment", "tool activation"],
    "exposure": "ambient",
    "auto_inject": ["tool_retrieval"],
}, returns={
    "type": "object",
    "properties": {
        "schema": {"type": "object", "description": "OpenAI function-call input schema"},
        "output_schema": {"type": ["object", "null"], "description": "JSON Schema for the tool's return shape (when declared)"},
        "safety_tier": {"type": "string"},
        "execution_policy": {"type": "string"},
        "tool_name": {"type": "string"},
        "server_name": {"type": "string", "description": "Set for MCP tools"},
        "error": {"type": "string"},
    },
})
async def get_tool_info(tool_name: str) -> str:
    """Return the full OpenAI function schema for a tool, enroll it, and activate it.

    Three effects on success:
      1. Returns the schema so the LLM can see what args to pass.
      2. Activates the tool on ``current_activated_tools`` so the next loop
         iteration gets it merged into ``tools_param`` (callable immediately).
      3. Enrolls the tool in ``bot_tool_enrollment`` with source='fetched' so
         future turns see it as pinned in the working set — the bot doesn't
         need to re-call ``get_tool_info`` for the same tool ever again.
    """
    schema_for_activation: dict | None = None
    response_json: str

    entry = _tools.get(tool_name)
    if entry is not None:
        schema_for_activation = entry["schema"]
        # Include the declared return schema (if any) so the model knows what
        # field names to access in the parsed result. Load-bearing for
        # programmatic tool composition via run_script.
        payload = {
            "schema": schema_for_activation,
            "output_schema": entry.get("returns"),
            "safety_tier": entry.get("safety_tier"),
            "execution_policy": entry.get("execution_policy", "normal"),
        }
        response_json = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        # Also check tool_embeddings DB for MCP tools
        from app.db.engine import async_session
        from app.db.models import ToolEmbedding
        from sqlalchemy import select
        async with async_session() as db:
            row = (await db.execute(
                select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_name)
            )).scalar_one_or_none()
            if row is None:
                # Forgiving fallback: LiteLLM's MCP gateway namespaces tools as
                # "<server>-<tool>" and small models drop the prefix. Try
                # resolving the bare name to a prefixed MCP tool before failing.
                from app.tools.mcp import resolve_mcp_tool_name
                _resolved = resolve_mcp_tool_name(tool_name)
                if _resolved and _resolved != tool_name:
                    logger.info("get_tool_info: resolved bare %r -> %r", tool_name, _resolved)
                    tool_name = _resolved
                    row = (await db.execute(
                        select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_name)
                    )).scalar_one_or_none()
        if row is None:
            return json.dumps({"error": f"Tool {tool_name!r} not found."}, ensure_ascii=False)
        schema_for_activation = row.schema_ if isinstance(row.schema_, dict) else None
        response_json = json.dumps({
            "tool_name": tool_name,
            "server_name": row.server_name,
            "schema": row.schema_,
        }, indent=2, ensure_ascii=False)

    # Activate the tool for the next loop iteration. The agent loop owns the
    # actual tools_param rebuild and authorization set expansion; we just
    # append the schema so it picks it up.
    if schema_for_activation is not None:
        try:
            from app.agent.context import current_activated_tools
            _active = current_activated_tools.get()
            if _active is not None:
                _existing = {
                    (t.get("function") or {}).get("name")
                    for t in _active
                    if isinstance(t, dict)
                }
                fn_name = (schema_for_activation.get("function") or {}).get("name")
                if fn_name and fn_name not in _existing:
                    _active.append(schema_for_activation)
                    logger.info("get_tool_info: activated %r for next iteration", fn_name)
        except Exception:
            logger.exception("get_tool_info: failed to activate %r", tool_name)

    # Enroll into the bot's persistent working set. Mirrors get_skill() — the
    # act of asking for the schema is a strong "I want this tool" signal, and
    # relying on the post-call enrollment in loop.py means a failed-args call
    # or a re-plan keeps the bot stuck re-fetching the same schema every turn.
    bot_id = current_bot_id.get()
    if bot_id:
        try:
            from app.services.tool_enrollment import enroll as _enroll_tool
            await _enroll_tool(bot_id, tool_name, source="fetched")
        except Exception:
            logger.warning(
                "Failed to enroll %s into working set for bot %s",
                tool_name, bot_id, exc_info=True,
            )

    return response_json


_TOOL_PRUNE_PROTECTION_DAYS = 7


@register({
    "type": "function",
    "function": {
        "name": "prune_enrolled_tools",
        "description": (
            "Remove tools from your persistent enrolled working set. The tools "
            "stay available in the catalog and will be re-enrolled on next "
            "successful use. Use this in memory hygiene runs to drop tools you "
            "don't actively use — their slot in your working set will be freed "
            "and the semantic discovery layer will resurface them only when a "
            "user message is relevant. Tools enrolled less than 7 days ago and "
            "tools listed in your bot's pinned_tools require an explicit override "
            "reason."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names to unenroll from this bot's working set",
                },
                "overrides": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Override reasons for protected tools. Map of tool_name to reason string. "
                        "Required for pinned tools or recently-enrolled tools (<7d). "
                        "Example reasons: 'user unpinned', 'replaced by X', 'capability deprecated'."
                    ),
                },
            },
            "required": ["tool_names"],
        },
    },
}, requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "removed": {"type": "integer"},
        "blocked": {"type": "integer"},
        "requested": {"type": "integer"},
        "message": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def prune_enrolled_tools(
    tool_names: list[str],
    overrides: dict[str, str] | None = None,
) -> str:
    """Remove the listed tools from this bot's persistent enrollment.

    Protected tools (pinned on the bot, or enrolled < 7 days ago) require an
    override reason. The unenroll batch is partial-allowed: protected names
    without overrides are reported as ``blocked`` and the rest are pruned.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import Bot, BotToolEnrollment
    from app.services.tool_enrollment import unenroll_many

    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "no bot context"}, ensure_ascii=False)
    if not tool_names:
        return json.dumps({"error": "no tool names provided"}, ensure_ascii=False)

    overrides = overrides or {}

    now = datetime.now(timezone.utc)
    protection_cutoff = now - timedelta(days=_TOOL_PRUNE_PROTECTION_DAYS)

    async with async_session() as db:
        enrollment_rows = (await db.execute(
            select(
                BotToolEnrollment.tool_name,
                BotToolEnrollment.source,
                BotToolEnrollment.enrolled_at,
            ).where(
                BotToolEnrollment.bot_id == bot_id,
                BotToolEnrollment.tool_name.in_(tool_names),
            )
        )).all()
        bot_row = await db.get(Bot, bot_id)

    enrollments_by_name = {r.tool_name: r for r in enrollment_rows}
    pinned_set: set[str] = set()
    if bot_row is not None:
        pinned_value = getattr(bot_row, "pinned_tools", None) or []
        if isinstance(pinned_value, list):
            pinned_set = {str(p) for p in pinned_value if p}

    allowed: list[str] = []
    blocked: list[dict] = []
    overridden: list[dict] = []

    for name in tool_names:
        is_pinned = name in pinned_set
        enrollment = enrollments_by_name.get(name)
        is_recent = False
        age_days: int | None = None
        if enrollment is not None:
            enrolled_at = enrollment.enrolled_at
            if enrolled_at.tzinfo is None:
                enrolled_at = enrolled_at.replace(tzinfo=timezone.utc)
            is_recent = enrolled_at > protection_cutoff
            age_days = (now - enrolled_at).days

        if is_pinned or is_recent:
            reason = overrides.get(name)
            entry = {
                "tool_name": name,
                "pinned": is_pinned,
                "recent": is_recent,
                "age_days": age_days,
            }
            if reason:
                entry["reason"] = reason
                overridden.append(entry)
                allowed.append(name)
            else:
                protection_reason = []
                if is_pinned:
                    protection_reason.append("pinned")
                if is_recent:
                    protection_reason.append(
                        f"enrolled {age_days}d ago (<{_TOOL_PRUNE_PROTECTION_DAYS}d)"
                    )
                entry["reason_needed"] = ", ".join(protection_reason)
                blocked.append(entry)
        else:
            allowed.append(name)

    if overridden:
        try:
            import asyncio

            from app.agent.context import current_correlation_id, current_session_id
            from app.agent.recording import _record_trace_event
            for ov in overridden:
                asyncio.create_task(_record_trace_event(
                    correlation_id=current_correlation_id.get(),
                    session_id=current_session_id.get(),
                    bot_id=bot_id,
                    client_id=None,
                    event_type="tool_prune_override",
                    event_name=ov["tool_name"],
                    data=ov,
                ))
        except Exception:
            logger.debug("Failed to record tool_prune_override trace events", exc_info=True)

    removed = 0
    if allowed:
        try:
            removed = await unenroll_many(bot_id, allowed)
        except Exception as exc:
            logger.exception("prune_enrolled_tools failed for bot %s", bot_id)
            return json.dumps(
                {"error": f"Failed to prune enrollments: {exc}", "removed": 0, "blocked": len(blocked)},
                ensure_ascii=False,
            )

    parts: list[str] = []
    if removed:
        parts.append(f"Pruned {removed} enrollment(s)")
    if blocked:
        protected_list = "; ".join(
            f"{b['tool_name']} ({b['reason_needed']})" for b in blocked
        )
        parts.append(
            f"{len(blocked)} blocked (need override): {protected_list}"
        )
    if not parts:
        parts.append(f"No matching enrollments to remove ({len(tool_names)} requested)")

    return json.dumps(
        {
            "removed": removed,
            "blocked": len(blocked),
            "requested": len(tool_names),
            "message": ". ".join(parts) + ".",
        },
        ensure_ascii=False,
    )


@register({
    "type": "function",
    "function": {
        "name": "search_tools",
        "description": (
            "Semantically search the full tool pool by a natural-language query. "
            "Use this when you think a tool should exist for the user's request but "
            "don't see it in your currently-loaded tools. Returns a ranked list of "
            "candidate tool names + one-line descriptions; call get_tool_info(tool_name=...) "
            "to load the full schema of any match."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Describe the capability you want (e.g. 'search the web', 'read a PDF').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max candidates to return (default 10).",
                },
            },
            "required": ["query"],
        },
    },
}, tool_metadata={
    "domains": ["tool_discovery"],
    "intent_tags": ["load tool schema", "tool enrollment", "tool discovery"],
    "exposure": "ambient",
}, returns={
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "similarity": {"type": "number"},
                },
                "required": ["name", "description", "similarity"],
            },
        },
        "hint": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def search_tools(query: str, limit: int = 10) -> str:
    """Semantic search across the full tool pool.

    Delegates to retrieve_tools(discover_all=True) with a low threshold so weak-model
    queries still surface candidates. Does NOT activate tools — the LLM must follow
    up with get_tool_info on a chosen name.
    """
    from app.agent.tools import retrieve_tools

    if not query or not query.strip():
        return json.dumps({"error": "query is required"}, ensure_ascii=False)
    try:
        n = max(1, min(int(limit or 10), 25))
    except (TypeError, ValueError):
        n = 10

    try:
        tools, _best_sim, candidates = await retrieve_tools(
            query.strip(),
            [], [],  # no declared — search the whole pool via discover_all
            top_k=n,
            threshold=0.2,  # loose: weak-model queries often score low
            discover_all=True,
        )
    except Exception as exc:
        logger.exception("search_tools failed for query=%r", query[:80])
        return json.dumps({"error": f"Search failed: {exc}"}, ensure_ascii=False)

    sim_by_name = {c["name"]: c["sim"] for c in candidates if isinstance(c, dict)}
    matches: list[dict] = []
    for t in tools[:n]:
        fn = t.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        matches.append({
            "name": name,
            "description": (fn.get("description") or "").strip().split("\n", 1)[0][:200],
            "similarity": round(sim_by_name.get(name, 0.0), 4),
        })

    return json.dumps({
        "query": query,
        "matches": matches,
        "hint": (
            "Call get_tool_info(tool_name=<name>) to load a match's full schema; "
            "it will become callable on the next turn."
        ) if matches else "No tools matched above the loose similarity floor (0.2).",
    }, ensure_ascii=False, indent=2)


def _summarize_returns(returns: dict | None) -> str:
    """Render a one-line summary of a tool's return shape for catalog browsing."""
    if not isinstance(returns, dict):
        return "?"
    t = returns.get("type")
    if t == "object":
        props = returns.get("properties") or {}
        if not props:
            return "{}"
        keys = list(props.keys())[:6]
        more = "" if len(props) <= 6 else f", +{len(props) - 6} more"
        return "{" + ", ".join(keys) + more + "}"
    if t == "array":
        items = returns.get("items") or {}
        return f"[{_summarize_returns(items)}]"
    if isinstance(t, list):
        return "|".join(t)
    return str(t or "?")


def _summarize_params(parameters: dict | None) -> str:
    """Render a compact ``required, [optional]`` parameter summary."""
    if not isinstance(parameters, dict):
        return ""
    props = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])
    parts: list[str] = []
    for name in props.keys():
        parts.append(name if name in required else f"[{name}]")
    return ", ".join(parts)


@register({
    "type": "function",
    "function": {
        "name": "list_tool_signatures",
        "description": (
            "Browse the catalog of tools you can call programmatically — returns "
            "compact `name(params) -> {return shape}` lines. Use this BEFORE "
            "writing a run_script body so you know what fields each tool returns. "
            "Filter by category (substring match against tool name or source "
            "integration). Cheaper than calling get_tool_info on every candidate. "
            "Only tools with a declared return schema are listed — those are the "
            "ones safe to compose programmatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Optional substring filter — matches against tool name "
                        "OR source integration id. Example: 'channel', 'slack', "
                        "'search'. Omit to list all composable tools."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max signatures to return (default 50, max 200).",
                },
            },
            "required": [],
        },
    },
}, tool_metadata={
    "domains": ["programmatic_tool_calling"],
    "intent_tags": ["tool signatures", "return schemas", "script composition"],
    "exposure": "explicit",
}, returns={
    "type": "object",
    "properties": {
        "category": {"type": ["string", "null"]},
        "count": {"type": "integer"},
        "signatures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "params": {"type": "string"},
                    "returns": {"type": "string"},
                    "description": {"type": "string"},
                    "safety_tier": {"type": "string"},
                    "execution_policy": {"type": "string"},
                    "source_integration": {"type": ["string", "null"]},
                },
                "required": ["name", "params", "returns"],
            },
        },
        "hint": {"type": "string"},
    },
    "required": ["count", "signatures"],
})
async def list_tool_signatures(category: str | None = None, limit: int = 50) -> str:
    """Compact catalog of tools that declare a return schema."""
    try:
        n = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        n = 50

    needle = (category or "").strip().lower()
    out: list[dict] = []
    for name, entry in _tools.items():
        returns = entry.get("returns")
        if not returns:
            continue  # only composable tools — others have unknown shapes
        integration = entry.get("source_integration") or ""
        if needle:
            if needle not in name.lower() and needle not in integration.lower():
                continue
        schema = entry.get("schema") or {}
        fn = (schema.get("function") or {})
        out.append({
            "name": name,
            "params": _summarize_params(fn.get("parameters")),
            "returns": _summarize_returns(returns),
            "description": (fn.get("description") or "").strip().split("\n", 1)[0][:160],
            "safety_tier": entry.get("safety_tier", "readonly"),
            "execution_policy": entry.get("execution_policy", "normal"),
            "source_integration": entry.get("source_integration"),
        })
        if len(out) >= n:
            break

    return json.dumps({
        "category": category,
        "count": len(out),
        "signatures": out,
        "hint": (
            "Call get_tool_info(tool_name=<name>) for the full input/output JSON "
            "Schema. To compose multiple tools in one round-trip, use run_script "
            "and call them as `tools.NAME(**kwargs)` from Python."
        ),
    }, ensure_ascii=False, indent=2)
