---
name: Agent Knowledge System
---

# Agent Knowledge System

This skill explains how to manage file-based skills and knowledge in the agent server.

## Directory Layout

The server watches the following directories for `.md` files and auto-syncs them into the database:

| Directory | What it creates | Scope |
|-----------|----------------|-------|
| `skills/*.md` | Skills (global) | Available to any bot that lists the skill |
| `bots/{id}/skills/*.md` | Skills (bot-scoped ID prefix) | Skill ID = `bots/{id}/{stem}` |
| `knowledge/*.md` | Knowledge entries (cross-bot) | `bot_id=NULL` — visible to all bots |
| `bots/{id}/knowledge/*.md` | Knowledge entries (bot-scoped) | `bot_id={id}` |
| `integrations/{id}/skills/*.md` | Skills from integration | Source type = `integration` |
| `integrations/{id}/knowledge/*.md` | Knowledge from integration | Source type = `integration` |

## File-Sourced vs Tool-Written Entries

- **File-sourced** entries (`source_type = file | integration`) are **read-only to tools**. Calling `upsert_knowledge` or `append_to_knowledge` on them will return an error.
- **Tool-written** entries (`source_type = tool`, the default) can be freely modified by knowledge tools.
- The admin UI shows a source badge and disables Edit/Delete for file-sourced rows.

## Editing File-Sourced Entries

To update a file-sourced skill or knowledge entry, edit the `.md` file on disk. The server picks up changes automatically:

1. **Live (via watcher)**: Seconds after saving the file, the watcher detects the change, re-syncs the row, and re-embeds it. No restart needed.
2. **On restart**: `sync_all_files()` runs during startup and catches any changes missed while the server was down.

### Example: update a global knowledge file

```bash
# Edit the file
nano knowledge/home_network.md

# Server automatically re-syncs within a few seconds
# Verify in admin: /admin/knowledge → look for "file" badge on "home_network"
```

### Example: create a bot-specific skill

```bash
mkdir -p bots/my_bot/skills
cat > bots/my_bot/skills/my_skill.md << 'EOF'
# My Skill

Content here...
EOF
# Server picks it up automatically as skill ID "bots/my_bot/my_skill"
```

## Persistence Across Deployments

File-sourced entries live in the database but are re-synced from files on every startup. To persist changes across redeployments, **commit and push the `.md` files to git**:

```bash
git add skills/ knowledge/ bots/
git commit -m "update knowledge files"
git push
```

## Manual Sync Trigger

An operator can force a full re-scan without restarting:

```
POST /admin/file-sync
```

This rescans all directories and returns a JSON summary of added/updated/deleted rows.

## Orphan Cleanup

If a `.md` file is **deleted** from disk:
- On next startup (or watcher event), the corresponding DB row is automatically removed.
- Manual knowledge rows (created by tools) are never deleted by the file sync system.


## Commit, Merge Request, Notify

After any changes, please commit the change, push for review and notify the channel.