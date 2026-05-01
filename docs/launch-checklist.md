---
tags: [spindrel, launch]
status: active
updated: 2026-04-27
---

# Launch Checklist

Run these in order. Each step is independent — stop after any step if you want.

---

## What's already on disk (NOT committed yet)

I edited 10 files in `/home/mtoth/personal/spindrel`:

- `CHANGELOG.md` (new) — high-level human-written summary per release (you/AI write a few bullets per version).
- `.github/workflows/release.yml` (new) — auto-builds Docker image + creates GitHub Release when you push a tag. The Release body = your CHANGELOG.md section for that version + a collapsed auto-generated PR list below it.
- `.github/workflows/test.yml` — added UI typecheck to CI.
- `.github/dependabot.yml` (new) — weekly auto-PRs for outdated dependencies.
- `.github/ISSUE_TEMPLATE/config.yml` (new) — issue funnel.
- `.github/ISSUE_TEMPLATE/bug_report.md` — better fields.
- `.github/PULL_REQUEST_TEMPLATE.md` — better fields.
- `CONTRIBUTING.md` — added "Release Process" section.
- `README.md` — added Tests + Releases badges.
- `ui/package.json` — version bumped to `0.2.0` to match `pyproject.toml`.

`git status` will show all of these as modified/untracked.

---

## Step 1 — Get the changes onto GitHub

You're already on the `development` branch. Just commit and push there:

```bash
cd /home/mtoth/personal/spindrel
git add -A
git commit -m "GitHub launch readiness"
git push
```

Then PR `development → master` the way you normally do. Merge it.

**That's the whole "Step 1". No release happens yet — this just lands the new files on master.**

---

## Step 2 — Create the GitHub Release for v0.2.0

The `v0.2.0` tag is already on GitHub. The release workflow won't auto-fire for tags that existed before the workflow was added. So you trigger it manually **once**:

1. Open `https://github.com/mtotho/spindrel/actions/workflows/release.yml`
2. Click the **"Run workflow"** dropdown (top right of the workflow runs list).
3. In the `tag` input, type: `v0.2.0`
4. Click the green **Run workflow** button.

Wait ~5 minutes. When it goes green:
- A new Release page appears at `https://github.com/mtotho/spindrel/releases`
- A Docker image is published at `ghcr.io/mtotho/spindrel:0.2.0`

If it fails, check the Actions log. Most likely cause: GHCR permissions. Fix: repo Settings → Actions → General → Workflow permissions → "Read and write permissions" + tick "Allow GitHub Actions to create and approve pull requests".

---

## Step 3 (optional) — Same for v0.1.0

Same as Step 2 but type `v0.1.0` instead. Skip if you don't care.

---

## Step 4 — Repo settings (web UI, ~2 min)

Go to `https://github.com/mtotho/spindrel/settings`:

1. **General** tab → Features section → check **Discussions** → Save. (Required because the new issue-template config links to Discussions.)
2. **Branches** tab → Add branch protection rule for `master`:
   - Require a pull request before merging
   - Require status checks: `Tests`, `ui-typecheck`
3. **General** tab → top of page → set **Description** + **Website** = `https://docs.spindrel.dev` + **Topics** = `ai-agent self-hosted fastapi llm mcp local-first claude-code`

---

## Versioning rules of thumb (early phase)

In `0.x`, SemVer is intentionally loose — the spec says "anything goes." Practical rules for Spindrel right now:

- **Default: bump the minor** (`0.3.0` → `0.4.0` → `0.5.0`) every release. Use this whenever the release ships features, refactors, or anything user-visible. Don't agonize.
- **Use patch** (`0.3.0` → `0.3.1`) only when fixing a bug in a release that's already out and not adding anything else. Hotfix only.
- **Don't major-bump for breaking changes in `0.x`.** Call them out in the changelog under `### Breaking changes`. The whole point of `0.x` is that breaking changes are expected.
- **Save `1.0.0`** for when you're willing to commit to API/schema stability and a deprecation policy. Not anywhere near that yet.

**Cadence:** every 1-3 weeks is healthy for an early-access self-hosted project. More often → self-hosters can't keep up. Less often → you lose momentum and accumulate "should have been released" features. Trigger: "we just merged something meaningful and it's been a week or two."

Realistic next few months: `v0.3.0` → `v0.4.0` → maybe `v0.4.1` (hotfix) → `v0.5.0` → ... Expect to be at `v0.10+` before you start thinking about `v1.0`.

---

## Step 5 — From now on, releasing v0.3.0+ is two commands

```bash
# Phase 1: bump versions, stub CHANGELOG.md, commit on development, open PR
scripts/release.sh 0.3.0

# (Edit CHANGELOG.md in the PR to write the actual release notes — that's the
#  only thing you write by hand. Then merge the PR.)

# Phase 2: tag master, push tag, release workflow takes over
scripts/release.sh 0.3.0 --tag
```

That's it. The script handles version bumps in **both** `pyproject.toml` and `ui/package.json`, stubs the CHANGELOG.md section, commits, opens the PR via `gh`, and after merge tags master and pushes the tag. The release workflow handles the Docker image push, the GitHub Release page, and pulling your CHANGELOG section into the release body with the auto-generated PR list collapsed below it.

This is also written into `CONTRIBUTING.md` under "Release Process (maintainer)".

---

## What if I want to revert any of this?

The whole change is on the `development` branch (Step 1). Close the PR without merging — nothing lands. Or after merging, the new files are: `CHANGELOG.md`, `.github/workflows/release.yml`, `.github/dependabot.yml`, `.github/ISSUE_TEMPLATE/config.yml`. Delete those four to fully back out.
