---
name: spindrel-backend-operator
description: "Use when editing Spindrel backend source: FastAPI routers, app services, agent loop/context code, local tools, auth/policy gates, migrations, and backend tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Backend Operator

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read the canonical guide for the surface you are touching:
   `docs/guides/development-process.md`, `docs/guides/api.md`,
   `docs/guides/discovery-and-enrollment.md`, or
   `docs/guides/context-management.md`.
3. Check `git status --short` and protect unrelated edits.
4. Search with `rg` before changing shared services, routers, models, or tools.

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
