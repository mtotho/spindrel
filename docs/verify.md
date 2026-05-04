---
title: Verification Queue
summary: Shipped features awaiting live/e2e verification beyond unit tests. Add a row when a plan/track ships with live acceptance criteria; mark verified and prune within ~30 days.
status: active
tags: [spindrel, verification, qa]
created: 2026-05-04
updated: 2026-05-04
---

# Verification Queue

Shipped features whose acceptance criteria require live verification beyond automated tests. **Read [[../AGENTS]] first** for navigation. Lifecycle and policy: `.spindrel/WORKFLOW.md` → "Verification Queue".

## How to use

1. **Add** a row when a plan moves to `docs/plans/completed/` or a track flips to `status: complete` AND its acceptance criteria require live/manual proof. If the plan's automated tests are explicitly sufficient, no row needed.
2. **Update** the row as verification progresses (`queued` → `in-progress` → `verified YYYY-MM-DD` or `failed YYYY-MM-DD → inbox#…`).
3. **Prune** verified entries 30 days after they pass. If a paper trail is wanted, move to `docs/audits/verification-archive.md`; otherwise delete. Failed entries leave the queue as soon as a corresponding `docs/inbox.md` row is filed.

## Methods (recommended)

- **`local API + live agent`** — start `uvicorn app.main:app --reload`, drive a real agent through the scenario, observe traces.
- **`e2e scenario`** — add or run a scenario; host/port come from `.env.agent-e2e` (`E2E_HOST` / `E2E_PORT`). See `.agents/skills/spindrel-e2e-development/SKILL.md`.
- **`test server`** — exercise against the operator-managed test server. Connection details (IP, SSH alias, credentials) live in the vault `Test Server Operations.md`, never in this repo.
- **`screenshot diff`** — UI changes; capture before/after.

## Queue

## mid-turn-chat-followup-absorption — shipped 2026-05-04
- **What to verify:** (1) Send a message that triggers a tool call, then send 2 followups while it runs — assert one final assistant answer that incorporates the followups, no second queued response. (2) Send a one-shot (no-tool) message, then 2 followups while it streams — assert the existing queued task answers the followups once after.
- **Method:** local API + live agent; inspect traces for `late_chat_burst_absorbed` (case 1) and `chat_burst` queued task (case 2).
- **Source:** `docs/plans/completed/mid-turn-chat-followup-absorption.md`
- **Status:** queued

<!-- Add new entries above this line. Order is newest-first. -->
