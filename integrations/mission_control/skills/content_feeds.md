---
name: Content Feeds
description: Working with external content delivered to workspaces by feed integrations (email, RSS, etc.) — includes feed health monitoring, quarantine review, and cross-feed digest patterns
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

## Tools

### Feed Store Queries (`query_feed_store`)

The `query_feed_store` tool provides direct access to ingestion SQLite stores for health monitoring, recent item lookups, and quarantine review.

#### Check feed health
```
query_feed_store(action="stats", store="gmail", source="gmail")
→ {"total_processed": 142, "total_quarantined": 3, "processed_24h": 12, "quarantined_24h": 0, "last_cursor": {...}}
```

#### List recently passed items
```
query_feed_store(action="recent", store="gmail", limit=10)
→ [{"source": "gmail", "source_id": "...", "action": "passed", "risk_level": "low", "ts": "..."}]
```

#### Review quarantined items
```
query_feed_store(action="quarantine", store="gmail")
→ [{"source_id": "...", "risk_level": "high", "flags": ["injection_attempt"], "reason": "...", ...}]
```

#### Discover all feed stores
```
query_feed_store(action="sources")
→ [{"store": "gmail", "sources": ["gmail"]}, {"store": "rss", "sources": ["rss"]}]
```

## Searching Feed Content

Use `search_channel_workspace` to find content across all feed sources:

```
search_channel_workspace(channel_id, query="quarterly report")
search_channel_workspace(channel_id, query="meeting notes from Sarah")
```

The workspace indexer processes feed files on delivery, so content is searchable immediately.

## Feed Health Monitoring

A good practice before any triage or digest work:

1. **Discover feeds** — `query_feed_store(action="sources")` to see what's active
2. **Check each feed** — `query_feed_store(action="stats", store="{name}", source="{source}")` for 24h activity
3. **Review quarantine** — If `quarantined_24h` is elevated, check `query_feed_store(action="quarantine", store="{name}")` for patterns
4. **Report issues** — Flag quarantine spikes, zero activity (feed may be down), or unusual risk levels

### Quarantine review workflow

When reviewing quarantined items:
- Check `flags` to understand what triggered the block (injection patterns, hidden chars, etc.)
- Check `reason` for the AI classifier's explanation
- Look for patterns: same sender repeatedly quarantined? Same flag type across items?
- Report findings to the user — they may need to adjust feed rules or investigate the source

## Creating Digests

### Single-feed digest

1. Check feed stats with `query_feed_store` for the time period
2. Search `data/{source}/` for content in the relevant time range
3. Read matched files and summarize
4. Write digest to an active workspace file (e.g., `digest.md`)

### Cross-feed digest

When a channel has multiple feed sources:

1. Discover all feeds: `query_feed_store(action="sources")`
2. Get stats for each: `query_feed_store(action="stats", store="{name}")`
3. Search across all `data/` subdirectories for the time period
4. Group by source, then by topic/category within each source
5. Write a combined digest with source sections

### Digest template

```markdown
# Feed Digest — {date}

## Email ({count} new)
- **[sender]** subject — summary

## RSS ({count} new)
- **[source]** title — summary

## Feed Health
| Feed | Processed (24h) | Quarantined (24h) | Status |
|------|-----------------|-------------------|--------|
| gmail | 12 | 0 | Healthy |
| rss | 8 | 1 | Warning |
```

## Timeline Integration

Feed deliveries are logged to `timeline.md` automatically. Use `append_timeline_event` for additional annotations like "Reviewed 5 emails from vendor" or "Created digest from RSS feeds".

## Task Card Integration

When creating task cards from feed content:
- Use descriptive tags: `email,from:{sender}` or `rss,source:{feed_name}`
- Include the source file path in the card description for traceability
- Set appropriate priority based on content urgency

## Security Pipeline

All feed content passes through the ingestion security pipeline before delivery:

1. **Structural extraction** — HTML stripping, Unicode normalization, truncation
2. **Injection filters** — Regex detection of prompt injection patterns, zero-width chars
3. **AI classifier** — LLM-based safety assessment (fails closed on errors)
4. **Typed envelope** — Pydantic validation

Content that fails any layer is quarantined and never delivered to the workspace. Use `query_feed_store(action="quarantine")` to review blocked items.

## When to Get This Skill

Retrieve this skill when:
- User asks about feeds, ingested content, email digests, or data sources
- You need to search or reference content in `data/` directories
- User wants to set up content monitoring or automatic ingestion
- User asks about the security pipeline for external content
- User asks about quarantined or blocked content
- User wants feed health stats or cross-feed reports
