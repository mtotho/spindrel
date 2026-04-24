---
tags: [agent-server, track, ui, vision]
status: active
updated: 2026-04-24
---

<!-- Latest pass (2026-04-24): Memory & Knowledge admin reframe + guide-reset control language adoption. See UI Polish shared-control reset. -->
<!-- Previous pass (2026-04-23): Pass 4a — ParticipantsTab + ToolsOverrideTab migrated (agent/channel tab first-landing continuity). See UI Polish track Pass 4a. -->
<!-- Previous pass (2026-04-23): Pass 3 — channel dashboard + settings migration + two-gear unification. -->


# Track — UI Vision

## North Star

Canonical design spec lives in `agent-server/docs/guides/ui-design.md`. This track is the **living companion** — what has been adopted, what is outstanding, and what the next pass looks like. The doc is target; this track is progress.

## Why this track exists (separate from UI Polish)

- **UI Polish** (`Track - UI Polish.md`) is the execution log — Pass 1 (Stitch-inspired chat polish, April 9) and Pass 2 (channel terminal mode, April 21), plus the April 23 channel-settings consistency pass. Every actual change is logged there.
- **UI Vision** (this track) is the adoption ledger for the canonical spec. Consistency keeps leaking despite `Track - UI Polish` capturing rationale — no single document said "this is the target" until now. That document is `docs/guides/ui-design.md`.

## Status

| Area | Status | Notes |
|---|---|---|
| Canonical spec doc | ✅ shipped 2026-04-23 | `agent-server/docs/guides/ui-design.md`, linked from mkdocs Guides nav |
| Surface taxonomy | ✅ reset 2026-04-24 | Command, app-shell/content, and control surfaces. Existing sidebar/rail/channel header/terminal mini-chat are reference surfaces; settings/admin controls get stricter chrome-budget rules plus UX-flow checks for mixed current/available catalogs. |
| Token system spec | ✅ refreshed 2026-04-24 | `bg-surface*`, `border-surface-border`, `text-text*`, `bg-accent*`, semantic color set all named; light mode now uses a cooler neutral surface ladder instead of extra accent color. |
| Active-row pill canonicalized | ✅ documented | `.sidebar-item-active` in `ui/global.css:11-13` is the one canonical active-state signal |
| Radius scale | ✅ documented | 0 / 2 / 4 / 6 / 10 / full — command surfaces go square, content surfaces default to 6px |
| Dark + light parity rules | ✅ documented | No mode branching in JSX; verify both before claiming done |
| Known-debt appendix | ✅ documented | Inline hex, Bootstrap-blue task states, `useThemeTokens()` callers — all listed with file:line |
| Cross-references in feedback memories | ✅ 2026-04-23 | `feedback_no_gratuitous_borders`, `feedback_no_left_colored_borders`, `feedback_tailwind_not_inline`, `feedback_widgets_use_app_theme` all point at the doc |
| `spindrel-ui` skill | ✅ corrected 2026-04-24 | Project-level at `agent-server/.claude/skills/spindrel-ui/SKILL.md`; gradient/shadow "signature moves" removed so it now follows the canonical guide instead of extending it. |
| Channel dashboard breadcrumb | ✅ migrated 2026-04-23 | `ChannelDashboardBreadcrumb.tsx` — left gear removed; scratch chip moved to Tailwind tokens; no `useThemeTokens()` |
| Channel settings header + tab strip | ✅ migrated 2026-04-23 | `settings.tsx:271-438` — dropped `border-b` between header and tabs (SKILL §6), dropped blur, underline via `after:` pseudo; no `useThemeTokens()` |
| Channel tab first-landing sections | ✅ migrated 2026-04-23 | `ChannelSettingsSections.tsx` — TagEditor, category chip, owner row, metadata footer, DangerZone all on Tailwind tokens; `DashboardSettingsLink` and `PresentationTabSections` migrated; no `useThemeTokens()` in this file |
| Two-gear unification | ✅ shipped 2026-04-23 | Left gear on channel dashboard breadcrumb REMOVED. Layout controls moved to new "Dashboard" tab in channel settings. `DashboardConfigForm.tsx` shared between drawer (non-channel) and tab (channel). Router redirect `/widgets/channel/:id/settings` now lands on `#dashboard` tab. |
| Debt migration (hex → token, Bootstrap-blue → accent) | ⏳ deferred | Tracked in doc §8; migrate opportunistically when touching each file |
| Agent tab supplement (`ToolsOverrideTab`) | ✅ migrated 2026-04-23 (Pass 4a) | SectionLabel on canonical `uppercase text-[10px] tracking-[0.08em] text-text-dim/70`; ToolChip/SkillChip on SKILL §4 badges; search + addable-skill rows on `bg-input` + `bg-surface-raised hover:bg-surface-overlay/60`; 0 `useThemeTokens()` |
| Channel tab supplement (`ParticipantsTab`) | ✅ migrated 2026-04-23 (Pass 4a) | All inline `style={{}}` removed; member badges on `rounded-full bg-surface-overlay text-text-dim` uppercase chip; `BotPicker` lost shadow per SKILL §3; shared `INPUT_CLASS` for number/textarea inputs; 0 `useThemeTokens()` |
| Integration control proof path | ✅ migrated 2026-04-24 (Pass 4b) | `ActivationsSection`, `ActivationCard`, `ActivationConfigFields`, `BindingsSection`, `BindingForm`, `SuggestionsPicker`, and `MultiSelectPicker` now use token/Tailwind control-surface chrome; activation add-ons split Added vs Available with a quiet filter; no `useThemeTokens()` in the integration settings flow. |
| `IntegrationsTab` wrapper | ✅ clean 2026-04-23 (Pass 4a) | 5-line re-export already token-free. |
| Channel Tasks tab | ✅ migrated 2026-04-24 (Pass 4c start) | `TasksTab`, `TaskCardRow`, `TaskConstants`, and `Spinner` now use grouped control flow, quiet segmented filters, borderless tonal rows, semantic token badges, and no `useThemeTokens()` in the visible task list path. |
| Admin Memory & Knowledge | ✅ first pass 2026-04-24 | `/admin/learning` is now Memory & Knowledge with shared tabs, read-first unified search, memory activity, knowledge inventory, conversation-history search, file-backed in-page source inspection, and lower-chrome Dreaming/Skills tabs. |
| Admin Machines + Integrations | ✅ migrated 2026-04-24 | `/admin/machines`, `/admin/integrations`, integration detail, and route-owned integration subcomponents now use shared control-surface primitives, Tailwind tokens, no `useThemeTokens()`, and no inline hex/RGBA in the refreshed paths. Machine-control integration detail remains summary/link-only, with Admin > Machines as the canonical lifecycle surface. |
| Deeper settings tab panels | ⏳ deferred | **Pass 4c remaining candidates**: HeartbeatTab (+ HeartbeatHistoryList, HeartbeatContextPreview), PipelinesTab (+ PipelineRunLive/PreRun), HistoryTab, QuietHoursPicker. **Pass 4d**: ContextTab (dirtiest — 10 inline hex). **Pass 4e (own plan)**: ChannelWorkspaceTab, AttachmentsTab, ChannelFileBrowser/Viewer/ExplorerParts. |

