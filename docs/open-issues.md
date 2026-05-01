---
tags: [spindrel, open-issues]
status: active
updated: 2026-04-23
---
# Open Issues

Accumulative log of review findings that haven't been triaged into bugs, tracks, or tech-debt lines yet. Distinct from [[loose-ends]]: Loose Ends is for **triaged** active bugs with a known fix shape; this doc is for findings straight out of review passes, waiting for the owner to decide "fix now / track / ignore / add a test".

New reviews append a new dated `##` section. When an item is triaged, move it into its destination (Loose Ends / a Track / Fix Log / delete) and strike it through here with a pointer.

---

## 2026-04-23 — Foundation sweep review (widgets + context + approval loop)

Scope: `development` branch `HEAD~2..HEAD` (5abd78f0 machine-control refactor + d0cf541e docs/context pass) plus ~70 dirty working-tree files sitting on top of the "core loop stabilization" session. Findings are verified against the tree, not agent-speculative. User: foundation-strength focus for widgets, context management, and planning.

### 🔴 Critical

1. ~~**`app/agent/rag_formatting.py` is untracked but imported by committed code.** `git ls-files` rejects the path; `context_assembly.py:38`, `reranking.py:20`, and `tests/unit/test_reranking.py:8` already import from it. Any fresh clone of `development` fails to boot with `ModuleNotFoundError`. WT changes to `context_assembly.py` import six more constants from it, tightening the dependence. **Fix:** `git add app/agent/rag_formatting.py`.~~ Resolved/stale on re-check: the file is tracked in the current tree (`git ls-files app/agent/rag_formatting.py` returns the path).

2. ~~**Session-lease uniqueness is a Python scan, no DB enforcement.** `app/services/machine_control.py:322-341` (`_find_conflicting_lease`) iterates every `Session` row and checks `metadata_['machine_target_lease']` in Python; `grant_session_lease` (344-385) does not take a row lock, uses no `UNIQUE` index, and has no `ON CONFLICT`. Two concurrent `POST .../lease` requests can both see "no conflict", both write, both succeed — directly breaking the one-session-one-target invariant the Roadmap advertises.~~ Fixed 2026-04-28 with `machine_target_leases` table and unique constraints on `session_id` and `(provider_id, target_id)`.

3. **Header-zone drop math missing `CANVAS_INNER_PADDING` subtraction.** `ui/app/(app)/widgets/ChannelDashboardMultiCanvas.tsx:451-459` passes raw `clientX - rect.left` / `clientY - rect.top` to `pointerToCell`, while the body-grid paths at 427-429 subtract `CANVAS_INNER_PADDING` (12px). Header drops land 12px off true cell; `clampPlacement` hides most of it at narrow column counts but the ghost and final placement disagree at wider presets. **Fix:** mirror the body-path subtraction.

4. **`_create_approval_state` partial-commit path is not exercised.** `app/agent/tool_dispatch.py:1356` inserts ToolCall + ToolApproval and commits in one session. `tests/unit/test_approval_orphan_pointers.py` mocks the whole helper to raise — never drives a failure *between* the two `add` calls. The "atomic approval state" claim rides on SQLAlchemy rollback semantics; worth a focused test that swaps out just the second `add`.

### 🟠 Major

5. **`strict=False` is the default on the new recording helpers.** `app/agent/recording.py:214, 264, 306` (`_start_tool_call`, `_complete_tool_call`, `_set_tool_call_status`). The "silent failure" fix is opt-in; any caller that doesn't pass `strict=True` or check the bool return keeps the old silent-failure behavior. Flip the default + audit call sites.

6. ~~**`reranking.py` hardcodes pinned/tagged/memory prefixes outside `rag_formatting.py`.** `app/services/reranking.py` `_EXCLUDED_PREFIXES` hand-spells `"Pinned skill context"`, `"Tagged skill context"`, `"Your persistent memory"`. The contract module is only half a contract; export those prefixes and import them.~~ Fixed in the context follow-up pass: `rag_formatting.py` now owns the non-rerankable prefix contract as well, and `reranking.py` imports it.

7. ~~**`/admin/machines` gates on `integrations:read`, not admin role.** `app/routers/api_v1_admin/machines.py:20, 30, 52`. Route is namespaced `/admin/` but the scope check is overbroad — any bot token with `integrations:read` can enumerate machine targets (hostname, capabilities, enrollment state).~~ Fixed 2026-04-28: machine admin routes now require admin-equivalent auth.

8. **Integration test for machine-target sessions deleted; replacement is mocked unit test.** `tests/integration/test_machine_target_sessions.py` gone (-172 LOC); `tests/unit/test_machine_target_sessions.py` (+190 LOC) uses `_FakeDbSession` + `_FakeProvider`. HTTP contract, router auth, and lease-race surface are now uncovered. Put it back, or add a concurrent-grant test against a real DB session.

9. **Tool-dispatch WT flips fire-and-forget → blocking `await` for recording helpers.** WT diff shows `safe_create_task(_start_tool_call(...))` → `await _start_tool_call(...)` and same for `_complete_tool_call`, paired with `strict=True`. Semantically correct, but adds a DB round-trip on the hot dispatch path for every tool call. No latency measurement. Consider: is a failure to record a `running`-state update severe enough to block dispatch, or do you want `strict=True` only on terminal writes?

10. ~~**`_inject_workspace_rag` param rename is WT-only.** WT diff renames `excluded_chunk_prefixes` → `excluded_path_prefixes` in `context_assembly.py`. Every call site needs to be updated in the same commit or kwargs will break at import. Grep before committing.~~ Resolved/stale on re-check: current call sites and tests already use `excluded_path_prefixes`.

