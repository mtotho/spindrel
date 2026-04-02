---
category: workspace_schema
description: Email ingestion and digest management — feed rules, digest summaries, and action tracking.
compatible_integrations: gmail
tags: email, digest, feeds
---
## Workspace File Organization — Email Digest

Organize channel workspace files as follows:

- **feeds.md** — Active feed rules: which senders/subjects to watch, filter criteria, digest frequency
- **digest.md** — Latest digest summary: grouped by feed, key items highlighted, action items extracted
- **actions.md** — Action items pulled from emails: follow-ups, deadlines, replies needed
- **notes.md** — Notes on email patterns, sender context, organizational preferences

### Guidelines
- Group incoming emails by feed rule when building digests
- Extract action items (deadlines, reply requests, approvals) into actions.md
- Keep digest.md as a rolling summary — archive old digests weekly
- Note sender context in notes.md so future digests can prioritize intelligently
- Archive processed digests and completed actions to the archive/ folder
