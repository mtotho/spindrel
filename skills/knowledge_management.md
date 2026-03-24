# SKILL: Knowledge Management & Workspace Organization

Applies to any agent with: a memory/knowledge system, a persistent workspace, and shell access.
Tool names and layer names are illustrative — map them to your actual tool names.

---

## Core Principle: Retrieval Reliability

The only thing that matters when choosing where to store something is:
**Will this information actually be in my context when I need it?**

Every storage layer has a different answer to that question:

| Layer | Reliability | Retrieval mechanism | Fails when |
|-------|------------|---------------------|------------|
| **Always-injected (persona/pinned)** | ~100% | Prepended every turn | Never (within token budget) |
| **Structured knowledge (RAG)** | 60–80% | Vector similarity match | User message doesn't semantically match |
| **Episodic memory** | 40–60% | Vector similarity match | Message doesn't match, or buried in top-K |
| **Workspace files** | 100% (explicit) | You read them on demand | You forget to read them |

Use the layer whose reliability matches the stakes of the information.

---

## Layer 1: Always-Injected Context ("Persona / Pinned Rules")

**This is the most powerful layer.** It is in your context every single turn with no retrieval step.

### What belongs here
- Rules that must never be broken ("never run destructive commands without asking")
- Communication and behavioral patterns ("user prefers concise output, no hedging")
- Core identity and role
- Anything where missing it even once causes a bad outcome

### What does NOT belong here
- Project-specific facts (use knowledge docs)
- Observations and notes (use memory or files)
- Anything you'd only need occasionally
- Large reference material — every token here costs you on every turn

### Discipline
- Keep it tight. Under ~300 tokens is a good target.
- Structure it with clear sections so edits are surgical.
- Periodically rewrite the whole thing rather than letting appended fragments accumulate into noise.
- If you find yourself ignoring or working around something in this layer, it's stale — remove it.

---

## Layer 2: Structured Knowledge Documents

These are living documents about topics, projects, or systems. Retrieved by semantic similarity.

### The single most important rule: keep documents focused

Each document gets **one embedding for all its content**. A document covering 5 subtopics produces an averaged embedding that matches none of them well. A document about one focused topic retrieves reliably.

**Bad:** one `home_lab` doc with network, hardware, services, and DNS all mixed together  
**Good:** `home_lab_network`, `home_lab_services`, `home_lab_hardware` — each small and specific

Target: one coherent topic per doc, under ~2000 characters. If it's grown past that with multiple sections, split it.

### Naming
Use descriptive identifiers, not vague shorthand:
- `project_bookt_architecture` not `bookt`
- `docker_build_conventions` not `docker`
- `michael_coding_preferences` not `prefs`

### Editing strategy
In order of preference:
1. **Surgical edit** (find-and-replace a specific section) — use this by default
2. **Append** — for adding new information without touching existing content
3. **Full rewrite** — for restructuring or major changes only; most expensive
4. **Split** — when a doc has grown too large: delete original, create focused sub-docs

### Pinning
If your system supports pinning a knowledge doc for guaranteed injection, use it for:
- Channel or project-specific reference that should always be available in that context
- Small, critical reference docs (entity lists, API shapes, environment variables)

Don't over-pin. Most docs work fine as RAG. Pin only what genuinely needs to be always-present.

---

## Layer 3: Episodic Memory

Individual facts and observations. Easy to create, unreliable to retrieve. Treat as an **inbox, not a filing cabinet**.

### Save freely — but consolidate aggressively
- Save observations during conversation that might be useful later
- Quick corrections ("actually that service runs on 8001 not 8000")
- Anything too small to be a knowledge doc yet

### Do NOT save memories for
- Rules that must always be followed → use always-injected layer instead
- Things already in knowledge docs → redundant, wastes retrieval slots
- Transient task state → use workspace files
- Routine command output

### Always search before saving
Duplicate memories dilute retrieval. Before creating a memory, search to see if one already exists on that topic.

### The graduation pipeline

```
Conversation observation
        ↓
    save to memory          ← low friction intake
        ↓
    3+ memories on same topic?
        ↓
    promote to knowledge doc    ← consolidate + purge originals
        ↓
    behavioral pattern noticed?
        ↓
    move to always-injected layer   ← permanent rules only
```

Compaction / heartbeat cycles are the right time to run this pipeline. Don't let memory accumulate indefinitely.

---

## Layer 4: Workspace Files (Persistent, On-Demand)

Files in your workspace (`/workspace` or equivalent) are **100% reliable** — they never fail to contain what you put in them. The tradeoff is that you must explicitly read them; they are not auto-injected.

