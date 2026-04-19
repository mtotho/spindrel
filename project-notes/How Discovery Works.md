---
tags: [agent-server, reference, discovery, architecture]
status: active
updated: 2026-04-14
---
# How Discovery Works

Reference for how bots discover tools, skills, and capabilities at runtime. All discovery is automatic — a bot needs only `model` + `system_prompt` to function.

## The Pipeline

Context assembly runs this pipeline on every user message:

```
1. Channel overrides          — merge carapaces_extra, apply _disabled lists
2. Integration activation     — auto-inject carapaces from activated integrations
3. Session capabilities       — merge capabilities activated via activate_capability this session
4. Carapace resolution        — flatten all carapace IDs → skills, tools, system prompts (recursive, cycle-safe)
5. Enrolled skill ranking     — rank bot's enrolled skills against user message; annotate relevant, auto-inject top match
6. Capability RAG index       — semantic search for relevant unactivated capabilities → inject activate_capability tool
7. Tool retrieval             — hybrid vector+BM25 search for relevant tools from the full pool + enrolled tools
8. Unenrolled skill discovery — RAG for unenrolled skills as fetchable suggestions
```

## Tool Discovery

**Key files**: `app/agent/tools.py`, `app/agent/context_assembly.py` (line ~1453)

- All local tools are embedded at startup into `tool_embeddings` table
- `retrieve_tools()` does hybrid search: pgvector cosine + BM25 full-text, fused via RRF
- `bot.tool_discovery = True` (default) → searches entire local tool pool, not just declared tools
- Discovered (undeclared) tools get a stricter threshold: `threshold + 0.1`, capped at 0.65
- Declared tools use `bot.tool_similarity_threshold` or `TOOL_RETRIEVAL_THRESHOLD` (default **0.35** as of 2026-04-11; was 0.45 before then — see [[Fix Log]])
- Discovered tools are pre-filtered against unconditional deny policies before injection
- `get_tool_info` auto-injected so LLM can inspect full schema of any discovered tool. When called, the schema is pushed onto `current_activated_tools` (a `ContextVar`), making the tool callable for the rest of the CURRENT LOOP only — it does not persist across turns.

**Caching**: 5-minute TTL on (query, tool_names, servers, top_k, threshold).

**Tool enrollment (persistent working set)**: ✅ Shipped 2026-04-12 — `bot_tool_enrollment` table mirrors skill enrollment exactly. Tools promote on successful use, persist across turns/sessions, are prunable via `prune_enrolled_tools`. Admin UI panel + REST endpoints. See [[Loose Ends]] (resolved).

