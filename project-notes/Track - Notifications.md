# Track - Notifications

Status: active
Updated: 2026-04-26

## Goal

Make human-facing notifications a core reusable subsystem instead of bespoke per-feature delivery code. Notification targets are admin-managed destinations that existing features, bots, and pipeline steps can reference by id.

## Phase 1 - Core targets shipped 2026-04-26

- Added `notification_targets` and `notification_deliveries` as the durable model.
- Target kinds: `user_push`, `channel`, `integration_binding`, `group`.
- Delivery reuses existing primitives:
  - `user_push` wraps the PWA `send_push` service.
  - `channel` persists a system message when a channel session exists, publishes SSE, and enqueues existing outbox delivery.
  - `integration_binding` directly resolves the existing integration renderer target and calls the renderer inline.
  - `group` fans out best-effort with cycle protection.
- Bot usage is explicit: `list_notification_targets` only shows targets whose `allowed_bot_ids` include the current bot; `send_notification` enforces the same grant.
- Usage spike alerts gained `target_ids`; legacy JSON targets migrate lazily into saved notification targets.
- Admin UI added at `/admin/notifications`; Usage Alerts now uses the shared target picker.

## Invariants

- Notification targets do not create a new integration delivery stack.
- A bot cannot send to a target just because the tool is assigned; the target grant must also include that bot.
- Channel targets should remain visible in web channel history when a channel session exists.
- Direct integration-binding sends are audited in notification delivery history but do not create channel history.

## Follow-ups

- Add richer API integration tests once the SQLite metadata fixture hang is resolved.
- Consider a future integration manifest declaration only after at least one external integration needs provider-owned target discovery.
- Keep v1 payload simple: title, body, optional URL, severity, tag.
