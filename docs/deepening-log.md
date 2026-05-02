---
title: Deepening log
summary: Append-only record of architectural deepenings (shallow→deep refactors). Read by the improve-codebase-architecture skill to avoid re-suggesting completed work and to spot drift.
status: archive
tags: [spindrel, architecture]
created: 2026-05-02
updated: 2026-05-02
---

# Deepening log

Append-only. Each entry records a deepening that landed: where the seam now lives, what was consolidated, and the friction it resolved. The `improve-codebase-architecture` skill reads this on every run — entries here are the "don't re-suggest, do drift-check" set.

## Entry schema

```
## YYYY-MM-DD — <module name>
- **Seam**: <file path or interface location>
- **What deepened**: 1–2 lines on what consolidated
- **Why**: the friction it resolved
- **Track / ADR**: optional link
```

Vocabulary: see `.claude/skills/improve-codebase-architecture/LANGUAGE.md` (module, interface, seam, adapter, depth, leverage, locality).

## Entries

_None yet — grows from real deepening passes._
