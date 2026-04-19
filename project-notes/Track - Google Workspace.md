---
tags: [agent-server, track, google-workspace]
status: active
created: 2026-04-07
---
# Track — Google Workspace Integration

**Goal:** Make the Google Workspace integration production-ready for Flynn Thoughts (first real-world deployment) and robust enough for general use.

**Context:** The integration is built and feature-complete across 12 Google APIs. What's missing is operational reliability — token lifecycle, scoping, and the ability to handle the photo-heavy workflows that interior design demands.

## Phase 1: Token Lifecycle (blocks go-live)

The access token expires after 1 hour. No refresh logic exists anywhere — the `gws` tool writes a temp credentials file with the stored access token and hopes it's still valid. After expiry, all commands fail silently until the user re-authorizes through the browser.

- [x] **Implement token refresh in `gws` tool** — `_ensure_fresh_token()` checks `GWS_TOKEN_EXPIRES_AT` with 120s buffer, refreshes via Google's token endpoint, persists new token + expiry to DB.
- [x] **Store token expiry timestamp** — OAuth callback now captures `expires_in` and stores `GWS_TOKEN_EXPIRES_AT` as epoch seconds.
- [x] **Handle refresh token revocation gracefully** — refresh failure returns clear "reconnect at Admin > Integrations" message. CLI auth errors (invalid_grant, 401, etc.) also detected from stderr and surfaced as friendly reconnect messages.
- [x] **Auth status endpoint reports token health** — `/auth/status` now returns `token_expires_at` and `token_healthy` fields.
- [ ] **Move state tokens to DB** — currently in-memory dict, lost on restart, won't work multi-process. Use `IntegrationSettings` or a short-lived DB record. (Low priority — only used during one-time admin OAuth flow.)

## Phase 2: Drive Scoping (blocks go-live)

The Flynn Thoughts deployment assumes each channel's workspace config constrains which Drive folder the agent can access (e.g., a client channel only sees `Clients/Smith Residence/`). Currently there's no folder-level scoping — the agent sees the entire Drive and relies on prompt instructions for isolation.

### Implementation plan

**Config field** — Add a `drive_root_folder` string field to `setup.py` `binding.config_fields`. The `ConfigField` type already supports `type: "string"` (used by Frigate and BlueBubbles integrations). UI rendering is automatic via `IntegrationsTab.tsx:298`. Value goes to `ChannelIntegration.activation_config` (JSONB column, `models.py:250`). The value should be a Google Drive folder ID (e.g., `1ABC...xyz`).

**Tool enforcement** — In `gws.py`, after the channel allowed-services check (~line 222), read `drive_root_folder` from the same `activation_config`. When set and the service is `drive`:
- For `files list` commands: inject `--params '{"q": "'<folder_id>' in parents"}'` if no `--params` already present, or merge into existing params.
- For `files get`/`files export`: allow (the file ID is already specific).
- For `files create`/upload: inject `--params '{"parents": ["<folder_id>"]}'` to force uploads into the scoped folder.
- Surface the folder constraint in the tool response so the agent knows its scope.

**Key files:**
- `setup.py:49` — add config field after `allowed_services`
- `gws.py:120` — extend `_get_channel_allowed_services` to also return `drive_root_folder` (or add a parallel helper)
- `gws.py:~230` — inject folder constraints before CLI execution
- `skills/google-workspace.md` — add section on folder scoping
- `carapaces/google-workspace.yaml` — mention folder scoping in system prompt

**Design decision:** Use folder ID, not folder path. Paths are ambiguous in Drive (duplicate names allowed). The admin copies the folder ID from the Drive URL (`drive.google.com/drive/folders/<ID>`). The config field description should say this.

**Testing:** Add unit tests for folder injection logic. Integration test: create a scoped channel, verify `files list` only returns files in the target folder.

