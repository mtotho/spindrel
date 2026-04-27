"""Docs ↔ images drift check.

Scans ``docs/**/*.md`` for ``![alt](path.png)`` references pointing at
``docs/images/`` and verifies each referenced file exists on disk. Prints a
report and exits non-zero if any are missing.

Runs standalone — no server, no staging required::

    python -m scripts.screenshots check
    python -m scripts.screenshots check --require-hero

The optional ``--require-hero`` mode additionally flags every guide under
``docs/guides/`` that has zero ``![...]`` references — the failure mode where
a feature ships, the guide is written, but the hero capture never gets wired
in (a class of drift the basic check missed). Exits non-zero if any guide
under ``docs/guides/`` lacks at least one image reference, EXCEPT the small
allow-list of intentionally text-only reference docs.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Reference / glossary / process docs that legitimately don't carry a hero.
# Adding a guide here is a deliberate decision — keep the list short and
# documented in the matching plan/Track entry.
_HERO_OPTIONAL = frozenset({
    "api.md",
    "clients.md",
    "feature-status.md",
    "ubiquitous-language.md",
    "ui-design.md",
    "ui-components.md",
    "context-management.md",
    "development-process.md",
    "e2e-testing.md",
    "plan-mode.md",
    "programmatic-tool-calling.md",
    "workflows.md",  # deprecated guide, intentionally hero-less
    "templates-and-activation.md",  # configuration concept; no single hero shot
    "slack.md",  # capturing real Slack delivery requires live tokens we don't run
                 # on the e2e instance; revisit once we either wire a Block Kit
                 # preview path or stand up a Slack workspace fixture.
})


# Match ``![alt text](../images/name.png)`` and ``(docs/images/name.png)``.
# The path group captures the raw src exactly as written; resolution is done
# relative to the .md file's directory.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+\.(?:png|jpg|jpeg|gif|svg|webp))\)")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _find_refs(docs_root: Path) -> list[tuple[Path, str, Path]]:
    """Return ``[(md_file, raw_src, resolved_path)]`` for every image ref.

    ``resolved_path`` is relative to repo root; callers check existence.
    """
    out: list[tuple[Path, str, Path]] = []
    for md in sorted(docs_root.rglob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for m in _MD_IMAGE_RE.finditer(text):
            raw = m.group(1)
            # Skip external URLs.
            if raw.startswith(("http://", "https://", "data:")):
                continue
            resolved = (md.parent / raw).resolve()
            out.append((md, raw, resolved))
    return out


def _guides_without_heroes(docs_root: Path) -> list[Path]:
    """Return guide paths under ``docs/guides/`` that have zero image refs.

    Skips files in ``_HERO_OPTIONAL``. Result is sorted, repo-rooted-relative.
    """
    guides_root = docs_root / "guides"
    if not guides_root.is_dir():
        return []
    out: list[Path] = []
    for md in sorted(guides_root.glob("*.md")):
        if md.name in _HERO_OPTIONAL:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if not _MD_IMAGE_RE.search(text):
            out.append(md)
    return out


def check(require_hero: bool = False) -> int:
    root = _repo_root()
    docs_root = root / "docs"
    if not docs_root.is_dir():
        print(f"ERROR: docs root not found at {docs_root}", file=sys.stderr)
        return 2

    refs = _find_refs(docs_root)
    missing: list[tuple[Path, str, Path]] = []
    ok_count = 0
    for md, raw, resolved in refs:
        if resolved.exists():
            ok_count += 1
        else:
            missing.append((md, raw, resolved))

    print(f"Scanned {len(refs)} image reference(s) across docs/.")
    print(f"  OK:      {ok_count}")
    print(f"  Missing: {len(missing)}")

    exit_code = 0
    if missing:
        print("\nMissing images (guide → referenced path):")
        for md, raw, resolved in missing:
            rel_md = md.relative_to(root)
            rel_resolved = resolved.relative_to(root) if resolved.is_relative_to(root) else resolved
            print(f"  {rel_md}  →  {raw}  (expected at {rel_resolved})")
        exit_code = 1

    if require_hero:
        bare = _guides_without_heroes(docs_root)
        print(f"\nGuides without a hero image: {len(bare)} (allow-listed: {len(_HERO_OPTIONAL)})")
        if bare:
            print("Guides under docs/guides/ that have zero image references:")
            for md in bare:
                print(f"  {md.relative_to(root)}")
            print(
                "\nFix: add `![Caption](../images/<file>.png)` after the H1 intro,"
                " or extend `_HERO_OPTIONAL` in scripts/screenshots/check_drift.py"
                " if this guide is intentionally text-only."
            )
            exit_code = 1

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(prog="scripts.screenshots check")
    parser.add_argument(
        "--require-hero",
        action="store_true",
        help="also fail if any non-allow-listed guide under docs/guides/ has zero image refs",
    )
    args = parser.parse_args()
    sys.exit(check(require_hero=args.require_hero))


if __name__ == "__main__":
    main()