**Known gap — BM25 fallback AND-semantics**: the BM25 rescue layer uses `plainto_tsquery('english', :q)`, which ANDs every non-stopword token. Conversational queries with typos or bot names reliably fail to match any tool because noise tokens kill the AND. Fix path (swap to `websearch_to_tsquery`) tracked in [[Loose Ends#Tool-retrieval BM25 fallback is brittle against conversational noise]].

## Skill Discovery

**Key files**: `app/agent/rag.py`, `app/agent/context_assembly.py`, `app/services/skill_enrollment.py`

### Per-Bot Persistent Working Set

Every bot has a persistent skill enrollment (`bot_skill_enrollment` table). This replaced the old per-turn ephemeral auto-enrollment. New bots get a starter pack (`STARTER_SKILL_IDS` in `app/config.py`); successful `get_skill()` calls promote into the working set; the hygiene loop prunes unused enrollments.

Enrollment sources: `starter` (initial pack), `fetched` (promoted from `get_skill()`), `manual` (admin UI), `authored` (bot-created skills).

### Per-Turn Enrolled Skill Ranking + Auto-Inject (2026-04-14)

On each user message, `rank_enrolled_skills()` in `rag.py` semantically ranks the bot's enrolled skills against the user message. The flat list is replaced with a two-tier format:

1. **Relevant skills** (above `SKILL_ENROLLED_RELEVANCE_THRESHOLD`, default 0.40) — marked with `↑` and labeled "relevant to this message — load them before responding"
2. **Auto-injected skills** (above `SKILL_ENROLLED_AUTO_INJECT_THRESHOLD`, default 0.55) — full content injected into context as synthetic `get_skill()` tool call/result pairs, eliminating the round-trip

All enrolled skills remain visible regardless of ranking (Phase 3 invariant: RAG as ranker, not filter).

**Auto-inject persistence**: Auto-injected content is recorded as synthetic tool call/result message pairs with `_no_prune` protection so they persist in the DB and survive session reload. History-scan dedup skips skills already in conversation context. Budget accounting (`_budget_can_afford` / `_budget_consume`) prevents large skills from overflowing the context window.

**Tracking**: Auto-injects are tracked separately from `get_skill()` calls via `auto_inject_count` / `last_auto_injected_at` on `BotSkillEnrollment`. Global `surface_count` is NOT incremented for auto-injects.

### Semantic Discovery (Unenrolled Skills)

A separate system message surfaces *unenrolled* skills as fetchable suggestions, distinct from the enrolled working-set listing. Uses hybrid vector+BM25 search on skill content embeddings in the `Document` table. Fetching an unenrolled skill promotes it into the working set.

### Tools for Skills

- `get_skill(skill_id)` — load full content; promotes to working set on success
- `get_skill_list()` — browse all available skills (enrolled + discoverable)
- `manage_bot_skill(action, ...)` — create/edit/archive/restore bot-authored skills

## Capability Discovery (activate_capability)

**Key files**: `app/agent/capability_rag.py`, `app/agent/capability_session.py`, `app/tools/local/capabilities.py`, `app/agent/context_assembly.py` (line ~515)

**This is fully automatic for all bots. No configuration needed.**

### How it works

1. All carapaces are embedded at startup into `capability_embeddings` table
2. On each user message, capability RAG searches for relevant unactivated capabilities
3. Excludes: already-active carapaces, globally disabled (`CAPABILITIES_DISABLED`), channel-disabled
4. If matches found above threshold (0.50), a system message lists them with instructions
5. `activate_capability` tool is auto-injected into bot's `local_tools` and `pinned_tools`
6. LLM can call `activate_capability(id="<id>", reason="...")` to load one

### Approval gate

Controlled by `CAPABILITY_APPROVAL` (default: `"required"`):
- **required**: User must approve before activation (unless capability is pinned in bot's `carapaces`)
- **none**: Activation happens silently

Approval creates a `ToolApproval` record with capability metadata (name, description, tool/skill counts). 300s timeout.

Session tracking: once approved, `is_approved(session_id, carapace_id)` prevents re-asking.

### What activation does

1. Records activation in session store (4-hour TTL)
2. Returns the capability's `system_prompt_fragment` immediately to the LLM
3. On next turn, context assembly merges the capability's tools and skills into the bot's config
4. Lists `tools_next_turn` and `skills_next_turn` in the response so LLM knows what's coming

## Permission / Approval System

**Key files**: `app/services/tool_policies.py`, `app/agent/tool_dispatch.py`

### Safety tiers (from tool registration)

| Tier | Default action |
|------|---------------|
| `readonly` | allow |
| `mutating` | allow (subject to policies) |
| `exec_capable` | require_approval |
| `control_plane` | require_approval |

### Policy evaluation order

1. Load enabled rules, ordered by priority ASC (cached 10s)
2. Filter: bot-specific rules (bot_id matches) OR global (bot_id IS NULL)
3. Match tool_name: exact, glob pattern, or `*`
4. Match conditions: argument regex/prefix/in checks
5. Bot-specific rules take precedence at same priority
6. **First matching rule wins**
7. Fallback: tier defaults → `TOOL_POLICY_DEFAULT_ACTION` (typically "allow")

### Session optimization

`is_session_allowed(correlation_id, tool_name)` skips full policy evaluation if already approved in this conversation. User only approves once per tool per session.

## Configuration Knobs

| Setting | Default | What it controls |
|---------|---------|-----------------|
| `bot.tool_retrieval` | `True` | Enable/disable tool RAG entirely |
| `bot.tool_discovery` | `True` | Search full tool pool (not just declared) |
| `bot.tool_similarity_threshold` | `TOOL_RETRIEVAL_THRESHOLD` (0.35) | Cosine threshold for declared tools |
| `SKILL_ENROLLED_RELEVANCE_THRESHOLD` | 0.40 | Min similarity for enrolled skill relevance annotation |
| `SKILL_ENROLLED_AUTO_INJECT_THRESHOLD` | 0.55 | Min similarity for auto-injecting enrolled skill content |
| `AUTO_INJECT_MAX` | 1 | Max skills auto-injected per turn |
| `SKILL_INDEX_RETRIEVAL_TOP_K` | 8 | Max unenrolled skills in discovery index per turn |
| `SKILL_INDEX_RETRIEVAL_THRESHOLD` | 0.35 | Min similarity for unenrolled skill discovery |
| `CAPABILITY_RETRIEVAL_THRESHOLD` | 0.50 | Min similarity for capability matches |
| `CAPABILITY_RETRIEVAL_TOP_K` | 5 | Max capabilities in index |
| `CAPABILITY_APPROVAL` | "required" | Whether user must approve activation |
| `CAPABILITIES_DISABLED` | "" | Globally hidden carapaces (CSV) |
| Channel `carapaces_disabled` | [] | Channel-level blocklist |
| Bot `carapaces` | [] | Pinned capabilities (always loaded, no approval) |
| Channel `carapaces_extra` | [] | Channel-specific auto-activated capabilities |

## Key Insight

A bot with zero explicit configuration still gets:
- Starter skill pack (auto-enrolled on creation)
- Per-turn relevance ranking of enrolled skills with auto-inject for top matches
- Semantic discovery of unenrolled skills as fetchable suggestions
- Tool enrollment (persistent across turns, promoted on successful use)
- Tool discovery across the full local pool (hybrid vector+BM25)
- Capability discovery with `activate_capability` auto-injected
- Policy-gated approval for dangerous tools
- `get_skill()` / `get_skill_list()` auto-injected for all bots
- Hygiene loop curating the working set (prune unused, protect recent/authored)

The only thing that requires explicit config is **pinning** — making a capability always-on without approval.
