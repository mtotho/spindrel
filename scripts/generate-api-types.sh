#!/usr/bin/env bash
# Regenerate ui/openapi.json + ui/src/types/api.generated.ts from the live
# FastAPI route table. Run after changing any Pydantic response model. CI
# (``api-type-drift`` job) runs this and fails if the result differs from
# what's committed.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

PYTHONPATH="${PYTHONPATH:-.}" "$PYTHON_BIN" scripts/dump_openapi.py ui/openapi.json
npm --prefix ui run generate-api-types
