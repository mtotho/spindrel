"""Validate harness parity JUnit skip results."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET


DEFAULT_ALLOWED_SKIP_REGEX = (
    r"Claude Code-specific|Codex app-server owns|does not advertise native compaction"
)


def unexpected_skips(path: str, allowed_skip_regex: str = DEFAULT_ALLOWED_SKIP_REGEX) -> list[tuple[str, str]]:
    allowed_re = re.compile(allowed_skip_regex) if allowed_skip_regex else None
    root = ET.parse(path).getroot()
    unexpected: list[tuple[str, str]] = []
    for node in root.iter():
        if node.tag != "testcase":
            continue
        skipped_nodes = [child for child in node if child.tag == "skipped"]
        if not skipped_nodes:
            continue
        name = f"{node.attrib.get('classname', '')}.{node.attrib.get('name', '')}"
        message = " ".join(str(child.attrib.get("message", "")) for child in skipped_nodes)
        if allowed_re and allowed_re.search(f"{name} {message}"):
            continue
        unexpected.append((name, message))
    return unexpected


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
