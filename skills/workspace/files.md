---
name: Workspace Files
description: Guide for using the file tool vs exec_command for reading, writing, editing, and searching files
triggers: file tool, read file, write file, append, edit file, grep, glob, search code, find files, exec_command, workspace files
category: core
---

# Workspace Files — `file` Tool Guide

You have a `file` tool for direct file operations inside your workspace. It bypasses the shell entirely — no quoting issues with apostrophes, backticks, dollar signs, or special characters.

---

## When to Use Which Tool

| Task | Use `file` | Use `exec_command` |
|---|---|---|
| Read a file | `file(read, path)` | — |
| Write/create a file | `file(write, path, content)` | — |
| Append to a file | `file(append, path, content)` | — |
| Find-and-replace in a file | `file(edit, path, find, replace)` | — |
| Replace a markdown section by heading | `file(replace_section, path, heading, content)` | — |
| Archive old entries from a log | `file(archive_older_than, path, older_than)` | — |
| Bundle multiple ops atomically | `file(batch, ops=[...])` | — |
| List directory contents | `file(list, path)` | — |
| Delete a file | `file(delete, path)` | — |
| Create directories | `file(mkdir, path)` | — |
| Move/rename a file | `file(move, path, destination)` | — |
| **Literal/regex text search** | `file(grep, path, pattern)` | — |
| **Find files by name pattern** | `file(glob, path, pattern)` | — |
| Run a program/script | — | `exec_command` or `delegate_to_exec` |
| Git operations | — | `exec_command` |
| Pipe commands / process data | — | `exec_command` |
| Install packages | — | `exec_command` |
| Complex multi-step shell tasks | — | `exec_command` |

**Rule of thumb**: If you're just reading, writing, or searching files, use `file`. If you need to *execute* something, use `exec_command`.

**Search tools — which one?**
- `file(grep, …)` — **literal** text / regex search when you know the exact string (function name, error message, config key, import path). Fast, deterministic.
- `search_workspace(query)` — **semantic** search via embeddings. Use for "find code that does X" when you don't know the exact names involved.
- `file(glob, …)` — find files by **filename** pattern (e.g. all `test_*.py` files). Doesn't look inside files.

---

## Memory Patterns

### Update a section in MEMORY.md (preferred)

```
file(operation="edit", path="memory/MEMORY.md", find="status: pending", replace="status: complete")
```

### Add a new section to MEMORY.md

```
file(operation="append", path="memory/MEMORY.md", content="\n## New Finding\n- Key insight here\n")
```

### Write a daily log entry

```
file(operation="append", path="memory/logs/2026-03-30.md", content="\n### 14:30 — Task completed\n- Details here\n")
```

### Create a reference document

```
file(operation="create", path="memory/reference/deployment-guide.md", content="# Deployment Guide\n\n...")
```

`create` errors if the path already exists — use it for every new-file write so you never
clobber a doc by accident. To INTENTIONALLY rewrite an existing file: read it first, then
`file(operation="overwrite", path="...", content="...")`. Without a prior `read`, `overwrite`
refuses — this is the safety net that prevents "I wrote a shrunken version because I forgot
what else was in there" bugs.

For JSON data files, use `file(operation="json_patch", path="...", patch=[...])` with RFC 6902
operations. Example: `[{"op": "replace", "path": "/shows/tt123/state", "value": "done"}]`.
The tool reads, applies the patch, and writes — so keys you didn't mention survive untouched.
This is how you update `data/tracked-*.json` and similar files safely.

### Replace a markdown section by its heading

When you need to rewrite a whole section of a markdown file, don't send the old contents as
the `find` string — use `replace_section`, which bounds the edit by heading level:

```
file(
  operation="replace_section",
  path="memory/MEMORY.md",
  heading="## Reflections",
  content="- New reflection 1\n- New reflection 2\n",
)
```

It replaces everything under `## Reflections` up to the next heading of the same or higher
level (or end of file). Idempotent — running it twice is safe. If the heading doesn't exist
and `create_if_missing=True` (default), the section is appended.

Why prefer it over `edit`: `edit` needs a `find` string that matches verbatim, and a
JSON-escaped `\n` in that string silently fails to match real newlines. `replace_section`
takes a heading name instead, sidestepping the trap entirely.

