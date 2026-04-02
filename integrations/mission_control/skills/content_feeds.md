---
name: Content Feeds
description: Working with external content delivered to workspaces by feed integrations (email, RSS, etc.)
---

# SKILL: Content Feeds

## Overview

Content feeds are integrations that automatically ingest external content (email, RSS, web) into channel workspaces. Each feed connector polls its source, runs content through the 4-layer ingestion security pipeline, and delivers approved items as markdown files in the workspace `data/` directory.

## Where Feed Content Appears

Feed content is delivered to `data/{source}/` within the channel workspace:

```
data/
  gmail/
    2026-03-30-meeting-recap.md
    2026-03-30-weekly-report.md
    2026-03-29-invoice-update.md
  rss/
    2026-03-30-blog-post-title.md
```

Data files are **listed but not auto-injected** into context. Use search tools to find and reference specific content.

## Searching Feed Content

Use `search_channel_workspace` to find content across all feed sources:

```
search_channel_workspace(channel_id, query="quarterly report")
search_channel_workspace(channel_id, query="meeting notes from Sarah")
```

The workspace indexer processes feed files on delivery, so content is searchable immediately.

## Creating Digests

A common pattern is composing summaries from feed content into active workspace files:

1. Search feed content for the relevant time period or topic
2. Read the matched files to understand the content
3. Write a digest summary to an active workspace file (e.g. `email-digest.md`, `daily-brief.md`)

Active workspace files (`.md` at root) are auto-injected into context, making digests immediately visible.

## Timeline Integration

Feed deliveries are logged to `timeline.md` automatically. Use `append_timeline_event` for additional annotations like "Reviewed 5 emails from vendor" or "Created digest from RSS feeds".

## Security Pipeline

All feed content passes through the ingestion security pipeline before delivery:

1. **Structural extraction** — HTML stripping, Unicode normalization, truncation
2. **Injection filters** — Regex detection of prompt injection patterns, zero-width chars
3. **AI classifier** — LLM-based safety assessment (fails closed on errors)
4. **Typed envelope** — Pydantic validation

Content that fails any layer is quarantined and never delivered to the workspace.

## When to Get This Skill

Retrieve this skill when:
- User asks about feeds, ingested content, email digests, or data sources
- You need to search or reference content in `data/` directories
- User wants to set up content monitoring or automatic ingestion
- User asks about the security pipeline for external content
