# E2E Lessons Learned

Append-only reference for `spindrel-e2e-development`. Add new lessons here
rather than the skill body.

- Run `doctor` first. If subscription bootstrap is already connected, do not
  restart browser/device-code OAuth.
- Rebuild current source before judging e2e behavior. If Docker context fails
  on generated dependency folders, exclude those folders instead of wiping the
  local e2e database.
- Normal local `prepare` preserves provider/OAuth state. Only
  `wipe-db --yes` should erase the durable local e2e Postgres volume.
- Prefer `prepare-deps` for normal source-tree development. It starts shared
  Docker dependencies and prints connection env; each agent owns its own
  source-run server process and port.
- `.env.agent-e2e` must keep the generated `ENCRYPTION_KEY` and `JWT_SECRET`
  alongside the durable local Postgres volume. If encrypted provider/OAuth rows
  were written under a lost key, the local app cannot boot until that local DB
  is wiped or the original key is restored.
- Never delete/regenerate `.env.agent-e2e` secrets as a convenience. If
  `doctor` reports subscription/provider state is connected, protect that file
  and use normal `prepare` / `prepare-harness-parity`; only `wipe-db --yes`
  should intentionally reset provider/OAuth state.
- Screenshot staging should use deterministic fixtures for documentation
  transcripts. Do not depend on a live model turn to render a docs artifact.
- Harness parity can now run locally against the agent-owned native API/UI
  through `run_harness_parity_local.sh`; use `--screenshots feedback` for throwaway
  visual review and `--screenshots docs` only when intentionally refreshing
  checked-in `docs/images/harness-*` fixtures.
- Before closing broad Codex/Claude SDK parity work, run
  `./scripts/run_harness_parity_local_batch.sh --preset all --screenshots docs`.
  The `all` preset is sequential, runs the replay tier without a `-k` selector,
  writes JUnit XML next to its log, and fails on unexpected pytest skips so
  provider auth, browser-runtime, and SDK-surface gaps do not look like local
  passes. Runtime-specific intentional skips are allowlisted by
  `HARNESS_PARITY_ALLOWED_SKIP_REGEX`.
- Keep deep SDK parity coverage close to documented native surfaces. Current
  required scenarios include Project cwd instruction discovery, mid-stream text
  deltas, image semantic reasoning, Claude `TodoWrite` progress persistence,
  and Claude `Agent`/`Task` subagent result persistence.
- `prepare-harness-parity` installs Codex/Claude integration deps, restarts the
  native local API so the harness modules reload, then creates stable
  parity bots/channels with baseline bridge tools and writes
  `scratch/agent-e2e/harness-parity.env`.
- Local parity can be parallelized with focused selectors, not full tier
  sweeps. Prefer `run_harness_parity_local_batch.sh --preset smoke|fast --jobs
  2` during development; raise jobs only for targeted, independent slices.
- Durable screenshot fixtures can outlive a regenerated encryption key. Staging
  should repair screenshot secret values through the API instead of clearing
  the stack.
- Local live PR smoke needs three independent credentials: Spindrel provider
  auth for normal model calls, host Codex auth mounted into the local e2e
  container, and a Project-bound GitHub token secret for clone/push/`gh pr`.
  The helper checks all three without printing secret values.
- GitHub handoff receipts may return `changed_files` as strings and may omit
  `handoff_type` when the agent only supplies a URL. Assert the durable URL and
  changed path; treat type as optional unless the product contract changes.
- Project Dependency Stacks separate spec from instance. The Project/Blueprint
  owns the compose source; coding runs get task-scoped dependency instances so
  parallel runs do not restart the same database/services. App/dev servers are
  native per-agent processes outside the dependency stack.
- Dependency-stack preflight belongs before the first harness turn for Project
  coding runs. If a stack is configured, the run should start with env keys
  such as `DATABASE_URL` already available; the tool remains available for
  reloads, health checks, logs, and recovery.
- Native local parity sets `CONFIG_STATE_FILE=` by default so source-mode API
  startup does not replay exported config into a fresh e2e DB. Opt into config
  restore explicitly only when that is the thing under test.
- Native local parity uses the repo-seeded `default` bot for e2e health checks;
  the compose-only `e2e` bot is not available unless a containerized app run
  mounts `tests/e2e/bot.e2e.yaml`.
- If the dependency compose project gets stuck in Docker removal state, debug
  and repair that shared dependency stack. Do not switch to a private compose
  project, and do not delete the durable default DB/auth state to unblock a
  proof run.
- Native Project parity dogfood requires both product UI evidence and the
  generated app screenshot. Capture and link the Project detail, Project
  channels binding, Codex session transcript, and generated app artifacts
  instead of stopping at the static app image.
