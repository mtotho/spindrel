"""Loose per-turn context / token estimates for admin UI (not exact; RAG-dependent parts are heuristic)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.config import settings
from sqlalchemy import func as sa_func

from app.db.engine import async_session
from app.db.models import Skill as SkillRow, ToolEmbedding


def _schema_json_chars(schema: dict[str, Any]) -> int:
    return len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class EstimateLine:
    label: str
    chars: int
    hint: str = ""


@dataclass
class ContextEstimateResult:
    lines: list[EstimateLine]
    total_chars: int
    approx_tokens: int
    disclaimer: str


def _parse_skill_entries(raw_skills: list) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse structured skill entries into (pinned, rag, on_demand) lists of dicts."""
    pinned, rag, on_demand = [], [], []
    for e in raw_skills:
        if isinstance(e, str):
            on_demand.append({"id": e, "mode": "on_demand"})
        elif isinstance(e, dict):
            mode = e.get("mode", "on_demand")
            if mode == "pinned":
                pinned.append(e)
            elif mode == "rag":
                rag.append(e)
            else:
                on_demand.append(e)
        else:
            on_demand.append({"id": str(e), "mode": "on_demand"})
    return pinned, rag, on_demand


async def _skill_index_chars(db, skill_ids: list[str]) -> tuple[int, int]:
    """Return (chars, n_skills) for the skill index system message."""
    if not skill_ids:
        return 0, 0
    rows = (
        await db.execute(
            select(SkillRow.id, SkillRow.name).where(SkillRow.id.in_(skill_ids))
        )
    ).all()
    if not rows:
        return 0, 0
    header = len("Available skills (use get_skill to retrieve full content):\n")
    body = sum(len(f"- {r.id}: {r.name}\n") for r in rows)
    return header + body, len(rows)


async def _pinned_skill_chars(db, skill_ids: list[str]) -> int:
    """Return estimated chars for pinned skills (full content injected)."""
    if not skill_ids:
        return 0
    result = await db.execute(
        select(sa_func.sum(sa_func.length(SkillRow.content)))
        .where(SkillRow.id.in_(skill_ids))
    )
    total = result.scalar() or 0
    wrap = len("Pinned skill context:\n\n") + len("\n\n---\n\n") * max(0, len(skill_ids) - 1)
    return wrap + total


def _rag_retrieval_factor(tool_threshold: float) -> float:
    """Higher threshold ⇒ fewer tools pass cosine filter ⇒ smaller estimate."""
    return _clamp((1.0 - tool_threshold) * 1.05, 0.15, 0.92)


def _memory_knowledge_hit_factor(similarity_threshold: float) -> float:
    """Higher similarity threshold ⇒ stricter match ⇒ fewer chunks."""
    return _clamp(1.05 - similarity_threshold + 0.35, 0.22, 0.95)


