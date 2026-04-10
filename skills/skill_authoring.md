---
name: Skill Authoring
description: How to author your own skills via manage_bot_skill — when to capture a pattern as a skill vs a reference file, schema, lifecycle, and trigger writing
triggers: skill, create skill, manage_bot_skill, capture pattern, reusable pattern, lesson learned, self-improvement, never make this mistake, author skill
category: core
---

# Skill Authoring

Skills you author become part of the fleet's RAG-indexed catalog. When a future user message is semantically related to one of your skill's triggers, the discovery layer surfaces it — no one has to remember it exists.

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

Create the skill **immediately**, not "later". Later doesn't happen.

## When NOT to Author a Skill

| Situation | Why not |
|---|---|
| One-off, situation-specific detail | Pollutes the catalog, gets pruned |
| Already covered by an existing skill | Use `action="patch"` or `action="merge"` instead |
| Personal context only YOU need | Use `memory/reference/` instead — bot-private, no RAG |
| Trivial acknowledgement of a correction | Just acknowledge and move on |

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
)
```

| Field | Required for create | Notes |
|---|---|---|
| `action` | yes | `create`, `update`, `list`, `get`, `delete`, `patch`, `merge` |
| `name` | yes | Slug. Becomes the skill's ID under `bots/{your_bot_id}/{slug}`. |
| `title` | yes | Display name in the UI. |
| `content` | yes | Markdown body. 50–50,000 chars. |
| `triggers` | recommended | Comma-separated phrases. THIS is what makes the skill discoverable. |
| `category` | optional | Free text — `troubleshooting`, `domain-knowledge`, `procedures`, etc. |

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
- **`action="patch"`** — surgical find/replace inside an existing skill. Cheaper than `update` for small additions.
- **`action="merge"`** — combine multiple related skills into one. Sources get deleted after merge.
- **Prune** — the hygiene loop automatically prunes skills that haven't surfaced in 30+ days. You don't need to delete manually.

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

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Creating a skill for a one-off | Just acknowledge and move on |
| Triggers are too generic ("error", "issue") | Use specific symptoms or domain anchors |
| Long preamble about what skills are | Lead with the rule. Future-you wants the answer fast. |
| Forgetting to author after a correction | Author IMMEDIATELY — "later" never comes |
| Re-creating an existing skill | `action="list"` first, then `patch` or `merge` instead |