### Archive old log entries in place

```
file(operation="archive_older_than", path="memory/logs/activity.md", older_than="14d")
```

The tool parses dated `### YYYY-MM-DD` headers, moves everything older than the window
to a sibling archive file (e.g. `memory/logs/activity.archive.md`), and leaves the newer
entries in place. Idempotent; safe to run repeatedly.

### Bundle multiple ops into one transaction

When you have a group of related edits, wrap them in `batch` so they run as one iteration:

```
file(operation="batch", ops=[
  {"operation": "append", "path": "memory/logs/2026-04-24.md", "content": "..."},
  {"operation": "replace_section", "path": "memory/MEMORY.md", "heading": "## Today", "content": "..."},
  {"operation": "archive_older_than", "path": "memory/logs/activity.md", "older_than": "30d"},
])
```

`archive_older_than` is batch-eligible — bundle it with the log-promotion edits in a
hygiene pass. Nested `batch` is rejected.

For hygiene-specific patterns (JSON-escape trap on `find`, why batching archive with
log-promotion matters, multi-channel sweep discipline), see
[`history_and_memory/memory_hygiene`](../history_and_memory/memory_hygiene.md).

Full list of write-family ops: `create` (new file), `overwrite` (full rewrite after
`read`), `edit` (find/replace), `append` (add to end), `json_patch` (RFC 6902 on JSON),
`replace_section` (heading-bounded markdown edits), `archive_older_than` (age-based log
archive), `batch` (atomic multi-op).

---

## Searching Code — `grep` and `glob`

### Find where a function is defined or called

```
file(operation="grep", path=".", pattern=r"def assemble_context")
file(operation="grep", path="app/", pattern=r"assemble_context\(")
```

Output is JSON with `matches: [{file, line, text}, …]`, `count`, `files_scanned`, `truncated`. Common junk dirs (`.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, …) and binary files are always skipped.

### Grep only certain files with `include`

```
file(operation="grep", path=".", pattern="TODO", include="*.py")
file(operation="grep", path="app/", pattern="deprecated", include="*.md")
```

### Find files by name

```
file(operation="glob", path=".", pattern="**/test_*.py")
file(operation="glob", path="app/services", pattern="*.py")
file(operation="glob", path=".", pattern="**/MEMORY.md")
```

`*` matches one path segment, `**` recurses. Results are sorted newest-modified first.

### Search a single file

`grep` accepts a file path as the root, not just a directory:

```
file(operation="grep", path="app/main.py", pattern=r"lifespan")
```

### When grep vs search_workspace

- Know the exact string or regex → **grep** (fast, precise, no embeddings needed).
- Fuzzy/conceptual search ("where do we rate-limit outgoing requests?") → **search_workspace** (semantic).
- Never shell out to `exec_command "grep -r …"` for code search — the `file` tool avoids the shell-quoting hazards that motivated it in the first place.

---

## Edit Safety

1. **Read before editing** when you need to be precise. Use `file(read, path)` first to see exact content.
2. **Try to use exact match strings.** The tool has whitespace flexibility (extra spaces, tabs, newlines are forgiven), but exact matches are fastest and most reliable.
3. **Use `replace_all` only when you're sure.** Default is first-occurrence only.
4. **For complex restructuring**, read the file, construct the full new content, and use `write`.
5. **If edit fails**, the error will show the closest matching text from the file — use it to retry with the correct string.

---

## Common Mistakes

| Mistake | What Happens | Do This Instead |
|---|---|---|
| Using `exec_command` with `echo '...'` for text containing `'` | Shell quoting breaks, content mangled | Use `file(write/append)` |
| Using `exec_command` for `cat > file << 'EOF'` with `$` in content | Shell may still expand variables | Use `file(write)` — no shell involved |
| Editing without reading first | `find` string doesn't match, edit fails | Always `file(read)` first |
| Using `file(write)` on MEMORY.md or any curated file | **All existing content destroyed** | Use `edit` to change sections, `append` to add. `write` is only for creating new files. |
| Using `file(write)` on an existing file without reading | Previous content lost | Read first, or use `append`/`edit` |
| Using `replace_all=true` without checking occurrences | Unintended replacements | Read first, count occurrences, then decide |