async def estimate_bot_context(
    *,
    draft: dict[str, Any],
    bot_id: str,
) -> ContextEstimateResult:
    """Draft keys mirror the bot edit form / JSON body from the admin estimator."""
    _ = bot_id  # reserved for future client/bot-scoped stats
    from app.agent.bots import get_bot as _get_bot
    from app.tools.client_tools import get_client_tool_schemas
    from app.tools.registry import get_local_tool_schemas

    system_prompt = (draft.get("system_prompt") or "").strip()
    persona_on = bool(draft.get("persona"))
    persona_content = (draft.get("persona_content") or "").strip()
    local_tools = list(draft.get("local_tools") or [])
    mcp_servers = list(draft.get("mcp_servers") or [])
    client_tools = list(draft.get("client_tools") or [])
    pinned_raw = list(draft.get("pinned_tools") or [])
    skills_raw = list(draft.get("skills") or [])
    tool_retrieval = bool(draft.get("tool_retrieval", True))
    tool_th = draft.get("tool_similarity_threshold")
    try:
        tool_threshold = float(tool_th) if tool_th is not None and str(tool_th).strip() != "" else settings.TOOL_RETRIEVAL_THRESHOLD
    except (TypeError, ValueError):
        tool_threshold = settings.TOOL_RETRIEVAL_THRESHOLD

    mem_enabled = bool(draft.get("memory_enabled"))
    try:
        mem_sim = float(draft.get("memory_similarity_threshold", settings.MEMORY_SIMILARITY_THRESHOLD))
    except (TypeError, ValueError):
        mem_sim = settings.MEMORY_SIMILARITY_THRESHOLD
    try:
        mem_max = int(draft.get("memory_max_inject_chars") or settings.MEMORY_MAX_INJECT_CHARS)
    except (TypeError, ValueError):
        mem_max = settings.MEMORY_MAX_INJECT_CHARS

    know_enabled = bool(draft.get("knowledge_enabled"))
    know_sim = settings.KNOWLEDGE_SIMILARITY_THRESHOLD
    try:
        know_max = int(draft.get("knowledge_max_inject_chars") or settings.KNOWLEDGE_MAX_INJECT_CHARS)
    except (TypeError, ValueError):
        know_max = settings.KNOWLEDGE_MAX_INJECT_CHARS

    fs_indexes = draft.get("filesystem_indexes") or []
    if isinstance(fs_indexes, str):
        try:
            fs_indexes = json.loads(fs_indexes or "[]")
        except json.JSONDecodeError:
            fs_indexes = []

    audio_input = (draft.get("audio_input") or "transcribe").strip()
    delegation = draft.get("delegation_config") or {}
    if isinstance(delegation, str):
        try:
            delegation = json.loads(delegation or "{}")
        except json.JSONDecodeError:
            delegation = {}
    delegate_bots = list(delegation.get("delegate_bots") or [])

    lines: list[EstimateLine] = []

    # --- base prompt (universal platform preamble) ---
    from app.agent.base_prompt import render_base_prompt
    from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, SkillConfig
    _draft_bot = BotConfig(
        id=bot_id, name=draft.get("name", bot_id), model=draft.get("model", ""),
        system_prompt=system_prompt,
        skills=[SkillConfig(id=e["id"] if isinstance(e, dict) else e) for e in skills_raw],
        memory=MemoryConfig(enabled=mem_enabled),
        knowledge=KnowledgeConfig(enabled=know_enabled),
        delegate_bots=delegate_bots,
        base_prompt=bool(draft.get("base_prompt", True)),
    )
    # Global base prompt (server-level, prepended before everything)
    if settings.GLOBAL_BASE_PROMPT:
        lines.append(EstimateLine("sys:global_base_prompt", len(settings.GLOBAL_BASE_PROMPT), "server-wide prompt prepended before all base/system prompts"))

    _base = render_base_prompt(_draft_bot)
    if _base:
        lines.append(EstimateLine("sys:base_prompt", len(_base), "universal platform prompt"))

    # --- datetime system line (loop.py) ---
    dt_chars = 72
    lines.append(EstimateLine("sys:datetime", dt_chars, "timezone + local/utc line"))

    # --- system prompt (may be duplicated in some clients; count once) ---
    sp_chars = len(system_prompt)
    lines.append(EstimateLine("sys:system_prompt", sp_chars, "main system prompt"))

    if persona_on and persona_content:
        lines.append(EstimateLine("sys:persona", len("[PERSONA]\n") + len(persona_content), "injected in session bootstrap"))

    async with async_session() as db:
        _pinned_s, _rag_s, _on_demand_s = _parse_skill_entries(skills_raw)

        # Pinned skills: full content every turn
        if _pinned_s:
            _pinned_ids = [e["id"] for e in _pinned_s]
            _p_chars = await _pinned_skill_chars(db, _pinned_ids)
            if _p_chars:
                lines.append(EstimateLine("sys:skill_pinned", _p_chars, f"{len(_pinned_ids)} pinned skill(s)"))

        # RAG skills: heuristic
        if _rag_s:
            _rag_thresholds = [e.get("similarity_threshold") or settings.RAG_SIMILARITY_THRESHOLD for e in _rag_s]
            _avg_th = sum(_rag_thresholds) / len(_rag_thresholds)
            _rag_h = _memory_knowledge_hit_factor(_avg_th)
            _est_rag = int(settings.RAG_TOP_K * 1200 * 0.45 * _rag_h)
            _wrap = len("Relevant skill context:\n\n---\n\n")
            lines.append(EstimateLine("sys:skill_rag", _wrap + _est_rag, f"{len(_rag_s)} RAG skill(s); varies by query"))

        # On-demand skills: index only
        _od_ids = [e["id"] for e in _on_demand_s]
        sk_chars, sk_n = await _skill_index_chars(db, _od_ids)
        if sk_chars:
            lines.append(EstimateLine("sys:skill_index", sk_chars, f"{sk_n} on-demand skill(s) listed"))

        # Tool schema sizes: local + client from live schemas; MCP from tool_embeddings
        by_name: dict[str, dict[str, Any]] = {}
        tool_server: dict[str, str | None] = {}

        for t in get_local_tool_schemas(local_tools):
            fn = t.get("function") or {}
            n = fn.get("name")
            if n:
                by_name[n] = t
                tool_server[n] = None

        for t in get_client_tool_schemas(client_tools):
            fn = t.get("function") or {}
            n = fn.get("name")
            if n:
                by_name[n] = t
                tool_server[n] = None

        need_get_skill = bool(skills_raw) and "get_skill" not in by_name
        if need_get_skill:
            for t in get_local_tool_schemas(["get_skill"]):
                fn = t.get("function") or {}
                n = fn.get("name")
                if n:
                    by_name[n] = t
                    tool_server[n] = None

        mcp_set = set(mcp_servers)
        if mcp_servers:
            stmt = select(ToolEmbedding.tool_name, ToolEmbedding.server_name, ToolEmbedding.schema_).where(
                ToolEmbedding.server_name.in_(mcp_servers)
            )
            mcp_rows = (await db.execute(stmt)).all()
            for tool_name, server_name, schema_obj in mcp_rows:
                if not isinstance(schema_obj, dict):
                    continue
                by_name[tool_name] = schema_obj
                tool_server[tool_name] = server_name
        # Fill missing local tools from DB embed table if present
        missing_local = [n for n in local_tools if n not in by_name]
        if missing_local:
            stmt = (
                select(ToolEmbedding.tool_name, ToolEmbedding.schema_)
                .where(ToolEmbedding.server_name.is_(None), ToolEmbedding.tool_name.in_(missing_local))
            )
            for tool_name, schema_obj in (await db.execute(stmt)).all():
                if isinstance(schema_obj, dict):
                    by_name[tool_name] = schema_obj
                    tool_server[tool_name] = None

        name_to_chars = {n: _schema_json_chars(s) for n, s in by_name.items()}

        client_name_set = set(client_tools)

        def expand_pins(pins: list[str]) -> set[str]:
            out: set[str] = set()
            for p in pins:
                if p in mcp_set:
                    for n, srv in tool_server.items():
                        if srv == p:
                            out.add(n)
                else:
                    out.add(p)
            return out

        pin_names = expand_pins(pinned_raw) | {"get_tool_info"}
        pin_names &= set(by_name.keys())

        # Tools eligible for embedding retrieval: local + MCP for enabled servers, never client-only.
        retrieval_names = [
            n
            for n in by_name
            if n not in client_name_set
            and n not in pin_names
            and (tool_server.get(n) is None or tool_server.get(n) in mcp_set)
        ]

        top_k = settings.TOOL_RETRIEVAL_TOP_K
        n_ret_pool = len(retrieval_names)
        factor = _rag_retrieval_factor(tool_threshold)
        est_retrieved = int(round(min(top_k, n_ret_pool) * factor)) if n_ret_pool else 0

        if retrieval_names:
            avg_pool = sum(name_to_chars.get(n, 400) for n in retrieval_names) / n_ret_pool
        else:
            avg_pool = 0.0

        pinned_chars = sum(name_to_chars.get(n, 0) for n in pin_names)
        client_chars = sum(name_to_chars.get(n, 0) for n in client_name_set if n in name_to_chars)
        retrieved_chars = int(est_retrieved * avg_pool) if est_retrieved and retrieval_names else 0

        tools_param_chars = pinned_chars + retrieved_chars + client_chars

        unretrieved_n = max(0, len(by_name) - len(pin_names | client_name_set) - est_retrieved)
        # tool index message (compact names + truncated descriptions)
        index_line_avg = 105
        tool_index_chars = 0
        if tool_retrieval and (local_tools or mcp_servers or client_tools) and by_name:
            hdr = len("Available tools (not yet loaded — use get_tool_info(tool_name) to get full schema):\n")
            tool_index_chars = hdr + unretrieved_n * index_line_avg if unretrieved_n else 0

        if not tool_retrieval and by_name:
            tools_param_chars = sum(name_to_chars.values())
            tool_index_chars = 0
            lines.append(
                EstimateLine(
                    "tools:param (all schemas)",
                    tools_param_chars,
                    "tool RAG off — every enabled tool sent each turn",
                )
            )
        elif by_name:
            hint = (
                f"RAG on · thresh≈{tool_threshold:.2f} · ~{est_retrieved}/{n_ret_pool} retrieved + "
                f"{len(pin_names)} pinned + {len(client_name_set)} client"
            )
            lines.append(EstimateLine("tools:param (schemas)", tools_param_chars, hint))
            if tool_index_chars:
                lines.append(
                    EstimateLine(
                        "sys:tool_index",
                        tool_index_chars,
                        f"~{unretrieved_n} compact entries for non-loaded tools",
                    )
                )
        else:
            lines.append(EstimateLine("tools:param", 0, "no tools enabled"))

    # Delegation index (when enabled)
    if delegate_bots:
        dele_lines = 0
        dele_chars = len("Available sub-agents (delegate via delegate_to_agent or @bot-id in your reply):\n")
        for did in delegate_bots:
            try:
                b = _get_bot(did)
                first = (b.system_prompt or "").strip().splitlines()[0][:120] if b.system_prompt else ""
                dele_chars += len(f"  • {did} — {b.name}" + (f": {first}" if first else "")) + 1
                dele_lines += 1
            except Exception:
                dele_chars += len(f"  • {did}\n")
                dele_lines += 1
        if dele_lines:
            lines.append(EstimateLine("sys:delegate_index", dele_chars, f"{dele_lines} bot(s)"))

    # Memory / knowledge / fs / pinned knowledge / plans — heuristics (query-dependent)
    if mem_enabled:
        mem_h = _memory_knowledge_hit_factor(mem_sim)
        est_mem = int(settings.MEMORY_RETRIEVAL_LIMIT * mem_max * 0.55 * mem_h)
        wrap = len("Relevant memories from past conversations (automatically recalled based on the user's message; you can use these directly):\n\n---\n\n")
        lines.append(EstimateLine("sys:memory (typical)", wrap + est_mem, "semantic recall; varies by query + store"))

    if know_enabled:
        kh = _memory_knowledge_hit_factor(know_sim)
        # retrieve_knowledge limits to 3 docs
        est_k = int(3 * know_max * 0.45 * kh)
        wrap = len("Relevant knowledge:\n\n---\n\n")
        lines.append(EstimateLine("sys:knowledge (typical)", wrap + est_k, "up to 3 docs; per-doc similarity overrides"))

    lines.append(
        EstimateLine(
            "sys:pinned_knowledge (typical)",
            min(6000, int(know_max * 0.45)),
            "only when the client has pinned docs",
        )
    )

    if fs_indexes:
        roots = len(fs_indexes)
        fs_thr = None
        for e in fs_indexes:
            if isinstance(e, dict) and e.get("similarity_threshold") is not None:
                try:
                    fs_thr = float(e["similarity_threshold"])
                except (TypeError, ValueError):
                    pass
        th = fs_thr if fs_thr is not None else settings.FS_INDEX_SIMILARITY_THRESHOLD
        fs_h = _memory_knowledge_hit_factor(th)
        chunk = settings.FS_INDEX_CHUNK_WINDOW
        est_fs = int(settings.FS_INDEX_TOP_K * chunk * 0.35 * fs_h)
        wrap = len("Relevant code/files from indexed directories:\n\n---\n\n")
        lines.append(
            EstimateLine(
                "sys:fs_context (typical)",
                wrap + est_fs,
                f"{roots} index root(s); varies heavily by query",
            )
        )

    # Section index (file history mode) — heuristic based on default 10 sections
    history_mode = draft.get("history_mode")
    if history_mode == "file":
        _est_si = 100 + 10 * 120  # header + 10 standard sections
        lines.append(EstimateLine("sys:section_index (typical)", _est_si, "~10 sections in standard verbosity; channel-configurable"))

    # Context pruning indicator
    _pruning = draft.get("context_pruning")
    _pruning_on = _pruning if _pruning is not None else settings.CONTEXT_PRUNING_ENABLED
    if _pruning_on:
        _keep = draft.get("context_pruning_keep_turns")
        _keep = _keep if _keep is not None else settings.CONTEXT_PRUNING_KEEP_TURNS
        lines.append(EstimateLine(
            "opt:context_pruning", 0,
            f"enabled — old tool results trimmed (keeping last {_keep} turns intact)",
        ))

    if audio_input == "native":
        from app.agent.message_utils import _AUDIO_TRANSCRIPT_INSTRUCTION

        lines.append(EstimateLine("sys:audio", len(_AUDIO_TRANSCRIPT_INSTRUCTION), "native audio mode"))

    total = sum(x.chars for x in lines)
    approx_tok = max(1, int(math.ceil(total / 4)))

    disclaimer = (
        "Rough per-turn lower bound before chat history, tool outputs, and @-tags. "
        "RAG rows use heuristics (threshold, top-k), not live cosine scores."
    )

    return ContextEstimateResult(lines=lines, total_chars=total, approx_tokens=approx_tok, disclaimer=disclaimer)
