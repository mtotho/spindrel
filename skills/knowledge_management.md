---
name: Knowledge Management & Learning
description: How to use the three-layer learning system (persona, memory, knowledge) for optimal long-term retention
---

# Knowledge Management & Learning

You have three layers for learning and retaining information across conversations. They differ fundamentally in **retrieval reliability** — understanding this is the key to using them well.

## Retrieval Reliability — The Most Important Concept

Not all layers are equal. The critical question is: **will this information actually be in my context when I need it?**

| Layer | Retrieval reliability | Injection method | When it fails |
|-------|----------------------|-----------------|---------------|
| **Persona** | **100% — always present** | Prepended after system prompt every turn | Never. It's always there. |
| **Pinned knowledge** | **~100% — always injected** | Injected every turn for matching scope | Only if char limit truncates it |
| **Knowledge (RAG)** | **~60-80%** | Vector similarity against user message | User message doesn't semantically match the document |
| **Memory** | **~40-60%** | Vector similarity against user message | User message doesn't match, or memory buried in top-K ranking |

**This means**: If something MUST be followed every time, only persona and pinned knowledge are reliable. Memories are probabilistic — they may or may not surface depending on what the user says.

## Layer 1: Persona — Your Rulebook

Persona is NOT just "who you are." It's the **only layer with guaranteed 100% injection**. This makes it the most powerful and important layer.

### How it works
- Stored as one text block per bot in the `bot_personas` table
- Injected as a `[PERSONA]` system message **immediately after your system prompt**, before everything else
- Present on **every single turn** — no similarity matching, no thresholds, no retrieval failures
- Persists across all sessions and all channels for this bot

### What belongs in persona
Because persona is the only guaranteed layer, use it for anything that must ALWAYS be in your context:
- **Permanent rules**: "Always use bun, never npm" / "Never run destructive commands without asking"
- **Communication style**: "I speak concisely; Matt hates hedging and filler"
- **Core user preferences**: The things that apply to every conversation, not just specific topics
- **Behavioral patterns**: "I check memory before saving to avoid duplicates"
- **Identity and role**: "I'm the primary assistant for Matt's home lab and projects"

### What does NOT belong in persona
- Specific facts about projects (use knowledge)
- Temporary observations (use memory)
- Reference material (use knowledge, pinned if always-needed)
- Anything over ~300 tokens — persona is injected every turn, so bloat is expensive

### Tools
- `update_persona(content)` — replaces the entire persona layer (use when restructuring)
- `append_to_persona(content)` — adds to the end (use for quick additions)
- `edit_persona(old_text, new_text)` — find-and-replace within persona (use for targeted fixes)

### Persona maintenance discipline
- **Structure your persona** with clear sections so edits are surgical. Example sections: Rules, Preferences, Identity, Patterns.
- **Review before appending** — the persona is always visible in your `[PERSONA]` block. Read it before adding.
- **Periodically rewrite** the whole thing via `update_persona` rather than letting appends accumulate into a disorganized mess.
- **Keep it tight**. Every token in persona costs you context budget on every single turn.

## Layer 2: Memory — The Probabilistic Intake Layer

Memories are individual facts and observations. They're **easy to create but unreliable to retrieve**. Treat them as a scratchpad and intake mechanism, not as a filing cabinet.

### How it works
- Each memory is a single row with a vector embedding
- On each turn, the user's message is embedded and compared against memories via **cosine similarity**
- Only memories above the similarity threshold (default 0.45) are injected
- Top-K matches (default 10) are returned, so important memories compete with each other
- Injected **after** persona as "Relevant memories from past conversations"
- Each memory is prefixed with its creation date: `[March 15, 2026] Matt's server runs Arch`

### Why memories are unreliable
If you save the memory "Matt always wants bun instead of npm" and the user says "install these packages," that memory might NOT fire because "install packages" doesn't semantically match "bun instead of npm" well enough. **Critical rules must go in persona, not memory.**

Memories work best when:
- The user's message is directly about the same topic
- The memory is specific enough to match but broad enough to be found
- There aren't too many competing memories diluting the top-K slots

### Scoping
| Scope flag | Effect |
|-----------|--------|
| `cross_session: true` | Recall memories from other sessions |
| `cross_client: false` | Only recall memories from this same client |
| `cross_bot: false` | Only recall memories saved by this same bot |

### Creation paths
1. **Manual save**: You call `save_memory(content)` during conversation
2. **Compaction phase**: When context is compacted, the system runs a memory phase where you review the conversation and save important facts before context is summarized away — this is your last chance to persist information

