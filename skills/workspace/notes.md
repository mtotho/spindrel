---
title: Notes
summary: Assist with Markdown notes stored in the active channel or project knowledge base while preserving user-authored content.
status: active
tags: [workspace, notes, knowledge-base, markdown]
---

# Notes

Use this skill when the user is creating, editing, organizing, or reviewing a Note.

Notes are Markdown documents stored under the active knowledge base:

- Channel notes: `channels/<channel_id>/knowledge-base/notes/`
- Project notes: `.spindrel/knowledge-base/notes/`

## Editing Rules

- Treat the Markdown file as the source of truth.
- Preserve user-written facts, wording, decisions, examples, and caveats unless the user explicitly asks to remove them.
- Prefer small, reviewable changes over whole-document rewrites.
- When improving clarity, use Markdown structure: headings, short paragraphs, lists, tables, and code fences where appropriate.
- Do not silently overwrite the document. Propose changes, explain the intent briefly, and let the user accept or save them.
- If a selected section is provided, operate only on that section unless the user asks for whole-document work.

## Metadata Hygiene

Occasionally, especially after creating a note or making a substantial update, suggest frontmatter improvements:

- `summary`: one concise sentence describing the note.
- `tags`: short retrieval-oriented labels.
- `category`: a broad grouping that would help the rich notes list.

Metadata suggestions are proposals, not hidden edits. Keep them aligned with the actual document content.

## Grill Mode

When the note is vague, incomplete, or intended to become a durable knowledge document, use the `grill_me` skill style:

- Ask focused questions.
- Extract decisions and unresolved questions.
- Convert answers into Markdown sections.
- Keep the user's original intent visible.
