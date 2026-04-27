# Track - Notifications

Status: active
Updated: 2026-04-27

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

## Phase 2 - Session Unread Receipts started 2026-04-27

- Added durable `session_read_states`: one row per `(user, session)` with a read high-watermark, first/latest unread timestamps, latest unread message/correlation, aggregate unread agent-reply count, and reminder stamps. This deliberately avoids per-submessage receipt fanout.
- Added `unread_notification_rules` for global and per-channel unread notification preferences. Rules reference shared notification targets and support immediate sends plus one reminder delay.
- Agent assistant persistence now updates unread state after bus publication. Web-visible sessions mark read instead of creating unread; user sends mark the current session read.
- Added `/api/v1/unread/state`, `/visible`, `/read`, `/rules`, and `/events`; UI badges now consume backend unread state and subscribe to user-scoped unread SSE for cross-session toasts.
- Notification delivery suppresses exact mirror targets for the source channel/integration so a channel already mirrored to Slack does not get duplicate Slack unread notifications from the generic unread mechanism.

## Invariants

- Notification targets do not create a new integration delivery stack.
- A bot cannot send to a target just because the tool is assigned; the target grant must also include that bot.
- Channel targets should remain visible in web channel history when a channel session exists.
- Direct integration-binding sends are audited in notification delivery history but do not create channel history.
- Read receipts are per user/session high-watermarks. Channel badges are rollups over visible sessions; assistant replies, not every harness submessage/token, create unread.
- Integration/channel targets matching the source mirror are suppressed for unread notifications.

## Follow-ups

- Add richer API integration tests once the SQLite metadata fixture hang is resolved.
- Consider a future integration manifest declaration only after at least one external integration needs provider-owned target discovery.
- Keep v1 payload simple: title, body, optional URL, severity, tag.
- Finish per-channel notification-rule UI; current Settings surface covers the global unread rule and target selection.
