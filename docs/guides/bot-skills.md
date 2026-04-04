# Self-Improving Agents: Bot-Authored Skills

Bots on Spindrel can author their own skills — structured knowledge documents that enter the semantic RAG pipeline and are automatically surfaced in future sessions when relevant.

## What Are Bot-Authored Skills?

Bot-authored skills are markdown documents created by bots at runtime using the `manage_bot_skill` tool. Unlike memory files (which are bot-scoped and searched via `search_memory`), skills enter the main RAG pipeline:

- **Chunked and embedded** into vector storage for semantic retrieval
- **Surfaced automatically** when a user message is semantically similar to the skill content
- **Persisted across sessions** — available to the bot forever, not just the current conversation

### Skills vs Memory Files

| Feature | Memory files | Bot-authored skills |
|---------|-------------|-------------------|
| Storage | Filesystem (`memory/reference/`) | Database (`skills` table) |
| Retrieval | `search_memory()` keyword+vector search | Main RAG pipeline (automatic) |
| Injection | Must be explicitly fetched | Auto-injected when relevant (RAG mode) |
| Scope | Bot-scoped | Bot-scoped (via ID prefix) |
| Context cost | Only when fetched | Up to 5 chunks per request (RAG_TOP_K) |

**Use memory files** for: personal notes, user preferences, session-specific context, daily logs.

**Use skills** for: reusable solution patterns, domain procedures, troubleshooting guides — anything that should surface automatically when relevant.

## How It Works

### Creating Skills

Bots use the `manage_bot_skill` tool with `action="create"`:

```
manage_bot_skill(
  action="create",
  name="docker-networking-fixes",
  title="Docker Networking Troubleshooting",
  content="# Docker Networking Fixes\n\n## Bridge network DNS resolution...",
  triggers="docker, networking, DNS, container connectivity",
  category="troubleshooting"
)
```

The skill is stored with ID `bots/{bot_id}/docker-networking-fixes` and immediately embedded for RAG retrieval.

### Skill ID Convention

All bot-authored skills follow the pattern `bots/{bot_id}/{slug}`. This ensures:

- **Isolation**: Bots can only CRUD skills under their own prefix
- **No collisions**: Different bots can have skills with the same slug
- **Admin visibility**: Easy to filter and attribute skills by bot

### Available Actions

| Action | Description |
|--------|-------------|
| `create` | Create a new skill (requires name, title, content) |
| `update` | Replace skill content (full rewrite) |
| `patch` | Find-and-replace within content (cheaper than rewrite) |
| `get` | Retrieve a skill by name |
| `list` | List all self-authored skills |
| `delete` | Remove a skill and its embeddings |

### Frontmatter

Skills automatically get YAML frontmatter with `name`, `triggers`, and `category` fields. This metadata helps the RAG pipeline surface skills at the right time.

## Context Budget Impact

Bot-authored skills use RAG mode, which has hard per-request limits:

- **`RAG_TOP_K=5`**: Maximum 5 skill chunks injected per request
- **`RAG_SIMILARITY_THRESHOLD=0.3`**: Only semantically relevant chunks
- **Priority P3**: RAG skills are trimmed before system prompt or history if context is tight
- **Chunk size**: Max 1500 chars each, so worst case ~7.5KB per request

A bot with 50+ skills generates ~100 chunks in the database. Vector search scans all chunks but only returns the 5 most relevant. No context bloat.

### Soft Limit Warning

When a bot exceeds 50 self-authored skills, the tool returns a warning suggesting the bot merge related skills or delete stale ones. This is advisory — there's no hard limit.

## Admin Visibility

### Skills List

Bot-authored skills appear in the admin skills list (`/admin/skills`) under the "Bot-Authored" group. Each skill shows:

- Bot attribution badge (which bot created it)
- Creation and update timestamps
- Chunk count

### Bot Detail Page

The bot editor's Skills section shows a banner with the count of self-authored skills and links to the filtered skills list.

### Filtering

The skills API supports filtering:

- `?source_type=tool` — only bot-authored skills
- `?bot_id=mybot` — only skills from a specific bot
- `?sort=recent` — order by most recently updated

## Content Validation

Skills enforce content limits to prevent empty stubs and abuse:

| Constraint | Value |
|------------|-------|
| Minimum content length | 50 characters |
| Maximum content length | 50,000 characters (~50KB) |
| Maximum name length | 100 characters |

Validation applies to create, update (when content is provided), and **patch** (the resulting content after replacement is validated).

## Skills vs Memory Files

The system prompt teaches bots the critical difference:

- **Memory files** (`memory/MEMORY.md`, `memory/reference/`, daily logs) = the bot's private notes. The bot must search for them or know they exist. Reference files are good for detailed personal context (system configs, user environment, project-specific notes).
- **Skills** (`manage_bot_skill`) = the bot's published playbook. Skills enter the RAG pipeline and **auto-surface** when a user's message is semantically similar — the bot doesn't need to remember they exist. Good for reusable patterns, procedures, troubleshooting guides, and domain knowledge.

**Rule of thumb**: If future-you should see this automatically when someone hits a similar problem, make it a skill. If future-you needs to actively look it up, put it in a reference file.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_TOP_K` | 5 | Max chunks injected per request |
| `RAG_SIMILARITY_THRESHOLD` | 0.3 | Min similarity for RAG retrieval |
| `SKILL_NUDGE_AFTER_ITERATIONS` | 8 | Inject learning nudge after N tool iterations (0 = disabled) |

## Prompt Guidance

When `memory_scheme: "workspace-files"` is active, the bot's system prompt includes guidance on when and how to create skills. The `manage_bot_skill` tool is automatically injected as a pinned tool.

### Mid-Conversation Learning Nudge

After `SKILL_NUDGE_AFTER_ITERATIONS` tool-call iterations (default 8), the agent loop injects a one-shot system message asking the bot to reflect on whether it learned something worth capturing as a skill. This is the key mechanism that shifts bots from "task execution mode" to "reflection mode" — without it, bots tend to solve problems and move on without recording what they learned.

The nudge only fires once per agent run, only for bots with `memory_scheme: "workspace-files"`, and not during compaction runs. Set to `0` to disable.

### Pre-Compaction Flush

The pre-compaction memory flush prompt also nudges bots to consider creating skills for reusable patterns discovered during the conversation. This is a last-chance opportunity before context is compacted.

## Embedding

Skills are embedded synchronously on create — the tool returns `"embedded": true/false` so the bot knows immediately if the skill entered the RAG pipeline. If embedding fails, the skill is still saved but won't appear in RAG results until re-embedded (e.g., on next server restart).

Updates and patches re-embed in the background (fire-and-forget) since the skill already has existing embeddings.

## Auto-Discovery Cache

Bot-authored skills are discovered via a DB query during context assembly. To avoid hitting the database on every message, results are cached per bot with a 30-second TTL. The cache is automatically invalidated when skills are created, updated, or deleted.
