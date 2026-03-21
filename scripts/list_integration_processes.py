#!/usr/bin/env python3
"""Print integration background process commands for use in dev-server.sh.

Output format: one shell-quoted command per line (shlex.join), preceded by a
comment line with the description. Lines starting with # are skipped by the
shell reader loop.

Usage in dev-server.sh:
    while IFS= read -r cmd; do
        [[ "$cmd" == \#* ]] && continue
        [ -z "$cmd" ] && continue
        echo "Starting: $cmd"
        eval "$cmd" &
        PIDS+=($!)
    done < <(python scripts/list_integration_processes.py)
"""
import shlex
import sys
from pathlib import Path

# Ensure repo root is on path so `integrations` package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations import discover_processes  # noqa: E402

for proc in discover_processes():
    print(f"# {proc['description']}")
    print(shlex.join(proc["cmd"]))
