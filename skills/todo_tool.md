---
name: todo-tool
description: "Load when the user asks to add, view, complete, update, or remove todo items — or when the agent needs to track a work item that persists across sessions. Trigger phrases: 'add to todo', 'put that on the list', 'what's on the todo list', 'mark that done', 'remove that todo', 'show todos'. Also load proactively when the agent completes a task and should update the list. Do NOT load for in-session task planning, Plans (multi-step checklists), or one-off reminders with no persistence needed."
---

# Todo Tool

## Core Principle
Todos are persistent, cross-session work items scoped to this bot and channel. They are NOT session-scoped plans or reminders — they survive across conversations and represent ongoing commitments.

## Available Tools

| Tool | Purpose | Required params |
|---|---|---|
| `create_todo` | Add a new work item | `content` |
| `list_todos` | Show current todos | `status` (default: `pending`) |
| `complete_todo` | Mark done by ID | `todo_id` |
| `update_todo` | Edit content, priority, or status | `todo_id` + at least one of: `content`, `priority`, `status` |
| `delete_todo` | Remove permanently (hard delete) | `todo_id` |

## Behavioral Patterns

**When the user says "add that to the todo list":**
Call `create_todo` immediately with a concise, action-oriented description. Don't ask for confirmation unless the content is ambiguous.

**When the user says "what's on the todo list" or "show todos":**
Call `list_todos` with `status="pending"`. Present results as a numbered list with priorities noted if non-zero.

**When a task is completed:**
Proactively call `complete_todo` if a matching todo exists. Don't wait to be asked.

**When the user says "remove" or "delete" a todo:**
Use `delete_todo` — this is a hard delete. Warn the user once if the item sounds like it might still be needed, but respect their decision.

**Priority values:**
`0` = normal (default). Higher integers = higher priority. Use sparingly — only elevate when the user explicitly calls something urgent.

## Common Mistakes

- Creating a todo for something that's already a Plan step — todos are standalone items, not sub-tasks
- Using `complete_todo` when the user said "delete" — complete preserves history conceptually, delete removes it permanently
- Listing todos without being asked when the list is long — only surface unprompted if directly relevant to the current task
- Forgetting to call `complete_todo` after finishing a task that had a corresponding todo

## Todos vs Plans

| | Todos | Plans |
|---|---|---|
| Scope | Cross-session | Current session |
| Structure | Flat list | Ordered checklist |
| Use for | Ongoing work items | Step-by-step task execution |
| Cleared by | `complete_todo` / `delete_todo` | Session end |

## Pre-Action Checklist
- [ ] Is this a new item or an update to an existing one? (`list_todos` first if unsure)
- [ ] Is `content` concise and action-oriented? (e.g. "Build search_history tool" not "we talked about maybe doing the search thing")
- [ ] For `complete_todo` / `delete_todo` — do I have the correct `todo_id`? (get it from `list_todos`)
