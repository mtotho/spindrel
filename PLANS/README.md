# PLANS

Active and archived multi-session plans. Each plan lives in its own `.md` file.

## Format

Every plan file must start with a standard header block:

```
---
status: draft | active | blocked | complete | archived
last_updated: YYYY-MM-DD
owner: mtoth
summary: |
  2-3 line summary of what this plan is for.
  Enough to understand scope without reading the file.
---
```

## Conventions

- Active plans are referenced in long-term memory so they appear in heartbeat context
- Completed plans move to `PLANS/archive/` — never deleted
- One plan per file, named clearly: `INGESTION_PIPELINE.md`, `GMAIL_INTEGRATION.md`, etc.
