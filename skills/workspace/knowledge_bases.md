---
name: Knowledge Bases
description: How to use the channel + bot knowledge-base folders and when to reach for the narrow search tools
triggers: knowledge base, search_channel_knowledge, search_bot_knowledge, kb, lookup, facts, what do you know
category: workspace
---

# Knowledge Bases — Bot Operating Guide

Every channel has an auto-indexed `knowledge-base/` folder, and every bot has its own
`knowledge-base/` folder that travels across every channel.

Current runtime behavior is:

1. **Channel knowledge auto-retrieval.** Relevant excerpts from
   `channels/<channel_id>/knowledge-base/` are surfaced automatically in normal
   channel chat/execution when they match the user's message.
2. **Bot knowledge auto-retrieval.** Relevant excerpts from the bot-wide
   `knowledge-base/` are also surfaced automatically by default, unless the bot's
   workspace settings have switched that layer to search-only mode.
3. **Narrow search tools.** Both the channel and bot knowledge bases can always be
   searched directly with the tools below.

Do not assume any knowledge base is guaranteed to already be in the prompt. Planning
and background profiles may suppress both. The safe model is: use the narrow KB tools
whenever the answer matters.

---

## The two folders

| Folder | Scope | Example contents |
|---|---|---|
| `channels/<channel_id>/knowledge-base/` | Facts that belong to **this channel** only | Household shopping list, this project's decisions, members of this room |
| `knowledge-base/` (or `bots/<bot_id>/knowledge-base/` for shared-workspace bots) | Facts that travel with **you, the bot**, across every channel | Your persona quirks, your preferred tools, reusable templates you've authored |

Subfolders inside either KB are organizational only. Everything is indexed recursively
— `knowledge-base/recipes/pasta.md` works exactly the same as `knowledge-base/pasta.md`.
Do not expect a subfolder to hard-scope retrieval.

---

## Which tool to use

- **`search_channel_knowledge(query)`** — the user is asking about something that belongs
  to *this channel*: "what's on the shopping list", "what did we decide about the kitchen
  remodel", "who lives in this house?"
- **`search_bot_knowledge(query)`** — the user is asking about something about *you* or
  about knowledge that should be the same in every channel: "what are your allergies",
  "what's the canonical curl recipe you use", "list your tools."
- **`search_channel_workspace(query)`** — broader than `search_channel_knowledge`. Also
  covers `data/`, `archive/`, and top-level `.md` files. Reach for this when the user is
  asking *where we did X*, not *what you know about X*.
- **`search_workspace(query)`** — broadest. Everything you have workspace access to. Use
  when neither knowledge-base had the answer and the user's question is clearly about code
  or documents, not facts.

If the user's ask could plausibly hit either knowledge-base, call both.

---

## Writing to a knowledge base

Use the file tool to write curated markdown files into the appropriate folder:

```
file(operation="write", path="knowledge-base/diet.md", content="# Diet\n- vegetarian\n- no cilantro")
```

or

```
file(operation="write", path="channels/<channel_id>/knowledge-base/shopping.md", content="...")
```

**When to write.** Prefer writing to a knowledge base over writing to `memory.md` when:

- The content is structured / list-like enough that the user might want to edit it themselves
- It's a *reference* ("the wifi password is X", "my kids' birthdays are…") rather than a
  behavioral note ("user prefers short replies")
- Several related facts group together — give them their own file inside `knowledge-base/`
  rather than bloating `memory.md`

Keep `memory.md` for short, high-signal behavioral notes. Keep knowledge-bases for
browsable reference material.

### Shared-understanding briefs

When the conversation starts with an interview / clarification pass, the default durable
home for that shared understanding is:

- `channels/<channel_id>/knowledge-base/project-brief.md`

Use that file for the current room's objective, success criteria, constraints, non-goals,
decisions, and open questions.

Only use the bot-wide KB when the user explicitly wants the brief to travel across channels:

- `knowledge-base/briefs/<slug>.md`
- for shared-workspace bots, the equivalent bot-root path under `bots/<bot_id>/knowledge-base/briefs/<slug>.md`

---

## Discoverability guardrails

- Do **not** invent a `knowledge-base/` folder with a different name. The convention is
  exactly `knowledge-base/` (with a hyphen).
- If you see stale entries in a KB file, rewrite or delete the file. Stale auto-surfaced
  facts are worse than no auto-surfaced facts.
- You do not need to configure anything. Segments, embedding models, similarity
  thresholds — all inherited defaults. The KB convention is zero-config by design.
- The one advanced exception is bot KB retrieval mode: operators can switch the bot-wide
  KB to search-only if they want the files indexed but never auto-injected.
