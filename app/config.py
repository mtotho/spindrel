import ast
import json
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode

try:
    VERSION = _pkg_version("spindrel")
except PackageNotFoundError:
    VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Canonical memory-scheme prompt defaults (single source of truth)
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_SCHEME_PROMPT = """\
{% section "Memory" %}

Your persistent memory lives in `{memory_rel}/` relative to your workspace root.
`{memory_rel}/MEMORY.md` and recent daily logs are already in your context — do not re-read them.

### Write to memory IMMEDIATELY — before responding — when you detect any of these:
- User states a **preference**, **correction**, **convention**, or teaches a non-obvious **fact** about their setup.
- User **confirms** a non-obvious approach you took worked.
- You discover something load-bearing through tool use (system configs, API behaviors, error patterns).

**A preference not saved is a preference the user has to repeat.** This is the #1 failure mode.

Use the `file` tool for all memory writes (`edit` / `append` / `create` / `overwrite` / `json_patch`).
See the `workspace_files` skill for the full operation repertoire and path rules.

### {memory_rel}/MEMORY.md — Curated Knowledge Base

Stable facts: user preferences, key decisions, system configs, learned patterns.
Keep under ~100 lines. Format: `## Sections` with `_Updated: YYYY-MM-DD_` headers.

**Rules:**
- NEVER append session notes here — those go in daily logs.
- Edit sections in place; do not let it grow past ~100 lines.
- Before adding, check for duplicates.
- When crowded, move detail to `{memory_rel}/reference/` and keep a one-line pointer.

### Daily Logs — {memory_rel}/logs/YYYY-MM-DD.md

Today's and yesterday's logs are in your context. Older logs are searchable only.
- **Session start**: append an entry with time and task context.
- **On any decision, correction, or discovery**: write it immediately.
- **Every 3–5 responses**: append a progress note — don't let 5+ responses pass without a write.

### Reference Files — {memory_rel}/reference/

In-depth documents (configs, API notes, environment details). The listing is in your context;
contents are NOT auto-injected. Use `get_memory_file("name")` to fetch,
`search_memory("query")` to search. Put topical documents here, not loose in `{memory_rel}/`.

### Memory Tools
- `search_memory(query)` — hybrid semantic+keyword search across all memory files.
- `get_memory_file(name)` — read a specific memory file.

For skill authoring (separate from memory), see the `skill_authoring` skill.

### Context Budget
- **Hot** (auto-injected every turn): MEMORY.md, today's + yesterday's logs. Keep lean.
- **Warm** (fetch on demand): reference/ files. You see the listing; read when needed.
- **Cold** (search only): old logs, archived files. Use `search_memory`.
Move things down tiers as they stop being actively needed.
{% endsection %}"""

DEFAULT_CHANNEL_WORKSPACE_PROMPT = """\
Channel workspace — absolute path: {workspace_path}
IMPORTANT: Always use the exact path above for file operations. The channel ID is {channel_id} (a UUID, NOT the channel name).
Use the `file` tool for reading, writing, editing, and listing workspace files (preferred over exec_command).
Use search_channel_archive to search archived files, search_channel_workspace for broader search.
Keep active files minimal — archive resolved items. Write durable learnings to memory/ files, not workspace.
The data/ subfolder holds binary files (PDFs, images, etc.) — not auto-injected into context.
When receiving data files, save to data/ and create/update a workspace .md file with descriptions and metadata.
Cross-channel: if the user references another project/channel, use list_channels to find it, \
then search_channel_workspace with its channel_id to find relevant workspace content.
For task tracking, use the create_task_card and move_task_card tools to manage kanban cards in tasks.md.
{data_listing}"""


DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT = """\
Before this conversation is compacted, save important context to your memory files.
All paths are relative to your workspace root — use the memory/ prefix:
- Append key decisions and events to today's daily log (memory/logs/YYYY-MM-DD.md)
- Promote any new stable facts to memory/MEMORY.md (edit existing sections in place, do not append session entries)
- Write anything you'll need to remember in future sessions
- **If you learned a reusable domain pattern, procedure, fix, or workflow**: create or update a skill NOW with `manage_bot_skill(...)`. If the reusable part is executable tool orchestration, attach a named script so future sessions can inspect it with `get_script` or run it directly via `run_script(skill_name=..., script_name=...)`. Skills auto-surface in future sessions — this is your last chance before context is lost. (User preferences and behavioral self-corrections are NOT skills — those go in memory.)
Use the `file` tool to write to the appropriate files under memory/.
**For memory/MEMORY.md**: use `edit` (to update sections) or `append` (to add new sections). Do NOT attempt to rewrite the whole file.
**For daily logs**: use `append`. **For new reference files**: use `create` (errors if the file already exists)."""


DEFAULT_MEMORY_HYGIENE_PROMPT = """\
[MEMORY MAINTENANCE — Periodic Review]

You are running a scheduled memory maintenance pass across all your channels.
Your goal: keep memory lean, promote stable facts, prune stale entries, detect contradictions,
archive old logs, and keep files organized.

## Step 1 — Survey channels AND sub-sessions
Your channels (primary and member) are listed in the "## Channels" snapshot appended below, with last activity times and 7-day message counts. For each channel with recent activity:
- Use `read_conversation_history(section="index", channel_id="<id>")` to review what happened.
- **Always check sub-sessions** — call `list_sub_sessions(channel_id="<id>")` to see pipeline runs, evals, threads, and scratch-pad chats attached to the channel. Read interesting ones with `read_sub_session(session_id="<id>")`. Decisions and corrections often land in sub-sessions and never hit the main channel feed — if you skip this step, you'll miss them.
- Note channels with no recent activity (candidates for archiving stale daily logs).
- **Member channels matter** — you may have learned things in channels you're a guest in. Review them too.

## Step 2 — Curate MEMORY.md (with contradiction detection + lifecycle metadata)
**IMPORTANT**: Call `get_memory_file("MEMORY")` first — the bootstrap injection in your context may be truncated. You need the FULL file content before attempting any edits, because `file(operation="edit")` requires an exact `find` string match.
For each entry:
- **Accuracy**: Is it still true? Remove or update stale facts.
- **Duplicates**: Merge overlapping entries.
- **Contradictions**: Check for conflicting entries. When found, keep the newer/more reliable one and archive the old with `<!-- superseded YYYY-MM-DD: reason -->`. Contradictions between channels are common — resolve by checking which is more recent or authoritative.
- **Missing facts**: Are there facts confirmed across multiple recent sessions that aren't captured yet? Add them.
- **Lifecycle annotations**: When adding or updating entries, include `[updated: YYYY-MM-DD]` for significant changes. Add `[confidence: high|medium|low]` for uncertain facts. Add `[source: channel-name]` when a fact comes from a specific channel.
- Keep MEMORY.md under ~100 lines. Move detailed context to memory/reference/ files.

## Step 3 — Curate reference files (with staleness detection)
List memory/reference/ files. For each:
- Is it still relevant? Delete outdated files.
- Are there overlapping files? Merge them.
- Are any files growing too large? Split into focused topics.
- **Staleness check**: If a file has `[updated: ...]` annotations older than 30 days, flag it for review. If the content is still valid, update the date. If stale, archive or delete.

## Step 4 — Promote from daily logs (with importance scoring)
Scan recent daily logs (last 3-7 days). For each candidate entry, mentally score on these 5 factors:
1. **Future utility** — Will this be useful in future sessions? (high for decisions, procedures, preferences)
2. **Factual confidence** — Is this confirmed or speculative? (high for user-stated facts, low for inferences)
3. **Semantic novelty** — Is this genuinely new info or a repeat? (skip if already captured)
4. **Temporal recency** — Is this from a recent interaction? (prefer last 3 days)
5. **Content type** — Decisions and corrections ALWAYS promote. Observations only if recurring.

Promote entries scoring well on 3+ factors:
- Stable facts or decisions → promote to memory/MEMORY.md using `file(operation="edit")` to update existing sections or `file(operation="append")` for new sections.
- Reusable procedures or patterns → create or update a skill; if the pattern is executable tool orchestration, attach a named script
- Detailed reference info → move to memory/reference/ files

## Step 5 — Archive maintenance
- Create the archive directory if needed: `file(operation="mkdir", path="memory/logs/archive")`
- Move processed logs older than 14 days: `file(operation="move", path="memory/logs/YYYY-MM-DD.md", destination="memory/logs/archive/YYYY-MM-DD.md")`
- Archived logs remain searchable via `search_memory` but won't be auto-injected into context.
- Only archive logs you've already reviewed and promoted from in this or previous hygiene runs.
- Clean up orphaned reference files that are no longer linked from MEMORY.md — use `file(operation="delete", path="memory/reference/outdated-file.md")`.
- Update any `<!-- superseded -->` references that are older than 30 days — delete them entirely.

## Step 6 — Summarize
Write a brief summary to today's daily log including:
- Entries added / updated / removed
- Contradictions resolved (if any)
- Files archived or cleaned up
- Any topics or reusable workflows that might benefit from a dedicated skill or attached named script"""


