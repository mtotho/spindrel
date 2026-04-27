#!/usr/bin/env bash
# scripts/release.sh - One-command Spindrel release helper.
#
# Usage:
#   scripts/release.sh X.Y.Z         # phase 1: bump versions, commit, open PR
#   scripts/release.sh X.Y.Z --tag   # phase 2 (after PR merges): tag master, trigger release
#
# What gets automated:
#   - pyproject.toml + ui/package.json version bumps
#   - CHANGELOG.md stub for the new version (you edit the bullets)
#   - commit + push on the development branch
#   - PR creation against master via gh CLI
#   - tag + push (which fires the release workflow)
#
# What you still do:
#   - Edit the new CHANGELOG.md section to write the high-level release notes
#   - Review and merge the PR

set -euo pipefail

VERSION="${1:-}"
MODE="${2:-prepare}"

if [ -z "$VERSION" ]; then
  echo "usage: scripts/release.sh X.Y.Z [--tag]" >&2
  exit 1
fi

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
  echo "error: version must look like 0.3.0 or 0.3.0-rc1, got '$VERSION'" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TAG="v$VERSION"
DATE="$(date +%Y-%m-%d)"

require_clean_tree() {
  if ! git diff-index --quiet HEAD --; then
    echo "error: working tree has uncommitted changes. Stash or commit first." >&2
    git status --short >&2
    exit 1
  fi
}

prepare() {
  echo "==> Preparing release $TAG on development"

  git checkout development
  git pull --ff-only
  require_clean_tree

  # Bump pyproject.toml
  sed -i -E "0,/^version = \".*\"$/s//version = \"$VERSION\"/" pyproject.toml

  # Bump ui/package.json (avoid jq dep — use a small python one-liner)
  python3 -c "
import json, pathlib
p = pathlib.Path('ui/package.json')
data = json.loads(p.read_text())
data['version'] = '$VERSION'
p.write_text(json.dumps(data, indent=2) + '\n')
"

  # Add a CHANGELOG.md stub for this version if it doesn't already exist
  if ! grep -q "^## \[$VERSION\]" CHANGELOG.md; then
    python3 - "$VERSION" "$DATE" <<'PY'
import sys, pathlib, re
version, date = sys.argv[1], sys.argv[2]
p = pathlib.Path('CHANGELOG.md')
text = p.read_text()

stub = f"""## [{version}] - {date}

_Edit me before merging the release PR. A few high-level bullets are enough — this is what shows up on the GitHub Release page._

### Highlights

- TODO: bullet 1
- TODO: bullet 2

"""

# Insert the stub right after the [Unreleased] block
text = re.sub(
    r"(## \[Unreleased\].*?)(\n## \[)",
    lambda m: m.group(1) + "\n" + stub + "## [",
    text,
    count=1,
    flags=re.DOTALL,
)

# Update link refs at the bottom: rewrite [Unreleased] compare and add a new [version] line above the previous version
prev_version_match = re.search(r"^\[Unreleased\]: .*compare/v([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?)\.\.\.HEAD", text, flags=re.MULTILINE)
if prev_version_match:
    prev = prev_version_match.group(1)
    text = re.sub(
        r"^\[Unreleased\]: .*$",
        f"[Unreleased]: https://github.com/mtotho/spindrel/compare/v{version}...HEAD",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    # Insert new [version] link above the [prev] link
    text = re.sub(
        rf"^(\[{re.escape(prev)}\]: .*$)",
        f"[{version}]: https://github.com/mtotho/spindrel/compare/v{prev}...v{version}\n\\1",
        text,
        count=1,
        flags=re.MULTILINE,
    )

p.write_text(text)
PY
  fi

  git add pyproject.toml ui/package.json CHANGELOG.md
  git commit -m "Release $TAG"
  git push

  echo
  echo "==> Opening release PR"
  PR_URL=$(gh pr create \
    --base master \
    --head development \
    --title "Release $TAG" \
    --body "Bumps version to $VERSION. Edit \`CHANGELOG.md\` in this PR to write the human-facing release notes — they get pasted into the GitHub Release page when the tag is pushed.

After merging this PR, run:

\`\`\`
scripts/release.sh $VERSION --tag
\`\`\`

That tags master and triggers the release workflow (Docker image push to GHCR + GitHub Release page)." 2>&1 | tail -1)

  echo
  echo "==> Done. Next steps:"
  echo "  1. Edit CHANGELOG.md in the PR to write your release notes:"
  echo "     $PR_URL"
  echo "  2. Merge the PR."
  echo "  3. Run: scripts/release.sh $VERSION --tag"
}

tag_and_release() {
  echo "==> Tagging master with $TAG"
  git checkout master
  git pull --ff-only
  require_clean_tree

  # Sanity check: pyproject.toml must say $VERSION
  py_version=$(grep -m1 -E '^version = ' pyproject.toml | sed -E 's/version = "(.*)"/\1/')
  if [ "$py_version" != "$VERSION" ]; then
    echo "error: pyproject.toml says '$py_version' but you asked to release '$VERSION'." >&2
    echo "Did you forget to merge the release PR?" >&2
    exit 1
  fi

  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "tag $TAG already exists locally"
  else
    git tag "$TAG"
  fi

  git push origin "$TAG"

  echo
  echo "==> Tag $TAG pushed. Release workflow is running."
  echo "Watch: https://github.com/mtotho/spindrel/actions/workflows/release.yml"
}

case "$MODE" in
  prepare)
    prepare
    ;;
  --tag|tag)
    tag_and_release
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    echo "usage: scripts/release.sh X.Y.Z [--tag]" >&2
    exit 1
    ;;
esac
