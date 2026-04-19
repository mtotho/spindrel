---
tags: [agent-server, user-management, auth, scoping, ownership]
status: active
updated: 2026-04-19 (Phases 0-2 shipped; Phase 3 next)
---

# Track — User Management

## North Star

**A non-admin user can log in, see only the channels and bots they own or have been granted, and use the UI without encountering any control they can't actually use.** Admins retain the superuser view. Backend enforcement is the source of truth; UI hiding is UX polish.

## Why now

User management infra is half-built. The bones exist — `User.is_admin`, 40+ scope system with presets, `channel.user_id` + `channel.private` with a working `apply_channel_visibility` helper. But enforcement is uneven:

- Ownership fields exist without checks (e.g., `bot.user_id` is decorative; every bot is globally listable to anyone with `bots:read`).
- All admin pages are discoverable by URL — non-admins see identical UI to admins and only get a 403 when they click a mutation.
- No bot-level access control at all.
- No coherent "my stuff" view for non-admins.

This track tightens the existing pieces into a clean admin-vs-user experience. Single install, not multi-tenant.

## Decisions (locked 2026-04-19)

| Decision | Choice |
|---|---|
| Bot ownership | Single `owner` (`bot.user_id`) + new `bot_grants(bot_id, user_id, role)` table. Role ∈ `{view, manage}`. Admin = implicit full access. |
| Channel default visibility | Public by default, private opt-in. Private channels visible only to owner + admins (`apply_channel_visibility` already does this). |
| Integration binding gating | Admin-only. Non-admins see which integration is bound to their channel read-only. No non-admin write path to `ChannelIntegration`. |
| Frontend permission strategy | `/auth/me` returns effective scopes array. Zustand store + `useScope('scope:name')` hook drive conditional rendering. Admin routes wrapped in `<AdminRoute>`. |

## Status

| Phase | Summary | Status |
|---|---|---|
| 0 | Create track + Roadmap entry | ✅ shipped 2026-04-19 |
| 1 | Baseline audit + scope hygiene (mutation endpoints gated; Scope Matrix doc) | ✅ shipped 2026-04-19 — 120+ endpoints classified, no leaks, 3 Loose Ends logged ([[Scope Matrix]]) |
| 1.5 | Fail-closed `require_scopes` for JWT users with no resolved scopes (Phase 2 prerequisite) | ✅ shipped 2026-04-19 — admin bypass preserved; 36/36 auth tests green; see [[Fix Log]] |
| 2 | `/auth/me` effective scopes + frontend hydration + `useScope()` hook | ✅ shipped 2026-04-19 — see [[Fix Log]] |
| 3 | UI route guards + nav filtering + control hiding | ⏳ planned |
| 4 | Channel ownership enforcement (auto-populate user_id, edit/delete gating) | ⏳ planned |
| 5 | Bot ownership + `bot_grants` table + view/manage roles + admin GrantsTab | ⏳ planned |
| 6 | Integration binding final lockdown (audit, confirm admin-only writes) | ⏳ planned |
| 7 | Non-admin self-service (`/settings/account`, `/settings/channels`, `/settings/bots`) | ⏳ planned |

## Phase detail

### Phase 1 — Baseline audit + scope hygiene ✅ shipped 2026-04-19

Audit outcome: **no endpoint-level fixes needed.** 120+ mutation endpoints classified. Admin namespace is doubly-gated (router-level `verify_admin_auth` + endpoint-level `require_scopes`); non-admin routers consistently use `require_scopes`. No mutation endpoint sits entirely outside enforcement.

Findings logged as Loose Ends (all are design decisions, not scope-gate regressions):

