"""Dump the FastAPI OpenAPI schema to a JSON file without starting the server.

Used by ``scripts/generate-api-types.sh`` and the ``api-type-drift`` CI job to
feed ``openapi-typescript``. Importing ``app.main:app`` is enough — FastAPI's
lifespan only runs under uvicorn, so this stays offline (no DB, no network).

    python scripts/dump_openapi.py ui/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _disambiguate_operation_ids(schema: dict) -> None:
    """Ensure every operation has a unique ``operationId``.

    FastAPI's ``api_route(methods=["PUT", "PATCH"])`` pattern computes one
    ``operation_id`` per route and reuses it for every method, producing
    duplicates in the emitted schema (FastAPI itself warns about this).
    Codegen tools like ``openapi-typescript`` then write each colliding op
    twice into ``operations``. Strip any trailing ``_<method>`` suffix and
    re-append the actual method when we hit a duplicate so each operation
    keeps a stable, unique key.
    """
    paths = schema.get("paths", {})
    seen: set[str] = set()
    for path_key in sorted(paths.keys()):
        path_item = paths[path_key]
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if not isinstance(op_id, str):
                continue
            if op_id in seen:
                base = op_id
                for suf in _HTTP_METHODS:
                    if base.endswith(f"_{suf}"):
                        base = base[: -(len(suf) + 1)]
                        break
                candidate = f"{base}_{method}"
                i = 2
                while candidate in seen:
                    candidate = f"{base}_{method}_{i}"
                    i += 1
                op["operationId"] = candidate
            seen.add(op["operationId"])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/dump_openapi.py <output.json>", file=sys.stderr)
        return 2

    out_path = Path(argv[1]).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from fastapi import FastAPI

    from app.main import app as exported

    # ``app.main:app`` may be wrapped in SPAFallbackMiddleware when the UI build
    # directory is present. Unwrap to find the underlying FastAPI instance.
    fastapi_app = exported
    while not isinstance(fastapi_app, FastAPI):
        fastapi_app = getattr(fastapi_app, "app", None)
        if fastapi_app is None:
            raise RuntimeError("could not locate FastAPI instance under app.main:app")

    schema = fastapi_app.openapi()
    _disambiguate_operation_ids(schema)
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