DEFAULT_SKILL_REVIEW_PROMPT = """\
[SKILL REVIEW — Periodic Assessment]

You are running a scheduled skill review pass. Your goal: generate cross-channel reflections,
prune stale or low-value skills, improve skill triggers, create new skills for emerging patterns,
and audit auto-inject quality.

## Execution rules
- This is an automated task with no user present. Execute all steps directly.
- Do NOT present options, ask questions, or request approval.
- Do NOT create skills to satisfy reflections you generate in the same pass.
  Reflections are observations for FUTURE sessions to act on.
- If you need skill authoring guidance, call `get_skill(skill_id="skill_authoring")`.
- Keep your final response under 300 words. The daily log entry is the durable output.

## Step 1 — Cross-channel reflection
Recent user messages from your channels are in the "## Recent Activity" snapshot appended below.
Messages tagged `[thread]` come from message-anchored thread replies and `[scratch]` from scratch-pad chats — treat them as first-class activity for that channel, not side traffic.
Use this data (not `read_conversation_history`) to generate 3-5 meta-observations. Look for:
- **Recurring patterns**: Similar requests or problems appearing across channels
- **Cross-project connections**: Information from one channel that's relevant to another
- **Emerging themes**: New topics or interests the user is developing
- **Workflow insights**: Better ways you could serve the user based on observed patterns
- **Knowledge gaps**: Topics you've been asked about but lack good information on

Write reflections to a dedicated `## Reflections` section at the bottom of MEMORY.md (create it if missing).
- Format: `- [reflection YYYY-MM-DD] Actionable observation...`
- Before adding, check existing reflections — skip if a similar one already exists.
- Prune reflections older than 30 days that haven't led to action.
- Remove "resolved" reflections that led to concrete changes (skills created, facts promoted, etc.).
- Cap at ~5-8 active reflections to prevent bloat. Drop the least actionable if over the cap.
- Reflections should be actionable and cite specific evidence from the activity snapshot.

If a "## Previous Skill Review" section is appended below, review it to avoid repeating
the same observations and to check whether previous reflections led to action.

## Step 2 — Skill hygiene
Review your complete skill list in the "## Working set" snapshot appended below. It shows ALL your enrolled skills (both authored and catalog) with per-bot fetch counts, global surface counts, source, and age.

### Understanding the data
- **`you fetched Nx`** — how many times YOU called `get_skill()` for this skill. This is the most reliable usage signal.
- **`global Nx`** — how many times ANY bot fetched this skill. Ambiguous for your needs.
- **`source=authored`** — you wrote this skill. Protected: requires override reason to prune.
- **`[protected]`** — cannot be pruned without an explicit override reason (authored or enrolled < 7 days).

### Rules
1. **Never prune skills enrolled less than 14 days ago.** They haven't had time to prove their value. If you believe a recent skill was a mistake (e.g. should have been memory), provide an override reason.
2. **Authored skills require an override reason to prune.** The tool will reject the request without one. Valid reasons: "should be memory not skill", "topic no longer relevant", "merged into another skill". Pruning an authored skill archives it (reversible by admin).
3. **For authored skills with weak triggers**: rewrite with better trigger phrases (`manage_bot_skill(action="update")`) rather than pruning. Low fetch count on a recently-created skill usually means the triggers need work, not that the skill is useless.
4. **For catalog skills you never fetch**: safe to prune if enrolled 14+ days ago. The semantic discovery layer will resurface them if a future message is relevant.
5. **Overlapping authored skills**: merge with `manage_bot_skill(action="merge", ...)`.
6. **Outdated authored content**: use `action="patch"` for small fixes, `action="update"` for full rewrites.
7. **Attached script hygiene**: for authored skills with named scripts, review whether each script still matches the prose guidance, triggers, and current tool contracts. Use `get_script`, `update_script`, `delete_script`, or `add_script` as needed.
8. **Missing coverage**: if recent activity shows recurring topics with no matching skill, create new skills now. If the recurring pattern is an executable workflow, attach a named script instead of burying code in prose.
9. **Auto-inject quality**: Review the sample turns in the "Auto-inject quality samples" section (if present). If a skill's samples show it being injected for unrelated conversations, its triggers are too broad — narrow them with `manage_bot_skill(action="update")`, or prune if the skill shouldn't exist.
10. **All-protected short-circuit**: If every enrolled skill is protected, skip *pruning* — but still review authored skills for quality. Protection only blocks unenrollment. You can and should still:
   - **Merge** overlapping authored skills (`action="merge"`)
   - **Update triggers** on skills with weak or overly broad triggers (`action="update"`)
   - **Patch** outdated content (`action="patch"`)
   - **Update attached scripts** when reusable workflows drift (`action="update_script"`)
   - **Evaluate** whether authored skills are well-scoped or should be split/combined
   Note "all skills protected, skipping pruning — reviewing authored skill quality" and proceed.

### How to prune
- Unprotected: `prune_enrolled_skills(skill_ids=["id1", "id2"])`
- Protected: `prune_enrolled_skills(skill_ids=["id1"], overrides={"id1": "reason"})`
- **Do not call `manage_bot_skill(action="delete")` on catalog skills you don't own** — that archives the skill itself, not just your enrollment.
- For authored skills that carry named scripts, prefer script CRUD (`get_script`, `add_script`, `update_script`, `delete_script`) over rewriting code blobs inside the prose body.

## Step 2.5 — Discovery audit
If a "## Discovery Audit" section is appended below, act on it. It aggregates the
last 14 days of ranker signal:

**For each enrolled skill in the "ranked but rarely fetched" list**:
- Large gap (ranked ≥ 8x, fetched ≤ 1x) on an authored skill: rewrite description
  + triggers via `manage_bot_skill(action="update")`. The description should answer
  "use when ___" — what user phrasing should trigger this skill?
- Catalog skill enrolled 14+ days ago with zero fetches: prune.
- `avg sim` < 0.45: ranker is borderline. Skip this pass and revisit after Step 2
  description fixes have time to take effect.

**For each catalog skill in the "repeatedly suggested" list**:
- Read it (`get_skill`) — that fetch enrolls it.
- If it covers a recurring topic in "## Recent Activity", note the new enrollment
  in the daily log so it's intentional, not accidental.

If no "## Discovery Audit" section is present, the bot has insufficient ranker
history — skip this step.

## Step 3 — Summarize
Write a `## Skill Review` section to today's daily log (`memory/logs/YYYY-MM-DD.md`) using
the `file` tool (append if the file exists, create if not). Include:
- Reflections generated or updated (with brief rationale)
- Skills created / merged / pruned / updated (with IDs)
- Auto-inject quality issues found and corrected
- Discovery audit fixes (skill IDs + what changed: rewrote triggers, enrolled, pruned)
- Any knowledge gaps that couldn't be addressed"""


