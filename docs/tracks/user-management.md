---
tags: [spindrel, user-management, auth, scoping, ownership]
status: complete
updated: 2026-04-20 (Phase 7 shipped — non-admin self-service + own API key)
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
| 1 | Baseline audit + scope hygiene (mutation endpoints gated; Scope Matrix doc) | ✅ shipped 2026-04-19 — 120+ endpoints classified, no leaks, 3 Loose Ends logged ([[scope-matrix]]) |
| 1.5 | Fail-closed `require_scopes` for JWT users with no resolved scopes (Phase 2 prerequisite) | ✅ shipped 2026-04-19 — admin bypass preserved; 36/36 auth tests green; see [[fix-log]] |
| 2 | `/auth/me` effective scopes + frontend hydration + `useScope()` hook | ✅ shipped 2026-04-19 — see [[fix-log]] |
| 2.5 | Widget dashboard rail scoping (per-user + everyone rail pins) | ✅ shipped 2026-04-19 — `dashboard_rail_pins` junction table, admin-only `scope='everyone'`, radio picker in Create/Edit drawers |
| 3 | UI route guards + nav filtering + control hiding | ✅ shipped 2026-04-19 — `<AdminRoute>` wraps `/admin/*`, rail+palette filter admin chrome for non-admins, Privacy section hoisted, new-channel owner picker (admin), owner chip in ChannelHeader, bot owner picker, UI tsc + 4/4 new channel-ownership tests green |
| 4 | Channel ownership enforcement (auto-populate user_id, edit/delete gating) | ✅ shipped 2026-04-19 — `assert_admin_or_channel_owner` helper + PUT/PATCH/DELETE wired + GET visibility (404 cross-user-private). 12 new tests, 32/32 green. |
| 5 | Bot ownership + `bot_grants` table + `view` role + admin GrantsSection + share-drawer coverage warning | ✅ shipped 2026-04-19 — migration 221, `apply_bot_visibility` helper, mint endpoint honors grants, `/bots` filtered for non-admins, GrantsSection tab on bot admin, `EditDashboardDrawer` shows "viewers can't use X" warning with one-click bulk grant, viewer-side mint 403 banner softened to amber with admin-vs-non-admin CTAs. 28/28 focused tests green. |
| 6 | Integration binding final lockdown (admin-only writes, parent-cover leak closed) | ✅ shipped 2026-04-19 — new `require_admin_and_scope` dep on 6 write endpoints + UI tab hidden for non-admins. 9 new tests (41/41 in `test_channel_ownership.py`). |
| 7 | Non-admin self-service (`/settings/account`, `/settings/channels`, `/settings/bots`) | ✅ shipped 2026-04-20 — three self-service pages, own API key view + rotate, sidebar gear visible to non-admins |

## Phase detail

### Phase 1 — Baseline audit + scope hygiene ✅ shipped 2026-04-19

Audit outcome: **no endpoint-level fixes needed.** 120+ mutation endpoints classified. Admin namespace is doubly-gated (router-level `verify_admin_auth` + endpoint-level `require_scopes`); non-admin routers consistently use `require_scopes`. No mutation endpoint sits entirely outside enforcement.

Findings logged as Loose Ends (all are design decisions, not scope-gate regressions):

