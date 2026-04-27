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

Spindrel uses a manual tag-driven release flow. Versions follow [SemVer](https://semver.org/); while we are in `0.x`, minor bumps may include breaking changes.

1. Bump the version in **both** `pyproject.toml` and `ui/package.json` to `X.Y.Z` (these must stay in sync).
2. Move the `## [Unreleased]` block in `CHANGELOG.md` into a new `## [X.Y.Z] - YYYY-MM-DD` section. Keep an empty `## [Unreleased]` skeleton at the top. Update the comparison links at the bottom of the file.
3. Open a PR titled `Release vX.Y.Z`. Once it merges to `master`:
   ```bash
   git checkout master && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. The `Release` workflow (`.github/workflows/release.yml`) builds and pushes `ghcr.io/mtotho/spindrel:X.Y.Z` (and `:latest`), then creates a GitHub Release whose body is the matching `CHANGELOG.md` section.
5. For pre-releases, tag `vX.Y.Z-rc1` (or similar) — the workflow auto-marks tags containing `-` as prereleases and skips `:latest`.

### Releasing a tag that already exists

If a tag was pushed before the release workflow existed (or the workflow run failed and you want to retry), go to **Actions → Release → Run workflow** in the GitHub UI, enter the tag name (`vX.Y.Z`), and click Run. Same effect as pushing the tag fresh.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).