## Adoption guardrails

- **New code**: every UI change must pass the doc's checks (§5 parity + §7 a11y floor). No new inline hex. No new Bootstrap-blue. No filled accent buttons for routine settings rows. No new colored-left-stripe hover states. No decorative gradients or shadow stacks on settings/admin/control surfaces.
- **Touched code**: when a file in the §8 debt list is modified for any reason, migrate its debt in the same commit.
- **Reviews**: the Anti-patterns table (§6) is the review checklist.

## Near-term debt migration targets (in §8 of the doc)

- `ui/src/components/shared/TaskStepEditor.tsx` — running step chrome + `animate-pulse` → token pair + dot.
- `ui/src/components/chat/ToolsInContextPanel.tsx:38-40` — `rgba(...)` status backgrounds → `bg-purple/10` / `bg-success/10` / `bg-accent/10`.
- `ui/src/components/layout/SystemPauseBanner.tsx`, `ApprovalToast.tsx`, `MemoryHygieneGroupBanner.tsx`, `DelegationCard.tsx`, `IndexStatusBadge.tsx` — inline-hex icon colors → `text-*` tokens.
- `ui/src/components/chat/MarkdownContent.tsx:54-58` — `MENTION_COLORS` hex quartet → paired light/dark tokens.
- `ui/src/components/shared/task/StepsJsonEditor.tsx` — JSON syntax colors → paired light/dark token set (a new "syntax" token family may be justified).

## Key invariants

- **There is one token system.** If a color does not have a token, it does not exist.
- **Light-mode depth is neutral.** Do not fix washed-out light screens by adding page-local accent washes; tune global surface tokens or shared primitive opacity recipes.
- **There are three archetypes.** Command surfaces (monospace, square chrome), app-shell/content surfaces (low-chrome navigation/header/content), and control surfaces (settings/admin/config forms with a strict chrome budget). Archetype is a font-and-density choice, not a theme choice.
- **Archetype is scoped.** The terminal vibe lives on the chat screen (and its dock / command surfaces). It is not the site-wide style.
- **Preserve the good header.** The existing channel header is a reference surface for the target low-chrome direction, not a redesign target.
- **Active-row signal is the pill in `ui/global.css:11-13`.** Do not invent alternatives.
- **Routine control actions are inline/ghost.** Filled accent buttons are reserved for rare final confirmation moments, not `Add`/`Edit`/`Run` rows.
- **Flow beats row paint.** Mixed current/available catalogs must be grouped and searchable before row styling is considered complete.
- **Dark and light are co-equal.** Neither is an afterthought.

## See Also

- `agent-server/docs/guides/ui-design.md` — the canonical spec (target).
- `Track - UI Polish.md` — execution log.
- `Architecture Decisions.md` — load-bearing design decisions.