### 🟡 Architectural

11. **`app/services/local_machine_control.py` is a one-line `from app.services.machine_control import *` shim.** It still exists and is still listed as dirty. Two options: delete and sed-update every import today, or tombstone with explicit `DeprecationWarning`. Don't leave `import *` in tree — static analysis won't catch stale callers.

12. **Three layout-derivation helpers with unclear precedence.** `ui/src/lib/widgetLayoutHints.ts`, `ui/src/components/chat/renderers/nativeApps/nativeWidgetLayout.ts`, `ui/src/components/chat/renderers/nativeApps/contextTrackerLayout.ts`. Which is authoritative when sizing a native-app widget on dashboard vs. chat feed vs. on resize? Tests don't cross-test. Write a top-of-file precedence comment or consolidate.

13. **Approval lifecycle ownership split across three modules.** `tool_dispatch._create_approval_state` (create), `loop._resolve_approval_verdict` (timeout), `api_v1_approvals.decide_approval` (decision). Both reconciliation branches (loop + router) mutate the ToolCall row with subtly different "terminal status" predicates. Future bug will surface as an approval that one side marked `approved` and the other marked `expired`. Extract a shared `reconcile_toolcall_with_approval_verdict` helper.

14. **Provider registry is YAML-scan implicit; `MachineControlProvider` is only `runtime_checkable`.** `app/services/machine_control.py:129-137`. Adding a second provider (SSH, WinRM) has no documented path. Protocol verification happens at call time, not import. Add a short "how to add a provider" doc + an `assert_provider_shape()` helper called at registration, or switch to explicit `register_provider()`.

15. **`.chat-test-dist/` JS is tracked *and* dirty alongside fresh `.ts` sources.** `widgetTheme.js` modified in WT; `dashboardCanvasHeight.js`, `widgetHostPolicy.js`, `widgetLayoutHints.js` untracked. Two representations of the same code. Tests can load stale JS without any CI catching it. Either remove `.chat-test-dist/` from git (generate pre-test) or add a pre-commit regenerate+stage hook.

### 🟢 DX

16. **~70 dirty files on top of 5 commits.** Riskiest: `app/agent/{context_assembly,tool_dispatch,loop,recording,tokenization}.py` all sitting on top of the "core loop stabilization" commit. Memory rule "commit ONLY E2E test scenarios" is respected, but the regression surface on the next `git add .` is large. Commit or stash before more exploratory work.

17. **Naming soup in machine-control surface.** `api_v1_admin/machines.py`, service `machine_control`, provider `local_companion`, state `SessionMachineTargetState`, renderer `MachineTargetStatusRenderer`, skill `machine_control.md`, integration ID `local_companion`, setup UI `MachineControlSetupSection.tsx` (untracked). Pick one noun before a second provider ships.

18. ~~**`estimate_content_tokens` multimodal fallback is 64 tokens.** `app/agent/tokenization.py` (`_NON_TEXT_PART_TOKEN_ESTIMATES`, ~line 41). A single Anthropic image is 85-2000 tokens depending on detail; 64 is under by 1.3-30×. Either refine with a real estimator or drop a "placeholder — refine for vision workloads" comment so the next reader doesn't assume it's empirical.~~ Fixed in the context follow-up pass: image parts are now detail-aware (`low` / `auto` / `high`) with explicit heuristic comments instead of a flat unknown fallback.

19. **`_default_grid_layout()` hardcodes 2-col flow.** `app/services/dashboard_pins.py:64-79`. Comment says "2-col flow"; math is `position % 2`. Correct only for `preset.cols.lg = 12`. A future `fine` preset (24 cols) will fan out wrong.

20. **`MachineControlSetupSection.tsx` is untracked UI scaffolding.** `ui/app/(app)/admin/integrations/[integrationId]/MachineControlSetupSection.tsx`. Ship / delete / side-branch — leaving it in WT is a cliff for accidental commit.

### Recommended triage ordering (when work resumes)

1. `git add app/agent/rag_formatting.py` — 30 sec, server-boot blocker.
2. ~~Admin machines route → admin scope — 10 min, real auth leak.~~ Fixed 2026-04-28.
3. ~~Session-lease DB uniqueness + race-hitting integration test — 1-2 h, the actual foundation fix.~~ DB uniqueness fixed 2026-04-28; real HTTP/concurrent integration coverage remains tracked in item 8.
4. Flip `strict` default to `True` in `recording.py` + sweep call sites — 20 min.
5. Move pinned/tagged/memory prefixes into `rag_formatting.py` — 15 min.
6. Header-zone padding fix in `ChannelDashboardMultiCanvas.tsx` — 5 min.
7. Decide fate of `local_machine_control.py` shim — 15 min.
8. Partial-commit test for `_create_approval_state` — 30 min.
9. Layout-helper precedence comment / consolidation — 10 min.

Everything else (approval-lifecycle helper, provider-registration story, `.chat-test-dist/` pipeline, naming soup) is its own track — polish, not bugs.

### Notes for mirror hook

`Open Issues.md` is **not currently in** `dotfiles/claude/hooks/_mirror-spindrel-docs-allowlist.sh`. If this doc should be public-facing (mirrored into `spindrel/project-notes/`), add the basename to the allowlist. Not doing that edit here — user's other sessions are still working and dotfiles auto-pushes. Flagging for next cleanup pass.