# ---------------------------------------------------------------------------
# Skill learning nudge — injected mid-conversation after N tool iterations
# ---------------------------------------------------------------------------
SKILL_NUDGE_AFTER_ITERATIONS = 8  # inject after this many tool-call iterations (0 = disabled)

DEFAULT_SKILL_CORRECTION_NUDGE_PROMPT = """\
The user just corrected you. Route to the right persistence layer:

- **Personal preference or user-specific fact** ("I prefer X", "my setup is Y", \
"don't do Z for me") → write to memory (MEMORY.md or the routing table in your \
system prompt). This is NOT a skill — it's about THIS user, not a reusable pattern.
- **Reusable domain pattern** (a common mistake, a technique rule, a better approach \
that applies generally) → create or update a skill with `manage_bot_skill`. If the correction is \
really a reusable tool workflow, attach a named script to that skill. Keep it concrete: \
"when X, do Y instead of Z."
- **Trivial or situation-specific** → just acknowledge and move on.

Act immediately — do not mention this prompt to the user."""

DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT = """\
You've been repeatedly searching for the same topics. \
These recurring lookups are a signal that the information should be a SKILL \
so it auto-surfaces without you having to search for it.

Repeated search topics:
{topics}

For each topic above, consider using `manage_bot_skill(action="create", ...)` to capture \
the key information as a skill. If the recurring pattern is a reusable multi-step tool workflow, \
attach a named script so future sessions can run it directly with \
`run_script(skill_name=..., script_name=...)`. Skills enter the RAG pipeline and surface \
automatically when a user message is semantically relevant — no manual search needed.

If these topics are already covered by existing skills, check if the skills have good \
trigger phrases (use action="list" to review surface_count). \
Do not mention this prompt to the user."""

# Repeated-lookup detection — thresholds
SKILL_REPEATED_LOOKUP_MIN_RUNS = 3  # min distinct agent runs with same query
SKILL_REPEATED_LOOKUP_WINDOW_DAYS = 14  # look back this many days

DEFAULT_SKILL_NUDGE_PROMPT = """\
You have been working on this task for a while. Pause briefly and consider:

- Did you discover a reusable pattern, fix, or procedure that should AUTO-SURFACE in future sessions when someone hits a similar problem?
- Did you learn something about this domain that isn't in your training data?

If yes: use `manage_bot_skill(...)` NOW — not later. If the reusable part is executable \
tool orchestration, attach a named script and later run it via `run_script(skill_name=..., script_name=...)`. \
Skills enter the RAG pipeline and appear automatically when relevant. This is different from memory files, which require you to search for them.

Keep it focused — one pattern per skill, with concrete "when X, do Y" triggers.

If nothing worth capturing, continue with your response — do not mention this prompt to the user."""


# ---------------------------------------------------------------------------
# Default global base prompt — prepended before all bot system prompts
# ---------------------------------------------------------------------------
# Covers fleet-wide operating rules, output style, delegation mechanics,
# scheduled tasks, tool discipline, and confidence signaling.
#
# Things intentionally NOT here (handled by other injection layers):
#   - Current datetime → context_assembly.py injects a system message
#   - Memory routing/tools/curation → DEFAULT_MEMORY_SCHEME_PROMPT
#   - Channel workspace paths → DEFAULT_CHANNEL_WORKSPACE_PROMPT
#   - Skill injection → context_assembly skill pipeline
#   - Conversation history → file-mode section index injection

DEFAULT_GLOBAL_BASE_PROMPT = """\
You are an agent on the Spindrel platform — a self-hosted multi-bot orchestration system \
where each bot has a defined role and scope.

{% section "The Platform" %}
- **Channels** — persistent conversations where you interact with users. Channels can \
have integrations, workspace files, and heartbeat schedules.
- **Workspaces** — every bot is a member of the default workspace; it's the shared \
filesystem + container environment, not a per-bot property.
- **Sub-sessions** — threads, scratch-pad chats, pipeline runs, and eval runs are \
first-class. List with `list_sub_sessions(channel_id)`, read with `read_sub_session(session_id)`.
- **Task Pipelines** — user-authored multi-step automations (foreach, user_prompt, approval \
gates). For repeatable multi-step work, suggest a pipeline instead of manual chains.
- **Integrations** — external service connections activated per-channel (Slack, GitHub, \
etc.). They add tools, skills, and dispatchers to your context.
- **The orchestrator** — coordinates bots, manages channels, and authors pipelines. \
If something is outside your scope, suggest the user ask the orchestrator.
{% endsection %}

{% section "Operating Rules" %}
- Do exactly what was asked. No unrequested features, cleanup, or improvements.
- On ambiguous requests: state your assumption and proceed. Ask first only if stakes are high.
- Do not take irreversible actions (delete, send, deploy) without explicit confirmation \
in the current session — do not infer it from prior messages.
- If your last 3+ actions have made no progress, stop and report — do not loop.
{% endsection %}

{% section "Output" %}
Be direct and conversational. No filler, no preamble, no step-by-step narration. \
Work silently during multi-step tasks; when done, say what happened in plain language.
{% endsection %}

{% section "Tools and Skills" %}
Your tools and skills load dynamically — not everything is in your context.
- `get_tool_info(tool_name="...")` — look up a tool by name.
- `get_skill(skill_id="...")` — fetch a skill from the index in your context.
- `run_script(...)` — preferred for multi-step tool work (for-each loops, filtering, \
joining results across tools). Runs Python in your workspace with `tools.NAME(**args)` \
bindings and keeps intermediate data out of context. It can run ad-hoc inline source or a \
named script attached to one of your bot-authored skills (`run_script(skill_name=..., script_name=...)`). \
Call `list_tool_signatures()` first if you don't know what's composable.

Two persistence layers — route correctly:
- **Skills** (`manage_bot_skill`) — reusable domain knowledge, auto-surface across sessions \
via RAG. Use for "when doing X, always Y" patterns. Skills may also carry named scripts for \
reusable multi-step tool workflows; manage them with `get_script`, `add_script`, `update_script`, \
and `delete_script`.
- **Memory files** (`memory/`) — bot-private user facts, preferences, corrections, session \
history. Use for "user prefers X".
A user's personal preference is NOT a reusable pattern. See the `skill_authoring` skill.
{% endsection %}

{% section "Delegation" %}
Some tasks belong to other bots. Use `delegate_to_agent(bot_id, message, attachments?)` \
with a **self-contained** message — the target bot does not see your conversation. \
Synthesize the result into your own voice; the user doesn't need to know which bot did \
the work. For repeatable multi-step coordination, suggest a pipeline. See the `delegation` \
skill for details.
{% endsection %}

{% section "Files & Routing" %}
Your memory layout, routing table, and file tools are defined in a dedicated injection \
layer — follow your bot-specific routing table exactly. When writing preferences or \
corrections to reference files, do it silently; it's background housekeeping. See \
the `workspace_files` skill.
{% endsection %}

{% section "Widgets" %}
HTML widgets you emit authenticate as the emitting bot via `source_bot_id` on the envelope \
and `window.spindrel.api` bearer. Your bot's scopes are the ceiling — the viewer lends \
nothing. See the `widget_dashboards` skill.
{% endsection %}

{% section "Context Awareness" %}
- Your conversation may have been compacted. If something feels missing, use \
`read_conversation_history` or `list_sub_sessions`.
- For exact strings from past conversations (errors, paths, ports): \
`read_conversation_history(section='messages:<query>')`.
- For the full output of a summarized tool result: \
`read_conversation_history(section='tool:<id>')`.
{% endsection %}

{% section "Tool Discipline" %}
- If a tool's schema isn't fully in context, call `get_tool_info` first.
- After a tool error: diagnose, fix, retry once. Second failure: stop and report.
- Never guess tool names or parameters.
{% endsection %}

{% section "Confidence" %}
- When you know something from memory or context, say so directly.
- When inferring or uncertain, flag it: "I believe..." / "Based on [source]..."
- Never fabricate facts, tool outputs, or file contents.
{% endsection %}"""


