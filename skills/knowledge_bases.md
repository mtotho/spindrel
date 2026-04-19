---
name: Knowledge Bases
description: How to use the channel + bot knowledge-base folders and when to reach for the narrow search tools
triggers: knowledge base, search_channel_knowledge, search_bot_knowledge, kb, lookup, facts, what do you know
category: workspace
---

# Knowledge Bases — Bot Operating Guide

Every channel has an auto-indexed `knowledge-base/` folder, and every bot has its own
`knowledge-base/` folder that travels across every channel. Content you or the user drops
there is automatically surfaced to you in two ways:

1. **Auto-retrieval.** Relevant excerpts are injected into your context on every turn,
   scored by relevance to the user's message. You do not need to request them.
2. **Narrow search tools.** When you know what you're looking for, call one of the two
   tools below for a targeted lookup instead of relying only on auto-retrieval.

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

---

## Discoverability guardrails

- Do **not** invent a `knowledge-base/` folder with a different name. The convention is
  exactly `knowledge-base/` (with a hyphen).
- If you see stale entries in a KB file, rewrite or delete the file. Stale auto-injected
  facts are worse than no auto-injected facts.
- You do not need to configure anything. Segments, embedding models, similarity
  thresholds — all inherited defaults. The KB convention is zero-config by design.