- [x] **Add `drive_root_folder` to channel activation config** — string field in `setup.py` activation.config_fields, folder ID from Drive URL.
- [x] **Soft folder hint in `gws` tool** — when drive_root_folder is set and service is `drive`, prepends "Note: This channel's Drive workspace is scoped to folder {id}" to the response. Soft hint, not hard enforcement.
- [x] **Config fields moved to activations** — `allowed_services` and `drive_root_folder` now live on `activation.config_fields` instead of `binding.config_fields`. Fallback reads old binding dispatch_config for migration.
- [x] **Integration composition** — `includes` in activation manifest merges carapaces + config_fields from included integrations. flynndesign now `includes: ["google_workspace"]`.
- [x] **Auto-activate/deactivate includes** — activating a parent auto-activates included integrations; deactivating only removes them if no other parent still includes them.
- [x] **IntegrationsTab rewrite** — extracted into 7 sub-components, converted from React Native to web-native, added save-on-change activation config fields, composition filtering (included_by integrations hidden).
- [ ] **Hard folder enforcement (deferred)** — inject `parents` constraints into Drive commands. Tracked as browse field type follow-up.
- [ ] **Document the scoping model** — update skill guide and carapace prompt to explain folder-based isolation.

## Phase 3: Photo & Image Handling (blocks core use case)

Interior design is photo-heavy. The core Flynn Thoughts workflow is: upload project photos to Drive, have the agent describe/organize them, build presentations. This needs to work end-to-end.

- [ ] **Test multimodal photo flow** — can the agent fetch a photo from Drive via `gws drive files get` + `--output`, then view/describe it? What's the size limit before Claude context breaks? Raw iPhone photos are 5-10MB.
- [ ] **Add image resize/optimization** — if raw photos are too large, add a post-download step to resize before passing to the model. Could be a simple Pillow call or a workspace file tool enhancement.
- [ ] **Test Slides image insertion** — can `gws slides` insert images by Drive file reference, or does it need a URL/base64? Document the working approach.
- [ ] **Drive upload from workspace** — verify the `--upload` flag works for putting workspace files (processed images, generated content) back into Drive.

## Phase 4: Operational Polish

- [ ] **Retry/backoff for Google API rate limits** — currently no retry logic. A burst of commands (morning briefing hitting Gmail + Calendar + Drive) could hit rate limits.
- [ ] **Fix service aliases** — `wf` and `reports` aliases point to services with no scope mappings. Either add scopes or remove the aliases.
- [ ] **Integration tests** — currently unit tests only with everything mocked. Need at least a few tests that exercise the real OAuth flow and token refresh logic (can use Google's OAuth playground or test credentials).
- [ ] **Temp credentials file security** — the current approach writes tokens to a temp file on disk. Explore passing credentials via environment variable or stdin to the GWS CLI instead.
- [ ] **Output handling for large responses** — 50KB truncation is aggressive for Drive file listings or Sheets data. Consider streaming or pagination guidance in error messages.

## Phase 5: UX for Non-Technical Users

- [ ] **Tool approval on mobile** — Gmail send and other approval-gated actions need clear, touch-friendly approval prompts. Kathy (first user) will primarily use her phone.
- [ ] **Error messages for end users** — current errors reference OAuth, CLI binaries, and config keys. Non-technical users need "Your Google connection expired, tap here to reconnect" style messaging.
- [ ] **Morning briefing reliability** — the Office channel heartbeat (8am ET) will hit Gmail + Calendar. This is the "does it just work every day" test. Token refresh (Phase 1) is prerequisite.

## Dependencies

- Phase 1 is prerequisite for everything else (nothing works reliably without token refresh)
- Phase 2 is prerequisite for multi-client channel deployment
- Phase 3 is prerequisite for the core interior design workflow
- Phase 5 depends on phases 1-3 being stable

## Related

- `../flynn-thoughts/Spindrel Integration Plan` — deployment plan and use cases
- Integration code: `integrations/google_workspace/`