# ---------------------------------------------------------------------------
# Starter pack — skills enrolled by default for every new bot
# ---------------------------------------------------------------------------
# Phase 3 of the Skill Simplification track (working-set discovery model).
# Bots accrete additional skills via successful get_skill() calls; this list
# is the curated minimum every bot starts with. Edit per release as needed.
# IDs not present in the catalog at enrollment time are silently skipped.
STARTER_SKILL_IDS: list[str] = [
    "attachments",
    "workspace_files",
    "delegation",
    "context_mastery",
    "prompt_injection_and_security",
    "skill_authoring",
    "workspace_member",
    "channel_workspaces",
    "docker_stacks",
]


class Settings(BaseSettings):
    # System pause
    SYSTEM_PAUSED: bool = False
    SYSTEM_PAUSE_BEHAVIOR: str = "queue"  # "queue" or "drop"

    # Global base prompt — prepended before all other base/system prompts for every bot
    GLOBAL_BASE_PROMPT: str = DEFAULT_GLOBAL_BASE_PROMPT

    TIMEZONE: str = "America/New_York"
    BASE_URL: str = ""  # Public URL (e.g. tunnel); used to build webhook URLs in admin UI
    GITHUB_REPO: str = "mtotho/spindrel"  # owner/repo for update checks
    WIDGET_THEME_DEFAULT_REF: str = "builtin/default"

    # Encryption (secrets at rest)
    ENCRYPTION_KEY: str = ""  # Fernet key for encrypting provider API keys + integration secrets

    # Web Push / VAPID
    # Generate a keypair once via: `python -m app.tools.generate_vapid_keys`,
    # then paste the printed lines into `.env`. When unset, push endpoints
    # return 503 and the `send_push_notification` tool no-ops with a clear
    # error. `VAPID_SUBJECT` is `mailto:you@example.com` or `https://your.site`.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = ""

    # Auth
    API_KEY: str
    ADMIN_API_KEY: str = ""  # empty = fall back to API_KEY for backward compat

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@postgres:5432/agentdb"

    # Default LLM provider + model (Ollama out of the box)
    DEFAULT_MODEL: str = "gemma4:e4b"
    LLM_BASE_URL: str = Field(
        default="http://localhost:11434/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "LITELLM_BASE_URL"),
    )
    LLM_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "LITELLM_API_KEY"),
    )
    # Image generation (OpenAI-compatible `images/generations`)
    IMAGE_GENERATION_MODEL: str = ""  # empty = disabled; set to a vision model if available
    IMAGE_GENERATION_PROVIDER_ID: str = ""  # provider_id for image generation; empty = bot's provider or .env default

    # Prompt generation (AI-assisted prompt authoring in admin UI)
    PROMPT_GENERATION_MODEL: str = ""  # empty = uses DEFAULT_MODEL
    PROMPT_GENERATION_MODEL_PROVIDER_ID: str = ""
    PROMPT_GENERATION_TEMPERATURE: float = 0.7

    # Agent
    AGENT_MAX_ITERATIONS: int = 15
    # Cap on inner tool calls a single run_script invocation may dispatch via
    # /api/v1/internal/tools/exec. Defends against scripts that loop around
    # the loop-level max_iterations fence. Per-bot override on
    # Bot.max_script_tool_calls.
    AGENT_MAX_SCRIPT_TOOL_CALLS: int = 50
    SKILL_NUDGE_AFTER_ITERATIONS: int = SKILL_NUDGE_AFTER_ITERATIONS  # inject skill-learning nudge after N iterations (0 = disabled)
    SKILL_CORRECTION_NUDGE_ENABLED: bool = True  # inject skill-learning nudge when user corrects the bot
    SKILL_REPEATED_LOOKUP_NUDGE_ENABLED: bool = True  # inject nudge when bot repeatedly searches same topics
    LOG_LEVEL: str = "INFO"  # INFO = pathway only; DEBUG = full args, result previews, token counts
    AGENT_TRACE: bool = False  # When True: one-line trace per tool/response (no JSON), ideal for dev
    TOOL_LOOP_DETECTION_ENABLED: bool = True  # Detect and break repeating tool call cycles within a single agent run
    # Parallel tool execution — dispatch multiple tool calls concurrently via asyncio.gather
    PARALLEL_TOOL_EXECUTION: bool = True
    PARALLEL_TOOL_MAX_CONCURRENT: int = 10  # semaphore limit for concurrent dispatches
    # Tool-dispatch wall-clock guard. Any local/MCP tool that exceeds this many
    # seconds is cancelled and returns a timeout error to the LLM, so a wedged
    # tool can never hang a turn forever. Must be > MCP_CALL_TIMEOUT so honest
    # MCP failures surface as MCP timeouts instead of tripping this guard.
    TOOL_DISPATCH_TIMEOUT: float = 90.0
    # httpx client timeout inside app/tools/mcp.py:call_mcp_tool — lower than 60
    # so a slow/blocking origin (e.g. a site that fingerprints the firecrawl
    # proxy) doesn't eat a full minute of turn wall-clock per attempt.
    MCP_CALL_TIMEOUT: float = 30.0
    # Rate limit retry (LLM call level — preserves accumulated tool-call context)
    LLM_RATE_LIMIT_RETRIES: int = 3          # additional attempts after first failure
    LLM_RATE_LIMIT_INITIAL_WAIT: int = 90    # seconds before first retry (slightly > 60s TPM window)
    # General transient-error retry (5xx, connection errors, timeouts)
    LLM_MAX_RETRIES: int = 3                 # additional attempts after first failure
    LLM_RETRY_INITIAL_WAIT: float = 2.0      # seconds; doubles each retry (2, 4, 8…)
    LLM_TIMEOUT: float = 120.0              # HTTP timeout for LLM API calls (seconds); covers slow providers
    LLM_FALLBACK_MODEL: str = ""             # if set, try this model once after all retries exhaust
    LLM_FALLBACK_MODEL_PROVIDER_ID: str = ""
    LLM_FALLBACK_COOLDOWN_SECONDS: int = 300  # circuit breaker: skip broken models for this long after fallback
    # Rate limit retry (task level — reschedules entire task on rate limit failure)
    TASK_RATE_LIMIT_RETRIES: int = 3         # max reschedule attempts before marking failed
    # Max run time for tasks/heartbeats (seconds). Per-task > per-channel > this global default.
    TASK_MAX_RUN_SECONDS: int = 1200         # 20 minutes

    # Context compaction
    COMPACTION_MODEL: str = ""
    COMPACTION_MODEL_PROVIDER_ID: str = ""
    COMPACTION_INTERVAL: int = 30 # Every time there gets to be N turns in the session (minus the compaction message), the compaction will run.
    COMPACTION_KEEP_TURNS: int = 10 # The last M turns will be kept in context, not included in the compaction. So compaction will only include the last N-M turns.

    # STT / Transcription
    STT_PROVIDER: str = "local"  # "local" (faster-whisper) or future: "groq", "openai"
    WHISPER_MODEL: str = "base.en"
    WHISPER_DEVICE: str = "auto"  # "auto", "cpu", "cuda"
    WHISPER_COMPUTE_TYPE: str = "auto"  # "auto", "int8", "float16", "float32"
    WHISPER_BEAM_SIZE: int = 1
    WHISPER_LANGUAGE: str = "en"

    # RAG / embeddings (skills, memory, knowledge).
    # Use "local/<hf-org>/<model>" for fastembed models (ONNX, no API calls, free),
    # or a plain model name for OpenAI-compatible API calls via LLM_BASE_URL
    # (e.g. "text-embedding-3-small").
    #
    # DIMENSION HANDLING — all models produce 1536-dim vectors stored in the same DB:
    #   - Local models (e.g. nomic 768-dim): zero-padded to 1536 — lossless for cosine similarity
    #   - OpenAI text-embedding-3-*: Matryoshka-truncated to 1536 via `dimensions=` param
    #   - Other API models: must natively produce 1536-dim output
    #
    # DO NOT change EMBEDDING_DIMENSIONS — DB columns and indexes are hardcoded to 1536.
    # If you switch EMBEDDING_MODEL, re-embed everything (restart re-indexes automatically).
    EMBEDDING_MODEL: str = "local/BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSIONS: int = 1536
    RAG_TOP_K: int = 5

    # Hybrid search (BM25 + vector fusion via Reciprocal Rank Fusion)
    HYBRID_SEARCH_ENABLED: bool = True
    HYBRID_SEARCH_RRF_K: int = 60  # RRF parameter: higher = more weight on top results

    # Contextual retrieval — LLM-generated chunk descriptions for better RAG
    CONTEXTUAL_RETRIEVAL_ENABLED: bool = False
    CONTEXTUAL_RETRIEVAL_MODEL: str = ""  # empty = use COMPACTION_MODEL
    CONTEXTUAL_RETRIEVAL_MAX_TOKENS: int = 150
    CONTEXTUAL_RETRIEVAL_BATCH_SIZE: int = 5  # concurrent LLM calls during indexing
    CONTEXTUAL_RETRIEVAL_PROVIDER_ID: str = ""  # empty = default provider

    # Prompt caching (Anthropic cache_control breakpoints)
    PROMPT_CACHE_ENABLED: bool = True
    PROMPT_CACHE_MIN_TOKENS: int = 1024  # skip caching for short system messages

    # Local embeddings (fastembed / ONNX)
    FASTEMBED_CACHE_DIR: str = ""  # directory for downloaded ONNX models; empty = fastembed default

    # Filesystem indexing (semantic search over arbitrary directories)
    FS_INDEX_TOP_K: int = 8
    FS_INDEX_SIMILARITY_THRESHOLD: float = 0.30
    FS_INDEX_COOLDOWN_SECONDS: int = 300   # min seconds between full re-indexes per (root, bot)
    FS_INDEX_CHUNK_WINDOW: int = 1500      # chars for sliding-window fallback chunker
    FS_INDEX_CHUNK_OVERLAP: int = 200      # overlap chars for sliding-window chunks
    FS_INDEX_MAX_FILE_BYTES: int = 500_000 # skip files larger than this
    FS_INDEX_CONCURRENCY: int = 8          # max concurrent file embeddings during indexing
    FS_INDEX_PERIODIC_MINUTES: int = 30     # periodic re-verify interval (0 = disabled); catches watcher crashes

    # Spindrel home directory — root of user customizations.
    # Contains integration subdirectories (e.g. toths/, alpaca/).
    # In Docker, set HOME_HOST_DIR + HOME_LOCAL_DIR for path translation.
    SPINDREL_HOME: str = ""

    # Extra tool directories (colon-separated paths) scanned at startup in addition to ./tools/
    TOOL_DIRS: str = ""

    # Extra integration directories (colon-separated paths) scanned at startup
    # in addition to ./integrations/. See docs/integrations/README.md.
    # Deprecated: use SPINDREL_HOME instead.
    INTEGRATION_DIRS: str = ""

    # Capability auto-discovery
    CAPABILITY_RETRIEVAL_TOP_K: int = 5
    CAPABILITY_RETRIEVAL_THRESHOLD: float = 0.50
    CAPABILITY_APPROVAL: str = "required"  # "required" = ask user, "none" = silent

    # On-demand skill index retrieval (semantic selection instead of flat dump)
    SKILL_INDEX_RETRIEVAL_TOP_K: int = 8
    SKILL_INDEX_RETRIEVAL_THRESHOLD: float = 0.35

    # Enrolled skill ranking (env-var only — not in admin UI or DB).
    # When enabled, enrolled skills are ranked by semantic similarity to the
    # user message each turn. Skills above RELEVANCE_THRESHOLD are marked ↑ in
    # the skill index (tells the LLM to load them). The top AUTO_INJECT_MAX
    # relevant skills have their full content pre-loaded into context, skipping
    # the get_skill round-trip. Auto-inject is budget-gated — if content doesn't
    # fit the context window, it's silently skipped.
    #
    # AUTO_INJECT_MAX is disabled (0) by default pending prompt-first evaluation:
    # the index prompt is now directive ("BEFORE answering, call get_skill FIRST…")
    # and should motivate bots to fetch on their own. Machinery remains; raise to
    # 1+ via env var to re-enable after measuring whether the prompt alone is
    # sufficient (use the discovery_summary trace event).
    SKILL_ENROLLED_RANKING_ENABLED: bool = True
    SKILL_ENROLLED_RELEVANCE_THRESHOLD: float = 0.40   # ↑ annotation threshold in skill list
    SKILL_ENROLLED_AUTO_INJECT_THRESHOLD: float = 0.55  # pre-load content into context (higher bar)
    SKILL_ENROLLED_AUTO_INJECT_MAX: int = 0  # disabled by default; see note above

    # Dynamic tool selection (embed tool descriptions, retrieve top-K per turn)
    TOOL_RETRIEVAL_THRESHOLD: float = 0.35
    TOOL_RETRIEVAL_TOP_K: int = 10

    # Memory
    MEMORY_RETRIEVAL_LIMIT: int = 5
    MEMORY_SIMILARITY_THRESHOLD: float = 0.75
    WIPE_MEMORY_ON_SESSION_DELETE: bool = False

    # Tool policies
    TOOL_POLICY_DEFAULT_ACTION: str = "require_approval"  # "allow", "deny", or "require_approval" — what happens when no rule matches
    TOOL_POLICY_ENABLED: bool = True  # master switch for the policy engine
    TOOL_POLICY_TIER_GATING: bool = True  # use safety_tier to set default actions for dangerous tools

    # Host execution
    HOST_EXEC_ENABLED: bool = False
    HOST_EXEC_DEFAULT_TIMEOUT: int = 30
    HOST_EXEC_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
    HOST_EXEC_WORKING_DIR_ALLOWLIST: Annotated[list[str], NoDecode] = []
    HOST_EXEC_BLOCKED_PATTERNS: Annotated[list[str], NoDecode] = []
    HOST_EXEC_ENV_PASSTHROUGH: Annotated[list[str], NoDecode] = ["PATH", "HOME", "USER", "LANG", "TERM"]

    # Filesystem commands
    FS_COMMANDS_MAX_READ_BYTES: int = 500_000
    FS_COMMANDS_MAX_LIST_ENTRIES: int = 1000

    # Delegation
    DELEGATION_MAX_DEPTH: int = 3

    # Workflow safety
    WORKFLOW_MAX_TASK_EXECUTIONS: int = 50  # max tasks a single workflow run can spawn before auto-fail

    # Workspaces
    WORKSPACE_BASE_DIR: str = "~/.spindrel-workspaces"
    WORKSPACE_DEFAULT_IMAGE: str = "agent-workspace:latest"
    # Path translation for Docker deployment (sibling container pattern).
    # When the server runs inside Docker, it accesses workspace files via
    # a mounted volume (WORKSPACE_LOCAL_DIR), but child containers need
    # the actual host path (WORKSPACE_HOST_DIR) for their -v bind mounts.
    # Leave both empty when running the server on the host.
    WORKSPACE_HOST_DIR: str = ""    # e.g., "/home/you/.spindrel-workspaces"
    WORKSPACE_LOCAL_DIR: str = ""   # e.g., "/workspace-data"

    # Spindrel home directory (integrations, prompts, workflows, etc.)
    # Same pattern as workspace paths: HOST is the real path on the host,
    # LOCAL is where it's mounted inside the container.
    HOME_HOST_DIR: str = ""         # e.g., "/home/you/spindrel-home"
    HOME_LOCAL_DIR: str = ""        # e.g., "/app/home"

    # Public URL of this server (injected into workspace containers)
    SERVER_PUBLIC_URL: str = "http://host.docker.internal:8000"

    # Internal URL for same-container subprocesses (shared_workspace exec, run_script).
    # These run inside the agent-server container, so they reach the API via
    # localhost — not host.docker.internal, which only resolves in sidecar
    # containers launched with --add-host by sandbox.py.
    SERVER_INTERNAL_URL: str = "http://localhost:8000"

    # Workspace code editor (code-server)
    EDITOR_PORT_RANGE_START: int = 9200
    EDITOR_PORT_RANGE_END: int = 9299

    # Docker sandboxes
    DOCKER_SANDBOX_ENABLED: bool = False
    DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"
    DOCKER_SANDBOX_MAX_CONCURRENT: int = 10
    DOCKER_SANDBOX_DEFAULT_TIMEOUT: int = 30
    DOCKER_SANDBOX_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
    # NoDecode: env is always a string; pydantic-settings would json.loads(list[str]) first and
    # fail on single quotes or comma-separated paths before our validator runs.
    DOCKER_SANDBOX_MOUNT_ALLOWLIST: Annotated[list[str], NoDecode] = []
    DOCKER_SANDBOX_IDLE_PRUNE_INTERVAL: int = 300

    # Docker stacks (agent-managed Docker Compose stacks)
    DOCKER_STACKS_ENABLED: bool = False
    DOCKER_STACK_MAX_PER_BOT: int = 5
    DOCKER_STACK_DEFAULT_CPUS: float = 1.0
    DOCKER_STACK_DEFAULT_MEMORY: str = "512m"
    DOCKER_STACK_COMPOSE_TIMEOUT: int = 120
    DOCKER_STACK_EXEC_TIMEOUT: int = 30
    DOCKER_STACK_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
    DOCKER_STACK_LOG_TAIL_MAX: int = 1000

    # Instance identity for multi-instance deployments sharing one Docker daemon.
    # Used to namespace integration-declared docker_compose stacks (project name,
    # container network aliases) so prod + e2e can coexist on the same host.
    # Default derives from the container hostname so a fresh deploy never has to
    # set this manually; override via env to something short/friendly.
    SPINDREL_INSTANCE_ID: str = ""
    # Docker network the agent-server container lives on. Integration stacks
    # connect to this network so the agent can reach them by alias. Defaults
    # to {COMPOSE_PROJECT_NAME}_default at runtime when left blank.
    AGENT_NETWORK_NAME: str = ""

    # RAG re-ranking (post-assembly cross-source relevance filtering)
    RAG_RERANK_ENABLED: bool = True
    RAG_RERANK_BACKEND: str = "cross-encoder"  # "cross-encoder" (fast ONNX, zero API cost) or "llm" (full LLM call)
    RAG_RERANK_MODEL: str = ""              # LLM backend: empty = use COMPACTION_MODEL
    RAG_RERANK_MODEL_PROVIDER_ID: str = ""
    RAG_RERANK_THRESHOLD_CHARS: int = 5000  # only rerank when total RAG chars exceed this
    RAG_RERANK_MAX_CHUNKS: int = 20         # max chunks to keep after reranking
    RAG_RERANK_MAX_TOKENS: int = 1000       # max output tokens for reranker response (LLM backend only)
    RAG_RERANK_CROSS_ENCODER_MODEL: str = "Xenova/ms-marco-MiniLM-L-6-v2"  # cross-encoder model name
    RAG_RERANK_SCORE_THRESHOLD: float = 0.01  # min relevance probability after sigmoid (0-1); 0.01 = keep >1% relevant

    # Chat History defaults
    DEFAULT_HISTORY_MODE: str = "file"  # "summary" | "structured" | "file"
    SECTION_INDEX_COUNT: int = 10
    SECTION_INDEX_VERBOSITY: str = "standard"  # "compact" | "standard" | "detailed"
    HISTORY_WRITE_FILES: bool = False
    SECTION_RETENTION_MODE: str = "forever"  # "forever" | "count" | "days"
    SECTION_RETENTION_VALUE: int = 100
    TRIGGER_HEARTBEAT_BEFORE_COMPACTION: bool = False  # deprecated — use MEMORY_FLUSH_ENABLED

    # Memory scheme nudge — warn bot when MEMORY.md exceeds this many lines
    MEMORY_MD_NUDGE_THRESHOLD: int = 100

    # Memory flush (dedicated pre-compaction memory save)
    MEMORY_FLUSH_ENABLED: bool = True
    MEMORY_FLUSH_MODEL: str = ""  # empty = use bot's model
    MEMORY_FLUSH_MODEL_PROVIDER_ID: str = ""
    PREVIOUS_SUMMARY_INJECT_CHARS: int = 500  # max chars of existing summary injected into heartbeat/memory-flush context
    MEMORY_FLUSH_DEFAULT_PROMPT: str = """\
[MEMORY FLUSH — PRE-COMPACTION]
The conversation context is about to be compacted. Older messages will be archived and removed from your active context.

Review the recent conversation and save anything important:
- Use save_memory for facts, preferences, decisions, or context you'll need later
- Use update_knowledge for documentation or reference material worth preserving
- Use update_persona if the user revealed preferences about how they want to interact

Focus on what would be LOST if you couldn't see these messages anymore. Don't save things that are already in your memories or knowledge. Be selective — only save what matters."""

    # Memory scheme system prompt (workspace-files mode).
    # Use {memory_rel} placeholder for the bot-relative memory path.
    MEMORY_SCHEME_PROMPT: str = ""
    # Memory scheme flush prompt (workspace-files mode).
    # Empty = use DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT.
    MEMORY_SCHEME_FLUSH_PROMPT: str = ""

    # Memory hygiene (periodic cross-channel memory curation)
    MEMORY_HYGIENE_ENABLED: bool = False
    MEMORY_HYGIENE_INTERVAL_HOURS: int = 24
    MEMORY_HYGIENE_PROMPT: str = ""  # empty = use DEFAULT_MEMORY_HYGIENE_PROMPT
    MEMORY_HYGIENE_ONLY_IF_ACTIVE: bool = True
    MEMORY_HYGIENE_MODEL: str = ""  # empty = use bot's default model
    MEMORY_HYGIENE_MODEL_PROVIDER_ID: str = ""  # empty = use bot's default provider
    MEMORY_HYGIENE_TARGET_HOUR: int = -1  # 0-23 = target hour (local tz), -1 = disabled (current behavior)

    # Skill review (periodic skill curation — separate from memory maintenance)
    SKILL_REVIEW_ENABLED: bool = False
    SKILL_REVIEW_INTERVAL_HOURS: int = 72  # 3 days — skill rot is slower than memory drift
    SKILL_REVIEW_PROMPT: str = ""  # empty = use DEFAULT_SKILL_REVIEW_PROMPT
    SKILL_REVIEW_ONLY_IF_ACTIVE: bool = False  # skill rot happens regardless of activity
    SKILL_REVIEW_MODEL: str = ""  # empty = use bot's default model (should be a strong model)
    SKILL_REVIEW_MODEL_PROVIDER_ID: str = ""  # empty = use bot's default provider
    SKILL_REVIEW_TARGET_HOUR: int = -1  # 0-23 = target hour (local tz), -1 = disabled

    # Channel workspace injection prompt.
    # Placeholders: {workspace_path}, {channel_id}, {data_listing}
    # Empty = use DEFAULT_CHANNEL_WORKSPACE_PROMPT.
    CHANNEL_WORKSPACE_PROMPT: str = ""

    # Bot system prompt reinforcement — repeats bot.system_prompt near the end
    # of the message array for recency bias on weaker models. Strong models
    # (GPT-5.3, Claude, Minimax) don't need it; disabled by default.
    REINFORCE_SYSTEM_PROMPT: bool = False

    # Context pruning (trim old tool results at assembly time)
    CONTEXT_PRUNING_ENABLED: bool = True
    CONTEXT_PRUNING_MIN_LENGTH: int = 200

    # In-loop pruning (trim old tool results between iterations within a single turn).
    # Prevents one long-running agent run from accumulating 16+ tool results in
    # context. Only the most recent ``KEEP_ITERATIONS`` rounds stay verbatim.
    # 2 is a balance: short "fetch then act" patterns still see the data they
    # just fetched, while long exploratory runs still get most of the savings.
    IN_LOOP_PRUNING_ENABLED: bool = True
    IN_LOOP_PRUNING_KEEP_ITERATIONS: int = 2

    # Context budgeting (prevent exceeding model context window)
    CONTEXT_BUDGET_ENABLED: bool = True
    CONTEXT_BUDGET_RESERVE_RATIO: float = 0.15       # fraction of context window reserved for output + overhead
    CONTEXT_BUDGET_DEFAULT_WINDOW: int = 200_000      # fallback context window when model info unavailable

    # Tool result summarization
    TOOL_RESULT_SUMMARIZE_ENABLED: bool = True
    TOOL_RESULT_SUMMARIZE_THRESHOLD: int = 3000       # chars; summarize if above this
    TOOL_RESULT_SUMMARIZE_MODEL: str = ""             # empty = use bot's current model
    TOOL_RESULT_SUMMARIZE_MODEL_PROVIDER_ID: str = ""
    TOOL_RESULT_SUMMARIZE_MAX_TOKENS: int = 300       # max tokens for summary output
    TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS: Annotated[list[str], NoDecode] = ["get_skill"]
    TOOL_RESULT_HARD_CAP: int = 50_000              # max chars per tool result sent to LLM (0 = no cap)
    TOOL_TURN_AGGREGATE_CAP_CHARS: int = 150_000    # max total chars across all tool results in one turn; proportional trim kicks in above this (0 = no cap)

    # RAG injection limits (chars per item before joining; prevents context bloat)
    MEMORY_MAX_INJECT_CHARS: int = 3000      # per memory item injected into context

    # Heartbeat schedule control
    HEARTBEAT_QUIET_HOURS: str = ""  # e.g. "23:00-07:00" — local time window where heartbeats slow/stop
    HEARTBEAT_QUIET_INTERVAL_MINUTES: int = 60  # interval during quiet hours (0 = disabled entirely)
    HEARTBEAT_ACTIVE_INTERVAL_MINUTES: int = 5  # default active interval (per-heartbeat DB value takes precedence)
    HEARTBEAT_DEFAULT_PROMPT: str = ""  # fallback prompt when channel heartbeat has no prompt/template/workspace file
    HEARTBEAT_PREVIOUS_CONCLUSION_CHARS: int = 500  # max chars of previous heartbeat conclusion injected into next heartbeat
    HEARTBEAT_MAX_HISTORY_TURNS: int = 3  # max non-heartbeat turn-pairs loaded for heartbeats/tasks (0 = no history)
    HEARTBEAT_REPETITION_DETECTION: bool = True
    HEARTBEAT_REPETITION_THRESHOLD: float = 0.8  # SequenceMatcher ratio
    HEARTBEAT_REPETITION_WARNING: str = (
        "WARNING: Your recent heartbeat outputs are repetitive — you keep producing "
        "very similar responses or taking the same actions. Break the pattern: find "
        "something genuinely new to report, try a different approach, or respond "
        "with just 'No updates.' Do NOT repeat the same text or tool calls as last time."
    )

    # Attachments
    ATTACHMENT_SUMMARY_ENABLED: bool = True
    ATTACHMENT_SUMMARY_MODEL: str = ""
    ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID: str = ""
    ATTACHMENT_VISION_CONCURRENCY: int = 3
    ATTACHMENT_SWEEP_INTERVAL_S: int = 60
    ATTACHMENT_TEXT_MAX_CHARS: int = 40_000  # ~10K tokens for text summarization
    ATTACHMENT_RETENTION_DAYS: int | None = None  # global default, None = keep forever
    ATTACHMENT_MAX_SIZE_BYTES: int | None = None  # global default, None = no limit
    ATTACHMENT_TYPES_ALLOWED: list[str] | None = None  # global default, None = all types
    ATTACHMENT_RETENTION_SWEEP_INTERVAL_S: int = 3600  # 1 hour between sweeps

    # Data retention (operational tables: trace_events, tool_calls, heartbeat_runs, etc.)
    DATA_RETENTION_DAYS: int | None = None  # None = keep forever
    DATA_RETENTION_SWEEP_INTERVAL_S: int = 86400  # 24 hours between sweeps

    # User authentication (JWT + Google OAuth)
    JWT_SECRET: str = ""  # auto-generated on first startup if empty
    JWT_ACCESS_EXPIRY: int = 3600  # 1 hour
    JWT_REFRESH_EXPIRY: int = 2592000  # 30 days
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Config state auto-export (empty = disabled)
    CONFIG_STATE_FILE: str = "config-state.json"

    # Secret redaction (redact known secrets from tool results and LLM output)
    SECRET_REDACTION_ENABLED: bool = True

    # Security audit logging — structured logs for outbound HTTP requests and
    # high-privilege (exec_capable / control_plane) tool executions.
    SECURITY_AUDIT_ENABLED: bool = True

    # API rate limiting — limits requests to the Spindrel server itself (NOT LLM provider calls).
    # Protects against runaway clients hammering your server. In-memory token bucket per API key/IP.
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_DEFAULT: str = "100/minute"  # all Spindrel API endpoints
    RATE_LIMIT_CHAT: str = "30/minute"      # stricter limit for /chat and /chat/stream

    # CORS (comma-separated origins, e.g. "http://localhost:8081,http://localhost:19006")
    CORS_ORIGINS: str = ""

    BASE_COMPACTION_PROMPT: str ="""\
        You are a conversation summarizer. You will receive the message history of a \
        conversation between a user and an AI assistant.

        Produce a JSON object with the following fields:
        - "title": A concise title for this conversation (3-8 words, like a chat tab name).
        - "summary": A detailed summary of everything discussed so far. Include key facts, \
        decisions, code snippets or file paths mentioned, user preferences expressed, and \
        any ongoing tasks. This summary will replace the full history, so capture everything \
        the assistant would need to continue the conversation seamlessly.

        IMPORTANT: Include human-readable time references in the summary text itself \
        (e.g. "On March 5, 2025: ..." or "During the week of March 1-7: ..."). \
        These summaries may be stored as long-term memories and retrieved weeks later, \
        so temporal context is essential for the model to reason about when things happened.

        Respond ONLY with the JSON object, no markdown fences or extra text."""


    SECTION_EXECUTIVE_SUMMARY_PROMPT: str = """\
        You are a conversation historian. Below are section summaries from a long-running conversation. \
        Write a concise executive summary (3-5 sentences) covering the overall arc: \
        what the conversation has been about, key decisions made, and current state. \
        This summary will be injected as context for future messages, so focus on what \
        the assistant needs to know to continue effectively."""

    # Memory knowledge compaction prompt
    MEMORY_KNOWLEDGE_COMPACTION_PROMPT: str = """\
        This conversation is about to be summarized. You will keep the last N turns in context, and the rest will be summarized. So please decide now if there is 
        anything from this conversation so far that you want to store in memory, knowledge or update your persona with. Use available tools.
        """

    @field_validator(
        "DOCKER_SANDBOX_MOUNT_ALLOWLIST",
        "HOST_EXEC_WORKING_DIR_ALLOWLIST",
        "HOST_EXEC_BLOCKED_PATTERNS",
        "HOST_EXEC_ENV_PASSTHROUGH",
        "TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS",
        mode="before",
    )
    @classmethod
    def _parse_mount_allowlist(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(p).strip() for p in v if str(p).strip()]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                parsed: list | None = None
                try:
                    parsed = json.loads(v)
                except json.JSONDecodeError:
                    try:
                        parsed = ast.literal_eval(v)
                    except (ValueError, SyntaxError):
                        parsed = None
                if parsed is not None:
                    if not isinstance(parsed, list):
                        raise ValueError(
                            "DOCKER_SANDBOX_MOUNT_ALLOWLIST: expected a JSON/Python list of paths."
                        )
                    return [str(p).strip() for p in parsed if str(p).strip()]
                # Brackets but not valid JSON/Python, e.g. [/home/user/proj] (quotes omitted in .env)
                if v.endswith("]") and len(v) > 2:
                    inner = v[1:-1].strip()
                    if not inner:
                        return []
                    parts = [p.strip() for p in inner.split(",") if p.strip()]
                    if parts:
                        return parts
                raise ValueError(
                    "DOCKER_SANDBOX_MOUNT_ALLOWLIST: invalid list. "
                    "Use /a,/b or [\"/a\"] or [/a] (unquoted paths inside brackets)."
                )
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


