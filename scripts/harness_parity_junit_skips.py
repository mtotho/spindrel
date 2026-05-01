"""Validate harness parity JUnit skip results.

Thin re-export shim. The implementation lives in
``tests.e2e.harness.parity_runner`` (single source of truth for harness parity
orchestration). The shell scripts and existing imports
(``from scripts.harness_parity_junit_skips import unexpected_skips``) keep
working through this shim.
"""

from __future__ import annotations

import argparse
import sys

from tests.e2e.harness.parity_runner import (
    DEFAULT_ALLOWED_SKIP_REGEX,
    validate_skips as unexpected_skips,
)


__all__ = ["DEFAULT_ALLOWED_SKIP_REGEX", "unexpected_skips", "main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit_xml")
    parser.add_argument("--allowed-skip-regex", default=DEFAULT_ALLOWED_SKIP_REGEX)
    args = parser.parse_args(argv)

    unexpected = unexpected_skips(args.junit_xml, args.allowed_skip_regex)
    if not unexpected:
        return 0
    print(
        f"Harness parity strict mode failed: {len(unexpected)} unexpected skipped test(s) in {args.junit_xml}",
        file=sys.stderr,
    )
    for name, message in unexpected[:20]:
        print(f"  - {name}: {message}", file=sys.stderr)
    if len(unexpected) > 20:
        print(f"  ... {len(unexpected) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
