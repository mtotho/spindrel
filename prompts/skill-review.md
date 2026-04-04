---
name: "Skill Review & Maintenance"
description: "Periodic review of bot-authored skills — prune stale skills, merge duplicates, improve trigger phrases, and identify learning gaps."
category: heartbeat
tags:
  - skills
  - learning
  - maintenance
  - self-improvement
group: "Core"
recommended_heartbeat:
  prompt: |
    Run a skill maintenance cycle. Use manage_bot_skill(action="list") to review all your skills.

    For each skill, evaluate:
    1. **Surfacing** — check surface_count and last_surfaced_at. Skills that haven't surfaced in 14+ days may have weak triggers or cover topics that never come up.
    2. **Relevance** — is this skill still accurate? Has your understanding improved since you wrote it?
    3. **Overlap** — are multiple skills covering the same topic? If so, merge them into one comprehensive skill.

    Take action:
    - **Low surface_count + old**: Either rewrite with better trigger phrases, or delete if the topic is no longer relevant.
    - **Overlapping skills**: Use manage_bot_skill(action="merge", names=["skill-a", "skill-b"], name="combined", title="...", content="...") to consolidate into one skill.
    - **Outdated content**: Use manage_bot_skill(action="patch") to fix specific sections, or action="update" for a full rewrite.

    After making changes, post a brief summary of what you did: skills pruned, merged, updated, or left alone. If you have no skills yet, say so and skip.
  interval: "weekly"
  quiet_start: "22:00"
  quiet_end: "08:00"
---

## Skill Review — Heartbeat Prompt

This heartbeat template runs a periodic skill maintenance cycle for bots that use the self-authored skill system (`manage_bot_skill` tool).

### What It Does

On each run, the bot:

1. **Lists all self-authored skills** with surfacing stats (surface_count, last_surfaced_at)
2. **Identifies problems**: stale skills (never surface), duplicates (overlapping topics), outdated content
3. **Takes action**: prunes, merges, rewrites triggers, or updates content
4. **Reports** a brief summary of changes made

### When to Use

Assign this heartbeat to any bot that has `manage_bot_skill` available and is expected to accumulate skills over time. A weekly interval is recommended — frequent enough to prevent skill rot, infrequent enough to not waste compute.

### Prerequisites

- Bot must have `memory_scheme: "workspace-files"` (enables the skill system)
- Bot must have `manage_bot_skill` in its tool set (automatic when memory_scheme is workspace-files)
- Works best after the bot has accumulated 5+ skills

### Customization

Adjust the recommended heartbeat prompt to fit your use case:

- **Tighten the staleness window**: Change "14+ days" to "7+ days" for bots that should learn faster
- **Add domain-specific review criteria**: e.g., "Check if any skills reference deprecated API versions"
- **Add a creation nudge**: Append "If you notice recurring topics in recent conversations that aren't covered by any skill, create new skills for them"
- **Change the merge threshold**: By default bots should merge skills on the same topic; you can be more aggressive ("merge anything in the same category")
