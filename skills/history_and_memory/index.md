---
name: History And Memory
description: Entry point for chat history and memory behavior. Explains which follow-up skill to read for current-session history, cross-session raw search, and periodic memory hygiene.
triggers: conversation history, chat history, scratch session, session history, memory hygiene, what did we decide, where is history, prior session, nearby session
category: core
---

# History And Memory

Use this family when the question is about prior conversation state rather than where durable knowledge should live.

## Read This First When

- You need to understand current session vs nearby sessions
- You are in a scratch session and need to know what "history" means there
- You are deciding between `read_conversation_history`, `search_history`, `list_sub_sessions`, and `read_sub_session`
- You are running a memory maintenance pass and want the history model straight before curating memory

## Which Skill Next

- [Session History](session_history.md)
  Read this for the session model and tool selection.
- [Memory Hygiene](memory_hygiene.md)
  Read this for scheduled maintenance and curation behavior.
- `search_history`
  Use this when you already know you need raw cross-session message search.
- `context_mastery`
  Use this when the question is where information should live after you find it.

## The Short Version

- `read_conversation_history` follows the current session.
- `search_history` searches raw messages across the whole channel.
- `list_sub_sessions` and `read_sub_session` are for deliberate inspection of adjacent sessions.
- Scratch, primary, thread, and pipeline sessions are all session-shaped, but they do not share one merged runtime archive.