### Use workspace files for
- Project state that's too large or too structured for memory (`status.json`, `todos.json`)
- Generated artifacts (HTML pages, reports, config files)
- Journal / log history
- Data that would bloat context if injected automatically
- The **source of truth** for anything that has a UI representation

### File organization conventions
```
/workspace/
  data/
    status.json          # current phase, last updated, top-level flags
    todos.json           # structured task list (sync with todos tool)
    journal/
      YYYY-MM-DD.md      # append-only daily log
    proposals/
      index.json         # proposal registry
      YYYY-MM-DD-slug.md # individual proposals
  web/                   # if serving a dashboard
    index.html
    style.css
    *.js
  dev-todos/
    active/              # prioritized work queue
    done/                # completed items (archive, don't delete)
```

Add folders as topics emerge. If you're storing a class of data with no home, that's a missing folder — create it and note it.

### File editing rules
See `@skill:web_editor_light` for HTML/CSS/JS. For all files:
- **Never use `>` redirect on an existing file** — it destroys content
- Always read before editing so you know what you're modifying
- Use Python `str.replace()` for surgical edits
- Use `>>` or `append` only for additive operations
- Verify after every write with `cat` or `grep`

---

## Workspace Self-Improvement (Python Docker)

Your workspace is a Python Docker container. You can install tools, write scripts, and improve your own environment. Use this.

### Install tools when they make a task significantly easier

```bash
# Better HTML/DOM editing
pip install -q beautifulsoup4 lxml

# Structured JSON diffing / patching
pip install -q deepdiff jsonpatch

# YAML manipulation
pip install -q pyyaml

# HTTP calls from shell (usually present, but)
pip install -q requests httpx

# Lightweight SQLite for structured local state
# (sqlite3 is in stdlib — no install needed)
```

Don't install blindly. Install when the stdlib alternative would be fragile (e.g., parsing HTML with regex, editing JSON by string replacement).

### Write reusable scripts

If you find yourself doing the same operation more than twice, write a script:

```bash
# Example: a helper to safely edit a specific section of a JSON file
cat > /workspace/scripts/patch_json.py << 'EOF'
#!/usr/bin/env python3
"""Usage: patch_json.py <file> <dot.path.key> <value>"""
import sys, json
path, key_path, value = sys.argv[1], sys.argv[2].split('.'), sys.argv[3]
with open(path) as f:
    data = json.load(f)
ref = data
for k in key_path[:-1]:
    ref = ref[k]
ref[key_path[-1]] = json.loads(value)
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
EOF
chmod +x /workspace/scripts/patch_json.py
```

### Maintain a scripts inventory
Keep `/workspace/scripts/README.md` updated when you add a script. Future you won't remember what `patch_json.py` does.

### Validate your own workspace periodically
During heartbeat cycles, run a quick sanity check:
```bash
# Are expected files present?
for f in /workspace/data/status.json /workspace/data/todos.json; do
  [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"
done

# Are JSON files valid?
python3 -c "import json, glob
for f in glob.glob('/workspace/data/**/*.json', recursive=True):
    try: json.load(open(f)); print(f'OK: {f}')
    except Exception as e: print(f'INVALID: {f} — {e}')
"
```

---

## Decision Framework: Where Does This Go?

```
Is this a rule or preference that must apply to every conversation?
  YES → always-injected layer (persona/pinned)
  NO  ↓

Is this a structured fact about a project, system, or topic?
  YES → knowledge document (focused, one topic per doc)
  NO  ↓

Is this a quick observation, correction, or note to self?
  YES → memory (then graduate to knowledge when 3+ accumulate)
  NO  ↓

Is this state, history, or data too large for auto-injection?
  YES → workspace file (read on demand)
  NO  ↓

Is this transient task state that won't matter after this session?
  → Don't save it anywhere.
```

---

## Common Mistakes

| Mistake | Problem | Fix |
|---------|---------|-----|
| Saving rules to memory | Won't reliably fire; you'll break the rule | Move to persona/pinned |
| One giant knowledge doc | Diluted embedding, poor retrieval | Split into focused sub-docs |
| Using memory as a filing cabinet | Retrieval is probabilistic, not guaranteed | Graduate to knowledge or files |
| Never consolidating memories | Top-K slots fill with low-value entries | Run graduation pipeline each heartbeat |
| Pinning everything | Blows context budget on every turn | Pin sparingly; use RAG as default |
| Overwriting files with `>` | Destroys existing content | Use Python replace or `>>` for append |
| Large monolithic workspace files | Hard to read, hard to edit surgically | Split by concern; use JSON structure |
| Ignoring `scripts/` for repeated ops | Re-deriving the same logic every time | Write a script, document it |