### Tools
- `save_memory(content)` — store a fact (auto-embedded for future retrieval)
- `search_memories(query)` — find memories by semantic similarity (returns IDs)
- `purge_memory(memory_id)` — delete one memory by ID
- `merge_memories(memory_ids, merged_content?)` — consolidate multiple memories into one re-embedded row
- `promote_memories_to_knowledge(memory_ids, knowledge_name, content?)` — graduate memories into a knowledge document and purge the originals

### When to save a memory
- Observations during conversation that might be useful later
- Quick facts you'll consolidate into knowledge later
- Corrections ("Actually, that server is Ubuntu not Arch")
- Anything you want to remember but isn't important enough for persona or structured enough for knowledge yet

### When NOT to save a memory
- **Rules or preferences that must always be followed** — use persona instead
- Transient info (current task state, today's weather)
- Things already captured in knowledge documents — that's redundant
- Routine commands or tool outputs
- **Always search first** to avoid duplicates

### Memory as intake → graduation
The right mental model: memories are your **inbox**. Save freely during conversation, but regularly:
1. **Search and merge** related memories into single concise entries
2. **Promote to knowledge** when 3+ memories cluster around a topic
3. **Promote to persona** when you notice a pattern that should be a permanent rule
4. **Purge** outdated or superseded memories

## Layer 3: Knowledge — Structured Reference Documents

Knowledge documents are living documents about topics, projects, or systems. They have medium-high retrieval reliability via RAG, and **can be pinned for guaranteed injection**.

### How it works
- Stored in the `bot_knowledge` table with a vector embedding
- Documents are stored and embedded as **one whole unit** (not chunked — more on this below)
- Retrieved via three mechanisms (in priority order):
  1. **@-tagged**: User or system explicitly references `@knowledge_name` → injected verbatim, bypasses all thresholds
  2. **Pinned** (`mode=pinned`): Always injected every turn for matching scope
  3. **RAG** (semantic similarity): User message compared against document embeddings → top matches above threshold injected
- Injected **after** memories, labeled `[Knowledge: document_name]`
- Each document capped at `knowledge_max_inject_chars` (default 8000) before injection

### The embedding dilution problem (important!)

Each knowledge document gets **one embedding for the entire content**. Unlike skills (which chunk by `##` headers with separate embeddings per section), knowledge documents are embedded as one blob.

This means: a large document covering many subtopics produces a diluted "average" embedding. If your `home_network` doc covers devices, VLANs, DNS, and firewall rules, and the user asks "what's my NAS IP?", the overall embedding might not match well enough.

**The fix: keep documents small and focused.**
- `home_network_devices` + `home_network_vlans` + `home_network_dns` will retrieve MUCH better than one giant `home_network` doc
- Aim for documents that cover one coherent topic
- If a document grows past ~2000 chars with multiple sections, consider splitting it

### Scoping

Knowledge uses the `knowledge_access` table. Each document has access entries:

| scope_type | scope_key | Meaning |
|-----------|-----------|---------|
| `channel` | channel UUID | Only visible in this specific channel |
| `bot` | bot_id | Visible to this bot across all channels |
| `global` | NULL | Visible to all bots in all channels |

Each access entry has a **mode**:

| Mode | Behavior | Retrieval reliability |
|------|----------|----------------------|
| `rag` | Retrieved by semantic similarity (default) | ~60-80% |
| `pinned` | Always injected into context | ~100% |
| `tag_only` | Only injected when explicitly @-mentioned | 0% unless tagged |

**Channel-scoped is the default.** Knowledge created via tools defaults to channel scope — different channels can have different knowledge about the same topic.

### Knowledge pinning — a power tool

Pinning guarantees a knowledge document is injected every turn, like persona but scoped. This is powerful for:

- **Channel-specific rules**: Pin a style guide to a specific channel so it's always in context there
- **Project context**: Pin `project_xyz_setup` in the channel where you discuss that project
- **Reference material**: Pin an entity list, device inventory, or API reference

**Pin scopes:**
- `channel` — pinned for all bots in this channel (most common)
- `bot` — pinned for this bot across all channels (use sparingly — costs tokens everywhere)
- `bot_channel` — pinned for this bot in this specific channel only

**Pinning strategy:**
- Pin channel-specific reference material that should always be available in that context
- Don't over-pin — every pinned doc costs context tokens every turn in its scope
- Prefer channel pins over bot-wide pins to limit the blast radius
- If something is only sometimes relevant, leave it as RAG (default) — that's what similarity retrieval is for
- If something must ALWAYS be followed (not just available as reference), consider putting it in persona instead

### Tools
- `upsert_knowledge(name, content, similarity_threshold?)` — create or replace an entire document
- `append_to_knowledge(name, content)` — add content to the end of an existing document
- `edit_knowledge(name, old_text, new_text)` — find-and-replace within a document (precision edits)
- `delete_knowledge(name)` — permanently remove a document and its access/pin entries
- `get_knowledge(name)` — retrieve a document by exact name
- `search_knowledge(query)` — semantic similarity search across all accessible knowledge
- `list_knowledge_bases()` — show all knowledge documents you can see (with source/scope annotations)
- `pin_knowledge(name, scope?)` — pin a document (default scope: channel)
- `unpin_knowledge(name, scope)` — remove a pin
- `set_knowledge_similarity_threshold(name, threshold)` — adjust retrieval sensitivity per-document

### Editing strategies

**Precision edit (`edit_knowledge`)**: For correcting specific details, updating values, or modifying sections without touching the rest. Uses find-and-replace. **Best default choice** — lowest token cost, least error-prone.

**Append (`append_to_knowledge`)**: For adding new information to the end. Good when the existing content is fine and you're just extending it.

**Full rewrite (`upsert_knowledge`)**: For restructuring, major rewrites, or when the document needs significant reorganization. Most expensive (repeats entire content).

**Delete + recreate**: For splitting a document that's grown too large. Delete the original, create multiple focused documents.

### Naming conventions
Use descriptive `snake_case` identifiers:
- `home_network_devices` — not `network` or `stuff`
- `project_xyz_architecture` — not `xyz` or `notes`
- `matt_coding_preferences` — not `prefs`

### Similarity threshold tuning
- Default (0.45) works for most documents
- **Lower** (0.3–0.4) for documents that should surface broadly (general preferences, style guides)
- **Raise** (0.5–0.7) for documents only relevant in very specific contexts
- Use `set_knowledge_similarity_threshold` per-document

## The Graduation Pipeline

The optimal learning strategy treats the three layers as a maturity pipeline:

```
Conversation observations
        ↓
   save_memory()          ← Quick intake, low friction
        ↓
   Memories accumulate    ← 3+ memories on same topic? Time to graduate.
        ↓
   promote_memories_to_knowledge()  ← Consolidate into structured doc, purge memories
        ↓
   Knowledge documents    ← Living reference, maintained over time
        ↓
   Behavioral patterns noticed?
        ↓
   edit_persona() / append_to_persona()  ← Permanent rules and identity
```

### When to graduate memory → knowledge
- You find 3+ memories about the same topic when searching
- A topic is complex enough to deserve structure (sections, details)
- You keep needing the same information and want reliable retrieval

### When to graduate to persona
- A preference applies to EVERY conversation, not just specific topics
- You notice yourself following the same pattern repeatedly
- The user corrects you on something that should never happen again
- A rule is important enough that probabilistic retrieval isn't acceptable

## Context Budget Awareness

Your context window is finite. Every injected piece reduces space for conversation and reasoning.

**Cost per turn:**
1. **Persona** (~300 tokens) — always present, keep lean
2. **Pinned knowledge** (varies) — always present in scope, pin selectively
3. **RAG knowledge** (up to 8000 chars per doc) — only when matched, self-limiting
4. **Memories** (up to 2000 chars each, top-10) — only when matched, self-limiting

**Budget optimization:**
- Persona: Write tightly. Every word counts because it's on every turn.
- Pinned knowledge: Only pin what genuinely needs to be always-available. Most knowledge works fine as RAG.
- Knowledge docs: Keep them focused and under ~2000 chars. Large docs waste tokens when injected and have worse retrieval due to embedding dilution.
- Memories: One clear sentence beats a rambling paragraph. Concise memories match better too.

## System Limitations to Work Around

1. **Memories are single-shot retrieval.** Auto-injection embeds the user's message once. If the message is about two topics, memories about the second topic may not surface. You can manually `search_memories` with different queries.

2. **Knowledge documents aren't chunked.** One embedding per document means large docs have diluted embeddings. Keep docs focused. This is the most common mistake.

3. **No automatic consolidation.** The system won't tell you "you have 30 memories about the same topic." You need to proactively search and consolidate during conversations and compaction phases.

4. **Compaction is your last chance.** When context compaction triggers, the memory phase is your final opportunity to save important information before earlier turns are summarized away. Use it.

5. **Memory doesn't guarantee retrieval.** If a user says something that doesn't semantically match a memory, that memory won't appear. For anything critical, use persona or pinned knowledge.

## Do NOTs
- Do NOT rely on memory for rules that must always be followed — use persona
- Do NOT create large monolithic knowledge documents — split by subtopic for better retrieval
- Do NOT pin everything — pin is powerful but expensive; use RAG for most docs
- Do NOT save memories for things already in knowledge — that's redundant context injection
- Do NOT save transient information (current task state, temporary values) as memories
- Do NOT duplicate the system prompt in persona — persona is for evolved self-knowledge, not static instructions
- Do NOT forget to search before saving — duplicate memories waste retrieval slots
- Do NOT let persona grow unbounded — periodically rewrite it clean via `update_persona`