1. **Phase 2 prerequisite** — `require_scopes` fails OPEN for JWT users with `_resolved_scopes=None` (`app/dependencies.py:242-246`). Combined with `_provision_user_api_key`'s silent exception-swallow (`app/services/auth.py:267`), users with failed provisioning get full access with empty scopes. This is a pre-Phase-2 blocker because Phase 2 will hydrate the UI with the empty scopes — the UI will hide everything while the backend grants everything. See [[Loose Ends#Phase 2 prerequisite — close the fail-open backcompat in require_scopes]].
2. **`channels:write` transitively covers `channels.integrations:write`** — member_user preset grants `channels:write`, and `has_scope` parent-covers-child semantics make that cover `channels.integrations:write`. Means non-admins already CAN bind integrations. Phase 6 material. See [[Loose Ends#`channels:write` parent scope covers `channels.integrations:write` for members]].
3. **`/transcribe` has no scope** — authentication-only (`app/routers/transcribe.py:68`). Minor. See [[Loose Ends#Transcribe endpoint has no per-feature scope]].
4. **Widget actions per-dispatch authorization has no regression test** — design is correct but unguarded by tests. See [[Loose Ends#Widget actions per-dispatch authorization needs unit test]].

Deliverable: [[Scope Matrix]] — living reference, endpoint → scope → preset, with a regeneration command. Covers the admin + non-admin surfaces, the intentionally-open endpoints (auth flow, self-service `/me`, widget actions per-dispatch), and the three findings above.

### Phase 2 — `/auth/me` effective scopes + frontend hydration ✅ shipped 2026-04-19

Backend:
- `app/services/auth.py::resolve_user_scopes(db, user)` — resolves from `user.api_key_id` → `ApiKey.scopes`, with `["admin"]` synthetic fallback for admins missing a key (matches the `is_admin` bypass invariant).
- `app/routers/auth.py`: `UserResponse.scopes: list[str]` field, populated from the helper in `/me` GET, `/me` PUT, login, setup, google. 4 integration tests in `test_auth_profile.py::TestAuthMeScopes` covering member/admin/orphan-non-admin/orphan-admin shapes. 40/40 integration tests green.

Frontend:
- `ui/src/stores/auth.ts` + `ui/src/types/api.ts`: `AuthUser.scopes: string[]`.
- `ui/src/hooks/useScope.ts` (NEW): exports `useScope(scope)`, `useScopes(...)` (all-of), `useAnyScope(...)` (any-of), `useIsAdmin()`. `hasScope()` function ported from backend `has_scope()` at `app/services/api_keys.py:518` — same parent-covers-child, write-implies-read, wildcard, and admin bypass semantics. UI tsc clean.

No behavior change on existing routes — this phase only plumbed the primitive. Phase 3 consumes `useScope()` to hide nav and gate routes.

### Phase 3 — UI route guards + nav filtering + control hiding

Goal: non-admins stop seeing admin chrome.

- New `ui/src/components/routing/AdminRoute.tsx` wrapper; apply to `ui/app/(app)/admin/**/*.tsx` via route config.
- Sidebar + OmniPanel + channel header settings menu filter items with `useScope()`.
- Destructive/mutation buttons (delete channel, edit bot, create binding): disabled/hidden via `useScope()`.
- Unauthorized URL access → friendly "no access" card, not raw 403.
- End state: non-admin login → ONLY chat + settings + allowed surfaces. No admin tabs.

### Phase 4 — Channel ownership enforcement

Goal: non-admin creates a channel → only they (and admins) can edit/delete it. Private channels isolated.

- `POST /api/v1/channels`: non-admin JWT user → auto-populate `channel.user_id = request.user.id`. Admin: optional `user_id` in body, defaults NULL.
- Edit/delete: new `require_admin_or_owner(channel)` helper in `app/dependencies.py`. 403 if non-admin and `channel.user_id != request.user.id`.
- Verify `apply_channel_visibility` (`app/services/channels.py:361-378`) is called on every channel-list path — two preview paths confirmed already. Add test: non-admin cannot GET another user's private channel by UUID.
- Channel settings page: hide Integration Bindings + "Advanced" + "Tool Policies" tabs for non-admin.
- Tests: ownership on create, edit denied for non-owner, private invisible cross-user, admin sees all.

### Phase 5 — Bot ownership + grants (biggest phase)

Goal: admin designates bot owners and grants subsets of users view/manage access.

- **Schema**: Alembic migration — `bot_grants(bot_id, user_id, role, created_at, granted_by)`. Role enum `view` | `manage`. Unique `(bot_id, user_id)`. Cascade on bot + user delete.
- **ORM**: `BotGrant` in `app/db/models.py`.
- **Visibility helper**: `app/services/bots.py::apply_bot_visibility(stmt, user)` — admin bypass, else `bot.user_id == user.id OR bot.id IN (bot_grants subquery)`. Mirrors channel visibility.
- **Role helpers**: `can_user_manage_bot(user, bot_id)`, `can_user_view_bot(user, bot_id)`.
- **Bot admin endpoints** (`app/routers/api_v1_admin/bots.py`): list filters via visibility; update/delete require manage-or-admin; create admin-only with assignable owner.
- **Grant endpoints** (new `app/routers/api_v1_admin/bot_grants.py`): `GET/POST/DELETE /api/v1/admin/bots/{id}/grants`. Admin-only.
- **Admin UI**: new `GrantsTab` on `ui/app/(app)/admin/bots/[botId]/` — pick user, assign role, list grants, revoke.
- **Non-admin UI**: `/admin/bots` scoped to visible; `/admin/bots/{id}` edit mode only if manage.
- **Channel creation**: non-admin sees only visible bots in picker.
- Tests: visibility (owner/grantee/stranger/admin), role enforcement (view cannot PATCH), revocation, cascade.

**Split**: 5a backend + migration + tests, 5b UI + GrantsTab. Each a separate session.

### Phase 6 — Integration binding final lockdown

Goal: non-admins cannot touch `ChannelIntegration` rows.

- Audit all `ChannelIntegration` write paths: `db.add(ChannelIntegration`, `.delete()` on query, `activated = ...`. Confirm every one sits behind `require_scopes("integrations:write")` (admin-preset only).
- Remove `integrations:write` from any non-admin preset if leaked.
- UI: channel settings Integration Bindings tab admin-only (Phase 3 gates visually; Phase 6 confirms backend matches).
- Tests: non-admin `POST /api/v1/admin/integrations/bindings` → 403; GET own channel's binding → 200 read-only.

### Phase 7 — Non-admin self-service

Goal: non-admin has a coherent "this is my stuff" landing.

- `/settings/account`: profile edit, password change, own API key.
- `/settings/channels`: owned + private.
- `/settings/bots`: owned + granted, role badge per row.
- Navigation: replace "Admin" gear with "Settings" gear for non-admins → `/settings/account`.
- Tests: user-updates-own-profile (verify existing), user-cannot-update-another.

## Critical invariants

1. **`is_admin=true` bypasses all ownership/grant checks everywhere.** No scoping ever hides data from admins. Every visibility helper starts with `if user.is_admin: return stmt`.
2. **Backend is the source of truth.** Every UI guard has a matching 403. Removing a UI guard must never unlock a forbidden action.
3. **Scopes govern API surface; ownership governs row access.** A user with `bots:write` scope cannot edit a bot they don't own/manage — scope is necessary but not sufficient.
4. **Private channels are the one place ownership is load-bearing for reads.** Bots are visibility-gated for `manage`; `view` includes "I can talk to it in my channel". Private channels are visibility-gated for any read.
5. **No user → channel deletion cascade.** Deleting a user orphans their channels (admin reassigns). Deleting a user DOES cascade `bot_grants`.
6. **First-user-is-admin rule preserved.** `/auth/setup` continues to mint an admin; subsequent user creation is admin-only.

## Key files

### Backend
- `app/db/models.py` — add `BotGrant` model (Phase 5)
- `app/services/bots.py` — new `apply_bot_visibility`, `can_user_manage_bot`, `can_user_view_bot` (Phase 5)
- `app/services/channels.py:361-378` — existing `apply_channel_visibility`
- `app/services/api_keys.py:518-566` — existing `has_scope()`, source of truth for frontend parity
- `app/dependencies.py:230-264` — existing `require_scopes`; add `require_admin_or_owner(Channel)`, `require_admin_or_bot_manager(bot_id)`
- `app/routers/auth.py` — extend `/auth/me` (Phase 2)
- `app/routers/api_v1_channels.py` — ownership enforcement (Phase 4)
- `app/routers/api_v1_admin/bots.py:30-49` — visibility filter + manage check (Phase 5)
- `app/routers/api_v1_admin/bot_grants.py` — NEW (Phase 5)
- Alembic `alembic/versions/XXX_bot_grants.py` — NEW (Phase 5)

### Frontend
- `ui/src/stores/auth.ts` — add `scopes` array (Phase 2)
- `ui/src/hooks/useScope.ts` — NEW (Phase 2)
- `ui/src/components/routing/AdminRoute.tsx` — NEW (Phase 3)
- `ui/src/components/layout/sidebar/SidebarRail.tsx` — scope-filter nav (Phase 3)
- `ui/app/(app)/admin/bots/[botId]/GrantsTab.tsx` — NEW (Phase 5)
- `ui/app/(app)/settings/account.tsx` — NEW (Phase 7)
- `ui/app/(app)/settings/channels.tsx` — NEW (Phase 7)
- `ui/app/(app)/settings/bots.tsx` — NEW (Phase 7)

## Deferred / out of scope

- Multi-user shared channels (team channels). Requires `channel_members`. Not asked.
- Channel-level bot grants. Bot grants are global; sufficient for this phase.
- SSO / SAML. Current local + Google OAuth stays.
- User invitation emails. Admin creates + shares credentials out-of-band.
- Audit log (who created/granted what). Separate track if needed.
- Session revocation on role change. JWT lifetime + refresh rotation are acceptable.
- Scope cache in JWT claims. Current DB fetch is fine at this scale.

## References

- Plan: `~/.claude/plans/fizzy-humming-aurora.md`
- Existing scope system: `app/services/api_keys.py:18-566`
- Existing channel visibility: `app/services/channels.py:361-378`
- User model: `app/db/models.py:1280-1299`

## Execution notes

- Phase 1 is a hygiene pass (cheap, de-risks later phases). Do first.
- Phase 3 depends on Phase 2. Don't parallelize.
- Phase 5 is the biggest — split 5a (backend) / 5b (UI) if it runs long.
- One commit per phase. No flag-off compat shims between phases.
