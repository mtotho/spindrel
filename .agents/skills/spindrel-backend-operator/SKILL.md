---
name: spindrel-backend-operator
description: "Use when editing Spindrel backend source: FastAPI routers, app services, agent loop/context code, local tools, auth/policy gates, migrations, and backend tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Backend Operator

This is a repo-dev skill for any agent editing this checkout: local CLI on the
operator's box, in-app Spindrel agent on the server, or a Project coding run.
It is not a Spindrel runtime skill and must not be imported into app skill
tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read the canonical guide for the surface you are touching:
   `docs/guides/development-process.md`, `docs/guides/api.md`,
   `docs/guides/discovery-and-enrollment.md`, or
   `docs/guides/context-management.md`.
3. Check `git status --short` and protect unrelated edits.
4. Search with `rg` before changing shared services, routers, models, or tools.

## Triage primitives

| Need | Primitive |
|---|---|
| Find an endpoint | `rg -n "@router\.(get\|post\|put\|delete\|patch).*<path>" app/routers` |
| Find a tool implementation | `rg -n "name=\"<tool_name>\"" app/tools` |
| Confirm a route's auth | grep `verify_auth_or_user` in the same file (public routes are listed by name in `SECURITY.md`) |
| Confirm a tool's `safety_tier` | grep `safety_tier=` near the tool registration in `app/services/tool_policies.py` |
| Find a migration | `ls migrations/versions/ \| grep <slug>` |
| Test a slice without DB | `. .venv/bin/activate && PYTHONPATH=. pytest tests/unit/<file> -q` (no Docker) |

## Named patterns to grep for

- **New tool without `safety_tier`** — defaults to `readonly`. For raw-payload returners (logs, file dumps, secrets) this is wrong; mark `control_plane`.
- **Router added without `verify_auth_or_user`** — public-by-default. Either declare publicly in `SECURITY.md` or add the dependency.
- **Service logic in a router body** — no test seam. Extract to a service module before wiring routes/tools.
- **Migration touching encrypted columns without a downgrade guard** — silent decryption / data loss. Pattern: see `migrations/versions/130_encrypt_secrets.py::downgrade()`.

## Worked example: add an internal admin endpoint

1. Service first: add the function to `app/services/<area>.py` with a typed return.
2. Add the route in `app/routers/api_v1_<area>.py` with `verify_auth_or_user` (and rate limit if user-callable).
3. Test the service unit (no DB), then the route integration with a fake auth fixture.
4. Update the matching `docs/guides/<area>.md` if the contract changes; document new env vars in `SECURITY.md`.
5. If a tool wraps it: register with the right `safety_tier` and add a tool-policy test.

## Do

- Keep source-of-truth logic in a service or domain module before wiring routes
  or tools around it.
- Preserve policy and scope checks when adding API or tool access.
- Add focused regression tests for logic changes and bug fixes.
- Split large functions you touch when a small extraction makes the change
  safer.
- Use structured schemas and existing envelopes for agent-facing returns.

## Avoid

- Do not create app runtime skills from this folder.
- Do not bypass existing approval, capability, or tool-policy paths.
- Do not add broad config knobs when a detector, manifest, or service contract
  can derive the answer.
- Do not query production data to understand behavior; read code and tests.

## Completion Standard

Run the smallest relevant backend tests first with native `PYTHONPATH=. pytest`
inside the repo venv, then broaden only as needed. If a DB-backed slice needs
Python 3.12 and the active venv is not Python 3.12, report that environment
blocker; do not wrap unit tests in Docker, Dockerfile.test, or docker compose.
Always finish with `git diff --check` over touched files.
