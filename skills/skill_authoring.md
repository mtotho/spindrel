---
name: Skill Authoring
description: How to author your own skills via manage_bot_skill — when to capture a pattern as a skill vs a reference file, schema, lifecycle, and trigger writing
triggers: skill, create skill, manage_bot_skill, capture pattern, reusable pattern, lesson learned, self-improvement, never make this mistake, author skill
category: core
---

# Skill Authoring

Skills you author become part of the fleet's RAG-indexed catalog. When a future user message is semantically related to one of your skill's triggers, the discovery layer surfaces it — no one has to remember it exists.

Skills can also carry one or more **named scripts**: reusable `run_script` snippets for multi-step tool workflows. Use them when the durable lesson is executable orchestration, not just prose.

This is the most powerful form of self-improvement available to you. Use it.

---

## When to Author a Skill

Author a skill the moment any of these happen:

| Trigger | Why |
|---|---|
| User corrects your approach | Same correction will hit another bot tomorrow |
| You discover a domain rule | Domain knowledge isn't in your training data |
| You repeatedly look up the same info | Repeated lookups = missing skill |
| You resolve a tricky gotcha | Next session shouldn't re-derive it |
| You refine a procedure that worked | Capture the working version, not the failed attempts |
| A tool returns surprising behavior | Save the surprise + the workaround |
| You build a reusable multi-step tool workflow | Save the code as a named script attached to the skill |

Create the skill **immediately**, not "later". Later doesn't happen.

## When NOT to Author a Skill

| Situation | Why not |
|---|---|
| One-off, situation-specific detail | Pollutes the catalog, gets pruned |
| Already covered by an existing skill | Use `action="patch"` or `action="merge"` instead |
| Personal context only YOU need | Use `memory/reference/` instead — bot-private, no RAG |
| Trivial acknowledgement of a correction | Just acknowledge and move on |

If the knowledge belongs in a skill but the execution also matters, keep both:
- prose in the skill body for discovery and explanation
- code in attached named scripts for direct reuse with `run_script(skill_name=..., script_name=...)`

## Skill vs Reference File

| | Skill | Reference File |
|---|---|---|
| Storage | RAG-indexed in DB | `memory/reference/*.md` on disk |
| Discovery | Auto-surfaces by trigger phrase | Fetched by name only |
| Scope | Fleet-visible (your bot owns the path) | Bot-private |
| Use for | Reusable patterns the fleet benefits from | Personal scratchpads, learned client preferences |

**Default to skills.** Reference files are for things only you need.

---

## The Schema

```
manage_bot_skill(
    action="create",
    name="my-pattern-slug",        # lowercase, hyphens, becomes bots/{your_id}/{slug}
    title="Human Readable Title",  # what the working-set UI shows
    content="...",                  # full markdown body
    triggers="trigger one, trigger two, key phrase",  # comma-separated
    category="troubleshooting",    # organizational tag
    scripts=[{
        "name": "workflow-slug",
        "description": "When to run this workflow",
        "script": "from spindrel import tools\n...",
        "timeout_s": 60,
    }],
)
```

| Field | Required for create | Notes |
|---|---|---|
| `action` | yes | `create`, `update`, `list`, `get`, `delete`, `patch`, `merge`, `get_script`, `add_script`, `update_script`, `delete_script` |
| `name` | yes | Slug. Becomes the skill's ID under `bots/{your_bot_id}/{slug}`. |
| `title` | yes | Display name in the UI. |
| `content` | yes | Markdown body. 50–50,000 chars. |
| `triggers` | recommended | Comma-separated phrases. THIS is what makes the skill discoverable. |
| `category` | optional | Free text — `troubleshooting`, `domain-knowledge`, `procedures`, etc. |
| `scripts` | optional | Named `run_script` snippets for reusable multi-step tool workflows. |

### Named Script CRUD

```python
manage_bot_skill(action="get_script", name="my-pattern-slug", script_name="workflow-slug")
manage_bot_skill(action="add_script", name="my-pattern-slug", script_name="workflow-slug", script_description="When to run it", script_body="from spindrel import tools\n...", script_timeout_s=60)
manage_bot_skill(action="update_script", name="my-pattern-slug", script_name="workflow-slug", script_body="...")
manage_bot_skill(action="delete_script", name="my-pattern-slug", script_name="workflow-slug")
run_script(skill_name="my-pattern-slug", script_name="workflow-slug")
```

