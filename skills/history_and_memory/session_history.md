---
name: Session History
description: How conversational history is structured across primary and scratch sessions, and when to use read_conversation_history, search_history, list_sub_sessions, and read_sub_session.
triggers: read_conversation_history, session history, scratch history, primary session, nearby session, prior session, what did we decide, current session archive, compacted history
category: core
---

# Session History

## Core Model

Conversation history is session-shaped, not one merged channel transcript.

- The current primary chat has its own history.
- Each scratch session has its own history.
- Other sub-sessions exist too, but treat them as separate sessions unless you inspect them deliberately.

When you switch sessions, you switch which history is "current."

## Tool Choice

### `read_conversation_history`

Use this for the current session's structured archive.

- In a primary session:
  - `recent` means the primary session
  - `index` means the primary session's section index
- In a scratch session:
  - `recent` means the current scratch session
  - `index` means the current scratch session's section index

Nearby sessions may be mentioned as pointers or short summaries, but they are not merged into the current session's index.

Common modes:

- `read_conversation_history(section="recent")`
- `read_conversation_history(section="index")`
- `read_conversation_history(section="search:<query>")`
- `read_conversation_history(section="tool:<id>")`

### `search_history`

Use this for raw cross-session message search across the whole channel.

Choose it when:

- the exact content might be in another session
- you need broad historical recall across multiple sessions
- you need older raw messages rather than the current session's section index

### `list_sub_sessions` and `read_sub_session`

Use these when adjacent sessions matter.

- `list_sub_sessions(channel_id=...)` shows the attached non-primary sessions
- `read_sub_session(session_id=...)` inspects one of them directly

Use this path when a nearby scratch, thread, pipeline, or eval run is likely relevant and you want to inspect it on purpose.

## Common Patterns

**"What did we just decide in this scratch pad?"**
Use `read_conversation_history(section="recent")` or `section="index"`.

**"What did we decide somewhere in this channel last week?"**
Use `search_history(...)`.

**"This scratch session probably branched off a main session decision."**
Use `read_conversation_history(...)` for the scratch session first, then `list_sub_sessions` / `read_sub_session` if you need adjacent context.

**"A summarized tool result hid the exact output."**
Use `read_conversation_history(section="tool:<id>")`.

## Common Mistakes

- Treating `read_conversation_history` as channel-wide search. It is current-session-first.
- Assuming nearby sessions are merged into the current section index. They are not.
- Using `search_history` for memory files. Use memory tools for that.
- Forgetting scratch sessions are first-class sessions with their own archive.

## Related Skills

- [History And Memory](index.md)
- [Memory Hygiene](memory_hygiene.md)
- `search_history`
- `context_mastery`
