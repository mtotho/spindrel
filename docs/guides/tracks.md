---
title: Track Contract
summary: When a track is created, format, lifecycle, and pruning rules. Tracks live in docs/tracks/ alongside the rest of the project state.
status: permanent
tags: [spindrel, process, agents]
---

# Track Contract

A **Track** is a multi-session work effort with phases, owned by a coherent goal. Tracks live in `docs/tracks/` (one file per track, kebab-case slug). Not every task is a track — bug fixes, weekend refactors, and one-shot polish passes are not tracks.

"Multi-session" means the work itself needs durable ownership across more than
one session. It does **not** mean the track is a place to paste every session
log. Session transcripts, receipts, parity ledgers, and investigation evidence
should be linked from the track and stored in the artifact that owns that kind
of history.

## When to create a track

Create a track when **either**:

- Work spans (or will span) **2+ sessions** AND has **3+ distinct phases**, OR
- A `docs/roadmap.md` "Active" item grows past **5 lines of inline detail** — extract it to a track and leave a 2-line summary + link in Roadmap.

Examples that are tracks: "Migrate auth from session cookies to JWT" (discovery → middleware swap → token rotation → cleanup); "Spatial canvas replaces HomeGrid" (design → primitives → channel pinning → migration). Examples that are *not* tracks: "Fix off-by-one in channel pagination"; "Rename `BotConfig` to `BotProfile`"; "Add a missing test for X".

## Format

```markdown
---
title: Track Name
summary: 1–2 sentences, ≤200 chars — what this track is achieving and why. Drives cheap retrieval.
status: active | complete | superseded
tags: [spindrel, <subsystem>, ...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Track Name

## North Star
One or two sentences on the end state. Updated when scope changes.

## Status
| Phase | State | Updated |
|---|---|---|
| 1. Discovery | done | YYYY-MM-DD |
| 2. Scaffold  | active | YYYY-MM-DD |
| 3. Migration | not started | — |
| 4. Cleanup   | not started | — |

## Phase Detail
Short per-phase summaries, linked artifacts, decisions. Compress old phase prose when it ships (see Pruning).

## Key Invariants
Constraints we won't violate. Things to remember when picking up this track cold.

## References
- Architecture Decisions entries: `[[architecture-decisions]]` or links into `docs/architecture-decisions.md`
- Plans / audits / parity ledgers / Project-run receipts that carry detailed evidence
- Related tracks: `[[Track Name]]`
- External docs / PRs / issues
```

## Lifecycle

- **Create**: when the criteria above are met. Add a row to `docs/roadmap.md`'s "Active" table linking to the track.
- **Update**: in the **same edit** as the underlying work. Mark phases done in the status table; bump `updated:` to today.
- **Compress**: when a phase ships, replace its detail prose with a one-paragraph summary in the Phase Detail section. Don't delete shipped work; compress it. See Pruning.
- **Supersede**: when two tracks converge — set the superseded one to `status: superseded`, leave a note pointing at the surviving track. Don't delete.
- **Close** (`status: complete`): when all phases are done OR remaining phases are explicitly deferred/frozen. Move the row from Roadmap "Active" to Roadmap "Recently completed". Keep the track file in `docs/tracks/`; closed tracks are read-only history. Do not move them to a separate folder.

## Pruning

- **Compression cadence**: phase prose older than 30 days post-ship → compress to a one-paragraph summary in place.
- **History extraction**: dated implementation diaries, command logs, screenshot ledgers, parity rerun notes, and session references belong in `docs/audits/`, `docs/plans/`, `.spindrel/audits/`, `.spindrel/runs/`, or Project receipts. Link them from the track.
- **Split**: tracks > 500 lines or covering 2+ unrelated themes → split into multiple tracks. Cross-link the new tracks; mark the original `status: superseded`.
- **Closed tracks**: closed tracks > 6 months old can be left alone unless they're actively misleading.

## Naming

- Filename is the kebab-case slug: `docs/tracks/harness-sdk.md`, `docs/tracks/spatial-canvas.md`, `docs/tracks/pwa-and-push.md`.
- Frontmatter `title:` is the human-readable name: `Harness SDK`, `Spatial Canvas`, `PWA & Push`.
- Wikilinks resolve via the `title:` field in Obsidian: `[[Harness SDK]]` works.
- Drop the `Track - ` prefix in filenames — the `tracks/` directory disambiguates.

## Anti-patterns

- **Don't spawn a new track for ongoing work in an existing track's domain.** Closed tracks are closed; if a follow-up is meaningfully new scope, that's a new track. If it's continuation, reopen the existing track (set `status: active` if it had been complete) and add a phase. Living tracks can stay open indefinitely.
- **Don't put implementation detail in `docs/roadmap.md`.** Roadmap rows are 1–2 lines + link to track. Detail belongs in the track.
- **Don't use tracks as session logs.** Tracks summarize current state and link to evidence. Session-by-session execution records belong in audits, receipts, plans, or `.spindrel/runs/`.
- **Don't duplicate Architecture Decisions in tracks.** A decision goes in `docs/architecture-decisions.md` once; the track references it.
- **Don't track bugs as tracks.** Bugs go in `docs/inbox.md` (active; see schema there) or `docs/fix-log.md` (resolved).
