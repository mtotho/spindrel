# Contributing to Spindrel

Thanks for your interest in contributing! Spindrel is early-access software under active development — contributions of all kinds are welcome.

## Ways to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected vs actual behavior, and your environment (Docker/host, LLM provider, OS).
- **Feature requests** — Open an issue describing the use case and why existing features don't cover it.
- **Pull requests** — Bug fixes, new integrations, documentation improvements, and test coverage are all appreciated.
- **Documentation** — Typo fixes, clearer explanations, new guides — docs live in `docs/` and are built with MkDocs.

## Before You Start

For non-trivial changes (new features, architectural changes, new integrations), please **open an issue first** to discuss the approach. This avoids wasted effort if the change doesn't align with the project direction.

## Project State & Architecture

High-level project state — current roadmap, architectural decisions, active work tracks, and test-quality audits — lives in [`project-notes/`](project-notes/). Read those before proposing a non-trivial change so your PR aligns with what's already in flight.

`project-notes/` is a one-way mirror of the maintainer's internal Obsidian vault. To suggest an edit, open an issue or PR against the file; the maintainer reconciles changes back into the vault. Direct edits to `project-notes/` will be overwritten on the next sync.

## Development Setup

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh
```

See [docs/setup.md](docs/setup.md) for detailed setup instructions.

## Running Tests

```bash
# Build and run the test suite (uses SQLite in-memory, no postgres needed)
docker build -f Dockerfile.test -t agent-server-test . && docker run --rm agent-server-test

# Run a specific test file
docker build -f Dockerfile.test -t agent-server-test . && docker run --rm agent-server-test pytest tests/unit/test_foo.py -v

# UI typecheck (required after any UI changes)
cd ui && npx tsc --noEmit
```

## Pull Request Guidelines

- **Write tests** — Bug fixes should include a test that fails without the fix. New features should have reasonable test coverage.
- **Run the test suite** before submitting.
- **Run the UI typecheck** (`cd ui && npx tsc --noEmit`) if you touched anything in `ui/`.
- **Keep PRs focused** — One logical change per PR. Don't bundle unrelated fixes.
- **Update docs** if your change is user-facing — `docs/` guides, `README.md`, or inline help text.

## Code Style

- Python: Follow existing patterns in the codebase. No strict formatter enforced yet.
- TypeScript/React: NativeWind (Tailwind) for styling, TanStack Query for data fetching.
- Prefer simple, direct solutions over abstractions. Don't over-engineer.

## Adding an Integration

Integrations live in `integrations/` and follow a standard structure. See `integrations/example/` for a template, and [docs/integrations/](docs/integrations/) for the development guide.

## Release Process (maintainer)

Spindrel ships releases via a single helper script: `scripts/release.sh`. Versions follow [SemVer](https://semver.org/); while we are in `0.x`, minor bumps may include breaking changes.

```bash
# 1. Prepare the release: bumps pyproject.toml + ui/package.json,
#    adds a CHANGELOG.md stub, commits on `development`, opens a PR to `master`.
scripts/release.sh 0.3.0

# 2. Edit CHANGELOG.md in the PR to write the high-level release notes
#    (this text becomes the GitHub Release body). Then merge the PR.

# 3. Tag master and trigger the release workflow.
scripts/release.sh 0.3.0 --tag
```

The release workflow (`.github/workflows/release.yml`) then builds and pushes `ghcr.io/mtotho/spindrel:0.3.0` (and `:latest`) and creates a GitHub Release. The Release body is composed as: **your CHANGELOG section first**, then a collapsed `<details>` block with the auto-generated PR list since the previous tag, then the container image line.

For pre-releases, use a suffixed version like `0.3.0-rc1` — the workflow auto-marks tags containing `-` as prereleases and skips `:latest`.

### Releasing a tag that already exists

If a tag was pushed before the release workflow existed (or the workflow run failed and you want to retry), go to **Actions → Release → Run workflow** in the GitHub UI, enter the tag name (`vX.Y.Z`), and click Run. Same effect as pushing the tag fresh.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).
