---
name: Workspace
description: Entry point for workspace operations — the file tool, channel workspaces, docker stacks, knowledge bases, attachments, and operating inside the workspace container. Routes to the right sub-skill by scenario.
triggers: workspace, channel files, workspace files, file tool, read file, write file, knowledge base, attachment, upload, docker stack, container, /workspace
category: core
---

# Workspace

Everything a bot does with files, containers, and knowledge lives under `workspace/`. The sub-skills split by concern rather than by tool — start here to find the right one.

## Read This First When

- You are reading, writing, editing, or searching files — workspace layout, ops, or escapes
- You are deciding between workspace memory, channel files, or a knowledge base for durable info
- You are looking at or spawning a docker stack, or running inside the container
- You are dealing with an uploaded file, an attachment, or an image from the user

## Which Skill Next

- [Files](files.md)
  The `file` tool — read / write / append / edit / replace_section / archive_older_than / batch / grep / glob. The authoritative guide for workspace file operations.
- [Project Coding Runs](project_coding_runs.md)
  Project-scoped implementation/review runs, handoff receipts, e2e evidence, and finalization.
- [Issue Intake](issue_intake.md)
  Conversational issue capture into Mission Control Review before Operator triage and approved Project runs.
- [Channel Workspaces](channel_workspaces.md)
  How to use a channel's workspace directory: active vs archived files, workspace vs memory, cross-channel search.
- [Workspace Member](member.md)
  Operating inside the workspace container: filesystem layout, write protection, API access via `call_api` / `list_api_endpoints`.
- [Knowledge Bases](knowledge_bases.md)
  The channel + bot knowledge-base folders and the narrow `search_channel_knowledge` / `search_bot_knowledge` tools.
- [Attachments](attachments.md)
  Sending files, finding uploads, generating/editing images, delegation with attachments.
- [Docker Stacks](docker_stacks.md)
  Creating and managing docker-compose stacks for databases, caches, and long-running services.

## The Short Version

- **`file` tool** for every content op on workspace files. Reach for `batch` when you have three or more ops to group atomically.
- **`workspace/memory/`** for durable structured notes. **Knowledge base folders** (`workspace/knowledge-base/`) for retrievable facts.
- **Attachments** are channel-scoped uploads; use `list_attachments` / `get_attachment` to surface them.
- **Docker stacks** live under `workspace/stacks/`; bot owns the compose file, container lifecycle is bot-managed.