1. **Phase 2 prerequisite** — `require_scopes` fails OPEN for JWT users with `_resolved_scopes=None` (`app/dependencies.py:242-246`). Combined with `_provision_user_api_key`'s silent exception-swallow (`app/services/auth.py:267`), users with failed provisioning get full access with empty scopes. This is a pre-Phase-2 blocker because Phase 2 will hydrate the UI with the empty scopes — the UI will hide everything while the backend grants everything. See [[loose-ends#Phase 2 prerequisite — close the fail-open backcompat in require_scopes]].
2. **`channels:write` transitively covers `channels.integrations:write`** — member_user preset grants `channels:write`, and `has_scope` parent-covers-child semantics make that cover `channels.integrations:write`. Means non-admins already CAN bind integrations. Phase 6 material. See [[loose-ends#`channels:write` parent scope covers `channels.integrations:write` for members]].
3. **`/transcribe` has no scope** — authentication-only (`app/routers/transcribe.py:68`). Minor. See [[loose-ends#Transcribe endpoint has no per-feature scope]].
4. **Widget actions per-dispatch authorization has no regression test** — design is correct but unguarded by tests. See [[loose-ends#Widget actions per-dispatch authorization needs unit test]].

Deliverable: [[scope-matrix]] — living reference, endpoint → scope → preset, with a regeneration command. Covers the admin + non-admin surfaces, the intentionally-open endpoints (auth flow, self-service `/me`, widget actions per-dispatch), and the three findings above.

### Phase 2 — `/auth/me` effective scopes + frontend hydration ✅ shipped 2026-04-19

Backend:
- `app/services/auth.py::resolve_user_scopes(db, user)` — resolves from `user.api_key_id` → `ApiKey.scopes`, with `["admin"]` synthetic fallback for admins missing a key (matches the `is_admin` bypass invariant).
- `app/routers/auth.py`: `UserResponse.scopes: list[str]` field, populated from the helper in `/me` GET, `/me` PUT, login, setup, google. 4 integration tests in `test_auth_profile.py::TestAuthMeScopes` covering member/admin/orphan-non-admin/orphan-admin shapes. 40/40 integration tests green.

Frontend:
- `ui/src/stores/auth.ts` + `ui/src/types/api.ts`: `AuthUser.scopes: string[]`.
- `ui/src/hooks/useScope.ts` (NEW): exports `useScope(scope)`, `useScopes(...)` (all-of), `useAnyScope(...)` (any-of), `useIsAdmin()`. `hasScope()` function ported from backend `has_scope()` at `app/services/api_keys.py:518` — same parent-covers-child, write-implies-read, wildcard, and admin bypass semantics. UI tsc clean.

No behavior change on existing routes — this phase only plumbed the primitive. Phase 3 consumes `useScope()` to hide nav and gate routes.

### Phase 2.5 — Widget dashboard rail scoping ✅ shipped 2026-04-19

Before diving into Phase 3 UI gating, filled a gap flagged mid-session: the `widget_dashboards.pin_to_rail: bool` column was a single toggle that forced the same sidebar rail on every user. Once non-admins can create dashboards, they'd be pinning personal projects into everyone's sidebar.

- **Schema.** Migration 217 added `dashboard_rail_pins(dashboard_slug, user_id NULL|uuid, rail_position, created_at)` junction with partial unique indexes (`ix_drp_everyone WHERE user_id IS NULL`, `ix_drp_user WHERE user_id IS NOT NULL`). Backfilled NULL-user rows from every existing `pin_to_rail=TRUE` dashboard, then dropped the legacy `pin_to_rail` + `rail_position` columns. ORM `DashboardRailPin` mirrors the indexes via both `postgresql_where` and `sqlite_where` so SQLite tests honor them.
- **Service.** New `app/services/dashboard_rail.py` — `set_rail_pin` / `unset_rail_pin` / `resolved_rail_state` / `resolved_rail_state_bulk`. `scope='everyone'` raises 403 unless `is_admin=True`; `scope='me'` requires a concrete `user_id`. Personal row wins the effective position when both exist.
- **Router.** `app/routers/api_v1_dashboard.py` dropped `pin_to_rail` + `rail_position` from `CreateDashboardRequest` / `UpdateDashboardRequest` and exposed `PUT`/`DELETE /api/v1/widgets/dashboards/{slug}/rail`. Every `serialize_dashboard` call now carries a resolved `rail: {me_pinned, everyone_pinned, effective_position}` block per the current viewer, so the sidebar hits one `GET /dashboards` and filters locally. `_auth_identity()` helper maps `ApiKeyAuth` (admin only when `"admin"` in scopes) or `User` (`is_admin`) to `(user_id, is_admin)`.
- **Frontend.** `Dashboard.pin_to_rail` / `rail_position` removed; replaced by `Dashboard.rail: DashboardRail` block. New `useDashboardsStore.setRailPin` / `unsetRailPin` actions. Sidebar filter reads `d.rail.me_pinned || d.rail.everyone_pinned`, sorts by `effective_position`. New `RailScopePicker.tsx` component (Off / For everyone / Just me radios) replaces the single checkbox in `EditDashboardDrawer` + `CreateDashboardSheet`. "For everyone" is admin-gated via `useIsAdmin()`; non-admins see an "Admins only" chip. Defaults on create: admin → "For everyone", non-admin → "Just me".
- **Tests.** 11 new unit tests (`tests/unit/test_dashboard_rail.py`) covering admin gating, personal-vs-everyone coexistence, upsert, cascade-on-dashboard-delete. 8 new integration tests (`tests/integration/test_dashboard_rail.py`) covering rail-block hydration, PUT/DELETE, lazy channel-dashboard create, legacy-field stripping, invalid scope rejection, per-dashboard isolation. Existing `test_dashboards_api.py` + `test_dashboards_service.py` updated to drop rail-field assertions. 55/55 green across dashboard+rail, 84/84 green across adjacent widget modules, 56/56 green across auth modules.

Plan: `~/.claude/plans/peaceful-sparking-spring.md` (status: executed).

### Phase 3 — UI route guards + nav filtering + control hiding ✅ shipped 2026-04-19

**Route guard + fallback card**
- `ui/src/components/routing/AdminRoute.tsx` — wraps the admin `Outlet` in `ui/src/router.tsx`. Admin → children; non-admin → `<UnauthorizedCard />`. Matches backend invariant: `verify_admin_auth` already rejects non-admin JWTs at every `/api/v1/admin/*` endpoint; UI now stops showing chrome that would 403 on click.
- `ui/src/components/shared/UnauthorizedCard.tsx` — small centered card: Lock + "Admin only" + "Back to home".

**Navigation filtering** (`useIsAdmin()` gate)
- `SidebarRail.tsx` — hides Tasks / Bots / Skills / Integrations / Activity / Learning for non-admins. Keeps Home + Widgets (widget dashboards are per-user via Phase 2.5).
- `CommandPalette.tsx` — skips bot edit items, `ADMIN_ITEMS`, integration admin pages, and sidebar sections (which all point into `/admin/*`). Filters recent pages whose href starts with `/admin/`. Channels + widgets remain searchable.
- `SidebarFooter.tsx` — Settings gear (links to admin-only `/settings`) and `UsageHudBadge` (calls `/api/v1/admin/usage/forecast`) hidden from non-admins. Both produced 403s when a non-admin clicked them. Search shortcut row stays. (Patched 2026-04-19 follow-up.)

**Channel owner / private polish**
- `ChannelList.tsx` was already Lock-vs-Hash; `CommandPalette` channel entries now mirror it. `ChannelHeader.tsx` swaps the hardcoded Hash icon for Lock when `channel.private`.
- `GeneralTab.tsx` — Privacy `Section` lifted out of `AdvancedSection` into the main body between General and Channel Prompt. Owner dropdown (admin only) uses new shared `UserSelect`; non-admins see a read-only `Owned by <name>` line. Danger Zone (delete) gated on admin-or-owner (`form.user_id === currentUser.id`).
- `channels/new.tsx` — admin-only "Owner" Section with `UserSelect`, default = current user. Non-admins rely on backend auto-populate.
- `ChannelHeader.tsx` — subtle inline "Owner: {name}" chip shown to admins when viewing a channel owned by another user.
- Backend `api_v1_channels.py::create_channel` — `ChannelCreate.user_id` field added; non-admin auth user always becomes owner, admin may pre-assign via body (invalid UUID → 400).

**Bot owner UI**
- `admin/bots/[botId]/index.tsx` — new "Owner" FormRow in Identity section using `UserSelect`, writes `draft.user_id`.
- `admin/bots/index.tsx` — `BotCard` gains an "Owned by {name}" subtle line when `bot.user_id` is set; uses shared `useAdminUsers()` for name lookup.

**Shared plumbing**
- `ui/src/api/hooks/useAdminUsers.ts` — `useQuery(["admin-users"])`, gated to admins, 60s stale time. One cache across all consumers.
- `ui/src/components/shared/UserSelect.tsx` — thin SelectInput wrapper.

**Tests**
- `test_channel_ownership.py::TestChannelOutSchema` — added `test_create_channel_honors_body_user_id_for_admin_key` + `test_create_channel_rejects_invalid_user_id`. 20/20 green.
- UI `tsc --noEmit` clean.

**Deferred to Phase 4**: backend 403 when a non-owner/non-admin JWT tries to `PATCH` / `DELETE` a channel they don't own — Phase 3 hides the UI, Phase 4 makes the enforcement match.

### Phase 4 — Channel ownership enforcement ✅ shipped 2026-04-19

Goal: non-admin creates a channel → only they (and admins) can edit/delete it. Private channels isolated.

**Backend**
- `app/dependencies.py::assert_admin_or_channel_owner(channel, auth)` — new helper. `ApiKeyAuth` → bypass (keys have no ownership concept; row-level access for keys is gated by scope). `User.is_admin` → bypass. Otherwise requires `channel.user_id == user.id`. Channels with `user_id=NULL` (legacy/orphan) are admin-only edits.
- Wired into:
  - `DELETE /api/v1/channels/{id}` (`api_v1_channels.py:744`)
  - `PUT /api/v1/channels/{id}` (`api_v1_channels.py:769`)
  - `PUT|PATCH /api/v1/channels/{id}/config` (`api_v1_channels.py:577`)
- `GET /api/v1/channels/{id}` now applies `apply_channel_visibility` to its single-row select — non-admin requesting another user's private channel returns **404** (not 403, to avoid leaking existence).
- `POST /api/v1/channels` already auto-populates owner for non-admin JWT (Phase 3 work, lines 339-350).

**Sub-resource endpoints not gated** (Phase 4 scope is the canonical channel itself):
- `POST/DELETE /channels/{id}/bot-members/*`, `PATCH /channels/{id}/bot-members/{id}/config` — still scope-only. Bot-membership is "soft" channel state; revisit if a non-admin owner pattern emerges.
- `POST/DELETE /channels/{id}/integrations/*` — Phase 6 covers integration lockdown.
- `POST /channels/{id}/messages/{reset,compact,switch-session,inject}` — these are conversation operations, not channel mutations. Still scope-gated by `channels.messages:write`.

**Tests** (`tests/integration/test_channel_ownership.py`)
- New `jwt_client_factory` fixture mirrors the `client_factory` shape from `test_widget_auth_mint.py` so JWT-as-non-admin paths are testable. Auto-attaches the member-preset scopes (`chat`, `channels:read`, `channels:write`) to satisfy the existing scope gates.
- `TestChannelOwnershipEnforcement` (8 tests): owner-can-update, non-owner-cannot-update, non-owner-cannot-delete, owner-can-delete, admin-can-update-any, admin-can-delete-any, unowned-channel-rejects-non-admin, non-owner-cannot-update-config.
- `TestChannelGetVisibility` (4 tests): non-admin-cannot-get-other-private-404, owner-gets-own-private, non-owner-gets-public, admin-gets-any-private.
- 32/32 green in `test_channel_ownership.py`. 5 join-test failures in `test_channel_members.py::TestJoinLeaveAPI` exist on baseline (verified by stash + rebuild) — unrelated to Phase 4.

**Deferred to Phase 6** Confirmed `apply_channel_visibility` use on the canonical list (`GET /channels`) and single GET. Did NOT audit every read sub-resource (`/messages/search`, `/state`, `/events`, `/integrations`, `/bot-members`); those still 200 for any user with the read scope. Most are admin-tier scopes today, so the surface is small, but Phase 6's audit should sweep them.

**UI work not in Phase 4** Hiding Integration Bindings / Advanced / Tool Policies tabs in `ChannelSettings.tsx` for non-admin. Backend matches the route guard now; the UI tabs are a separate small change.

### Phase 5 — Bot ownership + grants ✅ shipped 2026-04-19

Goal: admin designates bot owners and grants non-admin users access so widget dashboards shared via the "For everyone" rail don't 403.

**Scope delivered (single commit, not split 5a/5b):**

- **Schema.** Migration 221 adds `bot_grants(bot_id, user_id, role, granted_by, created_at)` with unique `(bot_id, user_id)`, `CASCADE` on bot + user delete, `SET NULL` on granter delete. `role` column kept for forward-compat; only `'view'` is accepted today (no non-admin edit UI exists yet, so `'manage'` is YAGNI).
- **ORM.** `BotGrant` in `app/db/models.py` mirroring `ChannelMember` shape.
- **Visibility helper.** `app/services/bots_visibility.py::apply_bot_visibility(stmt, user)` — admin bypass, else `Bot.user_id == user.id OR Bot.id IN (select bot_id from bot_grants where user_id == user.id)`. Mirrors `apply_channel_visibility`. `can_user_use_bot(db, user, bot)` companion helper.
- **Mint endpoint.** `app/routers/api_v1_widget_auth.py::_caller_may_use_bot` now checks grants in addition to admin/owner. 403 payload carries `reason='bot_access_denied'` + `bot_id` + `bot_name` so the viewer-side banner can render specific copy.
- **List endpoints.** Public `GET /bots` (`app/routers/chat/_routes.py`) filters by visibility for non-admin users. Channel-creation picker no longer shows bots non-admins can't use. Admin `GET /api/v1/admin/bots` is unchanged (router-level `verify_admin_auth`).
- **Grants CRUD.** New `app/routers/api_v1_admin/bot_grants.py`: `GET`, `POST`, `DELETE /api/v1/admin/bots/{id}/grants`, plus `POST .../grants/bulk` for the dashboard coverage CTA. 409 on duplicate, 422 on unknown role, 404 on missing bot/grant.
- **Admin UI.** `ui/app/(app)/admin/bots/[botId]/GrantsSection.tsx` + `useBotGrants` hook. New "Grants" section between "Permissions" and "Tool Policies" on the bot admin page. Shows owner chip (read-only), existing grants list with revoke, and a `UserSelect` + "Grant access" row that excludes admins + owner + already-granted users.
- **Dashboard share discoverability.** `ui/app/(app)/widgets/DashboardShareWarning.tsx` — when `RailScopePicker` is set to `everyone`, scans dashboard pins for `source_bot_id`, cross-references each bot's grants against active non-admin users, and surfaces one amber warning with "Grant access to all" (calls bulk endpoint per gap bot). `dashboardBotCoverage.ts` is the pure helper.
- **Viewer UX.** `InteractiveHtmlRenderer.tsx` mint-error banner keyed on `detail.reason`: `bot_access_denied` renders amber (not red) with "Viewers can't use '{bot}' yet — grant access…" for admins (links to `/admin/bots/{id}#grants`) or "Ask an admin for access to '{bot}'" for non-admins. Existing `bot_missing_api_key` path unchanged.

**Deferred (NOT in Phase 5):**
- `manage` role — schema supports it; no non-admin edit surface to gate, so no UI/enforcement work shipped.
- Channel-creation bot-picker filtering on the admin side (admin sees all; non-admins already filtered via `/bots`).
- Registry-only bots (no DB row) are not filtered — they stay admin-scoped. Flagged in Ideas & Investigations.
- `/settings/bots` self-service landing for non-admins → Phase 7.

**Tests (28/28 green):**
- `tests/unit/test_bot_grants.py` — `apply_bot_visibility` (admin/owner/grantee/stranger), `can_user_use_bot`, ORM cascade declarations.
- `tests/integration/test_bot_grants_api.py` — CRUD, 409 dup, 422 role, 404 missing, bulk idempotency, unknown-user rejection.
- `tests/integration/test_widget_auth_mint.py` — new grantee test + updated non-owner test asserts `reason='bot_access_denied'` payload.
- UI `tsc --noEmit` clean.

References: plan `~/.claude/plans/buzzing-honking-pumpkin.md`. Commit: `886cbf58` (bundled with unrelated tool-composition work).

### Phase 6 — Integration binding final lockdown ✅ shipped 2026-04-19

Goal: non-admins cannot mutate `ChannelIntegration` rows, regardless of scope-preset nuances.

**The bug** (Loose End #2, filed at Phase 1). `has_scope()` at `app/services/api_keys.py:518-566` implements parent-covers-child — `channels:write` transitively satisfies `channels.integrations:write`. Every preset that carried `channels:write` (`member_user`, `slack_integration`, `chat_client`) therefore passed the generic `require_scopes("channels.integrations:write")` gate on the 6 binding endpoints. Net effect: a non-admin member JWT (or any integration-shape key) could POST/DELETE/PATCH integration bindings on their own channel despite the Phase 0 "admin-only" decision.

**The fix.** New `app/dependencies.py::require_admin_and_scope(scope)` — wraps `require_scopes(scope)` and adds an admin assertion on top (`"admin" in ApiKeyAuth.scopes` OR `User.is_admin=True`). Applied to the 6 write endpoints in `app/routers/api_v1_channels.py`:
- `POST /api/v1/channels/{id}/integrations` — bind
- `DELETE /api/v1/channels/{id}/integrations/{binding_id}` — unbind
- `POST /api/v1/channels/{id}/integrations/{binding_id}/adopt`
- `POST /api/v1/channels/{id}/integrations/{integration_type}/activate`
- `POST /api/v1/channels/{id}/integrations/{integration_type}/deactivate`
- `PATCH /api/v1/channels/{id}/integrations/{integration_type}/config`

Read endpoints (`GET /channels/{id}/integrations`, `GET /channels/{id}/integrations/available`) stay on `require_scopes("channels.integrations:read")` — non-admins still see what's bound to their channel, read-only.

**Why not globally tighten `has_scope`?** Option (a) from the Loose End would change parent-cover semantics for every `*:*` preset in the system — wide blast radius for what's really a per-endpoint policy call. Option (b) (rewrite `member_user` to enumerate sub-scopes and omit `channels.integrations:*`) is honest but brittle — every new sub-scope is a drift risk. Option (c) — narrow admin assertion at the handler — is the tightest fix and leaves the reusable `require_admin_and_scope` dep for any future sub-scope that must remain admin-only despite the parent.

**UI match.** `ui/app/(app)/channels/[channelId]/settings.tsx` gains `adminOnly: true` on the `Integrations` tab definition; `visibleTabs = ALL_TABS.filter(tb => !tb.adminOnly || isAdmin)` drives both the rendered tab list and the content branch. Non-admin users no longer see the tab or its content. Matches the Phase 3 sidebar-rail / command-palette admin-chrome hiding pattern.

**Admin-router endpoints** (`api_v1_admin/channels.py:2233,2278`) are unchanged — those were always router-gated by `verify_admin_auth` and only held `:read` scopes anyway.

**Tests** (9 new in `tests/integration/test_channel_ownership.py::TestChannelIntegrationBindingAdminGate`):
- Non-admin JWT + default member scopes → 403 on POST bind / DELETE unbind / POST adopt / POST activate / POST deactivate / PATCH config; detail contains "admin".
- Non-admin JWT → 200 + `[]` on GET list (reads remain permitted).
- Admin JWT → 201 on POST bind (the gate passes; endpoint returns successfully).
- `ApiKeyAuth(scopes=["chat","channels:read","channels:write"])` — the `slack_integration`/`chat_client` shape — → 403 on POST bind, asserting the scoped-key path of the leak is also sealed.

41/41 green in `test_channel_ownership.py` (32 prior + 9 new). 7/7 still green in `test_integration_activation.py` (static-admin-key path unchanged). UI `tsc --noEmit` clean.

### Phase 7 — Non-admin self-service ✅ shipped 2026-04-20

Goal: non-admin has a coherent "this is my stuff" landing.

**Backend**
- `GET /auth/me/api-key` — metadata only (id, name, key_prefix, scopes, is_active, created_at, last_used_at). Never returns plaintext. Returns `null` for users without provisioned keys.
- `POST /auth/me/api-key/rotate` — mints fresh key with the caller's role preset (`admin_user` vs `member_user`), soft-revokes the prior key (`is_active=False`), reassigns `user.api_key_id`, returns plaintext **once** in `ApiKeyRotateResponse{key, full_key}`. Same flow handles "no prior key" as first-mint.
- `GET /auth/me/bots` — owned + granted bots with `role: "owner" | "view" | "manage"` badge. Owner wins when the user both owns and has a grant. Shape is separate from the visibility-filtered `GET /bots` so the UI gets role info without a join.
- No new endpoint for channels — the self-service page filters `GET /api/v1/channels` client-side by `channel.user_id === me.id`. That list is already scoped by `apply_channel_visibility`, so no data leak.

**Frontend**
- New `ui/app/(app)/settings/SettingsShell.tsx` — tab bar (Account / Channels / Bots; plus a "System" tab that links out to the existing `/settings` admin page for admins). Shared `PageHeader` + tab bar wraps the three self-service routes via an `<Outlet />`.
- `ui/app/(app)/settings/account.tsx` — consolidates the old `/profile` page (Account / Integrations / Security sections) and adds `ApiKeySection`: shows prefix + scopes + active status, "Rotate key" → confirmation → plaintext banner with Copy button (dismisses; no persistence).
- `ui/app/(app)/settings/channels.tsx` — "My Channels" list (owner-filtered). Public/private icon + Private badge, links to channel. "Create your first channel" CTA when empty.
- `ui/app/(app)/settings/bots.tsx` — "My Bots" list using `/auth/me/bots`. Bot avatar + display name + model + `RoleBadge` (Owner / Manage / View). Admin row links to `/admin/bots/{id}`, non-admin links to `/channels/new?bot_id={id}` (safest default since they can't edit the bot).
- Router: `{ path: "settings", element: <SettingsShell />, children: [account, channels, bots] }` sits alongside the existing `/settings` → `SettingsPage` route; react-router v6 matches `/settings` to the admin page and `/settings/*` to the shell. `/profile` now redirects to `/settings/account`; `profile.tsx` deleted. `AvatarMenu` "Profile" link renamed to "Account" → `/settings/account`.
- `SidebarFooter.tsx` — gear visible to all users (previously admin-only). Admin → `/settings` (system config unchanged); non-admin → `/settings/account`.

**Tests** (10 new, 19/19 green in `test_auth_profile.py`)
- `TestAuthMeApiKey` (5): null when unprovisioned, metadata shape (no plaintext leak), rotate mints new + revokes old + repoints user, admin rotation gets admin preset, rotate handles first-mint for orphaned user.
- `TestAuthMeBots` (4): owned returns `role="owner"`, grantee returns `role="view"`, owner wins when both apply, empty list for no bots.

**Intentionally deferred**
- No user-specific API-key CRUD beyond one key — `user.api_key_id` is 1:1 by design (`app/services/auth.py::_provision_user_api_key`).
- No "reveal stored plaintext" — `create_api_key(store_key_value=False)` means plaintext is shown at rotation and never recoverable. Matches admin-created keys.
- "User-cannot-update-another-user's-profile" was not added as a new test — `/auth/me` PUT/GET are structurally self-only (they act on `verify_user`'s return), and `/api/v1/admin/users/{id}` is already protected by `verify_admin_auth`. Covered by existing admin-route tests, not re-asserted here.

References: plan scope landed directly without a `~/.claude/plans/` file — the Track spec plus this session log are authoritative.

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
