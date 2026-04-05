---
name: Workspace Files
description: Guide for using the file tool vs exec_command for reading, writing, and editing files
triggers: file tool, read file, write file, append, edit file, exec_command, workspace files
category: workspace
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
| List directory contents | `file(list, path)` | — |
| Delete a file | `file(delete, path)` | — |
| Create directories | `file(mkdir, path)` | — |
| Run a program/script | — | `exec_command` or `delegate_to_exec` |
| Git operations | — | `exec_command` |
| Pipe commands / process data | — | `exec_command` |
| Install packages | — | `exec_command` |
| Complex multi-step shell tasks | — | `exec_command` |

**Rule of thumb**: If you're just reading or writing text to a file, use `file`. If you need to *execute* something, use `exec_command`.

---

## Memory Patterns

### Append to MEMORY.md

```
file(operation="append", path="memory/MEMORY.md", content="\n## New Finding\n- Key insight here\n")
```

### Write a daily log entry

```
file(operation="append", path="memory/logs/2026-03-30.md", content="\n### 14:30 — Task completed\n- Details here\n")
```

### Create a reference document

```
file(operation="write", path="memory/reference/deployment-guide.md", content="# Deployment Guide\n\n...")
```

### Update a specific fact

```
file(operation="edit", path="memory/MEMORY.md", find="status: pending", replace="status: complete")
```

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
| Using `file(write)` on an existing file without reading | Previous content lost | Read first, or use `append`/`edit` |
| Using `replace_all=true` without checking occurrences | Unintended replacements | Read first, count occurrences, then decide |