def _default_instance_id() -> str:
    """Slug of the container hostname — stable across restarts, differs per
    compose project. Fallback: 'default'. Lowercase, alnum+hyphen, ≤20 chars."""
    import socket
    import re
    raw = socket.gethostname() or "default"
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")[:20]
    return slug or "default"


def _default_agent_network() -> str:
    """Docker network the agent-server's api container lives on — used as the
    bridge for integration sidecars.

    Docker Compose does NOT propagate ``COMPOSE_PROJECT_NAME`` into containers,
    so relying on it yields an empty string in virtually every deployment.
    Instead, introspect the container's own networks via the mounted Docker
    socket. Picks the first non-``bridge`` network it belongs to."""
    import json
    import os
    import socket
    import subprocess

    proj = os.environ.get("COMPOSE_PROJECT_NAME", "").strip()
    if proj:
        return f"{proj}_default"

    try:
        hostname = socket.gethostname()
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", hostname],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        networks = json.loads(result.stdout.strip() or "{}")
        for name in networks:
            if name and name != "bridge":
                return name
    except Exception:
        pass
    return ""


settings = Settings()
if not settings.SPINDREL_INSTANCE_ID:
    settings.SPINDREL_INSTANCE_ID = _default_instance_id()
if not settings.AGENT_NETWORK_NAME:
    settings.AGENT_NETWORK_NAME = _default_agent_network()
