---
name: channel-workspace
description: >
  Operational guide for bots running in a channel with workspace enabled.
  Trigger this skill whenever a Channel Workspace section appears in your system
  context, or when you are about to read, write, create, or reference any file
  in the channel workspace. Use it to decide when to write to workspace vs memory,
  how to manage active vs archived files, and how to search the archive correctly.
---

# Channel Workspace — Bot Operating Guide

You have access to a channel workspace: a set of files that persist across conversations
and represent the current operational state of this channel. This skill tells you how to
use it correctly.

---

## The Core Distinction

| | Channel Workspace | `memory.md` |
|---|---|---|
| **What it is** | Operational state for this channel | Durable knowledge for you as a bot |
| **Example contents** | Open punch lists, current orders, active project status | Client preferences learned, reliable vendors, patterns that recur |
| **When to write** | Any time state changes | Only when something is worth knowing forever, regardless of channel |
| **Survives channel deletion?** | No | Yes |

**Do not treat workspace as a substitute for memory.** After any significant event — a resolved
issue, a discovered preference, a vendor worth remembering, a reusable pattern — write the
durable takeaway to `memory.md`. The workspace is what is happening now. Memory is what you
should always know.

---

## Active Workspace Files

All files in the workspace root are injected into your context automatically. You do not need
to load them — they are already present.

**When to create a new file:**
- A new ongoing concern has enough distinct state to warrant its own file (e.g. `open_items.md`, `current_orders.md`)
- A file is getting too long to stay useful — split it

**When to update an existing file:**
- State has changed: an item resolved, an order shipped, a milestone hit
- New information arrived that belongs to an existing concern

**File writing rules:**
- Use relative paths — they resolve to the channel workspace automatically
- Write clean, structured markdown — these files will be re-injected on every future message
- Keep files focused. One concern per file. Do not create catch-all files.
- After writing, do not summarize what you wrote back to the user unless they asked — just confirm the action briefly.

---

## Archive

Resolved or retired files live in `archive/`. You do not see them inline.

**When to archive a file:**
- The concern it tracks is fully resolved and unlikely to recur soon
- The file has grown stale and is consuming context without adding value

**How to archive:**
1. Move the file to `archive/`
2. Update `archive_index.md` in the workspace root — add a row with filename, date, and a one-line summary

**`archive_index.md` format:**
```
| filename | archived_date | summary |
|---|---|---|
| henderson_punch_list.md | 2025-03-01 | Henderson project closed, all punch items resolved |
```

**How to search the archive:**
Use the `search_channel_archive` tool with a keyword or topic query. Do not attempt to list or
load archive files directly. The tool will return the content of matching files.

---

## Memory Checkpoint — Run This Mentally After Significant Events

After any of the following, ask yourself: *does anything here belong in memory.md?*

- A project closes or a major milestone completes
- A client preference is clearly stated ("she always wants warm whites, never cool")
- A vendor proves reliable or unreliable
- A recurring process pattern is confirmed
- A mistake is made that should not be repeated

If yes — write it to `memory.md` before the conversation ends. Do not assume you will
find it in the workspace next time. The workspace may be archived, cleared, or the
channel may change bots.

---

## Data Files

The `data/` subfolder holds binary files (PDFs, images, spreadsheets, etc.) that are **not**
auto-injected into context. These files are indexed for search.

**When data arrives** (user sends a PDF, image, or any non-markdown file):
1. Save it to `data/` via `exec_command`
2. Create or update a workspace `.md` file that describes the data — what it is, key details,
   when it was received, and a reference to the data path

This way the context always has a human-readable summary while the raw file is preserved for
reference. Use `search_channel_workspace` to search data file content.

---

## Cross-Channel Search

Each channel has its own workspace. When the user references another project or channel:

1. Use `list_workspace_channels` to see all channels with workspace enabled — this returns
   display names and channel IDs
2. Use `search_channel_workspace(query, channel_id=...)` to search that channel's files
   (both active and archived)

This is useful when:
- The user says "do it like the Henderson project" — find the Henderson channel and search it
- You need to compare approaches across projects
- Information from one project is relevant to another

**Do not read another channel's files directly via exec_command** — use the search tool.
The search is indexed and will return relevant chunks efficiently.

---

## Quick Decision Reference

| Situation | Action |
|---|---|
| New ongoing task or concern | Create a workspace file |
| Existing concern updated | Update the relevant workspace file |
| Task resolved, file no longer useful | Archive it, update index |
| Need info from old resolved file | Use `search_channel_archive` tool |
| User references another project | `list_workspace_channels` then `search_channel_workspace` |
| Received a PDF/image/binary | Save to `data/`, describe in a workspace `.md` file |
| Learned something durable about client/vendor/pattern | Write to `memory.md` |
| State change is minor / transient | No file needed — conversation context is enough |