---

## Writing Good Triggers

Triggers are the load-bearing part. A skill with bad triggers might as well not exist — it'll never surface.

**Good triggers** are phrases the user is likely to say next time the situation comes up:

- ✅ `"deployment fails", "server won't start", "container exits"` — natural-language symptoms
- ✅ `"Henderson project", "client preferences", "warm whites"` — domain anchors
- ❌ `"skill", "knowledge", "important"` — too generic, will surface for anything
- ❌ `"the thing we discussed yesterday"` — not what a user will ever type

Aim for 4–8 triggers per skill, mixing symptoms and domain anchors.

---

## Lifecycle

```
list → get → patch / merge → (eventually) prune
```

- **`action="list"`** — see all your authored skills with surface counts. Run this when starting work in a new domain to see what's already captured.
- **`action="get"`** — fetch a specific skill's full content.
- **`action="get_script"`** — fetch the full body of one attached named script.
- **`action="patch"`** — surgical find/replace inside an existing skill. Cheaper than `update` for small additions.
- **`action="merge"`** — combine multiple related skills into one. Sources get deleted after merge.
- **`action="add_script"` / `update_script` / `delete_script`** — maintain attached reusable workflows without touching the prose body.
- **Prune** — the hygiene loop automatically prunes skills that haven't surfaced in 30+ days. You don't need to delete manually.

### Pruning vs deletion

Pruning drops your enrollment row. Deletion archives the skill from the catalog for everyone. They are not interchangeable.

- To stop a catalog skill from cluttering **your** working set: `prune_enrolled_skills(skill_ids=[...])`. Discovery will re-enroll it the next time a turn matches it.
- **Do not call `manage_bot_skill(action="delete")` on catalog skills you don't own** — that archives the skill itself, not just your enrollment. Only delete skills under your own `bots/{your_id}/...` namespace.

This rule is also enforced via the scheduled skill-review prompt; keep both surfaces aligned.

---

## Examples

### Capturing a user correction
```
manage_bot_skill(
    action="create",
    name="prefer-rg-over-grep",
    title="Use ripgrep, not grep",
    content="# Always use ripgrep (`rg`) not `grep`\n\nUser corrected this twice — `grep` is slower and doesn't respect .gitignore.\n\n## When\nAny shell search across files.\n\n## How\n```sh\nrg 'pattern' path/\n```",
    triggers="grep, search files, find in files, recursive search, ripgrep",
    category="tool-preferences",
)
```

### Capturing a domain rule
```
manage_bot_skill(
    action="create",
    name="invoice-cutoff-dates",
    title="Invoice cutoff is the 25th",
    content="# Henderson project — invoice cutoff\n\nBilling closes the 25th of each month. Anything submitted later rolls into the next cycle.",
    triggers="Henderson invoice, billing cutoff, when to bill, end of month billing, invoice deadline",
    category="domain-knowledge",
)
```

### Refining an existing skill
```
manage_bot_skill(
    action="patch",
    name="prefer-rg-over-grep",
    old_text="`grep` is slower",
    new_text="`grep` is slower, lacks color output by default",
)
```

### Attaching a reusable workflow
```
manage_bot_skill(
    action="add_script",
    name="prefer-rg-over-grep",
    script_name="search-repo",
    script_description="When you need to search the repo quickly with rg.",
    script_body="from spindrel import tools\nprint(tools.exec_command(command='rg \"pattern\" .'))\n",
    script_timeout_s=45,
)
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Creating a skill for a one-off | Just acknowledge and move on |
| Triggers are too generic ("error", "issue") | Use specific symptoms or domain anchors |
| Long preamble about what skills are | Lead with the rule. Future-you wants the answer fast. |
| Forgetting to author after a correction | Author IMMEDIATELY — "later" never comes |
| Re-creating an existing skill | `action="list"` first, then `patch` or `merge` instead |
| Burying code inside the markdown body | Store executable workflows as attached named scripts instead |
| Calling `manage_bot_skill(action="delete")` on a catalog skill you don't own | That archives the skill for everyone. Use `prune_enrolled_skills(skill_ids=[...])` to drop just your enrollment. |
